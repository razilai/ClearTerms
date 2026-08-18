"""Unit tests: text normalization + hashing — the cache key.

`normalize_text` + `compute_hash` are the foundation of "analyze once, filter
per user": a TOS is cached by the hash of its normalized text, so two copies
that differ only in whitespace, case, or unicode form must collapse to one
entry (or the same document gets re-analyzed, wasting an LLM run), while
genuinely different text must not (or one document's verdict is served for
another). Pure functions — no DB, no agent.
"""


from app.services.analysis import compute_hash, normalize_text

# --- normalization ----------------------------------------------------------


def test_normalize_collapses_whitespace_and_casefolds() -> None:
    assert (
        normalize_text("  You   AGREE\tto\nThese Terms.  ")
        == "you agree to these terms."
    )


def test_equivalent_texts_normalize_and_hash_identically() -> None:
    a = "You agree to binding arbitration."
    b = "  you AGREE   to\tbinding\narbitration.  "
    assert normalize_text(a) == normalize_text(b)
    assert compute_hash(normalize_text(a)) == compute_hash(normalize_text(b))


def test_unicode_forms_collapse_together() -> None:
    # "cafe" with an accent: one pre-composed code point (U+00E9) vs. plain e
    # plus a combining acute (U+0301). Same text, different bytes until NFC
    # normalization folds them together.
    composed = "caf\u00e9 terms"
    decomposed = "cafe\u0301 terms"
    assert composed != decomposed
    assert normalize_text(composed) == normalize_text(decomposed)
    assert compute_hash(normalize_text(composed)) == compute_hash(
        normalize_text(decomposed)
    )


# --- separation + hash shape ------------------------------------------------


def test_different_texts_hash_differently() -> None:
    assert compute_hash(normalize_text("clause a")) != compute_hash(
        normalize_text("clause b")
    )


def test_compute_hash_is_deterministic_sha256_hex() -> None:
    digest = compute_hash("some normalized text")
    assert digest == compute_hash("some normalized text")
    # 64 lowercase hex chars == a SHA-256 hexdigest.
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
