#include <clang-c/CXCompilationDatabase.h>
#include <clang-c/Index.h>

#include <algorithm>
#include <filesystem>
#include <fstream>
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

static std::string utf8(const fs::path& value) {
  return value.u8string();
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
    visit(cursor, "", "", clang_getNullCursor());
    return true;
  }

 private:
  struct VisitContext {
    Analyzer* analyzer;
    std::string currentFunction;
    std::string currentRecord;
  };

  static CXChildVisitResult visitor(CXCursor cursor, CXCursor parent, CXClientData data) {
    auto* context = static_cast<VisitContext*>(data);
    context->analyzer->visit(cursor, context->currentFunction, context->currentRecord, parent);
    return CXChildVisit_Continue;
  }

  void visit(CXCursor cursor, const std::string& parentFunction, const std::string& parentRecord,
             CXCursor parentCursor) {
    if (clang_Location_isInSystemHeader(clang_getCursorLocation(cursor))) return;
    const CXCursorKind kind = clang_getCursorKind(cursor);
    const Location location = locate(cursor);
    std::string currentFunction = parentFunction;
    std::string currentRecord = parentRecord;

    if (isFunction(kind) && clang_isCursorDefinition(cursor) && project(location)) {
      currentFunction = qualified(cursor);
      emitSymbol(kind == CXCursor_CXXMethod ? "method" : "function", cursor, location);
      emitRelation(currentFunction, text(clang_getTypeSpelling(clang_getCursorResultType(cursor))), "RETURNS_TYPE", location, 1.0);
    } else if (isRecord(kind) && clang_isCursorDefinition(cursor) && project(location)) {
      const char* recordKind = kind == CXCursor_StructDecl ? "struct" :
                               kind == CXCursor_UnionDecl ? "union" : "class";
      emitSymbol(recordKind, cursor, location);
      currentRecord = qualified(cursor);
    } else if (kind == CXCursor_EnumDecl && clang_isCursorDefinition(cursor) && project(location)) {
      emitSymbol("enum", cursor, location);
      currentRecord = qualified(cursor);
    } else if (kind == CXCursor_ParmDecl && !parentFunction.empty() && project(location)) {
      emitSymbol("parameter", cursor, location);
      emitRelation(parentFunction, qualified(cursor), "HAS_PARAMETER", location, 1.0);
      emitRelation(qualified(cursor), text(clang_getTypeSpelling(clang_getCursorType(cursor))), "USES_TYPE", location, 1.0);
    } else if (kind == CXCursor_FieldDecl && !parentRecord.empty() && project(location)) {
      emitSymbol("field", cursor, location);
      emitRelation(parentRecord, qualified(cursor), "HAS_FIELD", location, 1.0);
      emitRelation(qualified(cursor), text(clang_getTypeSpelling(clang_getCursorType(cursor))), "USES_TYPE", location, 1.0);
    } else if (kind == CXCursor_EnumConstantDecl && !parentRecord.empty() && project(location)) {
      emitSymbol("enum_value", cursor, location);
      emitRelation(parentRecord, qualified(cursor), "HAS_VALUE", location, 1.0);
    } else if (kind == CXCursor_TypedefDecl && project(location)) {
      emitSymbol("typedef", cursor, location);
      emitRelation(qualified(cursor), text(clang_getTypeSpelling(clang_getTypedefDeclUnderlyingType(cursor))), "USES_TYPE", location, 1.0);
    } else if (kind == CXCursor_MacroDefinition && project(location)) {
      emitSymbol("macro", cursor, location);
    } else if (kind == CXCursor_InclusionDirective && project(location)) {
      CXFile included = clang_getIncludedFile(cursor);
      emitRelation(location.path, included ? text(clang_getFileName(included)) : text(clang_getCursorSpelling(cursor)), "INCLUDES", location, 1.0);
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
        emitRelation(parentFunction, qualified(referenced), isWriteReference(cursor, parentCursor) ? "WRITES" : "READS", location, 1.0);
      } else if (isFunction(clang_getCursorKind(referenced)) && clang_getCursorKind(parentCursor) != CXCursor_CallExpr) {
        // A function referenced outside the direct callee position is commonly
        // a callback/function-pointer value. Keep the exact reference as a
        // compiler fact; higher-level callback rules may classify registration.
        emitRelation(parentFunction, qualified(referenced), "REFERENCES", location, 1.0);
      }
    } else if (kind == CXCursor_MemberRefExpr && !parentFunction.empty() && project(location)) {
      CXCursor referenced = clang_getCursorReferenced(cursor);
      if (clang_getCursorKind(referenced) == CXCursor_FieldDecl) {
        emitRelation(parentFunction, qualified(referenced), isWriteReference(cursor, parentCursor) ? "WRITES" : "READS", location, 1.0);
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

  static bool isWriteReference(CXCursor cursor, CXCursor parent) {
    const CXCursorKind parentKind = clang_getCursorKind(parent);
    if (parentKind == CXCursor_CompoundAssignOperator) return true;
    CXTranslationUnit unit = clang_Cursor_getTranslationUnit(parent);
    if (!unit) return false;
    CXToken* tokens = nullptr;
    unsigned count = 0;
    clang_tokenize(unit, clang_getCursorExtent(parent), &tokens, &count);
    bool write = false;
    if (parentKind == CXCursor_UnaryOperator) {
      for (unsigned index = 0; index < count; ++index) {
        const std::string token = text(clang_getTokenSpelling(unit, tokens[index]));
        if (token == "++" || token == "--") { write = true; break; }
      }
    } else if (parentKind == CXCursor_BinaryOperator) {
      unsigned cursorOffset = 0, line = 0, column = 0;
      CXFile cursorFile = nullptr;
      clang_getSpellingLocation(clang_getCursorLocation(cursor), &cursorFile, &line, &column, &cursorOffset);
      for (unsigned index = 0; index < count; ++index) {
        if (text(clang_getTokenSpelling(unit, tokens[index])) != "=") continue;
        unsigned tokenOffset = 0;
        CXFile tokenFile = nullptr;
        clang_getSpellingLocation(clang_getTokenLocation(unit, tokens[index]), &tokenFile, &line, &column, &tokenOffset);
        write = cursorFile == tokenFile && cursorOffset < tokenOffset;
        break;
      }
    }
    clang_disposeTokens(unit, tokens, count);
    return write;
  }

  Location locate(CXCursor cursor) const {
    CXFile file = nullptr;
    unsigned line = 0, column = 0, offset = 0;
    clang_getSpellingLocation(clang_getCursorLocation(cursor), &file, &line, &column, &offset);
    if (!file) return {};
    fs::path path = fs::weakly_canonical(fs::u8path(text(clang_getFileName(file))));
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
    const std::string usr = text(clang_getCursorUSR(cursor));
    std::cout << "{\"record\":\"symbol\",\"kind\":\"" << jsonEscape(kind)
              << "\",\"name\":\"" << jsonEscape(name)
              << "\",\"qualified_name\":\"" << jsonEscape(qualified(cursor))
              << "\",\"file_path\":\"" << jsonEscape(location.path)
              << "\",\"line_start\":" << location.line
              << ",\"line_end\":" << endLine
              << ",\"signature\":\"" << jsonEscape(signature)
              << "\",\"usr\":\"" << jsonEscape(usr)
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
  std::cerr << "Usage: clangwiki-analyzer -p <compdb-dir> --repo-root <repo> "
               "[--sources-file <file> | <source>...]\n";
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
    fs::path candidate = fs::weakly_canonical(fs::u8path(argument), error);
    if (!error && candidate == fs::weakly_canonical(source)) continue;
    result.push_back(std::move(argument));
  }
  return result;
}

int wmain(int argc, wchar_t** argv) {
  fs::path databaseDirectory;
  fs::path repositoryRoot;
  fs::path sourceList;
  std::vector<fs::path> sources;
  for (int index = 1; index < argc; ++index) {
    std::wstring argument = argv[index];
    if (argument == L"-p" && index + 1 < argc) databaseDirectory = fs::path(argv[++index]);
    else if (argument == L"--repo-root" && index + 1 < argc) repositoryRoot = fs::path(argv[++index]);
    else if (argument == L"--sources-file" && index + 1 < argc) sourceList = fs::path(argv[++index]);
    else if (argument == L"--help" || argument == L"-h") { usage(); return 0; }
    else sources.emplace_back(fs::path(argv[index]));
  }
  if (!sourceList.empty()) {
    std::ifstream input(sourceList, std::ios::binary);
    if (!input) {
      std::cerr << "Cannot open source list " << sourceList.string() << "\n";
      return 2;
    }
    std::string line;
    while (std::getline(input, line)) {
      if (!line.empty() && line.back() == '\r') line.pop_back();
      if (!line.empty()) sources.emplace_back(fs::u8path(line));
    }
  }
  if (databaseDirectory.empty() || repositoryRoot.empty() || sources.empty()) { usage(); return 2; }

  CXCompilationDatabase_Error databaseError;
  CXCompilationDatabase database = clang_CompilationDatabase_fromDirectory(
      utf8(databaseDirectory).c_str(), &databaseError);
  if (databaseError != CXCompilationDatabase_NoError) {
    std::cerr << "Cannot open compile_commands.json in " << databaseDirectory << "\n";
    return 2;
  }

  CXIndex index = clang_createIndex(0, 0);
  int parsed = 0;
  for (const fs::path& source : sources) {
    const fs::path absolute = fs::weakly_canonical(source);
    CXCompileCommands commands = clang_CompilationDatabase_getCompileCommands(database, utf8(absolute).c_str());
    if (clang_CompileCommands_getSize(commands) == 0) {
      std::cerr << "No compile command for " << absolute << "\n";
      clang_CompileCommands_dispose(commands);
      continue;
    }
    CXCompileCommand command = clang_CompileCommands_getCommand(commands, 0);
    const fs::path previousDirectory = fs::current_path();
    const fs::path commandDirectory = fs::u8path(text(clang_CompileCommand_getDirectory(command)));
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
    CXErrorCode error = clang_parseTranslationUnit2(index, utf8(absolute).c_str(), raw.data(),
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
