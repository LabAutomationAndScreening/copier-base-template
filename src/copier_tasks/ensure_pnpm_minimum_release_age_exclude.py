import argparse
import re
from pathlib import Path


def _parse_patterns(raw: str) -> list[str]:
    return [p.strip().strip('"').strip("'") for p in raw.split(",") if p.strip()]


def ensure_minimum_release_age_exclude(*, workspace_path: Path, patterns: list[str]) -> None:
    if not workspace_path.exists():
        print(f"{workspace_path} not found; skipping.")  # noqa: T201 -- copier task output must reach the user
        return

    text = workspace_path.read_text(encoding="utf-8")

    if not re.search(r"^minimumReleaseAgeExclude:", text, re.MULTILINE):
        addition = "\nminimumReleaseAgeExclude:\n"
        for p in patterns:
            addition += f'  - "{p}"\n'
        _ = workspace_path.write_text(text.rstrip("\n") + "\n" + addition, encoding="utf-8")
        print(f"Added minimumReleaseAgeExclude section with {len(patterns)} pattern(s).")  # noqa: T201 -- copier task output must reach the user


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--patterns", required=True)
    _ = parser.add_argument("--target-file", default="pnpm-workspace.yaml", dest="target_file")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    ensure_minimum_release_age_exclude(
        workspace_path=Path(args.target_file),
        patterns=_parse_patterns(args.patterns),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
