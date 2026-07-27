class ClangWikiError(RuntimeError):
    """Base error with a user-actionable message."""


class RepositoryError(ClangWikiError):
    pass


class CMakeError(ClangWikiError):
    pass


class CompilationDatabaseError(ClangWikiError):
    pass


class AnalysisError(ClangWikiError):
    pass


class OpenCodeError(ClangWikiError):
    pass


class MarkdownValidationError(ClangWikiError):
    pass

