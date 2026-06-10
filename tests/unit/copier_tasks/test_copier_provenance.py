# pylint: disable=duplicate-code  # duplication here is intentional — each case verifies its own expected content
from pathlib import Path

import pytest
import yaml

from src.copier_tasks.copier_provenance import CommentFormat
from src.copier_tasks.copier_provenance import Location
from src.copier_tasks.copier_provenance import apply_file_markers
from src.copier_tasks.copier_provenance import custom_file_handling
from src.copier_tasks.copier_provenance import get_base_filename
from src.copier_tasks.copier_provenance import update_manifest

expected_hash_comment = """\
#!!!!!!!!!!!!!! WARNING !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# File is managed by a copier template. See .copier-managed-files.yaml for details.
#
# You are welcome to make changes to this file in your repo if they are custom to your project,
# but if the change should be shared with other projects, please backport it to the template repo.
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"""

expected_markdown_comment = """\
<!--
!!!!!!!!!!!!!! WARNING !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
 File is managed by a copier template. See .copier-managed-files.yaml for details.

 You are welcome to make changes to this file in your repo if they are custom to your project,
 but if the change should be shared with other projects, please backport it to the template repo.
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
-->"""


# ─── get_base_filename ────────────────────────────────────────────────────────


class TestGetBaseFilename:
    def test_strips_jinja_base_suffix(self) -> None:
        assert get_base_filename("README.md.jinja-base") == "README.md"

    def test_strips_jinja_suffix(self) -> None:
        assert get_base_filename("ci.yaml.jinja") == "ci.yaml"

    def test_extracts_filename_from_jinja_if_check_without_stripping(self) -> None:
        # The extracted value is the actual destination filename; .jinja suffix must NOT be stripped
        assert get_base_filename("{% if is_python %}.coveragerc.jinja{% endif %}.jinja-base") == ".coveragerc.jinja"

    def test_returns_plain_filename_unchanged(self) -> None:
        assert get_base_filename("plain.txt") == "plain.txt"


# ─── apply_file_markers ───────────────────────────────────────────────────────


def _make_dirs(tmp_path: Path) -> tuple[Path, Path]:
    template_dir = tmp_path / "template"
    template_dir.mkdir()
    dst_dir = tmp_path / "destination"
    dst_dir.mkdir()
    return template_dir, dst_dir


def _write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("filename", "expected_location", "expected_comment"),
    [
        ("hash_comment.txt", "top", expected_hash_comment),
        ("testme.md", "bottom", expected_markdown_comment),
        ("test.json", "none", ""),
    ],
    ids=[
        "default-comments-are-on-top-and-use-hash-comment",
        "markdown-on-bottom-and-special-comment",
        "json-files-must-not-have-comments",
    ],
)
def test_add_comment(filename: str, expected_location: Location, expected_comment: str, tmp_path: Path) -> None:
    template_dir, dst_dir = _make_dirs(tmp_path)
    (template_dir / filename).touch()

    file_content = "some content\nmore\nstuff"
    _write_file(dst_dir / filename, file_content)

    apply_file_markers(template_dir, dst_dir)

    content = _read_file(dst_dir / filename)
    if expected_location == "none":
        assert content == file_content
        return

    if expected_location == "bottom":
        assert content == file_content + "\n" + expected_comment + "\n"
    else:
        assert content == expected_comment + "\n" + file_content


def test_jinja_base_suffix_stripped_when_matching(tmp_path: Path) -> None:
    template_dir, dst_dir = _make_dirs(tmp_path)
    (template_dir / "README.md.jinja-base").touch()

    file_content = "some content\nmore\nstuff"
    _write_file(dst_dir / "README.md", file_content)

    apply_file_markers(template_dir, dst_dir)

    content = _read_file(dst_dir / "README.md")
    assert content == file_content + "\n" + expected_markdown_comment + "\n"


def test_add_comment_added_when_wrapped_in_jinja_if_check(tmp_path: Path) -> None:
    template_dir, dst_dir = _make_dirs(tmp_path)
    (template_dir / "{% if is_python_template %}.coveragerc.jinja{% endif %}.jinja-base").touch()

    file_content = "some content\nmore\nstuff"
    _write_file(dst_dir / ".coveragerc.jinja", file_content)

    apply_file_markers(template_dir, dst_dir)

    content = _read_file(dst_dir / ".coveragerc.jinja")
    assert content == expected_hash_comment + "\n" + file_content


@pytest.mark.parametrize(
    ("filename", "expected_location", "expected_comment"),
    [
        ("hash_comment.txt", "top", expected_hash_comment),
        ("testme.md", "bottom", expected_markdown_comment),
    ],
    ids=[
        "existing-hash-comment-at-top",
        "existing-markdown-comment-at-bottom",
    ],
)
def test_comment_not_duplicated_when_already_present(
    filename: str, expected_location: Location, expected_comment: str, tmp_path: Path
) -> None:
    template_dir, dst_dir = _make_dirs(tmp_path)
    (template_dir / filename).touch()

    if expected_location == "top":
        file_content = expected_comment + "\nsome content\nmore\nstuff"
    else:
        file_content = "some content\nmore\nstuff\n" + expected_comment + "\n"
    _write_file(dst_dir / filename, file_content)

    apply_file_markers(template_dir, dst_dir)

    assert _read_file(dst_dir / filename) == file_content


