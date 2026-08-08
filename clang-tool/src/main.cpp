#include <clang-c/CXCompilationDatabase.h>
#include <clang-c/Index.h>

#include <algorithm>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

static std::string text(CXString value) {
  const char* raw = clang_getCString(value);
  std::string result = raw ? raw : "";
  clang_disposeString(value);
  return result;
}

static std::string jsonEscape(const std::string& value) {
  std::string out;
  for (unsigned char c : value) {
    switch (c) {
      case '\\': out += "\\\\"; break;
      case '"': out += "\\\""; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default:
        if (c < 0x20) {
          static const char* hex = "0123456789abcdef";
          out += "\\u00";
          out += hex[c >> 4];
          out += hex[c & 0x0f];
        } else {
          out += static_cast<char>(c);
        }
    }
  }
  return out;
}

struct Location {
  std::string path;
  unsigned line = 0;
};

class Analyzer {
 public:
  explicit Analyzer(fs::path root) : root_(fs::weakly_canonical(std::move(root))) {}

  bool analyze(CXTranslationUnit unit) {
    CXCursor cursor = clang_getTranslationUnitCursor(unit);
    visit(cursor, "", "");
    return true;
  }

 private:
  struct VisitContext {
    Analyzer* analyzer;
    std::string currentFunction;
    std::string currentRecord;
  };

  static CXChildVisitResult visitor(CXCursor cursor, CXCursor, CXClientData data) {
    auto* context = static_cast<VisitContext*>(data);
    context->analyzer->visit(cursor, context->currentFunction, context->currentRecord);
    return CXChildVisit_Continue;
  }

  void visit(CXCursor cursor, const std::string& parentFunction, const std::string& parentRecord) {
    if (clang_Location_isInSystemHeader(clang_getCursorLocation(cursor))) return;
    const CXCursorKind kind = clang_getCursorKind(cursor);
    const Location location = locate(cursor);
    std::string currentFunction = parentFunction;
    std::string currentRecord = parentRecord;

    if (isFunction(kind) && clang_isCursorDefinition(cursor) && project(location)) {
      currentFunction = qualified(cursor);
      emitSymbol(kind == CXCursor_CXXMethod ? "method" : "function", cursor, location);
    } else if (isRecord(kind) && clang_isCursorDefinition(cursor) && project(location)) {
      const char* recordKind = kind == CXCursor_StructDecl ? "struct" :
                               kind == CXCursor_UnionDecl ? "union" : "class";
      emitSymbol(recordKind, cursor, location);
      currentRecord = qualified(cursor);
    } else if (kind == CXCursor_EnumDecl && clang_isCursorDefinition(cursor) && project(location)) {
      emitSymbol("enum", cursor, location);
    } else if (kind == CXCursor_VarDecl && isGlobal(cursor) && project(location)) {
      emitSymbol("global", cursor, location);
    } else if (kind == CXCursor_CXXBaseSpecifier && !parentRecord.empty() && project(location)) {
      CXCursor referenced = clang_getCursorReferenced(cursor);
      emitRelation(parentRecord, qualified(referenced), "INHERITS", location, 1.0);
    } else if (kind == CXCursor_CallExpr && !parentFunction.empty() && project(location)) {
      CXCursor referenced = clang_getCursorReferenced(cursor);
      if (!clang_Cursor_isNull(referenced)) {
        emitRelation(parentFunction, qualified(referenced), "CALLS", location, 1.0);
      } else {
        emitRelation(parentFunction, "<indirect-call>", "POSSIBLE_CALL", location, 0.5);
      }
    } else if (kind == CXCursor_DeclRefExpr && !parentFunction.empty() && project(location)) {
      CXCursor referenced = clang_getCursorReferenced(cursor);
      if (clang_getCursorKind(referenced) == CXCursor_VarDecl && isGlobal(referenced)) {
        emitRelation(parentFunction, qualified(referenced), "REFERENCES", location, 1.0);
      }
    }

    VisitContext context{this, currentFunction, currentRecord};
    clang_visitChildren(cursor, visitor, &context);
  }

