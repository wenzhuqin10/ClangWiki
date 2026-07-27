#include <algorithm>
#include <memory>
#include <string>

#include "clang/AST/ASTConsumer.h"
#include "clang/AST/Decl.h"
#include "clang/AST/DeclCXX.h"
#include "clang/AST/Expr.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Frontend/FrontendAction.h"
#include "clang/Tooling/CommonOptionsParser.h"
#include "clang/Tooling/Tooling.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/raw_ostream.h"

using namespace clang;
using namespace clang::tooling;

static llvm::cl::OptionCategory Category("clangwiki-analyzer options");
static llvm::cl::opt<std::string> RepoRoot(
    "repo-root", llvm::cl::desc("Repository root used to relativize source paths"),
    llvm::cl::init(""), llvm::cl::cat(Category));

static std::string escapeJson(llvm::StringRef value) {
  std::string out;
  for (char c : value) {
    switch (c) {
      case '\\': out += "\\\\"; break;
      case '"': out += "\\\""; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default: out += c;
    }
  }
  return out;
}

static std::string sourcePath(const SourceManager &sm, SourceLocation location) {
  if (location.isInvalid()) return "";
  std::string path = sm.getFilename(sm.getSpellingLoc(location)).str();
  std::replace(path.begin(), path.end(), '\\', '/');
  std::string root = RepoRoot;
  std::replace(root.begin(), root.end(), '\\', '/');
  while (!root.empty() && root.back() == '/') root.pop_back();
  if (!root.empty() && path.rfind(root + "/", 0) == 0) path.erase(0, root.size() + 1);
  return path;
}

static unsigned lineOf(const SourceManager &sm, SourceLocation location) {
  return location.isInvalid() ? 0 : sm.getSpellingLineNumber(sm.getSpellingLoc(location));
}

class Visitor : public RecursiveASTVisitor<Visitor> {
 public:
  explicit Visitor(ASTContext &context) : sm_(context.getSourceManager()) {}

  bool TraverseFunctionDecl(FunctionDecl *decl) {
    const FunctionDecl *previous = currentFunction_;
    if (decl && decl->hasBody()) currentFunction_ = decl;
    const bool result = RecursiveASTVisitor::TraverseFunctionDecl(decl);
    currentFunction_ = previous;
    return result;
  }

  bool VisitFunctionDecl(FunctionDecl *decl) {
    if (!decl || !decl->hasBody() || !project(decl->getLocation())) return true;
    emitSymbol(isa<CXXMethodDecl>(decl) ? "method" : "function", decl->getNameAsString(),
               decl->getQualifiedNameAsString(), decl->getBeginLoc(), decl->getEndLoc(),
               decl->getType().getAsString());
    return true;
  }

  bool VisitRecordDecl(RecordDecl *decl) {
    if (!decl || !decl->isCompleteDefinition() || !project(decl->getLocation())) return true;
    const char *kind = decl->isStruct() ? "struct" : (decl->isUnion() ? "union" : "class");
    emitSymbol(kind, decl->getNameAsString(), decl->getQualifiedNameAsString(),
               decl->getBeginLoc(), decl->getEndLoc(), "");
    return true;
  }

  bool VisitCXXRecordDecl(CXXRecordDecl *decl) {
    if (!decl || !decl->isThisDeclarationADefinition() || !project(decl->getLocation())) return true;
    for (const auto &base : decl->bases()) {
      const CXXRecordDecl *baseDecl = base.getType()->getAsCXXRecordDecl();
      emitRelation(decl->getQualifiedNameAsString(),
                   baseDecl ? baseDecl->getQualifiedNameAsString() : base.getType().getAsString(),
                   "INHERITS", decl->getLocation(), 1.0);
    }
    return true;
  }

  bool VisitEnumDecl(EnumDecl *decl) {
    if (!decl || !decl->isCompleteDefinition() || !project(decl->getLocation())) return true;
    emitSymbol("enum", decl->getNameAsString(), decl->getQualifiedNameAsString(),
               decl->getBeginLoc(), decl->getEndLoc(), "");
    return true;
  }

