import re
import subprocess
import sys


def owner_repo_from_remote() -> tuple[str, str]:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],  # noqa: S607 — git is expected on PATH
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        _ = sys.stderr.write("Cannot read git remote 'origin'. Ensure it exists and points to GitHub.\n")
        sys.exit(1)
    url = result.stdout.strip()
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?",
        url,
    )
    if not match:
        _ = sys.stderr.write(f"Cannot parse GitHub owner/repo from remote: {url}\n")
        sys.exit(1)
    return match.group(1), match.group(2)
