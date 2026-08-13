import argparse
import json
import os
import re
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


def get_base_filename(template_filename: str) -> str:
    """Return the destination filename for a template file.

    Handles two cases:
    - Jinja if-check pattern: {% if cond %}actual_filename{% endif %}[.jinja-base]
      The text between %} and {% is the actual destination filename (no suffix stripping needed).
    - Plain template file: README.md.jinja-base → README.md (strip template suffix).
    """
    result = re.findall(r"%\}(.*?)\{%", template_filename, re.DOTALL)
    if len(result) > 0:
        assert isinstance(result[0], str)
        return result[0]
    for suffix in [".jinja-base", ".jinja"]:
        if template_filename.endswith(suffix):
            return template_filename[: -len(suffix)]
    return template_filename


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
    if ancestor_managed_by_src is not None:
        for origin_src, origin_files in ancestor_managed_by_src.items():
            if rel_str in origin_files:
                return origin_src
    return template_src


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


def _collect_template_base_paths(src_template_directory: Path) -> set[Path]:
    """Walk src_template_directory (following symlinks) and return resolved base paths."""
    paths: set[Path] = set()
    for root, _, files in os.walk(src_template_directory, followlinks=True):
        for fname in files:
            f = Path(root) / fname
            parts = [get_base_filename(p) for p in f.relative_to(src_template_directory).parts]
            paths.add(Path(*parts))
    return paths


def apply_file_markers(
    *,
    src_template_directory: Path,
    dst_directory: Path,
    template_src: str = "",
    ancestor_managed_by_src: dict[str, set[str]] | None = None,
) -> dict[str, list[str]]:
    """Stamp managed files with provenance headers.

    Returns files bucketed by originating template src. Files listed in
    ancestor_managed_by_src are attributed to their originating ancestor template;
    remaining files are attributed to template_src.
    """
    template_base_paths = _collect_template_base_paths(src_template_directory)

    managed: dict[str, list[str]] = {}

    dst_files: list[Path] = []
    for root, _, files in os.walk(dst_directory, followlinks=True):
        dst_files.extend(Path(root) / fname for fname in files)

    for file in sorted(dst_files):
        rel = file.relative_to(dst_directory)
        if rel not in template_base_paths:
            continue

        rel_str = str(rel)
        file_src = _resolve_file_src(rel_str, template_src, ancestor_managed_by_src)
        managed.setdefault(file_src, []).append(rel_str)

        base_format = custom_filename_handling.get(
            file.name, custom_file_handling.get(file.suffix, default_comment_format)
        )
        comment_formatting = _get_comment_format_for_file(file, base_format)
        if comment_formatting is None:
            continue

        specific_header = _build_specific_header(comment_formatting.comment_type, file_src)
        if specific_header is not None:
            _write_file_marker(file, comment_formatting, specific_header)

    for file_list in managed.values():
        file_list.sort()
    return managed


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


def update_manifest(
    *,
    dst_directory: Path,
    template_src: str,
    managed_files: list[str],
    parent_src: str | None = None,
) -> None:
    manifest_path = dst_directory / _MANIFEST_RELPATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    existing: Manifest = {"templates": []}
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))

    templates: list[TemplateEntry] = []
    for t in existing["templates"]:
        if t["src"] == template_src:
            continue
        templates.append(t)

    # Both branches spell the whole entry out so the JSON key order stays src, parent_src, managed_files.
    if parent_src is None:
        entry: TemplateEntry = {"src": template_src, "managed_files": managed_files}
    else:
        entry = {"src": template_src, "parent_src": parent_src, "managed_files": managed_files}
    templates.append(entry)

    _ = manifest_path.write_text(
        json.dumps({"templates": templates}, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_ancestor_manifest(src_template_dir: Path) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Return each ancestor template's managed paths and its own parent, keyed by template src.

    The ancestor manifest may contain paths with a "template/" prefix (from self-stamp tasks that run
    with src=dst=template/). Both the prefixed and stripped spellings are recorded so lookups match the
    destination repo's layout (where "template/" doesn't exist).
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
            path_set.add(f)
            stripped = f.removeprefix(subdir_prefix)
            path_set.add(stripped)
            # Apply get_base_filename to each part so .jinja/.jinja-base suffixes
            # and Jinja conditional names resolve to the final destination filename.
            parts = Path(stripped).parts
            if len(parts) > 0:
                resolved = str(Path(*[get_base_filename(p) for p in parts]))
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
    args = parser.parse_args()
    assert isinstance(args.src_template_dir, Path)
    assert isinstance(args.dst_dir, Path)
    assert isinstance(args.template_src, str)
    src_template_dir = args.src_template_dir
    dst_dir = args.dst_dir
    template_src = args.template_src

    # header_src drives what URL appears in file headers (empty → generic "managed by a copier template" text).
    # manifest_src is the key written to .config/.copier-managed-files.json and is always non-empty.
    header_src = template_src
    if template_src == "":
        manifest_src = str(src_template_dir)
    else:
        manifest_src = template_src

    ancestor_managed_by_src, ancestor_parent_by_src = _read_ancestor_manifest(src_template_dir)

    ancestor_argument: dict[str, set[str]] | None = None
    if len(ancestor_managed_by_src) > 0:
        ancestor_argument = ancestor_managed_by_src

    managed_by_src = apply_file_markers(
        src_template_directory=src_template_dir,
        dst_directory=dst_dir,
        template_src=header_src,
        ancestor_managed_by_src=ancestor_argument,
    )
    # Always write an entry for the current template even when no files matched.
    _ = managed_by_src.setdefault(header_src, [])

    parent_src = _read_parent_src(src_template_dir)
    for src, files in managed_by_src.items():
        if src == header_src:
            effective_src = manifest_src
        else:
            effective_src = src
        # Current template's parent comes from copier-answers; ancestor entries carry
        # their own parent_src forward from the ancestor manifest so the chain survives.
        if effective_src == manifest_src:
            effective_parent = parent_src
        else:
            effective_parent = ancestor_parent_by_src.get(src)
        update_manifest(
            dst_directory=dst_dir,
            template_src=effective_src,
            managed_files=files,
            parent_src=effective_parent,
        )


if __name__ == "__main__":
    main()
