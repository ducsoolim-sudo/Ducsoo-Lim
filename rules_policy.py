"""Versioned product rules. IDs correspond to 13GO 운영·개발 매뉴얼."""
MAIN_SECONDS = 300.0
BYOYOMI_SECONDS = 30.0
BYOYOMI_PERIODS = 3
FIRST_ACTION_SECONDS = 30.0
IDLE_WARNING_SECONDS = 60.0
IDLE_LOSS_SECONDS = 90.0
REVIEW_SECONDS = 30.0
# Implementation defaults; not a claim that the user separately approved these.
DISCONNECT_EPISODE_SECONDS = 10.0
DISCONNECT_BUDGET_SECONDS = 90.0
DISCONNECT_LIMIT = 3
POLICY = 'byoyomi-manners-v1'


def project_clock(main, periods, elapsed):
    """Return main left, periods left, visible seconds. No mutation on reads."""
    elapsed = max(0.0, elapsed)
    if elapsed < main:
        return main-elapsed, periods, main-elapsed
    overtime = elapsed-main
    spent = int(overtime // BYOYOMI_SECONDS)
    left = max(0, periods-spent)
    display = max(0.0, BYOYOMI_SECONDS - overtime % BYOYOMI_SECONDS) if left else 0.0
    return 0.0, left, display
