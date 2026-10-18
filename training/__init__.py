"""Training subsystem for the ALCANA PRINT lead-capture bot.

Scope is deliberately narrow: it teaches the workflow the production system
actually implements (a lead arrives in the manager group; a manager reads it and
telephones the customer). It does not model tickets, assignment, statuses or
SLAs, because the production system has none. See AUDIT.md.
"""

__all__ = ["modes", "production", "leads", "render", "scenarios"]
