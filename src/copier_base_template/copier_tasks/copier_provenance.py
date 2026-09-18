"""Stamp every file a copier template placed in a project with a provenance marker and record it in a manifest.

Run as a copier task after rendering. It walks the template directory, resolves each template path to the
path it rendered to, and for every such file that exists in the destination it inserts a comment naming the
template that owns the file, then writes .config/.copier-managed-files.json listing every managed file under
its owning template.
"""

import argparse
import json
import os
import re
import sys
from operator import itemgetter
from pathlib import Path
from typing import NotRequired
from typing import TypedDict


class Entry(TypedDict):
    src: str
    parent_src: NotRequired[str]
    managed_files: list[str]


class Manifest(TypedDict):
    templates: list[Entry]


MANIFEST_PATH = Path(".config") / ".copier-managed-files.json"
RENAMES_PATH = Path(".config") / "copier-renames.json"

# base-template declares _templates_suffix .jinja-base and child templates declare .jinja. Existing child
# templates still call this task without --templates-suffix, so both are stripped unless one is named.
DEFAULT_SUFFIXES = (".jinja-base", ".jinja")

# Tool caches and dependency trees that can sit inside a template checkout but are never template content.
PRUNED_DIRECTORIES = frozenset(
    {
        ".git",
        ".ruff_cache",
        ".pytest_cache",
        ".mypy_cache",
        "__pycache__",
        "node_modules",
        ".venv",
        ".pnpm-store",
        ".turbo",
        ".nuxt",
        ".output",
    }
)

# Code-generator output is committed in the template but regenerated in the project, so it is never claimed.
# An earlier marker in such a file is still stripped.
EXCLUDED_SEGMENT = "generated"

# Comment style -> (opener, per-line prefix, closer). A None prefix leaves lines bare; an empty opener means
# a line-comment style with no surrounding delimiters.
STYLES: dict[str, tuple[str, str | None, str]] = {
    "hash": ("", "#", ""),
    "batch": ("", "REM", ""),
    "block": ("/*", " *", " */"),
    "jinja": ("{#", "", "#}"),
    "markdown": ("<!--", None, "-->"),
}

# Keyed by exact filename first, then by suffix. A None style means the file takes no marker at all.
# Bottom placement keeps shebangs and @echo off on line one.
FORMATS: dict[str, tuple[str | None, str]] = {
    ".copier-answers.yml": (None, "top"),
    ".python-version": (None, "top"),
    ".prettierrc": (None, "top"),
    ".nvmrc": (None, "top"),
    ".node-version": (None, "top"),
    ".coveragerc": ("hash", "bottom"),
    ".md": ("markdown", "bottom"),
    ".sh": ("hash", "bottom"),
    ".bat": ("batch", "bottom"),
    ".js": ("block", "top"),
    ".cjs": ("block", "top"),
    ".mjs": ("block", "top"),
    ".ts": ("block", "top"),
    ".cts": ("block", "top"),
    ".mts": ("block", "top"),
    ".css": ("block", "top"),
    ".jsonc": ("block", "top"),
    ".json": (None, "top"),
    ".vue": ("markdown", "top"),
    ".html": ("markdown", "top"),
    ".svg": ("markdown", "top"),
    ".jinja": ("jinja", "top"),
    ".jinja-base": ("jinja", "top"),
}
DEFAULT_FORMAT: tuple[str | None, str] = ("hash", "top")

RAW_TAG = re.compile(r"\{%-?\s*(?:raw|endraw)\s*-?%\}")
ANY_TAG = re.compile(r"\{%.*?%\}")

# One marker in any comment style this task has ever written: an optional opener line, the WARNING rule, the
# body, the closing rule, and an optional closer. The closer of the Jinja style is glued to the content, so
# the newline after it is optional.
MARKER = (
    r"(?:(?:/\*|\{#|<!--)\n)?"
    r"[^\n]*={14} WARNING[^\n]*\n"
    r"(?:[^\n]*\n)*?"
    r"[^\n]*={50,}\n"
    r"(?:[ -]*(?:\*/|#\}|-->)\n?)?"
)
# Anchored to the two edges of the file: marker text also appears as ordinary data inside some managed
# files, such as this task's own test suite.
TOP_MARKERS = re.compile(r"\A(?:" + MARKER + ")+")
BOTTOM_MARKERS = re.compile(r"(?:\n?" + MARKER + r")+\s*\Z")


