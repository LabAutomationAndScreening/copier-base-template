import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Literal
from typing import cast

import yaml

CommentType = Literal["hash", "batch", "block", "jinja", "markdown", "none"]
Location = Literal["top", "bottom", "none"]


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

_HEADER_BASE = """\
============== WARNING ==============================================================================
File is managed by a copier template. See .copier-managed-files.json for details.

You are welcome to make changes to this file in your repo if they are custom to your project,
but if the change should be shared with other projects, please backport it to the template repo.
====================================================================================================="""


def _build_header(template_src: str) -> str:
    """Return the header text. With a template_src, embeds the URL on its own line."""
    if not template_src:
        return _HEADER_BASE
    lines: list[str] = list(_HEADER_BASE.split("\n"))
    # Replace the generic "File is managed" line with two lines: URL line + "See ..." line.
    lines[1] = f"File is managed by copier template: {template_src}"
    lines.insert(2, "See .copier-managed-files.json for details.")
    return "\n".join(lines)


def get_base_filename_handling_jinja_syntax_and_extensions(template_filename: str) -> str:
    """Return the destination filename for a template file.

    Handles two cases:
    - Jinja if-check pattern: {% if cond %}actual_filename{% endif %}[.jinja-base]
      The text between %} and {% is the actual destination filename (no suffix stripping needed).
    - Plain template file: README.md.jinja-base → README.md (strip template suffix).
    """
    result = re.findall(r"%\}(.*?)\{%", template_filename, re.DOTALL)
    if result:
        return result[0]
    for suffix in [".jinja-base", ".jinja"]:
        if template_filename.endswith(suffix):
            return template_filename[: -len(suffix)]
    return template_filename


def _build_specific_header(comment_type: CommentType, template_src: str = "") -> str | None:
    header = _build_header(template_src)
    if comment_type == "hash":
        return "\n".join(f"# {line}" if line else "#" for line in header.split("\n"))
    if comment_type == "batch":
        return "\n".join(f"REM {line}" if line else "REM" for line in header.split("\n"))
    if comment_type == "block":
        body = "\n".join(f" * {line}" if line else " *" for line in header.split("\n"))
        return f"/*\n{body}\n */"
    if comment_type == "jinja":
        # Jinja renders {# ... #} to empty string, so this marker is invisible in rendered output.
        body = "\n".join(f" {line}" if line else "" for line in header.split("\n"))
        return f"{{#\n{body}\n#}}"
    if comment_type == "markdown":
        return f"<!--\n{header}\n-->"
    return None


def _strip_existing_header(content: str, comment_format: CommentFormat) -> str:
    """Strip any existing copier header block regardless of template URL inside."""
    t = comment_format.comment_type
    loc = comment_format.location
    if t == "hash":
        pattern = r"# ={14} WARNING[^\n]*\n(?:.*\n)*?# ={50,}\n"
    elif t == "batch":
        pattern = r"REM ={14} WARNING[^\n]*\n(?:.*\n)*?REM ={50,}\n"
    elif t == "block":
        pattern = r"/\*\n \* ={14} WARNING[^\n]*\n(?: \*.*\n)*? \*/\n"
    elif t == "jinja":
        pattern = r"\{#\n ={14} WARNING[^\n]*\n(?:.*\n)*?#\}\n"
    elif t == "markdown":
        pattern = r"<!--\n={14} WARNING[^\n]*\n(?:.*\n)*?-->\n"
    else:
        return content
    if loc == "bottom":
        result = re.sub(r"\n" + pattern, "", content, count=1)
        if result == content:
            result = re.sub(pattern, "", content, count=1)
        return result
    return re.sub(pattern, "", content, count=1)


def _write_file_marker(file: Path, comment_format: CommentFormat, specific_header: str) -> None:
    with Path.open(file, "r+") as f:
        content = f.read()
        content = _strip_existing_header(content, comment_format)
        _ = f.seek(0)
        _ = f.truncate()
        if comment_format.location == "top":
            _ = f.write(specific_header + "\n")
        _ = f.write(content)
        if comment_format.location == "bottom":
            _ = f.write("\n" + specific_header + "\n")


def _resolve_file_src(
    rel_str: str,
    template_src: str,
    ancestor_managed_by_src: dict[str, set[str]] | None,
) -> str:
    """Return the template src that originally contributed this file path."""
    if ancestor_managed_by_src:
        for origin_src, origin_files in ancestor_managed_by_src.items():
            if rel_str in origin_files:
                return origin_src
    return template_src


