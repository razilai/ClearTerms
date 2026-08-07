"""Split a terms-of-service document into chunks the classifier can score.

Pure functions: text in, text out. No model, no cache, no database — the agent
layer's boundary rules apply here as they do in ``evidence.py``.

The unit of work is the **section**, not the paragraph and not a fixed window.
A cut that lands inside a clause is not merely untidy: an arbitration mandate
separated from its opt-out scores 2 in one chunk and nothing in the other, and
``services`` takes the per-category max, so the document is reported as
aggressive when it is standard. Section boundaries are the only cuts that
cannot cause that.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import tiktoken
from semantic_text_splitter import TextSplitter

#: How a caller measures a chunk against the budget. Injected rather than
#: hard-wired: the production counter is tiktoken, which downloads its BPE
#: table on first use, and unit tests must not depend on the network.
TokenCounter = Callable[[str], int]

# A heading is a number at the start of a line followed by a capitalised title.
# ``[ \t]`` rather than ``\s`` deliberately: ``\s`` matches newlines, which lets
# a match begin on a blank line and skip forward, so the reported offset would
# point at the line break rather than at the heading.
_NUMBERED = re.compile(r"^[ \t]*(\d+(?:\.\d+)*)\.?[ \t]+[A-Z]", re.MULTILINE)

# Real headings are short. Body prose that happens to open with a number runs
# past this, which is what separates "12. Termination." from a wrapped sentence.
MAX_HEADING_CHARS = 80

# Not the model's own tokenizer. qwen3's would need the HF `tokenizers` package
# and a hub download; cl100k is a close-enough proxy for English legal prose.
# It runs a little high on this text, so budgets built on it stay conservative
# — leave headroom rather than sizing a chunk to the context limit exactly.
TIKTOKEN_ENCODING = "cl100k_base"


@lru_cache
def tiktoken_counter() -> TokenCounter:
    """The production token counter. Built once — loading the table is slow."""
    encoding = tiktoken.get_encoding(TIKTOKEN_ENCODING)
    return lambda text: len(encoding.encode(text))


@dataclass(frozen=True, slots=True)
class Heading:
    """Where a section starts, and the heading line itself."""

    offset: int
    text: str


@dataclass(frozen=True, slots=True)
class Section:
    """One numbered section: its heading line and everything beneath it.

    ``heading`` is empty for the preamble that precedes the first numbered
    section — kept rather than dropped, since publishers put real obligations
    above section 1 often enough that discarding it would lose clauses.
    """

    heading: str
    body: str


def find_headings(text: str) -> list[Heading]:
    """Offsets of the lines that open a section, in document order.

    Two guards reject false positives that the pattern alone accepts:
    a length limit, and the requirement that section numbers ascend. The
    latter is what distinguishes a genuine section from an inline enumeration
    ("Prohibited activities include: 1. ... 2. ...") restarting at 1.
    """
    headings: list[Heading] = []
    highest: tuple[int, ...] = ()

    for match in _NUMBERED.finditer(text):
        start = match.start(1)
        line_end = text.find("\n", start)
        line = text[start : len(text) if line_end == -1 else line_end].rstrip()

        if len(line) > MAX_HEADING_CHARS:
            continue

        number = tuple(int(part) for part in match.group(1).split("."))
        if number <= highest:
            continue

        highest = number
        headings.append(Heading(offset=start, text=line))

    return headings


def split_sections(text: str) -> list[Section]:
    """Slice the document at its headings. Empty when no headings were found.

    An empty result is the caller's signal to fall back to sentence-aware
    windows: the document has no structure to preserve.
    """
    headings = find_headings(text)
    if not headings:
        return []

    sections: list[Section] = []

    preamble = text[: headings[0].offset].strip()
    if preamble:
        sections.append(Section(heading="", body=preamble))

    bounds = [heading.offset for heading in headings] + [len(text)]
    for index, heading in enumerate(headings):
        whole = text[bounds[index] : bounds[index + 1]]
        sections.append(
            Section(heading=heading.text, body=whole[len(heading.text) :].strip())
        )

    return sections


def _fit(
    sections: list[Section], count_tokens: TokenCounter, max_tokens: int
) -> list[str]:
    """Bring every section under budget, keeping its heading on each piece.

    Only the *body* is handed to the splitter. Handing it the whole section
    lets it cut at the newline after the heading, which strands the title in a
    chunk of its own and leaves the clause with nothing saying what it is.
    """
    units: list[str] = []

    for section in sections:
        prefix = f"{section.heading}\n" if section.heading else ""
        whole = f"{prefix}{section.body}"

        if count_tokens(whole) <= max_tokens:
            units.append(whole)
            continue

        # The heading is prepended after the split, so its cost comes out of
        # the budget first — otherwise every piece lands slightly over.
        body_budget = max(1, max_tokens - count_tokens(prefix))
        splitter = TextSplitter.from_callback(count_tokens, body_budget)
        units.extend(f"{prefix}{piece}" for piece in splitter.chunks(section.body))

    return units


def _pack(units: list[str], count_tokens: TokenCounter, max_tokens: int) -> list[str]:
    """Greedily merge consecutive units that fit together under the budget.

    A section is often a single sentence. Sending each as its own chunk pays
    the full system prompt to classify a dozen tokens, so neighbours travel
    together when there is room.
    """
    chunks: list[str] = []
    buffer = ""

    for unit in units:
        candidate = f"{buffer}\n\n{unit}" if buffer else unit
        if buffer and count_tokens(candidate) > max_tokens:
            chunks.append(buffer)
            buffer = unit
        else:
            buffer = candidate

    if buffer:
        chunks.append(buffer)
    return chunks


def split_document(
    text: str, *, count_tokens: TokenCounter, max_tokens: int
) -> list[str]:
    """Split a whole TOS into chunks, each one a forward pass for the model.

    Sections first, so cuts land on clause boundaries. A document with no
    detectable headings falls back to sentence-aware windows: worse chunks,
    but never a broken sentence and never an unbounded one.
    """
    if not text.strip():
        return []

    sections = split_sections(text)
    if not sections:
        splitter = TextSplitter.from_callback(count_tokens, max_tokens)
        return [chunk for chunk in splitter.chunks(text) if chunk.strip()]

    return _pack(_fit(sections, count_tokens, max_tokens), count_tokens, max_tokens)
