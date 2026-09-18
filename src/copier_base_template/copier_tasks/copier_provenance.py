import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from typing import NotRequired
from typing import TypedDict

CommentType = Literal["hash", "batch", "block", "jinja", "markdown", "none"]
Location = Literal["top", "bottom", "none"]


class TemplateEntry(TypedDict):
    src: str
    parent_src: NotRequired[str]
    managed_files: list[str]


class Manifest(TypedDict):
    templates: list[TemplateEntry]


@dataclass
class MarkerResult:
    managed: dict[str, list[str]]
    failures: list[str]


@dataclass
class CommentFormat:
    comment_type: CommentType = "hash"
    location: Location = "top"


default_comment_format = CommentFormat("hash", "top")
custom_file_handling: dict[str, CommentFormat] = {
    ".md": CommentFormat("markdown", "bottom"),
    ".sh": CommentFormat("hash", "bottom"),  # put at bottom to not mess with shebang
    ".bat": CommentFormat("batch", "bottom"),  # put at bottom to not mess with @echo off
    ".js": CommentFormat("block", "top"),
    ".cjs": CommentFormat("block", "top"),
    ".mjs": CommentFormat("block", "top"),
    ".css": CommentFormat("block", "top"),
    ".ts": CommentFormat("block", "top"),
    ".cts": CommentFormat("block", "top"),
    ".mts": CommentFormat("block", "top"),
    ".vue": CommentFormat("markdown", "top"),
    ".html": CommentFormat("markdown", "top"),
    ".svg": CommentFormat("markdown", "top"),
    ".jinja": CommentFormat("jinja", "top"),
    ".jinja-base": CommentFormat("jinja", "top"),
    ".json": CommentFormat("none", "none"),
    ".jsonc": CommentFormat("block", "top"),
    ".yaml": CommentFormat("hash", "top"),
    ".yml": CommentFormat("hash", "top"),
}
# Per-filename overrides for dotfiles/extensionless files where suffix alone is insufficient.
custom_filename_handling: dict[str, CommentFormat] = {
    ".copier-answers.yml": CommentFormat("none", "none"),
    ".coveragerc": CommentFormat("hash", "bottom"),
    ".python-version": CommentFormat("none", "none"),
    ".prettierrc": CommentFormat("none", "none"),
    ".nvmrc": CommentFormat("none", "none"),
    ".node-version": CommentFormat("none", "none"),
}

_MANIFEST_RELPATH = Path(".config") / ".copier-managed-files.json"


def _find_manifest(base_directory: Path) -> Path:
    config_manifest = base_directory / _MANIFEST_RELPATH
    if config_manifest.exists():
        return config_manifest
    return base_directory / ".copier-managed-files.json"


_HEADER_BASE = """\
============== WARNING ==============================================================================
File is managed by a copier template. See .config/.copier-managed-files.json for details.

You are welcome to make changes to this file in your repo if they are custom to your project,
but if the change should be shared with other projects, please backport it to the template repo.
====================================================================================================="""


def _build_header(template_src: str) -> str:
    """Return the header text. With a template_src, embeds the URL on its own line."""
    if template_src == "":
        return _HEADER_BASE
    lines: list[str] = list(_HEADER_BASE.split("\n"))
    # Replace the generic "File is managed" line with two lines: URL line + "See ..." line.
    lines[1] = f"File is managed by copier template: {template_src}"
    lines.insert(2, "See .config/.copier-managed-files.json for details.")
    return "\n".join(lines)


_RAW_MARKER_PATTERN = re.compile(r"\{%-?\s*(?:raw|endraw)\s*-?%\}")


# Which suffix is real depends on the template doing the rendering, so it cannot be inferred from the
# filename. base-template declares _templates_suffix: .jinja-base and ships
# template/template/Taskfile.yaml.jinja, where the trailing .jinja is literal content meant to survive
# into the child template; a child template declares _templates_suffix: .jinja, where it is the suffix.
# Both are stripped when no suffix is declared, because child templates already invoke this task
# without the argument and must keep working until they pass their own.
_DEFAULT_TEMPLATE_SUFFIXES = (".jinja-base", ".jinja")


