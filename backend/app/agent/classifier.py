"""TOS chunk classifier: PydanticAI agent against Ollama.

Plain text in, structured scores out. No cache, db, or preference awareness.
"""

import asyncio
import json
import logging
import tomllib
from functools import lru_cache
from importlib import resources
from typing import Any

from pydantic_ai import Agent, ModelRetry, NativeOutput, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings

from app.agent.categories import (
    CATEGORY_SPECS,
    SCORE_AGGRESSIVE,
    SCORE_SCALE,
    SCORE_STANDARD,
    ClauseCategory,
)
from app.agent.chunking import split_document, tiktoken_counter
from app.agent.evidence import is_verbatim
from app.agent.output import densify
from app.core.config import settings
from app.schemas.analysis import (
    ChunkClassification,
    ChunkFindings,
    ClauseScore,
    Finding,
)

logger = logging.getLogger(__name__)

PROMPTS_PACKAGE = "app.agent.prompts"
PROMPTS_FILE = "prompts.toml"

MAX_EVIDENCE_RETRIES = 1

# Ollama serialises requests past OLLAMA_NUM_PARALLEL, so a wider fan-out buys
# nothing and just queues. Re-measure on the GPU VM and match it to that value.
MAX_CONCURRENT_CHUNKS = 4


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


@lru_cache
def build_agent() -> Agent[str, ChunkFindings]:
    """Construct the classifier agent. Cached — one per process.

    ``deps_type=str`` carries the chunk text so the output validator can check
    quoted evidence against the source.

    For Ollama, ``NativeOutput`` sends the schema in ``response_format`` so the
    decode is constrained against it, rather than PydanticAI's default tool
    calling, which validates after the fact and pays a full forward pass per
    failure. Hosted models on OpenRouter don't all advertise native
    (json_schema) structured output — PydanticAI raises ``UserError`` when they
    don't — so there we fall back to PydanticAI's default tool-call output,
    which OpenRouter models support. The evidence validator below runs the same
    on either mode.
    """
    output_type: NativeOutput[ChunkFindings] | type[ChunkFindings]
    if settings.use_openrouter:
        provider: OllamaProvider | OpenRouterProvider = OpenRouterProvider(
            api_key=settings.openrouter_api_key.get_secret_value(),
        )
        output_type = ChunkFindings
    else:
        provider = OllamaProvider(base_url=f"{settings.ollama_base_url.rstrip('/')}/v1")
        output_type = NativeOutput(ChunkFindings)
    model = OpenAIChatModel(settings.agent_model, provider=provider)
    agent = Agent(
        model,
        deps_type=str,
        output_type=output_type,
        instructions=render_system_prompt(),
        retries=MAX_EVIDENCE_RETRIES,
        model_settings=ModelSettings(temperature=0.0),
    )

    @agent.output_validator
    def _validate_evidence(
        ctx: RunContext[str], output: ChunkFindings
    ) -> ChunkFindings:
        return ChunkFindings(
            findings=check_evidence(output.findings, ctx.deps, ctx.retry)
        )

    return agent


async def classify_chunk(text: str) -> ChunkClassification:
    """Classify one TOS chunk against all clause categories.

    Returns a score for every category, including the ones the model did not
    report. ``deps`` is the raw chunk, so evidence is checked against exactly
    the text the model was shown.
    """
    # The default model (gemma3:4b) is non-thinking, so this is a plain prompt.
    # `/no_think` is a model-side switch that suppresses a reasoning chain on
    # thinking models — harmless text here. Do NOT swap in a hybrid-reasoning
    # model (qwen3, deepseek-r1, ...): its `<think>` chain fights NativeOutput's
    # constrained JSON decoding over the /v1 endpoint and the request hangs
    # forever. Ollama's /v1 can't disable thinking; only native /api/chat can.
    result = await build_agent().run(f"/no_think\nExcerpt:\n{text}", deps=text)
    return densify(result.output.findings)


async def analyze(text: str) -> list[ClauseScore]:
    """Classify a whole document: chunk it, score the chunks, merge the results.

    The only entry point ``services`` needs. Takes plain text and returns one
    score per category for the document as a whole.

    Chunks are independent, so they run concurrently, bounded by a semaphore:
    Ollama serialises requests beyond ``OLLAMA_NUM_PARALLEL`` anyway, and an
    unbounded fan-out on a long document would queue hundreds of them.

    Merging is just ``densify`` again over the pooled findings. That gives the
    per-category max across chunks for free, drops findings repeated verbatim
    in two chunks, and restores the all-six-categories guarantee.
    """
    chunks = split_document(
        text, count_tokens=tiktoken_counter(), max_tokens=settings.chunk_tokens
    )
    limit = asyncio.Semaphore(MAX_CONCURRENT_CHUNKS)

    async def classify(chunk: str) -> ChunkClassification:
        async with limit:
            return await classify_chunk(chunk)

    classified = await asyncio.gather(*(classify(chunk) for chunk in chunks))
    pooled = [
        finding
        for result in classified
        for score in result.scores
        for finding in score.findings
    ]
    return densify(pooled).scores
