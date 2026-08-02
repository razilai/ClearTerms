# TOS Clause Classifier — Design

Date: 2026-08-02
Scope: `backend/app/agent/` only (`output.py`, `prompts/prompts.toml`, `classifier.py`).
Out of scope: chunking, caching, verdict computation, persistence — all owned by
`app/services/analysis.py`.

## Problem

Given one chunk of terms-of-service text, produce a score in 0–2 for each of the
six categories in `app/agent/categories.py`, cheaply enough that a full document
costs a handful of forward passes rather than hundreds.

The tempting framing — "split the chunk into clauses, classify each clause" — is
the wrong one, for two reasons.

**The data model does not store clauses.** `Analysis` is unique on
`(document_id, category, model_version)`. Six rows per document, one per
category. There is no per-clause row anywhere downstream, and `services` reduces
chunks by taking a per-category max. Per-clause classification would produce a
granularity nothing consumes.

**Clause boundaries are already resolved upstream.** `services` chunks by TOS
section heading, falling back to ~3k-token windows. A section such as
"14. Limitation of Liability" arrives as one chunk. The chunk *is* the clause
group; there is nothing left for the model to segment.

### Cost of the alternatives

For a typical ~15k-token TOS:

| Approach | Forward passes |
| --- | --- |
| One pass per chunk, all six categories | ~5–8 |
| One pass per (chunk × category) | ~30–48 |
| Split to individual clauses, one pass each | ~150–300 |

Per-clause is also *less accurate*, not merely slower: an arbitration opt-out
window often sits several paragraphs from the arbitration mandate, and a clause
scored in isolation reads as aggressive (2) when the section as a whole is
standard (1).

Latency is therefore addressed by concurrency, not by reducing passes. Chunks
are independent, so `services` can issue them together under a bounded
semaphore against `OLLAMA_NUM_PARALLEL`. That is a `services` concern; the agent
exposes a single-chunk call.

**Decision: one forward pass per chunk, scoring all six categories at once.**

## Contract

```
classify_chunk(text: str) -> ChunkClassification
```

Plain text in, exactly six scores out. The agent never sees the cache, the db,
or user preferences, per the layer rules in `backend/README.md`.

The PydanticAI agent is typed `Agent[str, ChunkFindings]`. The deps type is
`str` and carries the chunk text, which is what lets the output validator check
quoted evidence against the source. This replaces the `Agent[None,
ChunkClassification]` signature in the current stub.

## Output schema (`output.py`)

Two models, deliberately distinct. The model emits only what it found; the agent
returns a dense six-entry result.

```python
class Finding(BaseModel):
    """One category the model actually found. Model-facing schema."""
    category: ClauseCategory
    evidence: str          # verbatim span from the chunk
    score: Literal[1, 2]
    explanation: str

class ChunkFindings(BaseModel):
    findings: list[Finding]

class ClauseScore(BaseModel):
    """One category after densifying. Agent-facing schema."""
    category: ClauseCategory
    score: int             # 0..2
    evidence: str | None   # None if and only if score == 0
    explanation: str | None

class ChunkClassification(BaseModel):
    scores: list[ClauseScore]   # always six, in ClauseCategory declaration order
```

### Sparse model output

The model returns only categories it found. `classify_chunk` fills the rest with
`score=0, evidence=None, explanation=None` before returning.

Most chunks touch one or two categories, so a dense response would spend roughly
five times the output tokens on zeros — and a 7B model asked to justify a zero
tends to invent prose for it. `score: Literal[1, 2]` makes absence structurally
unrepresentable: the model cannot emit a zero, so "absent" and "omitted" are one
representation by construction rather than by convention.

The accepted risk is silent omission — the model overlooks a category and
nothing distinguishes that from genuine absence. This is mitigated by rendering
all six category specs into the system prompt, and bounded in impact by the
per-category max across chunks: a category missed in one chunk can still be
caught in another.

### Field order

Within `Finding`, `evidence` is declared before `score`, and `explanation` after
it. Under constrained decoding the model generates fields in schema order and
cannot backtrack, so this order forces it to quote the clause first, then judge
the text it has just written, then justify the judgment. Declaring `score` first
would have it commit to a number before attending to any specific span.

### Evidence

`evidence` is required whenever a category is reported and absent when it is
not. It gives the web app real clause text to highlight, and it makes
hallucination detectable: a quote that does not appear in the chunk is a
verifiable failure, whereas a paraphrase is not.

### Schema flatness

Enums, ints, strings, and one list of one object type — no unions, no `$ref`
nesting. Ollama applies the JSON schema as a decoding constraint but does not
implement OpenAI's `strict` contract (see below), and adherence degrades on
complex schemas. Flatness is a requirement here, not a style preference.

## Prompt (`prompts/prompts.toml`)

The TOML file holds the system-prompt template and few-shot examples. It does
**not** duplicate category text: `render_system_prompt()` injects `SCORE_SCALE`
and all six `CategorySpec` entries (`detection`, `standard`, `aggressive`,
`boundaries`) from `categories.py`, which stays the single source of truth.