def _strip_template_suffix(filename: str, suffixes: tuple[str, ...]) -> str:
    for suffix in suffixes:
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def get_base_filename(template_filename: str, suffixes: tuple[str, ...] = _DEFAULT_TEMPLATE_SUFFIXES) -> str:
    """Return the destination filename for a template file.

    Handles three cases:
    - Raw-escaped name: {% raw %}{% if cond %}LICENSE{% endif %}{% endraw %}[.jinja-base]
      Only the raw markers are dropped; the inner Jinja is destined to survive verbatim into the
      child template, so its if-check must not be resolved here.
    - Jinja if-check pattern: {% if cond %}actual_filename{% endif %}[.jinja-base]
      The text between %} and {% is the actual destination filename (no suffix stripping needed).
    - Plain template file: README.md.jinja-base → README.md (strip template suffix).
    """
    if _RAW_MARKER_PATTERN.search(template_filename) is not None:
        return _strip_template_suffix(_RAW_MARKER_PATTERN.sub("", template_filename), suffixes)
    result = re.findall(r"%\}(.*?)\{%", template_filename, re.DOTALL)
    if len(result) > 0:
        assert isinstance(result[0], str)
        return result[0]
    return _strip_template_suffix(template_filename, suffixes)


def _format_lookup_name(dst_filename: str) -> str:
    """Return the name to key comment-format lookups on.

    A destination file can keep a Jinja if-check in its name when it is itself a template file handed
    down to a grandchild (e.g. `{% if is_open_source %}CODE_OF_CONDUCT.md{% endif %}`). Path.suffix
    reads `.md{% endif %}` there, so the wrapper is dropped first. Any template suffix is deliberately
    kept: a `.jinja` file still needs a Jinja comment so it renders away.
    """
    result = re.findall(r"%\}(.*?)\{%", dst_filename, re.DOTALL)
    if len(result) > 0 and result[0] != "":
        assert isinstance(result[0], str)
        return result[0]
    return dst_filename


def _build_specific_header(comment_type: CommentType, template_src: str = "") -> str | None:
    header = _build_header(template_src)
    if comment_type == "hash":
        return "\n".join(f"# {line}" if line != "" else "#" for line in header.split("\n"))
    if comment_type == "batch":
        return "\n".join(f"REM {line}" if line != "" else "REM" for line in header.split("\n"))
    if comment_type == "block":
        body = "\n".join(f" * {line}" if line != "" else " *" for line in header.split("\n"))
        return f"/*\n{body}\n */"
    if comment_type == "jinja":
        # Jinja renders {# ... #} to empty string, so this marker is invisible in rendered output.
        body = "\n".join(f" {line}" if line != "" else "" for line in header.split("\n"))
        return f"{{#\n{body}\n#}}"
    if comment_type == "markdown":
        return f"<!--\n{header}\n-->"
    return None


# Every marker spelling this task has ever written, not just the one the current format would produce.
# A file whose comment format changed between template versions (.jsonc went hash → block) or whose
# format became "none" (.python-version) otherwise keeps the old marker forever, either stacked
# underneath the new one or stranded in a file that is no longer supposed to carry one at all.
_MARKER_BODIES = (
    r"# ={14} WARNING[^\n]*\n(?:.*\n)*?# ={50,}\n",
    r"REM ={14} WARNING[^\n]*\n(?:.*\n)*?REM ={50,}\n",
    r"/\*\n \* ={14} WARNING[^\n]*\n(?: \*.*\n)*? \*/\n",
    # The closing delimiter is glued to the content, so no trailing newline is required. "-?"
    # recognizes a marker written with Jinja whitespace control, which an earlier attempt at the
    # rendered-blank-line fix produced.
    r"\{#\n ={14} WARNING[^\n]*\n(?:.*\n)*?-?#\}\n?",
    r"<!--\n={14} WARNING[^\n]*\n(?:.*\n)*?-->\n",
)

# Anchored at the file's two edges rather than matched anywhere. A marker only ever sits at the very
# top or the very bottom, and marker text also appears as ordinary data inside some managed files --
# this task's own test file quotes every spelling as a string constant, and stamping it used to delete
# those constants out of the file. The bottom form also takes the blank separator line before it.
_TOP_MARKER_PATTERNS = tuple(re.compile(r"\A" + body) for body in _MARKER_BODIES)
_BOTTOM_MARKER_PATTERNS = tuple(re.compile(r"\n?" + body + r"\s*\Z") for body in _MARKER_BODIES)