def test_non_template_file_not_modified(tmp_path: Path) -> None:
    template_dir, dst_dir = _make_dirs(tmp_path)
    (template_dir / "template.txt").touch()

    file_content = "some content\nmore\nstuff"
    non_template = dst_dir / "pre-existing-file-non-template-file.txt"
    _write_file(non_template, file_content)

    apply_file_markers(template_dir, dst_dir)

    assert _read_file(non_template) == file_content


def test_handles_migration_of_comment_location(tmp_path: Path) -> None:
    shell_script_mapping = custom_file_handling.get(".sh")
    assert shell_script_mapping is not None, "Shell files expected to have custom mapping"
    assert shell_script_mapping.location == "bottom", (
        "Shell files expected to have comment at the bottom to not mess with shebang"
    )

    template_dir, dst_dir = _make_dirs(tmp_path)
    (template_dir / "test.sh").touch()

    file_content = "some content\nmore\nstuff"
    _write_file(dst_dir / "test.sh", expected_hash_comment + "\n" + file_content)

    apply_file_markers(template_dir, dst_dir)

    content = _read_file(dst_dir / "test.sh")
    assert content == file_content + "\n" + expected_hash_comment + "\n"


def test_result_lists_managed_files(tmp_path: Path) -> None:
    template_dir, dst_dir = _make_dirs(tmp_path)
    (template_dir / "a.txt").touch()
    (template_dir / "b.md").touch()
    (template_dir / "c.json").touch()

    _write_file(dst_dir / "a.txt", "content")
    _write_file(dst_dir / "b.md", "content")
    _write_file(dst_dir / "c.json", "{}")
    _write_file(dst_dir / "not-a-template.txt", "content")

    result = apply_file_markers(template_dir, dst_dir)

    assert result.managed_files == ["a.txt", "b.md", "c.json"]


# ─── update_manifest ──────────────────────────────────────────────────────────


class TestUpdateManifest:
    def test_creates_manifest_with_template_entry(self, tmp_path: Path) -> None:
        update_manifest(tmp_path, "https://github.com/org/base-template", ["file_a.py", "file_b.md"])

        manifest = yaml.safe_load((tmp_path / ".copier-managed-files.yaml").read_text())
        assert manifest == {
            "templates": [
                {"src": "https://github.com/org/base-template", "managed_files": ["file_a.py", "file_b.md"]}
            ]
        }

    def test_idempotent_on_second_run(self, tmp_path: Path) -> None:
        update_manifest(tmp_path, "https://github.com/org/base-template", ["file_a.py"])
        update_manifest(tmp_path, "https://github.com/org/base-template", ["file_a.py"])

        manifest = yaml.safe_load((tmp_path / ".copier-managed-files.yaml").read_text())
        assert len(manifest["templates"]) == 1

    def test_replaces_existing_entry_for_same_src(self, tmp_path: Path) -> None:
        update_manifest(tmp_path, "https://github.com/org/base-template", ["old_file.py"])
        update_manifest(tmp_path, "https://github.com/org/base-template", ["new_file.py"])

        manifest = yaml.safe_load((tmp_path / ".copier-managed-files.yaml").read_text())
        assert manifest["templates"][0]["managed_files"] == ["new_file.py"]

    def test_layering_preserves_other_template_entries(self, tmp_path: Path) -> None:
        update_manifest(tmp_path, "https://github.com/org/base-template", ["base_file.py"])
        update_manifest(tmp_path, "https://github.com/org/child-template", ["child_file.py"])

        manifest = yaml.safe_load((tmp_path / ".copier-managed-files.yaml").read_text())
        srcs = [t["src"] for t in manifest["templates"]]
        assert srcs == ["https://github.com/org/base-template", "https://github.com/org/child-template"]

    def test_updating_child_does_not_overwrite_base(self, tmp_path: Path) -> None:
        update_manifest(tmp_path, "https://github.com/org/base-template", ["base_file.py"])
        update_manifest(tmp_path, "https://github.com/org/child-template", ["child_file.py"])
        update_manifest(tmp_path, "https://github.com/org/child-template", ["child_file_v2.py"])

        manifest = yaml.safe_load((tmp_path / ".copier-managed-files.yaml").read_text())
        assert len(manifest["templates"]) == 2
        base = next(t for t in manifest["templates"] if "base" in t["src"])
        child = next(t for t in manifest["templates"] if "child" in t["src"])
        assert base["managed_files"] == ["base_file.py"]
        assert child["managed_files"] == ["child_file_v2.py"]

    def test_manifest_contains_comment_header(self, tmp_path: Path) -> None:
        update_manifest(tmp_path, "https://github.com/org/base-template", [])

        raw = (tmp_path / ".copier-managed-files.yaml").read_text()
        assert raw.startswith("# Generated by copier")
        assert "do not edit manually" in raw
