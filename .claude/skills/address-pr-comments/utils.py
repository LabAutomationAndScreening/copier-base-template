import json
import re
import subprocess
import sys
from pathlib import Path


def run_cmd(
    cmd: list[str],
    *,
    timeout: int,
    timeout_msg: str,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 — callers are responsible for only passing safe commands
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _ = sys.stderr.write(f"{timeout_msg}\n")
        sys.exit(1)


def owner_repo_from_remote() -> tuple[str, str]:
    try:
        result = run_cmd(
            ["git", "remote", "get-url", "origin"],
            timeout=15,
            timeout_msg="Timed out reading git remote 'origin'.",
        )
    except subprocess.CalledProcessError:
        _ = sys.stderr.write("Cannot read git remote 'origin'. Ensure it exists and points to GitHub.\n")
        sys.exit(1)
    url = result.stdout.strip()
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?",
        url,
    )
    if not match:
        _ = sys.stderr.write(f"Cannot parse GitHub owner/repo from remote: {url}\n")
        sys.exit(1)
    return match.group(1), match.group(2)


def read_body_file(body_file: Path) -> str:
    try:
        return body_file.read_text(encoding="utf-8")
    except OSError as e:
        _ = sys.stderr.write(f"Unable to read body file {body_file}: {e}\n")
        sys.exit(1)


def post_via_gh_api(*, cmd: list[str], body_file: Path, timeout_msg: str) -> None:
    """Run a gh api POST, print the new comment's URL, then delete the body file it was posted from.

    Exits with status 1 if gh api fails. A failure to delete the body file only warns, since the post went through.
    """
    try:
        result = run_cmd(cmd, timeout=30, timeout_msg=timeout_msg)
    except subprocess.CalledProcessError as e:
        _ = sys.stderr.write(f"gh api error: {e.stderr}\n")
        sys.exit(1)

    response = json.loads(result.stdout)
    _ = sys.stdout.write(f"Posted: {response.get('html_url', '(no URL in response)')}\n")

    try:
        body_file.unlink()
    except OSError as e:
        _ = sys.stderr.write(f"Warning: post succeeded but could not delete body file {body_file}: {e}\n")
