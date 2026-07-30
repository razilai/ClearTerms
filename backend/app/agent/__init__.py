"""LLM agent layer.

Owns everything model-facing: prompt loading, request construction, and
response parsing. Called only by services; must stay unaware of cache, db,
and user preferences.
"""
