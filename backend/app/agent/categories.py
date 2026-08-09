"""Clause category taxonomy: the fixed label set every TOS is scored against.

``ClauseCategory`` itself lives in ``app.schemas.analysis`` (a pure leaf, so the
wire contracts stay free of this module's import-time TOML loading) and is
re-exported here. Those slugs are stored verbatim in ``Analysis.category`` and
``Preference.category`` — both plain ``String(64)`` columns with no FK — so the
enum is what keeps them aligned: renaming a slug invalidates cached analyses and
orphans existing preference rows.

This module is the single source of truth for the prose around that enum:

- the neutral detection definitions and 0-2 score anchors rendered into the
  classifier system prompt,
- the user-facing display copy shown in the web app's per-clause breakdown.

Two text registers, deliberately kept apart. ``detection``/``standard``/
``aggressive``/``boundaries`` are neutral and go to the model — loaded framing
biases a small model toward finding aggression everywhere and collapses the
scale to all 2s. ``display_name``/``description`` carry the product voice and
go to humans.

The prose itself lives in ``prompts/categories.toml``, one table per slug; this
module owns the score scale and the ``CategorySpec`` schema, and loads +
validates the prose at import. Few-shot examples live in ``prompts/prompts.toml``,
keyed by these slugs. This module holds data only; rendering it into a prompt is
``classifier.py``'s job.
"""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from importlib import resources
from types import MappingProxyType

from app.schemas.analysis import ClauseCategory

SCORE_ABSENT = 0
SCORE_STANDARD = 1
SCORE_AGGRESSIVE = 2

MIN_SCORE = SCORE_ABSENT
MAX_SCORE = SCORE_AGGRESSIVE

SCORE_SCALE: Mapping[int, str] = MappingProxyType(
    {
        SCORE_ABSENT: "the category is not addressed in this text",
        SCORE_STANDARD: (
            "the category is addressed on terms typical of mainstream consumer services"
        ),
        SCORE_AGGRESSIVE: (
            "the category is addressed on terms materially worse for the user "
            "than typical"
        ),
    }
)


@dataclass(frozen=True, slots=True)
class CategorySpec:
    """Everything known about one clause category.

    ``detection``, ``standard``, ``aggressive`` and ``boundaries`` are prompt
    inputs; ``display_name`` and ``description`` are web app copy.
    """

    category: ClauseCategory
    display_name: str
    description: str
    detection: str
    standard: str
    aggressive: str
    boundaries: tuple[str, ...]


SPECS_PACKAGE = "app.agent.prompts"
SPECS_FILE = "categories.toml"


def _load_specs() -> Mapping[ClauseCategory, CategorySpec]:
    """Load and validate the category prose from ``categories.toml``.

    Runs once at import. Every ``ClauseCategory`` must have a table and no
    table may name an unknown slug, so a rename or typo fails fast here rather
    than silently shipping a half-populated taxonomy. ``boundaries`` arrives as
    a TOML array (list) and is frozen to a tuple to match ``CategorySpec``.
    """
    text = resources.files(SPECS_PACKAGE).joinpath(SPECS_FILE).read_text("utf-8")
    raw = tomllib.loads(text)

    slugs = {c.value for c in ClauseCategory}
    missing = slugs - raw.keys()
    if missing:
        raise RuntimeError(f"{SPECS_FILE} is missing tables for: {sorted(missing)}")
    unknown = raw.keys() - slugs
    if unknown:
        raise RuntimeError(
            f"{SPECS_FILE} has unknown category slugs: {sorted(unknown)}"
        )

    prose_fields = {f.name for f in fields(CategorySpec)} - {"category"}
    specs: dict[ClauseCategory, CategorySpec] = {}
    for slug, table in raw.items():
        extra = table.keys() - prose_fields
        if extra:
            raise RuntimeError(
                f"{SPECS_FILE} [{slug}] has unknown keys: {sorted(extra)}"
            )
        category = ClauseCategory(slug)
        specs[category] = CategorySpec(
            category=category,
            **{**table, "boundaries": tuple(table["boundaries"])},
        )
    return MappingProxyType(specs)


CATEGORY_SPECS: Mapping[ClauseCategory, CategorySpec] = _load_specs()