  static bool isFunction(CXCursorKind kind) {
    return kind == CXCursor_FunctionDecl || kind == CXCursor_CXXMethod ||
           kind == CXCursor_Constructor || kind == CXCursor_Destructor ||
           kind == CXCursor_FunctionTemplate;
  }

  static bool isRecord(CXCursorKind kind) {
    return kind == CXCursor_StructDecl || kind == CXCursor_UnionDecl || kind == CXCursor_ClassDecl;
  }

  static bool isGlobal(CXCursor cursor) {
    CXCursor parent = clang_getCursorSemanticParent(cursor);
    const CXCursorKind kind = clang_getCursorKind(parent);
    return kind == CXCursor_TranslationUnit || kind == CXCursor_Namespace || isRecord(kind);
  }

  Location locate(CXCursor cursor) const {
    CXFile file = nullptr;
    unsigned line = 0, column = 0, offset = 0;
    clang_getSpellingLocation(clang_getCursorLocation(cursor), &file, &line, &column, &offset);
    if (!file) return {};
    fs::path path = fs::weakly_canonical(fs::path(text(clang_getFileName(file))));
    std::error_code error;
    fs::path relative = fs::relative(path, root_, error);
    const std::string generic = relative.generic_string();
    if (error || relative.empty() || generic == ".." || generic.rfind("../", 0) == 0) return {};
    return {relative.generic_string(), line};
  }

  bool project(const Location& location) const { return !location.path.empty(); }

  static std::string qualified(CXCursor cursor) {
    if (clang_Cursor_isNull(cursor)) return "";
    std::string name = text(clang_getCursorSpelling(cursor));
    CXCursor parent = clang_getCursorSemanticParent(cursor);
    std::vector<std::string> parts;
    while (!clang_Cursor_isNull(parent)) {
      CXCursorKind kind = clang_getCursorKind(parent);
      if (kind == CXCursor_TranslationUnit) break;
      if (kind == CXCursor_Namespace || isRecord(kind)) {
        std::string part = text(clang_getCursorSpelling(parent));
        if (!part.empty()) parts.push_back(part);
      }
      parent = clang_getCursorSemanticParent(parent);
    }
    std::reverse(parts.begin(), parts.end());
    std::string result;
    for (const auto& part : parts) result += part + "::";
    return result + name;
  }

  void emitSymbol(const std::string& kind, CXCursor cursor, const Location& location) const {
    CXSourceRange range = clang_getCursorExtent(cursor);
    CXFile endFile = nullptr;
    unsigned endLine = location.line, column = 0, offset = 0;
    clang_getSpellingLocation(clang_getRangeEnd(range), &endFile, &endLine, &column, &offset);
    const std::string name = text(clang_getCursorSpelling(cursor));
    const std::string signature = text(clang_getTypeSpelling(clang_getCursorType(cursor)));
    std::cout << "{\"record\":\"symbol\",\"kind\":\"" << jsonEscape(kind)
              << "\",\"name\":\"" << jsonEscape(name)
              << "\",\"qualified_name\":\"" << jsonEscape(qualified(cursor))
              << "\",\"file_path\":\"" << jsonEscape(location.path)
              << "\",\"line_start\":" << location.line
              << ",\"line_end\":" << endLine
              << ",\"signature\":\"" << jsonEscape(signature)
              << "\",\"certainty\":\"compiler\"}\n";
  }

  static void emitRelation(const std::string& source, const std::string& target,
                           const std::string& kind, const Location& location, double confidence) {
    if (source.empty() || target.empty()) return;
    std::cout << "{\"record\":\"relation\",\"source\":\"" << jsonEscape(source)
              << "\",\"target\":\"" << jsonEscape(target)
              << "\",\"kind\":\"" << jsonEscape(kind)
              << "\",\"file_path\":\"" << jsonEscape(location.path)
              << "\",\"line\":" << location.line
              << ",\"confidence\":" << confidence
              << ",\"certainty\":\"compiler\"}\n";
  }

