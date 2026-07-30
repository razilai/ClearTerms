"""TOS chunk classifier: PydanticAI agent against Ollama (OpenAI-compatible API).

Plain text in, structured scores out. No cache, db, or preference awareness.
"""

from typing import Any

from pydantic_ai import Agent

from app.agent.output import ChunkClassification


def load_prompts() -> dict[str, Any]:
    """Load system prompt + few-shot examples from prompts/prompts.toml
    via importlib.resources (package data, not filesystem paths)."""
    raise NotImplementedError


def build_agent() -> Agent[None, ChunkClassification]:
    """Construct the PydanticAI agent: Ollama model at settings.ollama_base_url,
    model name settings.agent_model, output_type=ChunkClassification,
    system prompt + few-shots from load_prompts()."""
    raise NotImplementedError


async def classify_chunk(text: str) -> ChunkClassification:
    """Classify one TOS chunk against all clause categories."""
    raise NotImplementedError