def marker_text(template_src: str) -> str:
    if template_src == "":
        managed_by = "File is managed by a copier template. See .config/.copier-managed-files.json for details."
    else:
        managed_by = (
            f"File is managed by copier template: {template_src}\nSee .config/.copier-managed-files.json for details."
        )
    return (
        "============== WARNING ==============================================================================\n"
        f"{managed_by}\n"
        "\n"
        "You are welcome to make changes to this file in your repo if they are custom to your project,\n"
        "but if the change should be shared with other projects, please backport it to the template repo.\n"
        "====================================================================================================="
    )


def render_marker(style: str, text: str) -> str:
    opener, prefix, closer = STYLES[style]
    lines: list[str] = []
    for line in text.split("\n"):
        if prefix is None:
            lines.append(line)
        elif line == "":
            lines.append(prefix)
        else:
            lines.append(f"{prefix} {line}")
    body = "\n".join(lines)
    if opener == "":
        return body
    return f"{opener}\n{body}\n{closer}"


def comment_format(filename: str) -> tuple[str | None, str]:
    # A destination name can still carry a Jinja if-check when the file is itself handed down to a
    # grandchild template, so the tags come off before the suffix is read.
    name = ANY_TAG.sub("", filename)
    if name in FORMATS:
        return FORMATS[name]
    suffix = Path(name).suffix
    if suffix in FORMATS:
        return FORMATS[suffix]
    return DEFAULT_FORMAT


def stamp(file: Path, template_src: str | None) -> None:
    """Rewrite the file with exactly one marker naming template_src, or with no marker when it is None.

    Line endings are preserved: a file that is mostly CRLF is written back as CRLF. A file that is not
    UTF-8 text is left alone. A file that already has the right content is not written, so its mtime
    does not move.
    """
    original = file.read_bytes()
    try:
        raw = original.decode("utf-8")
    except UnicodeDecodeError:
        return
    crlf_count = raw.count("\r\n")
    if crlf_count > raw.count("\n") - crlf_count:
        newline = "\r\n"
    else:
        newline = "\n"

    content = BOTTOM_MARKERS.sub("", TOP_MARKERS.sub("", raw.replace("\r\n", "\n"), count=1), count=1)
    style, location = comment_format(file.name)
    if template_src is not None and style is not None:
        marker = render_marker(style, marker_text(template_src))
        if location == "top" and not content.startswith("#!/"):
            # A Jinja comment renders to nothing, so a newline after it would become a blank first line in
            # the rendered file. The marker is glued to the first line of content instead.
            if style == "jinja":
                content = marker + content
            else:
                content = marker + "\n" + content
        else:
            content = content + "\n" + marker + "\n"

    updated = content.replace("\n", newline).encode("utf-8")
    if updated != original:
        _ = file.write_bytes(updated)


def destination_name(template_name: str, suffixes: tuple[str, ...]) -> str:
    """Return the name a template path segment renders to.

    A raw-wrapped name keeps its inner Jinja verbatim, because that Jinja is meant for the child template
    to render later. Otherwise every tag is dropped, leaving the literal text of the if-check. Only a
    declared template suffix comes off: with .jinja-base declared, a trailing .jinja is literal content.
    """
    name = RAW_TAG.sub("", template_name)
    if name == template_name:
        name = ANY_TAG.sub("", template_name)
    for suffix in suffixes:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def destination_path(template_path: Path, suffixes: tuple[str, ...]) -> Path:
    return Path(*(destination_name(part, suffixes) for part in template_path.parts))


