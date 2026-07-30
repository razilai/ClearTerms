"""User preferences: CRUD, and verdict computation.

Verdict is computed at read time from cached category scores x the user's
preference weights (see README "Analyze once, filter per user"). Changing
preferences never re-triggers analysis.
"""
