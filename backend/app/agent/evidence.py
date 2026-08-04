"""Verbatim-evidence checking for classifier output.

The classifier requires the model to quote the words that justify a score, so
that a hallucinated finding is detectable — a quote either appears in the chunk
or it does not, whereas a paraphrase can never be checked.

Enforcing that literally would fail on quotes that are substantively correct:
models retype curly quotes as straight ones, flatten en and em dashes, and fold
a line break into a space. Both sides are normalized before comparison so those
differences do not count against the model, while an invented or paraphrased
quote still fails.
"""

import re

_GLYPHS = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "–": "-",
        "—": "-",
    }
)

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Straighten quote and dash glyphs, collapse whitespace runs, casefold."""
    return _WHITESPACE.sub(" ", text.translate(_GLYPHS)).strip().casefold()


def is_verbatim(evidence: str, chunk: str) -> bool:
    """True if ``evidence`` appears in ``chunk`` once both are normalized.

    Empty or whitespace-only evidence is rejected: it would otherwise match
    every chunk, since the empty string is a substring of anything.
    """
    normalized = normalize(evidence)
    if not normalized:
        return False
    return normalized in normalize(chunk)
