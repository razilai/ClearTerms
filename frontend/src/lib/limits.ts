// Input length caps, hand-mirrored from backend/app/core/config.py the same way
// api/types.ts mirrors the Pydantic schemas. The server is the enforcement
// point — a client cap is a courtesy that stops a user typing past a limit they
// can't see, and curl ignores it. Change a number here and there together.

export const MAX_EMAIL_CHARS = 254
export const MAX_PASSWORD_CHARS = 128
export const MAX_POST_TITLE_CHARS = 255
export const MAX_POST_BODY_CHARS = 10_000
export const MAX_COMMENT_BODY_CHARS = 5_000
export const MAX_URL_CHARS = 2_048

// Mirrors max_analyze_bytes, not a character setting: the backend bounds the
// paste box in bytes and answers 413. The two are the same number for ASCII,
// which is what nearly every TOS is; for a multibyte document this counter can
// read under the limit while the server still refuses it, and that 413 is the
// backstop. Enforced by clipping in AnalyzePage's onChange — never by
// maxLength, which would drop the tail of a paste silently.
export const MAX_ANALYZE_CHARS = 1_000_000