```toml
[system]
prompt = """...{score_scale}...{categories}...{example}..."""

[[few_shot.examples]]
text = "..."
findings = [{ category = "...", evidence = "...", score = 2, explanation = "..." }]
```

### One shared mixed example

A single worked example on a short synthetic chunk containing two categories at
different scores, omitting the other four. It demonstrates output shape,
sparseness, and the 1-vs-2 line together.

Budget: ~900 tokens of rendered specs + ~60 of score scale + ~350 of example ≈
1.3k of system prompt, leaving room for a 3k-token chunk. Six examples — one per
category — would roughly double prefill on every call for calibration the
`standard`/`aggressive` spec text already supplies. Zero-shot was rejected
because a 7B model reliably drifts on the sparseness and evidence-quoting rules
when only the schema enforces them.

The array-of-tables shape is retained so adding a second example later requires
no code change.

## Runtime and structured output (`classifier.py`)

### Ollama

Retained. It is already in `core/config.py` and `docker-compose.yml`, runs on
developer hardware, and supports schema-constrained decoding. vLLM offers better
throughput but wants a CUDA GPU and would only pay off under concurrent
multi-user load this project does not have.

Use `pydantic_ai.providers.ollama.OllamaProvider` rather than a generic
`OpenAIProvider` aimed at the base URL. `OllamaProvider` auto-applies the
matching model profile — including `qwen_model_profile` for any model name
beginning with `qwen` — which is what sets the structured-output capability
flags. A generic provider would require configuring those by hand.

### `NativeOutput`

Output mode is `NativeOutput(ChunkFindings)`, not PydanticAI's default tool
calling.

`NativeOutput` sends the schema in `response_format: {"type": "json_schema",
...}`. Ollama compiles it into a grammar and masks tokens that would violate it
during sampling, so an invalid category value or a non-integer score is never
sampleable. Tool calling is ordinary generation validated after the fact, and
each failure costs another full forward pass — a path 7B models hit often on a
six-way enum with a conditionally-required field.

Two limits, both accounted for above:

- Ollama does not support OpenAI's `strict` mode
  (`openai_supports_strict_tool_definition=False` in its PydanticAI profile).
  The schema constrains decoding but carries no exactness guarantee, hence the
  flatness requirement.
- Constrained decoding guarantees well-formed, schema-shaped JSON and nothing
  about content. Whether `evidence` is genuinely verbatim remains a semantic
  check, handled by the output validator.

### Components

- `load_prompts()` — read `prompts.toml` through `importlib.resources`, parse
  with `tomllib`, `@lru_cache`.
- `render_system_prompt()` — template + `SCORE_SCALE` + six rendered specs +
  example. A stable prefix, so Ollama's KV cache is reused across chunks.
- `build_agent()` — `@lru_cache`. `OpenAIChatModel(settings.agent_model,
  provider=OllamaProvider(...))`, `output_type=NativeOutput(ChunkFindings)`,
  `retries=1`, `temperature=0`.
- `classify_chunk(text)` — run the agent with `deps=text`, then densify to six.

`temperature=0` because analyses are cached on `text_hash + model_version`; the
same document must not score differently across runs.

## Error handling

An output validator runs in this order:

1. **Dedupe** — if a category appears more than once, keep the highest score.
2. **Normalize** — collapse whitespace runs, map `“”‘’` to `"` and `'`, casefold.
   Applied to both the evidence and the chunk before comparison.
3. **Substring check** — normalized evidence must appear in the normalized chunk.
4. **Retry once** — on a miss, raise `ModelRetry` naming the offending category.
5. **Drop on persistent failure** — if the retry still misses, drop that finding
   (it densifies to `score=0`), log a warning, and return the remaining
   findings.

Normalization is required because models routinely re-type a quote with
straightened quote glyphs or a line break collapsed to a space; a raw `evidence
in chunk` test would reject substantively correct quotes.

Dropping rather than raising keeps one bad quote from discarding every finding in
the chunk, and avoids forcing `services` to decide whether a partially failed
document is cacheable. The cost ceiling is two forward passes per chunk.

## Testing

`FunctionModel` with `Agent.override()` — no Ollama process in unit tests.

- Densify always returns six entries in `ClauseCategory` declaration order.
- `Literal[1, 2]` rejects a score of 0 in model output.
- Normalization accepts curly quotes and a folded line break.
- Retry fires once, then the finding is dropped and the rest survive.
- Duplicate categories dedupe to the highest score.
- `evidence` is non-None exactly when `score > 0`.
- The rendered system prompt contains all six category slugs.

An integration test hitting a live Ollama is out of scope for `tests/unit.py`
and belongs in `tests/integration.py`.

## Open implementation details

Neither blocks the design; both are settled while writing the code.

- Whether `OllamaProvider` expects `settings.ollama_base_url` with or without a
  `/v1` suffix.
- Whether `NativeOutput` round-trips `Literal[1, 2]` cleanly through Ollama's
  schema handling, or whether it needs to be widened to a plain `int` with a
  Pydantic-side constraint.
