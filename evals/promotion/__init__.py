"""Promotion gate: replay candidate policy/model changes K times and decide whether to promote them.

Discover (a miss or a reviewer override) -> Propose (a candidate) -> Replay (62 cases x K) -> Promote / Hold / Reject.
"""
