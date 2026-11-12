"""Tool error taxonomy."""

from __future__ import annotations


class ToolError(Exception):
    """Base class for all tool errors."""

    retryable: bool = False


class ToolNotFoundError(ToolError):
    """The requested tool is not registered."""


class ToolValidationError(ToolError):
    """Arguments do not match the tool's schema."""

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or [message]


class ToolExecutionError(ToolError):
    """The tool raised an exception while running."""


class ToolTimeoutError(ToolError):
    """The tool exceeded its timeout."""

    retryable = True


class ToolRateLimitError(ToolError):
    """The tool's rate limit was exceeded."""

    retryable = True


class ToolTransientError(ToolError):
    """Raise this from a tool to signal a retryable failure (e.g. a flaky network call)."""

    retryable = True


class ToolSandboxViolation(ToolError):
    """Code in the sandbox attempted a disallowed operation."""