def _base_format_for_file(file: Path) -> CommentFormat:
    """Return the base CommentFormat for a file.

    For .jinja/.jinja-base files the comment type is always 'jinja', but the
    location is derived from the underlying extension so that e.g. 'deploy.sh.jinja'
    inherits bottom placement from '.sh' without any content sniffing.
    """
    if file.name in custom_filename_handling:
        return custom_filename_handling[file.name]
    suffix = file.suffix
    if suffix not in (".jinja", ".jinja-base"):
        return custom_file_handling.get(suffix, default_comment_format)
    underlying = file.stem  # e.g. "deploy.sh" from "deploy.sh.jinja"
    underlying_format = custom_filename_handling.get(
        underlying, custom_file_handling.get(Path(underlying).suffix, default_comment_format)
    )
    if underlying_format.comment_type == "none":
        return underlying_format
    return CommentFormat("jinja", underlying_format.location)


def _get_comment_format_for_file(file: Path, default_format: CommentFormat) -> CommentFormat | None:
    """Return the effective CommentFormat, or None if the file is binary (track but skip marking)."""
    if default_format.location != "top" or default_format.comment_type == "none":
        return default_format
    try:
        first_line = file.read_text(encoding="utf-8").split("\n", 1)[0]
    except UnicodeDecodeError:
        return None
    if first_line.startswith("#!/"):
        return CommentFormat(default_format.comment_type, "bottom")
    return default_format


def _read_copier_answers(dst_directory: Path) -> dict[str, Any]:
    """Read boolean answers from .copier-answers.yml in dst_directory."""
    answers_path = dst_directory / ".copier-answers.yml"
    if not answers_path.exists():
        return {}
    raw = yaml.safe_load(answers_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    data = cast("dict[str, Any]", raw)
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, bool)}


def _is_false_jinja_conditional(component: str, answers: dict[str, Any]) -> bool:
    """Return True if this path component is a {% if var %}...{% endif %} whose var is false in answers."""
    m = re.fullmatch(r"\{%-?\s*if\s+(\w+)\s*-?%\}.*?\{%-?\s*endif\s*-?%\}", component, re.DOTALL)
    if not m:
        return False
    var_name = m.group(1)
    return var_name in answers and not answers[var_name]


def _collect_template_base_paths(src_template_directory: Path) -> set[Path]:
    """Walk src_template_directory (following symlinks) and return resolved base paths."""
    paths: set[Path] = set()
    for root, _, files in os.walk(src_template_directory, followlinks=True):
        for fname in files:
            f = Path(root) / fname
            parts = [
                get_base_filename_handling_jinja_syntax_and_extensions(p)
                for p in f.relative_to(src_template_directory).parts
            ]
            paths.add(Path(*parts))
    return paths


def _collect_false_conditional_paths(
    src_template_directory: Path,
    answers: dict[str, Any],
) -> set[Path]:
    """Return resolved paths of files whose template directory condition is false in answers."""
    excluded: set[Path] = set()
    for root, _, files in os.walk(src_template_directory, followlinks=True):
        for fname in files:
            f = Path(root) / fname
            rel_parts = list(f.relative_to(src_template_directory).parts)
            if any(_is_false_jinja_conditional(p, answers) for p in rel_parts):
                resolved = [get_base_filename_handling_jinja_syntax_and_extensions(p) for p in rel_parts]
                excluded.add(Path(*resolved))
    return excluded


def apply_file_markers(
    *,
    src_template_directory: Path,
    dst_directory: Path,
    template_src: str = "",
    ancestor_managed_by_src: dict[str, set[str]] | None = None,
    answers: dict[str, Any] | None = None,
) -> tuple[dict[str, list[str]], set[Path]]:
    """Stamp managed files with provenance headers.

    Returns a tuple of (files bucketed by originating template src, template_base_paths).
    Files listed in ancestor_managed_by_src are attributed to their originating ancestor
    template; remaining files are attributed to template_src.
    """
    template_base_paths = _collect_template_base_paths(src_template_directory)
    false_conditional_paths: set[Path] = (
        _collect_false_conditional_paths(src_template_directory, answers) if answers else set()
    )

    managed: dict[str, list[str]] = {}

    dst_files: list[Path] = []
    for root, _, files in os.walk(dst_directory, followlinks=True):
        dst_files.extend(Path(root) / fname for fname in files)

    for file in sorted(dst_files):
        rel = file.relative_to(dst_directory)
        rel_base = Path(*map(get_base_filename_handling_jinja_syntax_and_extensions, rel.parts))
        if rel not in template_base_paths and rel_base not in template_base_paths:
            continue
        if rel in false_conditional_paths or rel_base in false_conditional_paths:
            continue

        rel_str = str(rel)
        file_src = _resolve_file_src(rel_str, template_src, ancestor_managed_by_src)
        managed.setdefault(file_src, []).append(rel_str)

        base_format = _base_format_for_file(file)
        comment_formatting = _get_comment_format_for_file(file, base_format)
        if comment_formatting is None:
            continue

        specific_header = _build_specific_header(comment_formatting.comment_type, file_src)
        if specific_header is not None:
            _write_file_marker(file, comment_formatting, specific_header)

    for file_list in managed.values():
        file_list.sort()
    return managed, template_base_paths


