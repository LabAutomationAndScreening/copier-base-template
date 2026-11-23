"""What the test-guidance-wording scripts share: where a run may happen, and how one run is made.

A run is one headless `claude -p` call with tools off. The guidance reaches it in one of two ways, and the two
measure different things:

- "pasted": the guidance sits inside the prompt, under a one-line system prompt. Nothing is read from disk, so the
  run folder stays empty. Used for reviewing, where every arm must see exactly the bytes the prompt holds.
- "project": the run folder holds the arm's guidance files and the CLI loads them as project instructions, under
  its own system prompt. This is how guidance reaches an agent in real use. Used for authoring.

Either way the run folder has to sit outside every repository, with no instruction file above it. A subagent or
a CLI call started inside a repository loads that repository's guidance, working-tree edits included, so every
arm would see the same thing and no two wordings could be told apart.
"""

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

PASTED = "pasted"
PROJECT = "project"
MODES = (PASTED, PROJECT)
DEFAULT_MODEL = "opus"
DEFAULT_EFFORT = "medium"
DEFAULT_TIMEOUT_SECONDS = 900
REVIEWER_SYSTEM_PROMPT = "You are a careful reviewer. Answer exactly what is asked."
RULES_DIR = Path(".claude") / "rules"
_FRONTMATTER_FENCE = "---"

_INSTRUCTION_PATHS = (
    Path("AGENTS.md"),
    Path("CLAUDE.md"),
    Path("CLAUDE.local.md"),
    Path(".claude") / "CLAUDE.md",
    RULES_DIR,
    Path(".claude") / "settings.json",
    Path(".claude") / "settings.local.json",
)


class RunFolderError(Exception):
    pass


class ResultFormatError(Exception):
    pass


@dataclass(frozen=True)
class CliSettings:
    cli: str
    model: str
    effort: str
    keep_api_key: bool
    timeout_seconds: int


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--model", default=DEFAULT_MODEL)
    _ = parser.add_argument("--effort", default=DEFAULT_EFFORT)
    _ = parser.add_argument(
        "--keep-api-key", action="store_true", help="leave ANTHROPIC_API_KEY in the run's environment"
    )
    _ = parser.add_argument("--cli", default="claude", help="the CLI to run; a stand-in when testing this script")
    _ = parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)


def cli_settings(args: argparse.Namespace) -> CliSettings:
    return CliSettings(
        cli=args.cli,
        model=args.model,
        effort=args.effort,
        keep_api_key=args.keep_api_key,
        timeout_seconds=args.timeout_seconds,
    )


@dataclass(frozen=True)
class RunResult:
    turns: int
    input_tokens: int
    output_tokens: int
    is_error: bool
    reply: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _instruction_paths_above(folder: Path) -> list[Path]:
    found: list[Path] = []
    for ancestor in folder.resolve().parents:
        found.extend(ancestor / relative for relative in _INSTRUCTION_PATHS if (ancestor / relative).exists())
    return found


