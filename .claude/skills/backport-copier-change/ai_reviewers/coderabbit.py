"""CodeRabbit's PR review wording.

A review with findings opens "Actionable comments posted: N" and may add "Follow-ups (N)",
"Nitpick comments (N)", "Outside diff range comments (N)" and "Additional comments: N"
sections; a review can carry only follow-ups or additional comments, with "Actionable comments
posted: 0" or no actionable line at all. One with none says "No
actionable comments were generated in the recent review.", and the summary comment says the
same once it is refreshed for the latest commit. Each review's "Review info" names the
commit it covered by its 7-character short SHA (`**Commit**: [abc1234]`), which is how a
review of an older commit is told apart from one of the PR's head. Every review footer on
the included plan ends "0 remain after this review", so that line alone does not mean the
allowance is used up.
"""

import re
from typing import Any

NAME = "coderabbit"
CONFIG_FILES = (".coderabbit.yaml", ".coderabbit.yml")
LOGIN = re.compile(r"^coderabbitai(\[bot\])?$", re.IGNORECASE)

_CLEAN = "No actionable comments were generated"
_ACTIONABLE = re.compile(r"Actionable comments posted: (\d+)")
_FOLLOW_UPS = re.compile(r"Follow-ups \((\d+)\)")
_NITPICKS = re.compile(r"Nitpick comments \((\d+)\)")
_OUTSIDE_DIFF = re.compile(r"Outside diff range comments \((\d+)\)")
_ADDITIONAL = re.compile(r"Additional comments: (\d+)")
_SKIPPED = re.compile(r"Review skipped", re.IGNORECASE)
_ALLOWANCE = re.compile(r"rate limit exceeded", re.IGNORECASE)
_HELD_BACK = re.compile(
    r"review limit reached|rate limit exceeded|review in progress|currently processing", re.IGNORECASE
)
_REVIEWING = re.compile(r"review in progress|currently processing", re.IGNORECASE)
_NEXT_REVIEW = re.compile(r"next included review available in \d+ minutes", re.IGNORECASE)
# CodeRabbit can leave a small follow-up commit unreviewed without saying so; this long after the commit its silence
# is a verdict in itself, and any note that it is held back goes to the agent with it
QUIET_AFTER_SECONDS = 300


def classify(*, reviews: list[str], comments: list[str], head: str) -> dict[str, Any] | None:
    current_reviews = [b for b in reviews if head[:7] in b]
    text = "\n".join([*current_reviews, *(b for b in comments if head[:7] in b)])
    counts = {
        "actionable": sum(int(n) for n in _ACTIONABLE.findall(text)),
        "follow_ups": sum(int(n) for n in _FOLLOW_UPS.findall(text)),
        "nitpicks": sum(int(n) for n in _NITPICKS.findall(text)),
        "outside_diff": sum(int(n) for n in _OUTSIDE_DIFF.findall(text)),
        "additional": sum(int(n) for n in _ADDITIONAL.findall(text)),
    }
    if any(counts.values()):
        return {"verdict": "flagged", **counts}
    if _CLEAN in text:
        return {"verdict": "clean", **counts}
    if _ACTIONABLE.search(text):
        return {"verdict": "clean", **counts}
    if _SKIPPED.search(text):
        return {"verdict": "skipped", **counts}
    if current_reviews:
        # a review of the head exists but says nothing this module recognizes; waiting would never end
        return {"verdict": "unrecognized", **counts}
    return None


def allowance_used_up(bodies: list[str]) -> bool:
    if not bodies:
        return False
    return _ALLOWANCE.search(bodies[-1]) is not None


def still_reviewing(comments: list[str]) -> bool:
    """Return whether CodeRabbit's summary comment, which it rewrites in place, says a review is running now."""
    for body in comments:
        if _REVIEWING.search(body) is not None:
            return True
    return False


def held_back(comments: list[str]) -> str | None:
    """Return CodeRabbit's own note that it is out of allowance or still reviewing, or None without one.

    CodeRabbit rewrites its summary comment in place, so a note there is its current state. A limit note comes with
    when the next review is available, counted from the summary's last refresh, which the note keeps.
    """
    for body in comments:
        match = _HELD_BACK.search(body)
        if match is None:
            continue
        note = match.group()
        timing = _NEXT_REVIEW.search(body)
        if timing is not None:
            note = f"{note}; {timing.group()}"
        return note
    return None
