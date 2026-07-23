#include <algorithm>
#include <string>
#include <utility>

#include "clang/AST/ASTConsumer.h"
#include "clang/AST/DeclCXX.h"
#include "clang/AST/Expr.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Frontend/FrontendAction.h"
#include "clang/Tooling/CommonOptionsParser.h"
#include "clang/Tooling/Tooling.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/raw_ostream.h"

using namespace clang;
using namespace clang::tooling;

static llvm::cl::OptionCategory Category("cpp-analyzer options");
static llvm::cl::opt<std::string> RepoRoot(
    "repo-root", llvm::cl::desc("Repository root used to relativize paths"),
    llvm::cl::init(""), llvm::cl::cat(Category));

static std::string escapeJson(llvm::StringRef input) {
  std::string output;
  for (char c : input) {
    switch (c) {
      case '\\': output += "\\\\"; break;
      case '"': output += "\\\""; break;
      case '\n': output += "\\n"; break;
      case '\r': output += "\\r"; break;
      case '\t': output += "\\t"; break;
      default: output += c;
    }
  }
  return output;
}

static std::string normalizedPath(const SourceManager &sm, SourceLocation location) {
  if (location.isInvalid()) return "";
  SourceLocation spelling = sm.getSpellingLoc(location);
  std::string path = sm.getFilename(spelling).str();
  std::replace(path.begin(), path.end(), '\\', '/');
  std::string root = RepoRoot;
  std::replace(root.begin(), root.end(), '\\', '/');
  while (!root.empty() && root.back() == '/') root.pop_back();
  if (!root.empty() && path.rfind(root + "/", 0) == 0) {
    path.erase(0, root.size() + 1);
  }
  return path;
}

static unsigned lineOf(const SourceManager &sm, SourceLocation location) {
  if (location.isInvalid()) return 0;
  return sm.getSpellingLineNumber(sm.getSpellingLoc(location));
}

class AnalyzerVisitor : public RecursiveASTVisitor<AnalyzerVisitor> {
 public:
  explicit AnalyzerVisitor(ASTContext &context)
      : context_(context), sm_(context.getSourceManager()) {}

  bool TraverseFunctionDecl(FunctionDecl *decl) {
    if (!decl) return true;
    const FunctionDecl *previous = currentFunction_;
    if (decl->hasBody()) currentFunction_ = decl;
    bool result = RecursiveASTVisitor::TraverseFunctionDecl(decl);
    currentFunction_ = previous;
    return result;
  }

  bool VisitFunctionDecl(FunctionDecl *decl) {
    if (!decl->hasBody() || !isProjectLocation(decl->getLocation())) return true;
    std::string kind = isa<CXXMethodDecl>(decl) ? "method" : "function";
    emitSymbol(kind, decl->getNameAsString(), decl->getQualifiedNameAsString(),
               decl->getBeginLoc(), decl->getEndLoc(), decl->getType().getAsString());
    return true;
  }

  bool VisitCXXRecordDecl(CXXRecordDecl *decl) {
    if (!decl->isThisDeclarationADefinition() || decl->isImplicit() ||
        !isProjectLocation(decl->getLocation())) return true;
    std::string kind = decl->isClass() ? "class" : "struct";
    emitSymbol(kind, decl->getNameAsString(), decl->getQualifiedNameAsString(),
               decl->getBeginLoc(), decl->getEndLoc(), "");
    for (const auto &base : decl->bases()) {
      const CXXRecordDecl *baseDecl = base.getType()->getAsCXXRecordDecl();
      std::string target = baseDecl ? baseDecl->getQualifiedNameAsString()
                                    : base.getType().getAsString();
      emitRelation(decl->getQualifiedNameAsString(), target, "INHERITS",
                   decl->getLocation(), 1.0);
    }
    return true;
  }

  bool VisitEnumDecl(EnumDecl *decl) {
    if (!decl->isCompleteDefinition() || !isProjectLocation(decl->getLocation())) return true;
    emitSymbol("enum", decl->getNameAsString(), decl->getQualifiedNameAsString(),
               decl->getBeginLoc(), decl->getEndLoc(), "");
    return true;
  }

