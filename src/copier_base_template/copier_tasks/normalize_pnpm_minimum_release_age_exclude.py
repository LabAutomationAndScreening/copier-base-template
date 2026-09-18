# PNPM12-MIGRATION -- this entire module is transient. It exists only to carry repos across the pnpm 11 -> 12
# boundary, where minimumReleaseAgeExclude changed from a comma-delimited string to a YAML sequence. Once every
# downstream repo has taken an update that runs it, delete this file, its symlink under
# `template/src/copier_tasks/`, its test module, and the migration that invokes it. Grep PNPM12-MIGRATION.
import argparse
from pathlib import Path

_WORKSPACE_FILENAME = "pnpm-workspace.yaml"
_SETTING_NAME = "minimumReleaseAgeExclude"
_COMMENT_SEPARATOR = " #"


# Identical to the helper in ensure_pnpm_minimum_release_age_exclude.py on purpose: each copier task script is
# symlinked into generated repos on its own, so one importing another would break wherever only one lands, and
# this module is deleted at the end of the pnpm 12 migration regardless.
# pylint: disable=duplicate-code
def _parse_patterns(raw: str) -> list[str]:
    patterns: list[str] = []
    for raw_pattern in raw.split(","):
        # Quotes are removed before the emptiness check so a quoted-empty entry doesn't yield an empty pattern.
        pattern = raw_pattern.strip().strip('"').strip("'")
        if pattern == "":
            continue
        patterns.append(pattern)
    return patterns


# pylint: enable=duplicate-code


def _split_trailing_comment(*, raw_value: str) -> tuple[str, str]:
    separator_index = raw_value.find(_COMMENT_SEPARATOR)
    if separator_index < 0:
        return raw_value, ""
    return raw_value[:separator_index], raw_value[separator_index:]


def _sequence_lines(*, patterns: list[str], comment: str) -> list[str]:
    lines = [f"{_SETTING_NAME}:{comment}\n"]
    for pattern in patterns:
        # YAML single-quoted scalars escape an embedded quote by doubling it
        escaped = pattern.replace("'", "''")
        lines.append(f"  - '{escaped}'\n")
    return lines


def normalize_minimum_release_age_exclude(*, workspace_dir: Path) -> None:
    """Rewrite a pre-pnpm-12 comma-delimited `minimumReleaseAgeExclude` string as a YAML sequence.

    pnpm 12 refuses to load a workspace manifest whose value for this setting is a scalar, and that
    refusal fails every pnpm command rather than just an install, so the value cannot be repaired
    with `pnpm config` once pnpm 12 is in place. Only the setting's own line is rewritten, leaving
    the rest of the manifest -- including its comments -- byte for byte as it was.
    """
    workspace_path = workspace_dir / _WORKSPACE_FILENAME
    if not workspace_path.exists():
        print(f"{workspace_path} not found; skipping.")  # noqa: T201 -- copier migration output must reach the user
        return

    lines = workspace_path.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.startswith(f"{_SETTING_NAME}:"):
            continue
        raw_value, comment = _split_trailing_comment(raw_value=line[len(_SETTING_NAME) + 1 :].strip())
        if raw_value.strip() == "":
            print(f"{_SETTING_NAME} in {workspace_path} is already a list; nothing to do.")  # noqa: T201 -- copier migration output must reach the user
            return
        patterns = _parse_patterns(raw_value)
        if len(patterns) == 0:
            # An empty string is not a valid list either, and the copier task rewrites the value anyway
            del lines[index]
            _ = workspace_path.write_text("".join(lines), encoding="utf-8")
            print(f"Removed the empty {_SETTING_NAME} string from {workspace_path}.")  # noqa: T201 -- copier migration output must reach the user
            return
        lines[index : index + 1] = _sequence_lines(patterns=patterns, comment=comment)
        _ = workspace_path.write_text("".join(lines), encoding="utf-8")
        print(f"Rewrote {_SETTING_NAME} in {workspace_path} as a YAML list of {len(patterns)} pattern(s).")  # noqa: T201 -- copier migration output must reach the user
        return

    print(f"{_SETTING_NAME} not set in {workspace_path}; nothing to do.")  # noqa: T201 -- copier migration output must reach the user


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--target-dir", default=".", dest="target_dir")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    normalize_minimum_release_age_exclude(workspace_dir=Path(args.target_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
