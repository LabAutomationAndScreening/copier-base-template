"""AI review agents that analyze PRs on their own, one module per agent.

Each module defines:

  NAME          the name used on the command line and in output
  CONFIG_FILES  repo-relative paths; the agent counts as enabled when any of them exists
  LOGIN         a regex matching the agent's GitHub login
  CHECK_NAME    the name of the check run the agent puts on each commit it reviews, or None if it puts none.
                Its state on the PR's head comes first: in progress means a review is running, and a
                finished check that didn't succeed means the head went unreviewed (its title and summary
                say why). Without such a check on the head, the agent's comments are all there is to go by
  classify(*, reviews, comments, head) -> dict | None
                the verdict on commit `head` from the agent's review bodies and comment bodies:
                {"verdict": "clean" | "flagged" | "skipped" | "unrecognized", ...counts}, or
                None while it has not reviewed that commit yet. "unrecognized" means a review
                of `head` exists in wording the module doesn't know, so a human has to read it
  QUIET_AFTER_SECONDS
                how long after a PR's latest commit the agent's silence about it means it won't review
                it (it reviewed an earlier commit, and judged the change too small)
  asks_for_review(comment_body) -> bool
                whether a PR comment by someone other than the agent asks it for a review; the
                quiet period after the newest such request is waited out like the one after a commit,
                since the agent replies to a request a few seconds after it is made
  still_reviewing(comment_bodies) -> bool
                whether the agent says a review is running right now, so its silence about the
                latest commit is waited on rather than reported
  reviewing_since(comments) -> datetime | None
                when the comment saying a review is running was last edited, or None if none says so;
                `comments` as for held_back
  held_back(comments) -> str | None
                the agent's own note that it is out of allowance or still reviewing, with when its
                next review is available if it says, as a time rather than a countdown; it goes into
                a head_not_reviewed verdict so the agent reading it can wait for that review or go
                on. `comments` are the agent's PR comments, oldest first, each a dict with its
                `body` and `edited_at` (ISO 8601), since a note in a comment rewritten in place is
                only as current as that edit
  allowance_returns_at(comments) -> datetime | None
                when the agent's newest note says its next review is available, if that is still to
                come: review-watch keeps waiting until then rather than calling the PR's head unreviewed
  allowance_used_up(review_bodies) -> bool
                whether the agent's last review says it has no reviews left for now, so a wait
                that times out can say why

To support another agent, add a module and list it in REVIEWERS.
"""

from types import ModuleType

from . import coderabbit

REVIEWERS: tuple[ModuleType, ...] = (coderabbit,)
