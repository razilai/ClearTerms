"""HTTP layer.

FastAPI routers and request/response wiring only — no business logic.
Routes validate input with app.schemas and delegate to app.services.
"""