def destination_paths(template_dir: Path, suffixes: tuple[str, ...]) -> list[Path]:
    # The template is walked and the destination probed, never the reverse: a project's node_modules can
    # hold symlink cycles that a followlinks walk of the destination would never finish.
    paths: list[Path] = []
    for root, dirnames, filenames in os.walk(template_dir, followlinks=True):
        dirnames[:] = [d for d in dirnames if destination_name(d, suffixes) not in PRUNED_DIRECTORIES]
        paths.extend(destination_path((Path(root) / f).relative_to(template_dir), suffixes) for f in filenames)
    return sorted(paths)


def find_manifest(repo_dir: Path) -> Path:
    preferred = repo_dir / MANIFEST_PATH
    if preferred.exists():
        return preferred
    return repo_dir / MANIFEST_PATH.name


def load_manifest(path: Path) -> Manifest:
    manifest: Manifest = json.loads(path.read_text(encoding="utf-8"))
    return manifest


class Rename(TypedDict):
    source: str
    target: str
    when: str | None


def load_renames(template_dir: Path) -> list[Rename]:
    """Return the moves the calling template's own tasks make after rendering, as declared in its repo.

    The same file drives copier_renames.py, which performs the moves, so the two never disagree about
    where a file ends up. `when` names a copier answer that has to be true for the move to happen.
    """
    renames_path = template_dir.parent / RENAMES_PATH
    if not renames_path.exists():
        return []
    declared: dict[str, list[dict[str, str]]] = json.loads(renames_path.read_text(encoding="utf-8"))
    return [
        {"source": rename["from"], "target": rename["to"], "when": rename.get("when")} for rename in declared["renames"]
    ]


def read_answer(dst_dir: Path, name: str) -> str | None:
    answers = dst_dir / ".config" / ".copier-answers.yml"
    if not answers.exists():
        answers = dst_dir / ".copier-answers.yml"
    if not answers.exists():
        return None
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", answers.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        return None
    return match.group(1).strip()


def rename_applies(dst_dir: Path, rename: Rename) -> bool:
    """Tell whether the rename is in effect in this destination, judged by its `when` answer alone.

    The state of the filesystem is deliberately not consulted: a stray directory at the target, such as a
    gitignored .venv, says nothing about what the project answered.
    """
    if rename["when"] is None:
        return True
    return read_answer(dst_dir, rename["when"]) == "true"


def landing_paths(dst_dir: Path, renames: list[Rename]) -> dict[str, str]:
    """Map each declared source path to where it actually lands in this destination."""
    landing: dict[str, str] = {}
    for rename in renames:
        if rename_applies(dst_dir, rename):
            landing[rename["source"]] = rename["target"]
    return landing


