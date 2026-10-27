"""Anki SM-2 scheduling for convo-live, using Anki's default deck options.

Each word keeps one card per language in a Firestore map field (srsCantonese / srsMandarin). The due
time stays in nextReview<Lang>, so every query that already reads it keeps working.

Pure functions only: no Firestore, no clock. The caller passes `now`.

Why this replaced the old fixed list (3d / 15d / 60d): the old code measured how LATE a review was
(now minus the due time) and picked the next interval from that. An on-time correct answer always got
3 days, and a word only reached 15 or 60 days if it was reviewed 3+ or 15+ days late.
"""
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Anki's default deck options.
LEARNING_STEPS_MIN = [1, 10]
RELEARNING_STEPS_MIN = [10]
GRADUATING_IVL_DAYS = 1
LAPSE_IVL_DAYS = 1          # Anki: "New interval" 0% of the old interval, "Minimum interval" 1 day
STARTING_EASE = 2.5
EASE_FLOOR = 1.3
EASE_AGAIN = -0.20
EASE_HARD = -0.15
HARD_FACTOR = 1.2
MAX_IVL_DAYS = 36500
DAY_STARTS_HOUR = 4         # Anki: "Next day starts at" 4 AM

# The owner's clock. A review card falls due at 4 AM local time on its due day, not at the minute it
# was graded, so a word graded at 9 PM is ready for the next morning's session.
TZ = ZoneInfo(os.getenv("SRS_TZ", "America/New_York"))

AGAIN, HARD, GOOD = "again", "hard", "good"


def grade_from(evaluation: dict, had_difficulty: bool) -> str:
    """Map a graded reply to an Anki button.

    Again: the learner flagged difficulty (tapped the target word, revealed the translation, or pressed
    the struggle face), or used the target word wrongly. Hard: the target word is right but the grammar
    elsewhere is off; the slip isn't about the word being drilled. Good: both right.
    """
    if had_difficulty or not evaluation.get("meaningful_usage"):
        return AGAIN
    if not evaluation.get("fluent"):
        return HARD
    return GOOD


def day_of(t: datetime) -> date:
    """The Anki day `t` falls on: local date, with the day starting at DAY_STARTS_HOUR."""
    return (t.astimezone(TZ) - timedelta(hours=DAY_STARTS_HOUR)).date()


def day_start(d: date) -> datetime:
    """The moment Anki day `d` begins, in UTC. 4 AM is clear of the 2 AM DST switch."""
    return datetime(d.year, d.month, d.day, DAY_STARTS_HOUR, tzinfo=TZ).astimezone(timezone.utc)


def new_card() -> dict:
    return {"state": "new", "step": 0, "ivl": 0, "ease": STARTING_EASE, "reps": 0, "lapses": 0}


def legacy_card() -> dict:
    """A word the old fixed-interval code scheduled. Its history can't be trusted, so it starts as a
    one-day review card, and its first grading gets no credit for lateness (see schedule)."""
    return {"state": "review", "step": 0, "ivl": 1, "ease": STARTING_EASE, "reps": 0, "lapses": 0,
            "legacy": True}


def learning_card(card: dict | None) -> dict:
    """Put a word into learning step 0 (drawer "Schedule", "Unmark"). Keeps ease, reps and lapses."""
    base = dict(card) if card else new_card()
    base.pop("legacy", None)
    base.update({"state": "learning", "step": 0})
    return base


def _round_days(x: float) -> int:
    return min(MAX_IVL_DAYS, int(x + 0.5))  # round half up; Python's round() is round-half-even


def _ease(x: float) -> float:
    return round(max(EASE_FLOOR, x), 2)  # 2.3, not 2.3000000000000003, in Firestore


def _review_due(now: datetime, ivl: int) -> datetime:
    return day_start(day_of(now) + timedelta(days=ivl))


def _hard_delay_min(steps: list[int], step: int) -> float:
    """Anki: Hard repeats the current step; on the first of 2+ steps it waits the average of the two."""
    if step == 0 and len(steps) > 1:
        return (steps[0] + steps[1]) / 2
    if len(steps) == 1:
        return min(steps[0] * 1.5, steps[0] + 1440)
    return steps[step]


def schedule(card: dict, grade: str, now: datetime, due_before: datetime | None) -> tuple[dict, datetime]:
    """Apply one Anki answer to `card`. Returns (new card, new due time in UTC).

    `due_before` is the word's due time before this answer; review cards use it for lateness.
    """
    if grade not in (AGAIN, HARD, GOOD):
        raise ValueError(f"unknown grade {grade!r}")
    c = dict(card)
    legacy = bool(c.pop("legacy", False))
    c["reps"] = c.get("reps", 0) + 1
    c["last"] = now
    state = c.get("state", "new")

    if state in ("new", "learning"):
        steps = LEARNING_STEPS_MIN
        step = min(c.get("step", 0), len(steps) - 1)
        if grade == AGAIN:
            c.update(state="learning", step=0)
            return c, now + timedelta(minutes=steps[0])
        if grade == HARD:
            c.update(state="learning", step=step)
            return c, now + timedelta(minutes=_hard_delay_min(steps, step))
        if step + 1 < len(steps):
            c.update(state="learning", step=step + 1)
            return c, now + timedelta(minutes=steps[step + 1])
        c.update(state="review", step=0, ivl=GRADUATING_IVL_DAYS)
        return c, _review_due(now, GRADUATING_IVL_DAYS)

    if state == "relearning":
        steps = RELEARNING_STEPS_MIN
        step = min(c.get("step", 0), len(steps) - 1)
        if grade == AGAIN:
            c["step"] = 0
            return c, now + timedelta(minutes=steps[0])
        if grade == HARD:
            return c, now + timedelta(minutes=_hard_delay_min(steps, step))
        if step + 1 < len(steps):
            c["step"] = step + 1
            return c, now + timedelta(minutes=steps[step + 1])
        ivl = max(1, c.get("ivl", LAPSE_IVL_DAYS))
        c.update(state="review", step=0, ivl=ivl)
        return c, _review_due(now, ivl)

    # Review card.
    ivl = max(1, c.get("ivl", 1))
    ease = c.get("ease", STARTING_EASE)
    if grade == AGAIN:
        c.update(state="relearning", step=0, ivl=LAPSE_IVL_DAYS,
                 ease=_ease(ease + EASE_AGAIN), lapses=c.get("lapses", 0) + 1)
        return c, now + timedelta(minutes=RELEARNING_STEPS_MIN[0])

    late = 0 if legacy or due_before is None else max(0, (day_of(now) - day_of(due_before)).days)
    hard_ivl = max(ivl + 1, (ivl + late / 4) * HARD_FACTOR)
    if grade == HARD:
        new_ivl = _round_days(hard_ivl)
        c["ease"] = _ease(ease + EASE_HARD)
    else:
        new_ivl = _round_days(max(hard_ivl + 1, (ivl + late / 2) * ease))
    c.update(state="review", step=0, ivl=new_ivl)
    return c, _review_due(now, new_ivl)