def _is_inside_git_work_tree(folder: Path) -> bool:
    completed = subprocess.run(  # noqa: S603 — git with fixed arguments and one path
        ["git", "-C", str(folder), "rev-parse", "--is-inside-work-tree"],  # noqa: S607 — git is expected on PATH
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "true"


def _nearest_existing(folder: Path) -> Path:
    for candidate in (folder, *folder.parents):
        if candidate.exists():
            return candidate
    raise RunFolderError(f"Nothing on the way to {folder} exists")


def check_run_folder(folder: Path) -> None:
    """Refuse a folder that could leak guidance into a run, and create it once it is known to be safe."""
    if folder.exists() and not folder.is_dir():
        raise RunFolderError(f"{folder} is not a directory. Name a folder outside every repository.")
    if _is_inside_git_work_tree(_nearest_existing(folder.resolve())):
        raise RunFolderError(
            f"{folder} is inside a git work tree, so a run there could load that repository's guidance."
        )
    above = _instruction_paths_above(folder)
    if above:
        listed = ", ".join(str(path) for path in above)
        raise RunFolderError(f"Instruction files sit above {folder} and would reach every run: {listed}")
    folder.mkdir(parents=True, exist_ok=True)


def files_under(tree: Path) -> set[Path]:
    return {path.relative_to(tree) for path in tree.rglob("*") if path.is_file()}


def empty_run_folder(*, folder: Path, placed_by_arms: set[Path]) -> None:
    """Remove what an earlier arm left in the run folder, and refuse to go on if anything else is there.

    Only paths that some arm could have placed are removed, so pointing this at the wrong folder deletes nothing
    of the user's. Whatever remains afterwards was not put there by this tool, and the CLI might load it, so it
    is reported instead of ignored.
    """
    for relative in placed_by_arms:
        placed = folder / relative
        if placed.is_file():
            placed.unlink()
    directories = {parent for relative in placed_by_arms for parent in relative.parents if parent != Path()}
    for relative in sorted(directories, key=lambda directory: len(directory.parts), reverse=True):
        directory = folder / relative
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    leftovers = sorted(str(path.relative_to(folder)) for path in folder.rglob("*"))
    if leftovers:
        raise RunFolderError(f"{folder} holds files this tool did not place: {', '.join(leftovers)}")


def _without_paths_frontmatter(text: str) -> str:
    lines = text.splitlines(keepends=True)
    if not lines:
        return text
    if lines[0].rstrip("\r\n") != _FRONTMATTER_FENCE:
        return text
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") == _FRONTMATTER_FENCE:
            if not any(entry.startswith("paths:") for entry in lines[1:index]):
                return text
            rest = lines[index + 1 :]
            while rest and not rest[0].strip():
                rest = rest[1:]
            return "".join(rest)
    return text


def as_delivered(*, relative: Path, text: str) -> str:
    """Return the guidance file's text as a run is given it.

    A rules file whose frontmatter has `paths:` loads only when the agent touches a matching file, which never
    happens with tools off, so the rule would be absent from every run. Runs get it without that frontmatter, as
    if it had loaded. Whether it loads at the moment it is needed is therefore not something a run can show.
    """
    if relative.is_relative_to(RULES_DIR):
        return _without_paths_frontmatter(text)
    return text


def rules_files_with_paths(tree: Path) -> list[Path]:
    found: list[Path] = []
    for relative in sorted(files_under(tree)):
        text = (tree / relative).read_text(encoding="utf-8")
        if as_delivered(relative=relative, text=text) != text:
            found.append(relative)
    return found


def place_arm(*, arm_tree: Path, folder: Path) -> None:
    for relative in files_under(arm_tree):
        destination = folder / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = (arm_tree / relative).read_bytes().decode("utf-8")
        _ = destination.write_bytes(as_delivered(relative=relative, text=source).encode("utf-8"))


def _cli_arguments(*, mode: str, model: str, effort: str) -> list[str]:
    shared = [
        "-p",
        "--model",
        model,
        "--effort",
        effort,
        "--tools",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--output-format",
        "json",
    ]
    if mode == PASTED:
        return [*shared, "--setting-sources", "", "--system-prompt", REVIEWER_SYSTEM_PROMPT]
    return [*shared, "--setting-sources", "project"]


def _executable(cli: str) -> str:
    # The run happens in the run folder, where a path relative to the caller's directory would point at nothing.
    if os.sep in cli:
        return str(Path(cli).resolve())
    return cli


def _environment(*, keep_api_key: bool) -> dict[str, str]:
    environment = dict(os.environ)
    if not keep_api_key:
        # A devcontainer may export a placeholder key, which the CLI prefers over the stored login and fails on.
        _ = environment.pop("ANTHROPIC_API_KEY", None)
    return environment


def run_cli(*, settings: CliSettings, mode: str, folder: Path, prompt: str, result_path: Path) -> int:
    completed = subprocess.run(  # noqa: S603 — the CLI named by the caller, with every value a separate argument
        [_executable(settings.cli), *_cli_arguments(mode=mode, model=settings.model, effort=settings.effort)],
        cwd=folder,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=settings.timeout_seconds,
        env=_environment(keep_api_key=settings.keep_api_key),
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    _ = result_path.write_text(completed.stdout, encoding="utf-8")
    _ = result_path.with_suffix(".err").write_text(completed.stderr, encoding="utf-8")
    return completed.returncode


def _field(*, container: object, key: str, source: Path) -> object:
    if not isinstance(container, dict):
        raise ResultFormatError(f"{source}: expected a JSON object around {key!r}")
    if key not in container:
        raise ResultFormatError(f"{source}: no {key!r} in the result")
    return container[key]


def _count(*, container: object, key: str, source: Path) -> int:
    value = _field(container=container, key=key, source=source)
    if isinstance(value, bool):
        raise ResultFormatError(f"{source}: {key!r} is not a count")
    if not isinstance(value, int):
        raise ResultFormatError(f"{source}: {key!r} is not a count")
    return value


def _optional_count(*, container: object, key: str, source: Path) -> int:
    if isinstance(container, dict) and key not in container:
        return 0
    return _count(container=container, key=key, source=source)


def read_result(path: Path) -> RunResult:
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ResultFormatError(f"{path}: not JSON ({error.msg}). Its .err file may say why.") from error
    usage = _field(container=parsed, key="usage", source=path)
    reply = _field(container=parsed, key="result", source=path)
    if not isinstance(reply, str):
        raise ResultFormatError(f"{path}: 'result' is not text")
    # Cached input still entered the context, so all three counts together are what the model was given.
    input_tokens = (
        _count(container=usage, key="input_tokens", source=path)
        + _optional_count(container=usage, key="cache_creation_input_tokens", source=path)
        + _optional_count(container=usage, key="cache_read_input_tokens", source=path)
    )
    return RunResult(
        turns=_count(container=parsed, key="num_turns", source=path),
        input_tokens=input_tokens,
        output_tokens=_count(container=usage, key="output_tokens", source=path),
        is_error=_field(container=parsed, key="is_error", source=path) is True,
        reply=reply,
    )
