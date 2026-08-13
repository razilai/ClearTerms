"""Database models.

ORM entities only. Not the API surface — wire format lives in app.schemas.

All entities are re-exported here so importing app.models registers every
table on Base.metadata (needed by init_db / create_all).
"""

from app.models.analysis import Analysis
from app.models.attachment import Attachment
from app.models.base import Base
from app.models.document import Document
from app.models.finding import Finding
from app.models.forum import Comment, Like, Post
from app.models.history import HistoryEntry
from app.models.preference import Preference
from app.models.rate_limit import RateLimit
from app.models.user import User

__all__ = [
    "Analysis",
    "Attachment",
    "Base",
    "Comment",
    "Document",
    "Finding",
    "HistoryEntry",
    "Like",
    "Post",
    "Preference",
    "RateLimit",
    "User",
]
