"""Builds the `context` block the agent receives (school rules, professor, memory).

Order of authority: school policy (or the PHACT default) > professor > course > memory.
A professor may be stricter than the school, never looser.
"""

from phact_contracts.agent import Context


def build_context(school_id: str, user_id: str, course_code: str) -> Context:
    # TODO: db.get_policy(school_id) or db.get_policy("_default")  → school_rules, policy_source
    #       PROFILE item → professor summary; memory summary item → memory
    raise NotImplementedError
