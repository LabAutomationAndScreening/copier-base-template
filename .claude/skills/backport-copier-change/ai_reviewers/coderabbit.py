"""CodeRabbit's PR review wording.

A review with findings opens "Actionable comments posted: N" and may add "Follow-ups (N)",
"Nitpick comments (N)", "Outside diff range comments (N)" and "Additional comments: N"
sections; a review can carry only follow-ups or additional comments, with "Actionable comments
posted: 0" or no actionable line at all. One with none says "No
actionable comments were generated in the recent review.", and the summary comment says the
same once it is refreshed for the latest commit. A review that found nothing in the code may
instead carry only "Failed pre-merge checks:", one "- <name>:" line per PR-wide check that
failed (such as docstring coverage); that is clean too. Each review's "Review info" names the
commit it covered by its 7-character short SHA (`**Commit**: [abc1234]`), which is how a
review of an older commit is told apart from one of the PR's head. Every review footer on
the included plan ends "0 remain after this review", so that line alone does not mean the
allowance is used up.
"""

import datetime
import re
from typing import Any

NAME = "coderabbit"
CONFIG_FILES = (".coderabbit.yaml", ".coderabbit.yml")
LOGIN = re.compile(r"^coderabbitai(\[bot\])?$", re.IGNORECASE)
CHECK_NAME = "CodeRabbit"

_CLEAN = "No actionable comments were generated"
_ACTIONABLE = re.compile(r"Actionable comments posted: (\d+)")
_FOLLOW_UPS = re.compile(r"Follow-ups \((\d+)\)")
_NITPICKS = re.compile(r"Nitpick comments \((\d+)\)")
_OUTSIDE_DIFF = re.compile(r"Outside diff range comments \((\d+)\)")
_ADDITIONAL = re.compile(r"Additional comments: (\d+)")
_PRE_MERGE_SECTION = re.compile(r"^Failed pre-merge checks:\n(.*?)(?:\n\n|\Z)", re.MULTILINE | re.DOTALL)
_PRE_MERGE_CHECK = re.compile(r"^- ([^:\n]+):", re.MULTILINE)
_SKIPPED = re.compile(r"Review skipped", re.IGNORECASE)
_ALLOWANCE = re.compile(r"rate limit exceeded", re.IGNORECASE)
_HELD_BACK = re.compile(
    r"review limit reached|rate limit exceeded|review in progress|currently processing", re.IGNORECASE
)
_REVIEWING = re.compile(r"review in progress|currently processing", re.IGNORECASE)
_NEXT_REVIEW = re.compile(r"next included review available in (\d+) minutes", re.IGNORECASE)
_REVIEW_REQUEST = re.compile(r"@coderabbitai\s+(?:full\s+)?review\b", re.IGNORECASE)
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
    # each review of the head is judged on its own, so one listing failed checks can't make another clean
    for body in current_reviews:
        if not _recognized(body):
            return {"verdict": "unrecognized", **counts}
    clean = _clean_details(text=text, current_reviews=current_reviews)
    if clean is not None:
        return {"verdict": "clean", **counts, **clean}
    if _SKIPPED.search(text):
        return {"verdict": "skipped", **counts}
    if current_reviews:
        # a review of the head exists but says nothing this module recognizes; waiting would never end
        return {"verdict": "unrecognized", **counts}
    return None


def _recognized(body: str) -> bool:
    # whether one review says, in wording this module knows, that it found nothing, found something, or was skipped
    if _CLEAN in body:
        return True
    if _ACTIONABLE.search(body):
        return True
    if _SKIPPED.search(body):
        return True
    return bool(_failed_pre_merge_checks(body))


def _clean_details(*, text: str, current_reviews: list[str]) -> dict[str, Any] | None:
    # None unless the text says the review found nothing; else what the clean verdict should add. A review of the head
    # that found nothing in the code still lists the PR-wide pre-merge checks that failed, whichever way it says clean
    failed_checks = _failed_pre_merge_checks("\n".join(current_reviews))
    details: dict[str, Any] = {}
    if failed_checks:
        details["failed_pre_merge_checks"] = failed_checks
    if _CLEAN in text:
        return details
    if _ACTIONABLE.search(text):
        return details
    if failed_checks:
        return details
    return None


def _failed_pre_merge_checks(text: str) -> list[str]:
    # each failed check opens a "- <name>:" line in the section, its advice on the lines after it
    names: set[str] = set()
    for section in _PRE_MERGE_SECTION.findall(text):
        names.update(_PRE_MERGE_CHECK.findall(section))
    return sorted(names)


def allowance_used_up(bodies: list[str]) -> bool:
    if not bodies:
        return False
    return _ALLOWANCE.search(bodies[-1]) is not None


def asks_for_review(body: str) -> bool:
    """Return whether a PR comment asks CodeRabbit for a review, as `@coderabbitai review` or `full review` do."""
    return _REVIEW_REQUEST.search(body) is not None


def reviewing_since(comments: list[dict[str, str]]) -> datetime.datetime | None:
    """Return when the comment that says a review is running was last edited, or None if no comment says so."""
    for comment in sorted(comments, key=lambda c: c["edited_at"], reverse=True):
        if _REVIEWING.search(comment["body"]) is not None:
            return datetime.datetime.fromisoformat(comment["edited_at"])
    return None


def held_back(comments: list[dict[str, str]]) -> str | None:
    """Return CodeRabbit's newest note that it is out of allowance or still reviewing, or None without a current one.

    CodeRabbit rewrites its summary comment in place, and a limit note's "available in N minutes" counts from that
    rewrite, which can be hours old by the time anyone reads it. So the countdown becomes the time it ends, and a
    note whose time has passed is dropped: the allowance is back. A note with no countdown says when it was written.
    """
    note = _newest_note(comments)
    if note is None:
        return None
    text, edited_at, available_at = note
    if available_at is None:
        return f"{text} (as of {edited_at})"
    if available_at <= datetime.datetime.now(datetime.UTC):
        return None
    return f"{text}; next included review available at {available_at.isoformat()}"


def allowance_returns_at(comments: list[dict[str, str]]) -> datetime.datetime | None:
    """Return when CodeRabbit's newest limit note says its next review is available, or None without a future one.

    A wait can end then: CodeRabbit doesn't start a held-back review by itself, so that is when to ask for it again.
    """
    note = _newest_note(comments)
    if note is None:
        return None
    available_at = note[2]
    if available_at is None:
        return None
    if available_at <= datetime.datetime.now(datetime.UTC):
        return None
    return available_at


def _newest_note(comments: list[dict[str, str]]) -> tuple[str, str, datetime.datetime | None] | None:
    # the note's text, when its comment was last edited, and when the countdown in it ends, if it has one. The summary
    # comment is CodeRabbit's oldest but is rewritten in place, so notes are taken newest edit first, not newest comment
    for comment in sorted(comments, key=lambda c: c["edited_at"], reverse=True):
        match = _HELD_BACK.search(comment["body"])
        if match is None:
            continue
        timing = _NEXT_REVIEW.search(comment["body"])
        if timing is None:
            return match.group(), comment["edited_at"], None
        edited_at = datetime.datetime.fromisoformat(comment["edited_at"])
        return match.group(), comment["edited_at"], edited_at + datetime.timedelta(minutes=int(timing.group(1)))
    return None
