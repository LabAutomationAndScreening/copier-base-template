import argparse
import tomllib
from pathlib import Path

_ERRORS_TABLE_HEADER = "[errors]"
_SETTING_NAME = "implicit-reexport"
_SETTING_LINES = [
    "# The check keeps a distributed library's public API deliberate: consumers should only reach symbols the\n",
    "# package explicitly re-exports via __all__ or a redundant alias. This project is not a distributed library,\n",
    "# so every importer is in-repo and the __all__ bookkeeping buys nothing.\n",
    f'{_SETTING_NAME} = "ignore"\n',
]


def _end_of_table(*, lines: list[str], header_index: int) -> int:
    end_index = header_index + 1
    while end_index < len(lines):
        if lines[end_index].startswith("["):
            break
        end_index += 1
    while lines[end_index - 1].strip() == "":
        end_index -= 1
    return end_index


def ignore_implicit_reexport(*, config_path: Path) -> None:
    text = config_path.read_text(encoding="utf-8")
    if _SETTING_NAME in tomllib.loads(text)["errors"]:
        print(f"{_SETTING_NAME} already configured in {config_path}; nothing to do.")  # noqa: T201 -- copier task output must reach the user
        return
    lines = text.splitlines(keepends=True)
    header_index = lines.index(f"{_ERRORS_TABLE_HEADER}\n")
    insert_index = _end_of_table(lines=lines, header_index=header_index)
    lines[insert_index:insert_index] = _SETTING_LINES
    _ = config_path.write_text("".join(lines), encoding="utf-8")
    print(f"Ignored {_SETTING_NAME} in {config_path}.")  # noqa: T201 -- copier task output must reach the user


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ignore pyrefly's implicit-reexport check in a pyrefly config file.",
    )
    _ = parser.add_argument("--target-file", required=True, dest="target_file")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config_path = Path(args.target_file)
    # the task only runs for templates that render this file, so its absence means the path or template layout is wrong
    if not config_path.exists():
        print(f"{config_path} not found; cannot ignore {_SETTING_NAME}.")  # noqa: T201 -- copier task output must reach the user
        return 1
    ignore_implicit_reexport(config_path=config_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
