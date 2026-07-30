"""Clause category taxonomy.

Placeholder set — final taxonomy + few-shot examples per category are an open
question (see root README "Open Questions"). Scoring scale TBD alongside it
(e.g. 0-2: absent / present-standard / present-aggressive).
"""

from enum import StrEnum


class ClauseCategory(StrEnum):
    DATA_SELLING = "data_selling"
    ARBITRATION = "arbitration"
    UNILATERAL_CHANGES = "unilateral_changes"
    CONTENT_LICENSING = "content_licensing"
    AUTO_RENEWAL = "auto_renewal"
