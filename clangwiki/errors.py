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


class ModuleConfigurationError(ClangWikiError):
    pass


class OpenCodeError(ClangWikiError):
    pass


class MarkdownValidationError(ClangWikiError):
    pass


class GenerationCancelled(ClangWikiError):
    """Raised when a running generation is cancelled by the local web UI."""

    pass
