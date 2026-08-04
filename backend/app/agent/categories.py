"""Clause category taxonomy: the fixed label set every TOS is scored against.

Single source of truth for:

- the category slugs stored in ``Analysis.category`` and ``Preference.category``
  (both plain ``String(64)`` columns with no FK — this enum is what keeps them
  aligned, so renaming a slug invalidates cached analyses and orphans existing
  preference rows),
- the neutral detection definitions and 0-2 score anchors rendered into the
  classifier system prompt,
- the user-facing display copy shown in the web app's per-clause breakdown.

Two text registers, deliberately kept apart. ``detection``/``standard``/
``aggressive``/``boundaries`` are neutral and go to the model — loaded framing
biases a small model toward finding aggression everywhere and collapses the
scale to all 2s. ``display_name``/``description`` carry the product voice and
go to humans.

Few-shot examples live in ``prompts/prompts.toml``, keyed by these slugs. This
module holds data only; rendering it into a prompt is ``classifier.py``'s job.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class ClauseCategory(StrEnum):
    UNILATERAL_CHANGES = "unilateral_changes"
    ARBITRATION = "arbitration"
    LIABILITY = "liability"
    CONTENT_LICENSING = "content_licensing"
    DATA_COLLECTION = "data_collection"
    TERMINATION = "termination"


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


CATEGORY_SPECS: Mapping[ClauseCategory, CategorySpec] = MappingProxyType(
    {
        spec.category: spec
        for spec in (
            CategorySpec(
                category=ClauseCategory.UNILATERAL_CHANGES,
                display_name="Changes",
                description=(
                    "Companies can rewrite the rules, alter fees, or revoke features "
                    "at any time without your explicit consent. By simply continuing "
                    "to use the service, you are legally bound to these new terms."
                ),
                detection=(
                    "Clauses letting the provider modify the agreement, pricing, or "
                    "available features, and clauses defining how users are notified "
                    "of those modifications and how consent to them is established."
                ),
                standard=(
                    "The provider may change the terms but commits to advance notice "
                    "through a direct channel (email or in-product), and material "
                    "changes take effect at the next billing period or leave the user "
                    "a window to reject them by cancelling."
                ),
                aggressive=(
                    "Changes take effect immediately on posting, the only notice is an "
                    "instruction to check the page periodically, continued use is "
                    "deemed acceptance, and no cancellation or refund window follows a "
                    "change the user objects to."
                ),
                boundaries=(
                    (
                        "Mid-term changes to price, features, or the terms themselves "
                        "belong here; renewal pricing and cancellation mechanics "
                        "belong to termination."
                    ),
                    (
                        "An amendment that expands data collection scores here for the "
                        "amendment mechanism; data_collection covers the collection "
                        "scope itself."
                    ),
                ),
            ),
            CategorySpec(
                category=ClauseCategory.ARBITRATION,
                display_name="Arbitration",
                description=(
                    "Users are stripped of their right to a public trial or joining "
                    "class-action lawsuits for corporate wrongdoing. Disputes are "
                    "instead forced into private, company-favored systems that make "
                    "fighting widespread, small-dollar exploitation financially "
                    "impossible."
                ),
                detection=(
                    "Clauses governing where and how disputes are resolved: binding "
                    "arbitration, jury-trial waiver, class-action waiver, forum, venue "
                    "and governing-law selection, notice-before-suit requirements, "
                    "claim-filing deadlines, and who bears the cost of bringing a "
                    "claim."
                ),
                standard=(
                    "Arbitration is required, but with a stated opt-out window "
                    "(commonly 30 days), a small-claims-court carve-out, a neutral "
                    "administering body, and provider-paid filing fees for consumer "
                    "claims."
                ),
                aggressive=(
                    "Mandatory arbitration with no opt-out, class-action and jury "
                    "waiver, a provider-selected arbitrator or forum, a distant "
                    "mandatory venue, a shortened deadline to file claims, or "
                    "loser-pays fee shifting onto the user."
                ),
                boundaries=(
                    (
                        "Where and how a dispute is heard belongs here, including "
                        "fee-shifting that deters bringing a claim at all; what the "
                        "user can recover belongs to liability."
                    ),
                    (
                        "Forum, venue and governing-law selection are scored here "
                        "rather than as a separate category."
                    ),
                ),
            ),
            CategorySpec(
                category=ClauseCategory.LIABILITY,
                display_name="Accountability",
                description=(
                    "Companies completely shield themselves from responsibility for "
                    "bugs, data loss, or financial damages caused by their own "
                    "platforms. They shift all risk onto the user, sometimes even "
                    "requiring you to cover their legal fees if disputes arise."
                ),
                detection=(
                    "Clauses limiting the provider's responsibility or shifting risk "
                    "onto the user: warranty disclaimers, exclusion of consequential "
                    "or data-loss damages, monetary caps on total liability, and user "
                    "indemnification obligations."
                ),
                standard=(
                    "An 'as is' warranty disclaimer plus a liability cap tied to fees "
                    "the user actually paid over a recent period (commonly the "
                    "preceding 12 months), with carve-outs for gross negligence, "
                    "willful misconduct, or where the law forbids the limitation."
                ),
                aggressive=(
                    "Total liability capped at a nominal sum regardless of fees paid, "
                    "all damages excluded with no carve-outs, disclaimers extended to "
                    "affiliates and to security breaches, or broad user indemnification "
                    "covering the provider's own conduct or legal fees."
                ),
                boundaries=(
                    (
                        "What the user can recover, and what the user must cover for "
                        "the provider, belong here; where and how the dispute is heard "
                        "belongs to arbitration."
                    ),
                    (
                        "Fee-shifting written into a dispute-resolution clause scores "
                        "under arbitration; standalone indemnification scores here."
                    ),
                ),
            ),
            CategorySpec(
                category=ClauseCategory.CONTENT_LICENSING,
                display_name="Content Grab",
                description=(
                    "Uploading photos, text, or digital creations often grants the "
                    "company a perpetual, royalty-free license to commercialize or "
                    "train AI on your work. You technically retain \"ownership\" but "
                    "surrender all control and potential profit."
                ),
                detection=(
                    "Clauses granting the provider a license to content the user "
                    "deliberately uploads, posts, or authors — text, images, video, "
                    "audio, code, messages — including the license's scope, duration, "
                    "sublicensing rights, and use for AI or model training."
                ),
                standard=(
                    "A non-exclusive license limited to operating, hosting, and "
                    "promoting the service, terminating when the user deletes the "
                    "content or the account, with a stated allowance for residual "
                    "backup copies."
                ),
                aggressive=(
                    "A perpetual, irrevocable, worldwide, royalty-free, sublicensable "
                    "and transferable license that survives account deletion; rights to "
                    "modify, create derivative works, commercialize, or train models on "
                    "user content; or waiver of moral rights and attribution."
                ),
                boundaries=(
                    (
                        "Content the user deliberately uploads or authors belongs "
                        "here — including chat messages, voice recordings, and "
                        "uploaded photos; data observed about the user belongs to "
                        "data_collection."
                    ),
                    (
                        "Model training on authored content scores here; model "
                        "training on behavioral data scores under data_collection."
                    ),
                ),
            ),
            CategorySpec(
                category=ClauseCategory.DATA_COLLECTION,
                display_name="Data Harvesting",
                description=(
                    "These agreements compel users to consent to sweeping behavioral "
                    "tracking far beyond what is needed to run the service. This allows "
                    "companies to freely monetize, profile, and share your personal "
                    "digital footprint with third-party brokers."
                ),
                detection=(
                    "Clauses covering what personal data is collected, how it is used "
                    "beyond delivering the service, who it is shared with or sold to, "
                    "how long it is retained after account deletion, and what consent "
                    "the user is deemed to have given."
                ),
                standard=(
                    "Collection scoped to what operating the service requires, sharing "
                    "limited to named processors under contract, advertising and "
                    "analytics offered on an opt-out basis, and retention tied to a "
                    "stated period after account closure."
                ),
                aggressive=(
                    "Consent to tracking unrelated to the service (cross-site or "
                    "cross-device, precise location, contacts, biometrics), sale or "
                    "transfer of personal data to third-party brokers or advertisers, "
                    "unrestricted transfer on acquisition, indefinite retention after "
                    "deletion, or bundled consent the user cannot refuse without losing "
                    "access."
                ),
                boundaries=(
                    (
                        "Data observed about the user belongs here — clickstream, "
                        "location, device fingerprint, purchase history; content the "
                        "user deliberately uploads or authors belongs to "
                        "content_licensing."
                    ),
                    (
                        "Retention of personal data after account deletion is scored "
                        "here rather than under termination."
                    ),
                ),
            ),
            CategorySpec(
                category=ClauseCategory.TERMINATION,
                display_name="Exit Terms",
                description=(
                    "The company can cut off your account without warning and keep what "
                    "you paid for, while your own way out is deliberately narrow — "
                    "silent renewals, cancellation obstacles, and no way to take your "
                    "data with you."
                ),
                detection=(
                    "Clauses governing how the relationship ends in either direction: "
                    "provider suspension or termination of accounts, subscription "
                    "auto-renewal, cancellation mechanics, refunds, and the user's "
                    "access to or export of their data after termination."
                ),
                standard=(
                    "Termination for cause or material breach with notice and a cure "
                    "period, self-serve cancellation, a reminder before an automatic "
                    "renewal charge, a stated refund policy, and a defined window to "
                    "export data."
                ),
                aggressive=(
                    "Termination or suspension at any time for any reason without "
                    "notice or appeal, forfeiture of paid balances, purchased content, "
                    "or credits; automatic renewal with no reminder; cancellation only "
                    "by phone or mail or subject to a notice period; or immediate "
                    "deletion of user data with no export."
                ),
                boundaries=(
                    (
                        "Renewal mechanics, cancellation friction, and forfeiture on "
                        "termination belong here; mid-term changes to price, features, "
                        "or terms belong to unilateral_changes."
                    ),
                    (
                        "The forfeiture term itself is scored here; general caps on "
                        "what the user can recover in damages belong to liability."
                    ),
                ),
            ),
        )
    }
)

_missing = set(ClauseCategory) - set(CATEGORY_SPECS)
if _missing:
    raise RuntimeError(
        f"CATEGORY_SPECS is missing specs for: {sorted(c.value for c in _missing)}"
    )