  bool VisitCallExpr(CallExpr *expr) {
    if (!currentFunction_ || !isProjectLocation(expr->getExprLoc())) return true;
    if (const FunctionDecl *callee = expr->getDirectCallee()) {
      emitRelation(currentFunction_->getQualifiedNameAsString(),
                   callee->getQualifiedNameAsString(), "CALLS", expr->getExprLoc(), 1.0);
    } else {
      emitRelation(currentFunction_->getQualifiedNameAsString(),
                   expr->getCallee()->getStmtClassName(), "POSSIBLE_CALL",
                   expr->getExprLoc(), 0.5);
    }
    return true;
  }

  bool VisitDeclRefExpr(DeclRefExpr *expr) {
    if (!currentFunction_ || !isProjectLocation(expr->getExprLoc())) return true;
    const auto *variable = dyn_cast<VarDecl>(expr->getDecl());
    if (!variable || variable->isLocalVarDeclOrParm()) return true;
    emitRelation(currentFunction_->getQualifiedNameAsString(),
                 variable->getQualifiedNameAsString(), "REFERENCES",
                 expr->getExprLoc(), 0.9);
    return true;
  }

 private:
  bool isProjectLocation(SourceLocation location) const {
    if (location.isInvalid() || sm_.isInSystemHeader(location)) return false;
    const std::string path = normalizedPath(sm_, location);
    return !path.empty() && (RepoRoot.empty() || path.find(':') == std::string::npos);
  }

  void emitSymbol(const std::string &kind, const std::string &name,
                  const std::string &qualified, SourceLocation begin,
                  SourceLocation end, const std::string &signature) {
    llvm::outs() << "{\"record\":\"symbol\",\"kind\":\"" << escapeJson(kind)
                 << "\",\"name\":\"" << escapeJson(name)
                 << "\",\"qualified_name\":\"" << escapeJson(qualified)
                 << "\",\"file_path\":\"" << escapeJson(normalizedPath(sm_, begin))
                 << "\",\"line_start\":" << lineOf(sm_, begin)
                 << ",\"line_end\":" << lineOf(sm_, end)
                 << ",\"signature\":\"" << escapeJson(signature) << "\"}\n";
  }

  void emitRelation(const std::string &source, const std::string &target,
                    const std::string &kind, SourceLocation location,
                    double confidence) {
    llvm::outs() << "{\"record\":\"relation\",\"source\":\"" << escapeJson(source)
                 << "\",\"target\":\"" << escapeJson(target)
                 << "\",\"kind\":\"" << escapeJson(kind)
                 << "\",\"file_path\":\"" << escapeJson(normalizedPath(sm_, location))
                 << "\",\"line\":" << lineOf(sm_, location)
                 << ",\"confidence\":" << confidence << "}\n";
  }

  ASTContext &context_;
  SourceManager &sm_;
  const FunctionDecl *currentFunction_ = nullptr;
};

class AnalyzerConsumer : public ASTConsumer {
 public:
  explicit AnalyzerConsumer(ASTContext &context) : visitor_(context) {}
  void HandleTranslationUnit(ASTContext &context) override {
    visitor_.TraverseDecl(context.getTranslationUnitDecl());
  }
 private:
  AnalyzerVisitor visitor_;
};

class AnalyzerAction : public ASTFrontendAction {
 public:
  std::unique_ptr<ASTConsumer> CreateASTConsumer(CompilerInstance &ci,
                                                 llvm::StringRef) override {
    return std::make_unique<AnalyzerConsumer>(ci.getASTContext());
  }
};

int main(int argc, const char **argv) {
  auto parser = CommonOptionsParser::create(argc, argv, Category);
  if (!parser) {
    llvm::errs() << parser.takeError();
    return 2;
  }
  ClangTool tool(parser->getCompilations(), parser->getSourcePathList());
  return tool.run(newFrontendActionFactory<AnalyzerAction>().get());
}

