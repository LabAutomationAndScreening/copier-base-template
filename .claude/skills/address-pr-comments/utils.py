import re
import subprocess
import sys


def owner_repo_from_remote() -> tuple[str, str]:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],  # noqa: S607 — git is expected on PATH
        capture_output=True,
        text=True,
        check=True,
    )
    url = result.stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
    if not match:
        _ = sys.stderr.write(f"Cannot parse GitHub owner/repo from remote: {url}\n")
        sys.exit(1)
    return match.group(1), match.group(2)
