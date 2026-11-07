import subprocess
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 60


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    stdin: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and return its result whatever its exit status, for scripts that report failures themselves.

    The pr-comments skill's run_cmd raises on failure and exits on a timeout. commit_for_comment.py and
    push_and_post.py decide per command what a failure or a timeout means, so they need the raw result.
    """
    return subprocess.run(  # noqa: S603 — git, bd and this repo's own skill scripts, with every value a separate argument
        cmd,
        cwd=cwd,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        # a hook's stray bytes must not turn a commit that happened into a crash that hides its SHA
        errors="replace",
        check=False,
        timeout=timeout,
        env=env,
    )