def _read_parent_src(src_template_directory: Path) -> str | None:
    answers_path = src_template_directory.parent / ".copier-answers.yml"
    if not answers_path.exists():
        return None
    raw = yaml.safe_load(answers_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    data = cast("dict[str, Any]", raw)
    src_path = data.get("_src_path")
    return str(src_path) if src_path else None


def update_manifest(
    *,
    dst_directory: Path,
    template_src: str,
    managed_files: list[str],
    parent_src: str | None = None,
) -> None:
    manifest_path = dst_directory / ".copier-managed-files.json"

    existing: dict[str, Any] = {}
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))

    templates: list[dict[str, Any]] = existing.get("templates", [])
    templates = [t for t in templates if t.get("src") != template_src]

    entry: dict[str, Any] = {"src": template_src}
    if parent_src:
        entry["parent_src"] = parent_src
    entry["managed_files"] = managed_files
    templates.append(entry)

    _ = manifest_path.write_text(
        json.dumps({"templates": templates}, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Add copier provenance markers and manifest")
    _ = parser.add_argument("src_template_dir", type=Path, help="Template source directory")
    _ = parser.add_argument("dst_dir", type=Path, help="Destination directory")
    _ = parser.add_argument("--template-src", default="", help="Template source identifier for the manifest")
    args = parser.parse_args()

    # header_src drives what URL appears in file headers (empty → generic "managed by a copier template" text).
    # manifest_src is the key written to .copier-managed-files.json and is always non-empty.
    header_src = args.template_src
    manifest_src = args.template_src or str(args.src_template_dir)

    ancestor_managed_by_src: dict[str, set[str]] = {}
    ancestor_parent_by_src: dict[str, str] = {}
    ancestor_manifest_path = args.src_template_dir.parent / ".copier-managed-files.json"
    if ancestor_manifest_path.exists():
        data: dict[str, Any] = json.loads(ancestor_manifest_path.read_text(encoding="utf-8"))
        # The ancestor manifest may contain paths with a "template/" prefix (from self-stamp
        # tasks that run with src=dst=template/). Strip that prefix so paths match the
        # destination repo's layout (where "template/" doesn't exist).
        subdir_prefix = args.src_template_dir.name + "/"
        for t in data.get("templates", []):
            path_set: set[str] = set()
            for f in t.get("managed_files", []):
                path_set.add(f)
                stripped = f.removeprefix(subdir_prefix)
                path_set.add(stripped)
                # Apply get_base_filename to each part so .jinja/.jinja-base suffixes
                # and Jinja conditional names resolve to the final destination filename.
                parts = Path(stripped).parts
                if parts:
                    resolved = str(Path(*[get_base_filename_handling_jinja_syntax_and_extensions(p) for p in parts]))
                    path_set.add(resolved)
            ancestor_managed_by_src[t["src"]] = path_set
            if t.get("parent_src"):
                ancestor_parent_by_src[t["src"]] = t["parent_src"]

    answers = _read_copier_answers(args.dst_dir)

    managed_by_src, _ = apply_file_markers(
        src_template_directory=args.src_template_dir,
        dst_directory=args.dst_dir,
        template_src=header_src,
        ancestor_managed_by_src=ancestor_managed_by_src or None,
        answers=answers or None,
    )
    # Always write an entry for the current template even when no files matched.
    _ = managed_by_src.setdefault(header_src, [])

    # Every ancestor discoverable from this template's own manifest gets its entry
    # refreshed on every run, not just when this run happened to re-attribute files
    # to it. Relying on an overlap heuristic left a gap: if an ancestor's files were
    # all under a Jinja conditional directory (e.g. {% if is_circuit_python_driver %}
    # helm{% endif %}) and that overlap check missed a case, the ancestor never
    # appeared in managed_by_src and its stale manifest entry (listing now-deleted
    # files) would persist indefinitely. Unconditionally seeding every known ancestor
    # here guarantees update_manifest() is called for it every run, so its entry is
    # always a fresh, fully-recomputed reflection of current state (empty if nothing
    # is attributed to it), never a carryover from a previous run.
    for src in ancestor_managed_by_src:
        _ = managed_by_src.setdefault(src, [])

    parent_src = _read_parent_src(args.src_template_dir)
    for src, files in managed_by_src.items():
        effective_src = manifest_src if src == header_src else src
        # Current template's parent comes from copier-answers; ancestor entries carry
        # their own parent_src forward from the ancestor manifest so the chain survives.
        effective_parent = parent_src if effective_src == manifest_src else ancestor_parent_by_src.get(src)
        update_manifest(
            dst_directory=args.dst_dir,
            template_src=effective_src,
            managed_files=files,
            parent_src=effective_parent,
        )


if __name__ == "__main__":
    main()
