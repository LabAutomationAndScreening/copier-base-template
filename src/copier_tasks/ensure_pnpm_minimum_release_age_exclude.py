import argparse
import shutil
import subprocess
from pathlib import Path

_EXIT_CODE_PNPM_NOT_FOUND = 1
_WORKSPACE_FILENAME = "pnpm-workspace.yaml"


def _parse_patterns(raw: str) -> list[str]:
    return [p.strip().strip('"').strip("'") for p in raw.split(",") if p.strip()]


def ensure_minimum_release_age_exclude(*, workspace_dir: Path, patterns: list[str]) -> None:
    if shutil.which("pnpm") is None:
        print(  # noqa: T201 -- copier task output must reach the user
            "pnpm not found on PATH; cannot update minimumReleaseAgeExclude. Install pnpm and try again: npm install -g pnpm"
        )
        raise SystemExit(_EXIT_CODE_PNPM_NOT_FOUND)

    if not (workspace_dir / _WORKSPACE_FILENAME).exists():
        print(f"{workspace_dir / _WORKSPACE_FILENAME} not found; skipping.")  # noqa: T201 -- copier task output must reach the user
        return

    get_result = subprocess.run(
        ["pnpm", "config", "--location", "project", "get", "minimumReleaseAgeExclude"],  # noqa: S607 -- pnpm is a trusted tool, not user input
        check=True,
        capture_output=True,
        text=True,
        cwd=workspace_dir,
    )
    raw_existing = get_result.stdout.strip()
    existing = _parse_patterns(raw_existing) if raw_existing != "undefined" else []
    merged = existing + [p for p in patterns if p not in existing]
    _ = subprocess.run(  # noqa: S603 -- merged patterns come from pnpm config get and CLI input, both trusted in this copier task context
        ["pnpm", "config", "--location", "project", "set", "minimumReleaseAgeExclude", ",".join(merged)],  # noqa: S607 -- pnpm is a trusted tool, not user input
        check=True,
        cwd=workspace_dir,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--patterns", required=True)
    _ = parser.add_argument("--target-dir", default=".", dest="target_dir")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    ensure_minimum_release_age_exclude(
        workspace_dir=Path(args.target_dir),
        patterns=_parse_patterns(args.patterns),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