def read_parent_src(template_dir: Path) -> str | None:
    """Return the _src_path of the template repo's own copier answers, i.e. the template that generated it."""
    answers = template_dir.parent / ".config" / ".copier-answers.yml"
    if not answers.exists():
        answers = template_dir.parent / ".copier-answers.yml"
    if not answers.exists():
        return None
    match = re.search(r"^_src_path:\s*(.+)$", answers.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        return None
    return match.group(1).strip()


def read_ancestors(template_dir: Path, suffixes: tuple[str, ...]) -> list[tuple[str, str | None, set[str]]]:
    """Return (src, parent_src, handed-down paths) for each template in the template repo's own manifest.

    Only an ancestor's files under the template directory are handed down to a destination, so only those
    are returned, re-rooted to the destination and in both their template and their rendered spelling.
    """
    manifest_path = find_manifest(template_dir.parent)
    if not manifest_path.exists():
        return []
    prefix = template_dir.name + "/"
    ancestors: list[tuple[str, str | None, set[str]]] = []
    for entry in load_manifest(manifest_path)["templates"]:
        handed_down: set[str] = set()
        for managed_file in entry["managed_files"]:
            if not managed_file.startswith(prefix):
                continue
            template_relative = managed_file.removeprefix(prefix)
            handed_down.add(template_relative)
            handed_down.add(str(destination_path(Path(template_relative), suffixes)))
        ancestors.append((entry["src"], entry.get("parent_src"), handed_down))
    return ancestors


def build_entry(src: str, managed_files: list[str], parent_src: str | None) -> Entry:
    if parent_src is None:
        return {"src": src, "managed_files": managed_files}
    return {"src": src, "parent_src": parent_src, "managed_files": managed_files}


def write_manifest(dst_dir: Path, managed: dict[str, list[str]], parents: dict[str, str | None]) -> None:
    """Write this run's attributions over the manifest on disk.

    Entries for templates this run knows nothing about survive, minus any path this run claimed, so two
    templates never list the same file and a retired template's entry disappears once nothing is left in it.
    """
    manifest_path = dst_dir / MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    claimed = {path for files in managed.values() for path in files}
    entries = [build_entry(src, sorted(files), parents[src]) for src, files in managed.items()]
    if manifest_path.exists():
        for entry in load_manifest(manifest_path)["templates"]:
            if entry["src"] in managed:
                continue
            remaining = [path for path in entry["managed_files"] if path not in claimed]
            if len(remaining) > 0:
                entries.append(build_entry(entry["src"], remaining, entry.get("parent_src")))
    entries.sort(key=itemgetter("src"))
    _ = manifest_path.write_text(json.dumps({"templates": entries}, indent=2) + "\n", encoding="utf-8")


def stamp_all(
    *,
    template_dir: Path,
    dst_dir: Path,
    template_src: str,
    manifest_src: str,
    suffixes: tuple[str, ...],
) -> list[str]:
    """Stamp every destination file the template placed, write the manifest, and return the files that failed.

    A file handed down from an ancestor template is stamped with, and listed under, that ancestor rather than
    the current template. A file the calling template's own tasks move after rendering is found at its renamed
    path but attributed by its source path, which is the one an ancestor manifest records. One unstampable
    file costs neither the rest of the run nor the manifest.
    """
    ancestors = read_ancestors(template_dir, suffixes)
    landing = landing_paths(dst_dir, load_renames(template_dir))
    managed: dict[str, list[str]] = {manifest_src: []}
    parents: dict[str, str | None] = {manifest_src: read_parent_src(template_dir)}
    failures: list[str] = []
    for relative in destination_paths(template_dir, suffixes):
        source = str(relative)
        if source in landing:
            landed = landing[source]
        else:
            landed = source
        file = dst_dir / landed
        if not file.is_file():
            continue
        owner = None
        if EXCLUDED_SEGMENT not in relative.parts:
            owner = template_src
            managed_by = manifest_src
            for ancestor_src, ancestor_parent, handed_down in ancestors:
                if source in handed_down:
                    owner = managed_by = ancestor_src
                    parents[ancestor_src] = ancestor_parent
                    break
            managed.setdefault(managed_by, []).append(landed)
        try:
            stamp(file, owner)
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: no single file may abort the run
            failures.append(f"{landed}: {type(exc).__name__}: {exc}")
    write_manifest(dst_dir, managed, parents)
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Add copier provenance markers and manifest")
    _ = parser.add_argument("src_template_dir", type=Path, help="Template source directory")
    _ = parser.add_argument("dst_dir", type=Path, help="Destination directory")
    _ = parser.add_argument("--template-src", default="", help="Template source identifier for the manifest")
    _ = parser.add_argument(
        "--templates-suffix",
        default="",
        help="The calling template's _templates_suffix. Defaults to stripping both '.jinja-base' and '.jinja'.",
    )
    args = parser.parse_args()
    template_dir = Path(args.src_template_dir)
    template_src = str(args.template_src)
    if args.templates_suffix == "":
        suffixes = DEFAULT_SUFFIXES
    else:
        suffixes = (str(args.templates_suffix),)
    # Without --template-src the markers stay generic, but the manifest still needs a key naming the template.
    if template_src == "":
        manifest_src = str(template_dir)
    else:
        manifest_src = template_src

    failures = stamp_all(
        template_dir=template_dir,
        dst_dir=Path(args.dst_dir),
        template_src=template_src,
        manifest_src=manifest_src,
        suffixes=suffixes,
    )
    if len(failures) > 0:
        print(f"Failed to stamp {len(failures)} file(s):", file=sys.stderr)  # noqa: T201 -- task output is meant for the copier console
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)  # noqa: T201 -- task output is meant for the copier console
        sys.exit(1)


if __name__ == "__main__":
    main()