  fs::path root_;
};

static void usage() {
  std::cerr << "Usage: clangwiki-analyzer -p <compdb-dir> --repo-root <repo> <source>...\n";
}

static std::vector<std::string> commandArguments(CXCompileCommand command, const fs::path& source) {
  std::vector<std::string> result;
  const unsigned count = clang_CompileCommand_getNumArgs(command);
  bool skipNext = false;
  for (unsigned index = 1; index < count; ++index) {
    std::string argument = text(clang_CompileCommand_getArg(command, index));
    if (skipNext) { skipNext = false; continue; }
    if (argument == "-c") continue;
    if (argument == "-o") { skipNext = true; continue; }
    if (argument.rfind("/Fo", 0) == 0) continue;
    std::error_code error;
    fs::path candidate = fs::weakly_canonical(fs::path(argument), error);
    if (!error && candidate == fs::weakly_canonical(source)) continue;
    result.push_back(std::move(argument));
  }
  return result;
}

int main(int argc, char** argv) {
  fs::path databaseDirectory;
  fs::path repositoryRoot;
  std::vector<fs::path> sources;
  for (int index = 1; index < argc; ++index) {
    std::string argument = argv[index];
    if (argument == "-p" && index + 1 < argc) databaseDirectory = argv[++index];
    else if (argument == "--repo-root" && index + 1 < argc) repositoryRoot = argv[++index];
    else if (argument == "--help" || argument == "-h") { usage(); return 0; }
    else sources.emplace_back(argument);
  }
  if (databaseDirectory.empty() || repositoryRoot.empty() || sources.empty()) { usage(); return 2; }

  CXCompilationDatabase_Error databaseError;
  CXCompilationDatabase database = clang_CompilationDatabase_fromDirectory(
      databaseDirectory.string().c_str(), &databaseError);
  if (databaseError != CXCompilationDatabase_NoError) {
    std::cerr << "Cannot open compile_commands.json in " << databaseDirectory << "\n";
    return 2;
  }

  CXIndex index = clang_createIndex(0, 0);
  int parsed = 0;
  for (const fs::path& source : sources) {
    const fs::path absolute = fs::weakly_canonical(source);
    CXCompileCommands commands = clang_CompilationDatabase_getCompileCommands(database, absolute.string().c_str());
    if (clang_CompileCommands_getSize(commands) == 0) {
      std::cerr << "No compile command for " << absolute << "\n";
      clang_CompileCommands_dispose(commands);
      continue;
    }
    CXCompileCommand command = clang_CompileCommands_getCommand(commands, 0);
    const fs::path previousDirectory = fs::current_path();
    const fs::path commandDirectory = fs::path(text(clang_CompileCommand_getDirectory(command)));
    std::error_code directoryError;
    fs::current_path(commandDirectory, directoryError);
    if (directoryError) {
      std::cerr << "Cannot enter compile command directory " << commandDirectory << "\n";
      clang_CompileCommands_dispose(commands);
      continue;
    }
    std::vector<std::string> arguments = commandArguments(command, absolute);
    std::vector<const char*> raw;
    raw.reserve(arguments.size());
    for (const auto& argument : arguments) raw.push_back(argument.c_str());

    CXTranslationUnit unit = nullptr;
    CXErrorCode error = clang_parseTranslationUnit2(index, absolute.string().c_str(), raw.data(),
        static_cast<int>(raw.size()), nullptr, 0, CXTranslationUnit_DetailedPreprocessingRecord, &unit);
    fs::current_path(previousDirectory, directoryError);
    if (error != CXError_Success || !unit) {
      std::cerr << "libclang failed to parse " << absolute << " (error " << error << ")\n";
    } else {
      Analyzer(repositoryRoot).analyze(unit);
      clang_disposeTranslationUnit(unit);
      ++parsed;
    }
    clang_CompileCommands_dispose(commands);
  }
  clang_disposeIndex(index);
  clang_CompilationDatabase_dispose(database);
  return parsed == 0 ? 3 : 0;
}
