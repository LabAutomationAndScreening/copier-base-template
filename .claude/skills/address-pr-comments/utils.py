import json
import re
import subprocess
import sys
from collections.abc import Mapping
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


def _read_body_file(body_file: Path) -> str:
    try:
        return body_file.read_text(encoding="utf-8")
    except OSError as e:
        _ = sys.stderr.write(f"Unable to read body file {body_file}: {e}\n")
        sys.exit(1)


def post_via_gh_api(
    *,
    endpoint: str,
    body_file: Path,
    string_fields: Mapping[str, str] | None = None,
    int_fields: Mapping[str, int] | None = None,
    timeout_msg: str,
) -> None:
    """POST a comment to a GitHub API endpoint with gh api, print its URL, then delete the body file it came from.

    The comment's `body` field is read from body_file. string_fields are sent as strings (--raw-field) and int_fields as
    JSON numbers (--field), which is what GitHub expects for values like line numbers.

    Exits with status 1 if gh api fails. Once gh api succeeds the comment exists, so an unparseable response still counts
    as posted and the body file is still deleted (otherwise a retry would post a duplicate). A failure to delete the body
    file only warns.
    """
    body = _read_body_file(body_file)
    cmd = ["gh", "api", endpoint, "--method", "POST", "--raw-field", f"body={body}"]
    if string_fields is not None:
        for key, value in string_fields.items():
            cmd += ["--raw-field", f"{key}={value}"]
    if int_fields is not None:
        for key, value in int_fields.items():
            cmd += ["--field", f"{key}={value}"]

    try:
        result = run_cmd(cmd, timeout=30, timeout_msg=timeout_msg)
    except subprocess.CalledProcessError as e:
        _ = sys.stderr.write(f"gh api error: {e.stderr}\n")
        sys.exit(1)

    try:
        url = json.loads(result.stdout).get("html_url", "(no URL in response)")
    except json.JSONDecodeError:
        url = "(unparseable response)"
    _ = sys.stdout.write(f"Posted: {url}\n")

    try:
        body_file.unlink()
    except OSError as e:
        _ = sys.stderr.write(f"Warning: post succeeded but could not delete body file {body_file}: {e}\n")
