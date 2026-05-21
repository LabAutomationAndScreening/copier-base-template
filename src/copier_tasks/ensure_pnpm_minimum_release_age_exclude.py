import argparse
from pathlib import Path


def _parse_patterns(raw: str) -> list[str]:
    return [p.strip().strip('"').strip("'") for p in raw.split(",") if p.strip()]


def ensure_minimum_release_age_exclude(*, workspace_path: Path, patterns: list[str]) -> None:
    if not workspace_path.exists():
        print(f"{workspace_path} not found; skipping.")  # noqa: T201 -- copier task output must reach the user
        return


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