  bool VisitVarDecl(VarDecl *decl) {
    if (!decl || !decl->hasGlobalStorage() || decl->isLocalVarDecl() || !project(decl->getLocation())) return true;
    emitSymbol("global", decl->getNameAsString(), decl->getQualifiedNameAsString(),
               decl->getBeginLoc(), decl->getEndLoc(), decl->getType().getAsString());
    return true;
  }

  bool VisitCallExpr(CallExpr *expr) {
    if (!currentFunction_ || !project(expr->getExprLoc())) return true;
    if (const FunctionDecl *callee = expr->getDirectCallee()) {
      emitRelation(currentFunction_->getQualifiedNameAsString(), callee->getQualifiedNameAsString(),
                   "CALLS", expr->getExprLoc(), 1.0);
    } else {
      emitRelation(currentFunction_->getQualifiedNameAsString(), "<indirect-call>",
                   "POSSIBLE_CALL", expr->getExprLoc(), 0.5);
    }
    return true;
  }

  bool VisitDeclRefExpr(DeclRefExpr *expr) {
    if (!currentFunction_ || !project(expr->getExprLoc())) return true;
    const auto *variable = dyn_cast<VarDecl>(expr->getDecl());
    if (!variable || variable->isLocalVarDeclOrParm()) return true;
    emitRelation(currentFunction_->getQualifiedNameAsString(), variable->getQualifiedNameAsString(),
                 "REFERENCES", expr->getExprLoc(), 1.0);
    return true;
  }

 private:
  bool project(SourceLocation location) const {
    return !location.isInvalid() && !sm_.isInSystemHeader(location) && !sourcePath(sm_, location).empty();
  }

  void emitSymbol(const std::string &kind, const std::string &name, const std::string &qualified,
                  SourceLocation begin, SourceLocation end, const std::string &signature) const {
    llvm::outs() << "{\"record\":\"symbol\",\"kind\":\"" << escapeJson(kind)
                 << "\",\"name\":\"" << escapeJson(name)
                 << "\",\"qualified_name\":\"" << escapeJson(qualified)
                 << "\",\"file_path\":\"" << escapeJson(sourcePath(sm_, begin))
                 << "\",\"line_start\":" << lineOf(sm_, begin)
                 << ",\"line_end\":" << lineOf(sm_, end)
                 << ",\"signature\":\"" << escapeJson(signature)
                 << "\",\"certainty\":\"compiler\"}\n";
  }

  void emitRelation(const std::string &source, const std::string &target, const std::string &kind,
                    SourceLocation location, double confidence) const {
    llvm::outs() << "{\"record\":\"relation\",\"source\":\"" << escapeJson(source)
                 << "\",\"target\":\"" << escapeJson(target)
                 << "\",\"kind\":\"" << escapeJson(kind)
                 << "\",\"file_path\":\"" << escapeJson(sourcePath(sm_, location))
                 << "\",\"line\":" << lineOf(sm_, location)
                 << ",\"confidence\":" << confidence << ",\"certainty\":\"compiler\"}\n";
  }

  const SourceManager &sm_;
  const FunctionDecl *currentFunction_ = nullptr;
};

class Consumer : public ASTConsumer {
 public:
  explicit Consumer(ASTContext &context) : visitor_(context) {}
  void HandleTranslationUnit(ASTContext &context) override { visitor_.TraverseDecl(context.getTranslationUnitDecl()); }
 private:
  Visitor visitor_;
};

class Action : public ASTFrontendAction {
 public:
  std::unique_ptr<ASTConsumer> CreateASTConsumer(CompilerInstance &instance, llvm::StringRef) override {
    return std::make_unique<Consumer>(instance.getASTContext());
  }
};

int main(int argc, const char **argv) {
  auto parser = CommonOptionsParser::create(argc, argv, Category);
  if (!parser) { llvm::errs() << parser.takeError(); return 2; }
  ClangTool tool(parser->getCompilations(), parser->getSourcePathList());
  return tool.run(newFrontendActionFactory<Action>().get());
}