def _strip_existing_header(content: str) -> str:
    """Strip copier marker blocks from the top and bottom of the file, in any comment format.

    Repeats until nothing more comes off, so a file that somehow acquired two stacked markers sheds
    both, and a marker whose comment format changed between template versions is still recognized.
    """
    while True:
        stripped = content
        for pattern in _TOP_MARKER_PATTERNS + _BOTTOM_MARKER_PATTERNS:
            stripped = pattern.sub("", stripped, count=1)
        if stripped == content:
            return content
        content = stripped


def _top_separator(comment_type: CommentType) -> str:
    """Return what goes between a top marker and the content it sits above.

    Jinja renders {# ... #} to an empty string, but a newline after the closing delimiter would
    survive into the rendered file as a blank first line -- for a script, a blank line ahead of its
    shebang, which stops the shebang working. Gluing the content straight onto the closing delimiter
    avoids that. It also leaves the first line of content untouched, which matters: giving the marker
    a line of its own rewrites that line, and in a child template that has customized the file the
    resulting hunk swallows the whole divergent body on update.
    """
    if comment_type == "jinja":
        return ""
    return "\n"


def _read_file_raw(file: Path) -> str | None:
    """Return the file's text with line endings untouched, or None if it is not valid UTF-8 (binary)."""
    # newline="" disables newline translation, so a CRLF file is seen as CRLF and can be written back
    # unchanged rather than silently rewritten to LF.
    try:
        with Path.open(file, encoding="utf-8", newline="") as f:
            return f.read()
    except UnicodeDecodeError:
        return None


def _write_file_marker(file: Path, raw: str, comment_format: CommentFormat, specific_header: str | None) -> None:
    # The strip/insert work happens on an LF-normalized copy (the header patterns are written against
    # "\n") and the file's original ending is restored on the way out. A file with mixed endings is
    # normalized to whichever ending it uses for the majority of its lines.
    newline = _dominant_newline(raw)
    content = _strip_existing_header(raw.replace("\r\n", "\n"))
    if specific_header is not None:
        if comment_format.location == "top":
            content = specific_header + _top_separator(comment_format.comment_type) + content
        else:
            # Only "bottom" is left: every format declaring location "none" also declares comment_type
            # "none", and _build_specific_header returns None for those, so the header is None here.
            content = content + "\n" + specific_header + "\n"
    if newline != "\n":
        content = content.replace("\n", newline)
    if content == raw:
        # Nothing to do. Skipping the write keeps mtime stable so a copier run does not look like
        # it touched every managed file.
        return
    with Path.open(file, "w", encoding="utf-8", newline="") as f:
        _ = f.write(content)


def _dominant_newline(raw: str) -> str:
    crlf_count = raw.count("\r\n")
    lf_count = raw.count("\n") - crlf_count
    if crlf_count > lf_count:
        return "\r\n"
    return "\n"


def _resolve_file_src(
    rel_str: str,
    template_src: str,
    ancestor_managed_by_src: dict[str, set[str]] | None,
) -> str:
    """Return the template src that originally contributed this file path."""
    if ancestor_managed_by_src is not None:
        for origin_src, origin_files in ancestor_managed_by_src.items():
            if rel_str in origin_files:
                return origin_src
    return template_src


def _get_comment_format_for_file(raw: str, default_format: CommentFormat) -> CommentFormat:
    """Return the effective CommentFormat: a top marker moves to the bottom when a shebang is on line one."""
    if default_format.location != "top" or default_format.comment_type == "none":
        return default_format
    if raw.startswith("#!/"):
        return CommentFormat(default_format.comment_type, "bottom")
    return default_format


