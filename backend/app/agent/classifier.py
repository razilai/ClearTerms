"""TOS chunk classifier: PydanticAI agent against Ollama.

Plain text in, structured scores out. No cache, db, or preference awareness.
"""

import json
import logging
import tomllib
from functools import lru_cache
from importlib import resources
from typing import Any

from pydantic_ai import ModelRetry

from app.agent.categories import (
    CATEGORY_SPECS,
    SCORE_AGGRESSIVE,
    SCORE_SCALE,
    SCORE_STANDARD,
    ClauseCategory,
)
from app.agent.evidence import is_verbatim
from app.agent.output import Finding

logger = logging.getLogger(__name__)

PROMPTS_PACKAGE = "app.agent.prompts"
PROMPTS_FILE = "prompts.toml"

MAX_EVIDENCE_RETRIES = 1


@lru_cache
def load_prompts() -> dict[str, Any]:
    """Load the prompt template and few-shot examples from package data."""
    text = resources.files(PROMPTS_PACKAGE).joinpath(PROMPTS_FILE).read_text("utf-8")
    return tomllib.loads(text)


def render_score_scale() -> str:
    """Render the 0-2 scale as prompt lines."""
    return "\n".join(
        f"- {score}: {meaning}" for score, meaning in sorted(SCORE_SCALE.items())
    )


def render_categories() -> str:
    """Render the neutral half of every ``CategorySpec``.

    ``display_name`` and ``description`` are deliberately excluded: they carry
    the product voice, and loaded framing biases a small model toward finding
    aggression everywhere.
    """
    blocks: list[str] = []
    for category in ClauseCategory:
        spec = CATEGORY_SPECS[category]
        boundaries = "\n".join(f"  - {rule}" for rule in spec.boundaries)
        blocks.append(
            f"### {category.value}\n"
            f"What counts: {spec.detection}\n"
            f"Score {SCORE_STANDARD} when: {spec.standard}\n"
            f"Score {SCORE_AGGRESSIVE} when: {spec.aggressive}\n"
            f"Boundaries:\n{boundaries}"
        )
    return "\n\n".join(blocks)


@lru_cache
def render_system_prompt() -> str:
    """Build the system prompt: template + score scale + specs + example.

    Stable across every chunk, so Ollama reuses its KV cache for the prefix.
    """
    prompts = load_prompts()
    example = prompts["few_shot"]["examples"][0]
    return prompts["system"]["prompt"].format(
        score_scale=render_score_scale(),
        categories=render_categories(),
        example_text=example["text"].strip(),
        example_output=json.dumps({"findings": example["findings"]}, indent=2),
    )


def check_evidence(findings: list[Finding], chunk: str, retry: int) -> list[Finding]:
    """Enforce that every finding quotes the chunk verbatim.

    Constrained decoding guarantees the output is schema-shaped; it says
    nothing about whether the quote is real. This is that check.

    On the first failing attempt the model is asked to try again, with the
    offending categories named. If it fails again, the offending findings are
    dropped — they densify to a score of 0 — so that one stubborn quote does
    not cost the chunk its other findings.
    """
    bad = [f for f in findings if not is_verbatim(f.evidence, chunk)]
    if not bad:
        return findings

    if retry < MAX_EVIDENCE_RETRIES:
        names = ", ".join(sorted(f.category.value for f in bad))
        raise ModelRetry(
            f"The evidence given for these categories does not appear in the "
            f"excerpt: {names}. Copy the exact words from the excerpt, or leave "
            f"the category out."
        )

    for finding in bad:
        logger.warning(
            "dropping %s: evidence not found in chunk", finding.category.value
        )
    dropped = {id(f) for f in bad}
    return [f for f in findings if id(f) not in dropped]
