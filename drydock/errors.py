"""Error taxonomy (docs/design/03-lld.md section 8).

The CLI maps any ``DrydockError`` to exit code 2 with its message; anything else is a bug
and exits 1 with a traceback.
"""

from __future__ import annotations


class DrydockError(Exception):
    """Base class for every expected, user-facing DRYDOCK failure."""


class CorpusError(DrydockError):
    """A corpus spec, sample or manifest is missing, malformed or does not match its pin."""


class ProviderError(DrydockError):
    """A generation provider failed or returned an unusable artifact."""


class SandboxError(DrydockError):
    """The evaluation sandbox could not run the candidate pipeline."""


class SandboxTimeout(SandboxError):  # noqa: N818 - name frozen by LLD section 8
    """The candidate pipeline exceeded the sandbox wall-clock budget.

    ``run_in_sandbox`` reports a timeout as ``SandboxResult.timed_out`` so the harness can
    turn it into an H1 finding; this class is reserved for callers that need to raise.
    """


class RunNotFound(DrydockError):  # noqa: N818 - name frozen by LLD section 8
    """No run exists with the requested id."""


class InvalidTransition(DrydockError):  # noqa: N818 - name frozen by LLD section 8
    """A run lifecycle transition was requested from an incompatible status."""