# Tool caches, dependency trees and build output. These are never template content, but they do turn up
# inside a template directory when the source is a working copy rather than a clean clone (base-template
# has an untracked template/.ruff_cache), and their paths collide with real destination paths --
# .ruff_cache/.gitignore and CACHEDIR.TAG exist in both. Pruning them during the walk also keeps the
# traversal out of node_modules.
always_excluded_directories: frozenset[str] = frozenset(
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


def _collect_template_base_paths(
    src_template_directory: Path,
    suffixes: tuple[str, ...] = _DEFAULT_TEMPLATE_SUFFIXES,
) -> set[Path]:
    """Walk src_template_directory (following symlinks) and return resolved base paths."""
    paths: set[Path] = set()
    for root, dirnames, files in os.walk(src_template_directory, followlinks=True):
        # Mutating dirnames in place is what prunes the walk.
        dirnames[:] = [d for d in dirnames if get_base_filename(d, suffixes) not in always_excluded_directories]
        for fname in files:
            f = Path(root) / fname
            parts = [get_base_filename(p, suffixes) for p in f.relative_to(src_template_directory).parts]
            paths.add(Path(*parts))
    return paths


# Code-generator output. A template does commit these files, so nothing about the file itself gives it
# away, but a project regenerates them on its own and the fresh copy never carries a marker -- which is
# how a manifest ends up claiming files that visibly have no marker in them. Excluded by default rather
# than left to each template to declare, since the convention holds everywhere it appears: across 250
# such files in a downstream project and 20 in the templates, the only path segment containing
# "generated" is exactly "generated".
#
# Matched as a whole path segment, not a substring, so a hand-maintained generated_client.py or
# regenerated.md is unaffected.
always_excluded_path_segments: frozenset[str] = frozenset({"generated"})


def _is_excluded(rel: Path) -> bool:
    """Decide whether a destination-relative path is one the template does not maintain by hand."""
    return not always_excluded_path_segments.isdisjoint(rel.parts)


def apply_file_markers(
    *,
    src_template_directory: Path,
    dst_directory: Path,
    template_src: str = "",
    ancestor_managed_by_src: dict[str, set[str]] | None = None,
    suffixes: tuple[str, ...] = _DEFAULT_TEMPLATE_SUFFIXES,
) -> MarkerResult:
    """Stamp managed files with provenance headers.

    Returns files bucketed by originating template src, plus a description of any file that could not
    be stamped. Files listed in ancestor_managed_by_src are attributed to their originating ancestor
    template; remaining files are attributed to template_src.
    """
    template_base_paths = _collect_template_base_paths(src_template_directory, suffixes)

    managed: dict[str, list[str]] = {}
    failures: list[str] = []

    # Iterate the template paths and probe the destination rather than walking the destination:
    # a destination repo can contain symlink cycles (e.g. pnpm workspace node_modules farms) that
    # make os.walk(followlinks=True) never terminate.
    for rel in sorted(template_base_paths):
        file = dst_directory / rel
        if not file.is_file():
            continue

        rel_str = str(rel)
        excluded = _is_excluded(rel)
        file_src = template_src
        if not excluded:
            file_src = _resolve_file_src(rel_str, template_src, ancestor_managed_by_src)
            managed.setdefault(file_src, []).append(rel_str)

        # One unstampable file must not cost the rest of the run, so anything this file raises is
        # recorded and the walk continues. main() reports the failures and exits non-zero, but only
        # after the manifest has been written.
        try:
            _stamp_one_file(file, file_src, strip_only=excluded)
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: no single file may abort the run
            failures.append(f"{rel_str}: {type(exc).__name__}: {exc}")

    for file_list in managed.values():
        file_list.sort()
    return MarkerResult(managed=managed, failures=failures)


def _stamp_one_file(file: Path, file_src: str, *, strip_only: bool = False) -> None:
    lookup_name = _format_lookup_name(file.name)
    base_format = custom_filename_handling.get(
        lookup_name, custom_file_handling.get(Path(lookup_name).suffix, default_comment_format)
    )
    raw = _read_file_raw(file)
    if raw is None:
        # Binary: tracked in the manifest but never stamped.
        return
    comment_formatting = _get_comment_format_for_file(raw, base_format)

    # strip_only covers a newly excluded file: we stop claiming it, but a marker an earlier run left
    # behind is still ours to clean up. Otherwise the writer is called even when the format emits no
    # marker, so a marker left by an older template version is stripped from a file that no longer
    # takes one.
    specific_header = None if strip_only else _build_specific_header(comment_formatting.comment_type, file_src)
    _write_file_marker(file, raw, comment_formatting, specific_header)


def _read_parent_src(src_template_directory: Path) -> str | None:
    template_root = src_template_directory.parent
    answers_path = template_root / ".config" / ".copier-answers.yml"
    if not answers_path.exists():
        answers_path = template_root / ".copier-answers.yml"
    if not answers_path.exists():
        return None
    text = answers_path.read_text(encoding="utf-8")
    m = re.search(r"^_src_path:\s*(.+)$", text, re.MULTILINE)
    if m is None:
        return None
    return m.group(1).strip()


def _entry_src(entry: TemplateEntry) -> str:
    """Sort key for manifest entries. A named function rather than a lambda so the param is typed."""
    return entry["src"]


def _build_entry(src: str, managed_files: list[str], parent_src: str | None) -> TemplateEntry:
    # Both branches spell the whole entry out so the JSON key order stays src, parent_src, managed_files.
    if parent_src is None:
        return {"src": src, "managed_files": managed_files}
    return {"src": src, "parent_src": parent_src, "managed_files": managed_files}


def update_manifest(
    *,
    dst_directory: Path,
    produced: dict[str, list[str]],
    parents: dict[str, str | None],
) -> None:
    """Write the manifest in one pass, with this run's attributions taken as authoritative.

    `produced` holds every src this run attributed files to. Those entries replace whatever was on
    disk. An entry for some other src -- a second, unrelated template applied to the same repo -- is
    kept, minus any path this run claimed, because two srcs must never list the same file. Writing
    once rather than once per src is what makes that pruning possible: the previous version
    re-read and re-appended the file for each src in turn, so it could only ever add to what was
    already there. A stale entry therefore survived forever, and a file that moved from one template
    to another ended up listed under both.
    """
    manifest_path = dst_directory / _MANIFEST_RELPATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    # Annotated on the json.loads branch rather than assigned into a pre-annotated name, so the
    # decoded Any is pinned to Manifest instead of widening everything read out of it back to Any.
    if manifest_path.exists():
        existing: Manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        existing = {"templates": []}

    claimed = {path for files in produced.values() for path in files}

    templates: list[TemplateEntry] = [_build_entry(src, files, parents.get(src)) for src, files in produced.items()]
    for t in existing["templates"]:
        if t["src"] in produced:
            continue
        surviving = [path for path in t["managed_files"] if path not in claimed]
        if len(surviving) == 0:
            # Nothing left to point at, so the entry is stale rather than merely unrelated.
            continue
        templates.append(_build_entry(t["src"], surviving, t.get("parent_src")))

    # Sorted so the array order does not depend on which src happens to own the first managed file.
    templates.sort(key=_entry_src)

    _ = manifest_path.write_text(
        json.dumps({"templates": templates}, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_ancestor_manifest(
    src_template_dir: Path,
    suffixes: tuple[str, ...] = _DEFAULT_TEMPLATE_SUFFIXES,
) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Return each ancestor template's handed-down paths and its own parent, keyed by template src.

    An ancestor entry in a template repo's manifest holds two different kinds of path:

    - files the ancestor manages in the template repo itself: its own tooling, such as pyproject.toml
      or .github/workflows/ci.yaml. These are not handed down to anything.
    - files under the template repo's template/ subdirectory. These are the ones that get rendered
      into a project, so they are the only ones a destination file can have come from.

    Only the second kind is returned, re-rooted to the destination layout (where "template/" does not
    exist). Matching the first kind too meant a destination file was credited to the ancestor purely
    because a same-named file happened to exist at the template repo's root, which made attribution
    depend on an unrelated coincidence -- and move between entries whenever that coincidence changed.
    """
    ancestor_managed_by_src: dict[str, set[str]] = {}
    ancestor_parent_by_src: dict[str, str] = {}
    ancestor_manifest_path = _find_manifest(src_template_dir.parent)
    if not ancestor_manifest_path.exists():
        return ancestor_managed_by_src, ancestor_parent_by_src

    data: Manifest = json.loads(ancestor_manifest_path.read_text(encoding="utf-8"))
    subdir_prefix = src_template_dir.name + "/"
    for t in data["templates"]:
        path_set: set[str] = set()
        for f in t["managed_files"]:
            if not f.startswith(subdir_prefix):
                continue
            stripped = f.removeprefix(subdir_prefix)
            path_set.add(stripped)
            # Apply get_base_filename to each part so .jinja/.jinja-base suffixes
            # and Jinja conditional names resolve to the final destination filename.
            parts = Path(stripped).parts
            resolved = str(Path(*[get_base_filename(p, suffixes) for p in parts]))
            path_set.add(resolved)
        ancestor_managed_by_src[t["src"]] = path_set
        ancestor_parent = t.get("parent_src")
        if ancestor_parent is not None:
            ancestor_parent_by_src[t["src"]] = ancestor_parent
    return ancestor_managed_by_src, ancestor_parent_by_src


def main() -> None:
    parser = argparse.ArgumentParser(description="Add copier provenance markers and manifest")
    _ = parser.add_argument("src_template_dir", type=Path, help="Template source directory")
    _ = parser.add_argument("dst_dir", type=Path, help="Destination directory")
    _ = parser.add_argument("--template-src", default="", help="Template source identifier for the manifest")
    _ = parser.add_argument(
        "--templates-suffix",
        default="",
        help=(
            "The calling template's _templates_suffix, e.g. '.jinja-base'. Only this suffix is treated "
            "as a template marker, so any other trailing suffix is kept as part of the destination "
            "filename. Defaults to stripping both '.jinja-base' and '.jinja'."
        ),
    )
    args = parser.parse_args()
    assert isinstance(args.src_template_dir, Path)
    assert isinstance(args.dst_dir, Path)
    assert isinstance(args.template_src, str)
    assert isinstance(args.templates_suffix, str)
    src_template_dir = args.src_template_dir
    dst_dir = args.dst_dir
    template_src = args.template_src
    suffixes = (args.templates_suffix,) if args.templates_suffix != "" else _DEFAULT_TEMPLATE_SUFFIXES

    # header_src drives what URL appears in file headers (empty → generic "managed by a copier template" text).
    # manifest_src is the key written to .config/.copier-managed-files.json and is always non-empty.
    header_src = template_src
    if template_src == "":
        manifest_src = str(src_template_dir)
    else:
        manifest_src = template_src

    ancestor_managed_by_src, ancestor_parent_by_src = _read_ancestor_manifest(src_template_dir, suffixes)

    ancestor_argument: dict[str, set[str]] | None = None
    if len(ancestor_managed_by_src) > 0:
        ancestor_argument = ancestor_managed_by_src

    result = apply_file_markers(
        src_template_directory=src_template_dir,
        dst_directory=dst_dir,
        template_src=header_src,
        ancestor_managed_by_src=ancestor_argument,
        suffixes=suffixes,
    )
    managed_by_src = result.managed
    # Always write an entry for the current template even when no files matched.
    _ = managed_by_src.setdefault(header_src, [])

    parent_src = _read_parent_src(src_template_dir)
    produced: dict[str, list[str]] = {}
    parents: dict[str, str | None] = {}
    for src, files in managed_by_src.items():
        effective_src = manifest_src if src == header_src else src
        produced[effective_src] = files
        # Current template's parent comes from copier-answers; ancestor entries carry
        # their own parent_src forward from the ancestor manifest so the chain survives.
        if effective_src == manifest_src:
            parents[effective_src] = parent_src
        else:
            parents[effective_src] = ancestor_parent_by_src.get(src)
    update_manifest(dst_directory=dst_dir, produced=produced, parents=parents)

    # Reported only after the manifest is on disk, so a single unstampable file cannot also cost the
    # run its record of what is managed.
    if len(result.failures) > 0:
        print(f"Failed to stamp {len(result.failures)} file(s):", file=sys.stderr)  # noqa: T201 -- task output is meant for the copier console
        for failure in result.failures:
            print(f"  {failure}", file=sys.stderr)  # noqa: T201 -- task output is meant for the copier console
        sys.exit(1)


if __name__ == "__main__":
    main()
