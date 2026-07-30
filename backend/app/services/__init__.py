"""Business logic layer.

Orchestrates the domain: api routes call services; services call the agent,
db, and each other. Keep the LLM (app.agent) unaware of cache/db/preferences —
that seam lives here in analysis.py.
"""
