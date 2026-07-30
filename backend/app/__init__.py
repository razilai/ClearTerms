"""ClearTerms backend application package.

Layered layout: api (HTTP) -> services (business logic) -> agent/db (LLM and
persistence). models hold DB entities, schemas hold API contracts, core holds
cross-cutting config.
"""
