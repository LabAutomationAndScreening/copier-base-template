import argparse
import json
import re
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import Literal

CommentType = Literal["hash", "block", "markdown", "none"]
Location = Literal["top", "bottom", "none"]


@dataclass
class CommentFormat:
    comment_type: CommentType = "hash"
    location: Location = "top"


default_comment_format = CommentFormat("hash", "top")
custom_file_handling: dict[str, CommentFormat] = {
    ".md": CommentFormat("markdown", "bottom"),
    ".sh": CommentFormat("hash", "bottom"),  # put at bottom to not mess with shebang
    ".js": CommentFormat("block", "top"),
    ".cjs": CommentFormat("block", "top"),
    ".mjs": CommentFormat("block", "top"),
    ".ts": CommentFormat("block", "top"),
    ".cts": CommentFormat("block", "top"),
    ".mts": CommentFormat("block", "top"),
    ".json": CommentFormat("none", "none"),
    ".jsonc": CommentFormat("none", "none"),
    ".yaml": CommentFormat("hash", "top"),
    ".yml": CommentFormat("hash", "top"),
}

HEADER = """\
============== WARNING ==============================================================================
File is managed by a copier template. See .copier-managed-files.json for details.

You are welcome to make changes to this file in your repo if they are custom to your project,
but if the change should be shared with other projects, please backport it to the template repo.
====================================================================================================="""


def get_base_filename(template_filename: str) -> str:
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


@dataclass
class ProvenanceResult:
    managed_files: list[str] = field(default_factory=list[str])


def _build_specific_header(comment_type: CommentType) -> str | None:
    if comment_type == "hash":
        return "\n".join(f"# {line}" if line else "#" for line in HEADER.split("\n"))
    if comment_type == "block":
        body = "\n".join(f" * {line}" if line else " *" for line in HEADER.split("\n"))
        return f"/*\n{body}\n */"
    if comment_type == "markdown":
        return f"<!--\n{HEADER}\n-->"
    return None


def _write_file_marker(file: Path, comment_format: CommentFormat, specific_header: str) -> None:
    with Path.open(file, "r+") as f:
        content = f.read()
        if comment_format.location == "top":
            content = content.replace(f"{specific_header}\n", "")
        elif comment_format.location == "bottom":
            content = content.replace(f"\n{specific_header}\n", "")
            content = content.replace(f"{specific_header}\n", "")
        _ = f.seek(0)
        _ = f.truncate()
        if comment_format.location == "top":
            _ = f.write(specific_header + "\n")
        _ = f.write(content)
        if comment_format.location == "bottom":
            _ = f.write("\n" + specific_header + "\n")


def apply_file_markers(
    src_template_directory: Path,
    dst_directory: Path,
) -> ProvenanceResult:
    template_base_paths: set[Path] = set()
    for f in src_template_directory.glob("**/*"):
        if not f.is_file():
            continue
        parts = list(f.relative_to(src_template_directory).parts)
        parts[-1] = get_base_filename(parts[-1])
        template_base_paths.add(Path(*parts))

    managed: list[str] = []

    for file in sorted(dst_directory.glob("**/*")):
        if not file.is_file():
            continue
        if file.relative_to(dst_directory) not in template_base_paths:
            continue

        comment_formatting = custom_file_handling.get(file.suffix, default_comment_format)
        if comment_formatting.location == "top" and comment_formatting.comment_type != "none":
            first_line = file.read_text(encoding="utf-8").split("\n", 1)[0]
            if first_line.startswith("#!/"):
                comment_formatting = CommentFormat(comment_formatting.comment_type, "bottom")

        specific_header = _build_specific_header(comment_formatting.comment_type)
        if specific_header is None:
            managed.append(str(file.relative_to(dst_directory)))
            continue

        _write_file_marker(file, comment_formatting, specific_header)
        managed.append(str(file.relative_to(dst_directory)))

    managed.sort()
    return ProvenanceResult(managed_files=managed)


def update_manifest(dst_directory: Path, template_src: str, managed_files: list[str]) -> None:
    manifest_path = dst_directory / ".copier-managed-files.json"

    existing: dict[str, Any] = {}
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))

    templates: list[dict[str, Any]] = existing.get("templates", [])
    templates = [t for t in templates if t.get("src") != template_src]
    templates.append({"src": template_src, "managed_files": managed_files})

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

    result = apply_file_markers(args.src_template_dir, args.dst_dir)
    update_manifest(args.dst_dir, args.template_src or str(args.src_template_dir), result.managed_files)


if __name__ == "__main__":
    main()
