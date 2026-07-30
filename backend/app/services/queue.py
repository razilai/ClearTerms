"""Priority queue for TOS analysis (guardrail).

Prevents a single user from spamming analysis requests; cache hits skip the
queue entirely so repeat requests are free.
"""
