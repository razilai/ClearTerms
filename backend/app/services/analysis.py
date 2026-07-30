"""Analysis pipeline orchestration (preference-independent).

Steps: normalize text -> hash -> cache lookup. On miss: clean, chunk by TOS
section headings (fallback ~3k-token windows, ~200-token overlap), call
app.agent to classify each chunk against all clause categories, take per-category
max across chunks, persist to the Analysis cache keyed by text_hash + model_version.

Owns the seam between the LLM (app.agent) and the rest of the system: the agent
receives plain text and returns structured scores; cache/db/preferences live here.
"""
