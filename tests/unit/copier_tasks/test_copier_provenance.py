# pylint: disable=duplicate-code  # duplication here is intentional — each case verifies its own expected content
import json
import subprocess
from pathlib import Path

import pytest

from .helpers import run_copier_task

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _PROJECT_ROOT / "src" / "copier_tasks" / "copier_provenance.py"

expected_hash_comment = """\
# ============== WARNING ==============================================================================
# File is managed by a copier template. See .copier-managed-files.json for details.
#
# You are welcome to make changes to this file in your repo if they are custom to your project,
# but if the change should be shared with other projects, please backport it to the template repo.
# ====================================================================================================="""

expected_block_comment = """\
/*
 * ============== WARNING ==============================================================================
 * File is managed by a copier template. See .copier-managed-files.json for details.
 *
 * You are welcome to make changes to this file in your repo if they are custom to your project,
 * but if the change should be shared with other projects, please backport it to the template repo.
 * =====================================================================================================
 */"""

expected_markdown_comment = """\
<!--
============== WARNING ==============================================================================
File is managed by a copier template. See .copier-managed-files.json for details.

You are welcome to make changes to this file in your repo if they are custom to your project,
but if the change should be shared with other projects, please backport it to the template repo.
=====================================================================================================
-->"""


class TestCopierProvenanceViaSubprocess:
    def _run_script(
        self,
        *,
        src_template_dir: Path,
        dst_dir: Path,
        template_src: str = "",
    ) -> subprocess.CompletedProcess[str]:
        args = [str(src_template_dir), str(dst_dir)]
        if template_src:
            args += ["--template-src", template_src]
        return run_copier_task(_SCRIPT_PATH, *args)

    # ─── file markers ────────────────────────────────────────────────────────

    @pytest.mark.parametrize(
        ("template_filename", "dst_filename", "expected_location", "expected_comment"),
        [
            ("hash_comment.txt", "hash_comment.txt", "top", expected_hash_comment),
            ("testme.md", "testme.md", "bottom", expected_markdown_comment),
            ("eslint.config.mjs", "eslint.config.mjs", "top", expected_block_comment),
            ("config.yaml", "config.yaml", "top", expected_hash_comment),
            ("test.json", "test.json", "none", ""),
        ],
        ids=[
            "default-comments-are-on-top-and-use-hash-comment",
            "markdown-on-bottom-and-special-comment",
            "mjs-uses-block-comment-on-top",
            "yaml-uses-hash-comment-on-top",
            "json-files-must-not-have-comments",
        ],
    )
    def test_add_comment(
        self,
        template_filename: str,
        dst_filename: str,
        expected_location: str,
        expected_comment: str,
        tmp_path: Path,
    ) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / template_filename).touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "some content\nmore\nstuff"
        _ = (dst_dir / dst_filename).write_text(file_content, encoding="utf-8")

        result = self._run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert result.returncode == 0
        content = (dst_dir / dst_filename).read_text(encoding="utf-8")

        if expected_location == "none":
            assert content == file_content
        elif expected_location == "bottom":
            assert content == file_content + "\n" + expected_comment + "\n"
        else:
            assert content == expected_comment + "\n" + file_content

    def test_jinja_base_suffix_stripped_when_matching(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "README.md.jinja-base").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "some content\nmore\nstuff"
        _ = (dst_dir / "README.md").write_text(file_content, encoding="utf-8")

        result = self._run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert result.returncode == 0
        content = (dst_dir / "README.md").read_text(encoding="utf-8")
        assert content == file_content + "\n" + expected_markdown_comment + "\n"

    def test_add_comment_added_when_wrapped_in_jinja_if_check(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        template_file = template_dir / "{% if is_python_template %}.coveragerc.jinja{% endif %}.jinja-base"
        template_file.touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "some content\nmore\nstuff"
        _ = (dst_dir / ".coveragerc.jinja").write_text(file_content, encoding="utf-8")

        result = self._run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert result.returncode == 0
        content = (dst_dir / ".coveragerc.jinja").read_text(encoding="utf-8")
        assert content == expected_hash_comment + "\n" + file_content

    @pytest.mark.parametrize(
        ("template_filename", "expected_location", "expected_comment"),
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
        self,
        template_filename: str,
        expected_location: str,
        expected_comment: str,
        tmp_path: Path,
    ) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / template_filename).touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        if expected_location == "top":
            file_content = expected_comment + "\nsome content\nmore\nstuff"
        else:
            file_content = "some content\nmore\nstuff\n" + expected_comment + "\n"
        _ = (dst_dir / template_filename).write_text(file_content, encoding="utf-8")

        result = self._run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert result.returncode == 0
        assert (dst_dir / template_filename).read_text(encoding="utf-8") == file_content

    def test_add_comment_does_not_happen_if_not_a_template_file(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "template.txt").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "some content\nmore\nstuff"
        non_template = dst_dir / "pre-existing-file-non-template-file.txt"
        _ = non_template.write_text(file_content, encoding="utf-8")

        result = self._run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert result.returncode == 0
        assert non_template.read_text(encoding="utf-8") == file_content

    @pytest.mark.parametrize(
        ("shebang_line", "expected_location"),
        [
            ("#!/usr/bin/env python3\n", "bottom"),
            ("#!/bin/bash\n", "bottom"),
            ("# not a shebang\n", "top"),
            ("#! not-a-path\n", "top"),
            ("", "top"),
        ],
        ids=[
            "python-shebang-goes-bottom",
            "bash-shebang-goes-bottom",
            "hash-comment-not-shebang-stays-top",
            "hash-bang-without-slash-stays-top",
            "no-shebang-stays-top",
        ],
    )
    def test_shebang_forces_comment_to_bottom(
        self,
        shebang_line: str,
        expected_location: str,
        tmp_path: Path,
    ) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "script.py").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = shebang_line + "print('hello')\n"
        _ = (dst_dir / "script.py").write_text(file_content, encoding="utf-8")

        result = self._run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert result.returncode == 0
        content = (dst_dir / "script.py").read_text(encoding="utf-8")
        if expected_location == "bottom":
            assert content == file_content + "\n" + expected_hash_comment + "\n"
        else:
            assert content == expected_hash_comment + "\n" + file_content

    def test_handles_migration_of_comment_location(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "test.sh").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "some content\nmore\nstuff"
        # Force the existing comment at the top (wrong location for .sh)
        _ = (dst_dir / "test.sh").write_text(expected_hash_comment + "\n" + file_content, encoding="utf-8")

        result = self._run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert result.returncode == 0
        content = (dst_dir / "test.sh").read_text(encoding="utf-8")
        assert content == file_content + "\n" + expected_hash_comment + "\n"

    # ─── manifest ────────────────────────────────────────────────────────────

    def test_manifest_created_with_managed_files(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "a.txt").touch()
        (template_dir / "b.md").touch()
        (template_dir / "c.json").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "a.txt").write_text("content", encoding="utf-8")
        _ = (dst_dir / "b.md").write_text("content", encoding="utf-8")
        _ = (dst_dir / "c.json").write_text("{}", encoding="utf-8")
        _ = (dst_dir / "not-a-template.txt").write_text("content", encoding="utf-8")

        result = self._run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )

        assert result.returncode == 0
        manifest = json.loads((dst_dir / ".copier-managed-files.json").read_text(encoding="utf-8"))
        assert len(manifest["templates"]) == 1
        entry = manifest["templates"][0]
        assert entry["src"] == "https://github.com/org/base-template"
        assert sorted(entry["managed_files"]) == ["a.txt", "b.md", "c.json"]

    def test_manifest_is_idempotent_on_second_run(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "a.txt").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "a.txt").write_text("content", encoding="utf-8")

        _ = self._run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )
        result = self._run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )

        assert result.returncode == 0
        manifest = json.loads((dst_dir / ".copier-managed-files.json").read_text(encoding="utf-8"))
        assert len(manifest["templates"]) == 1

    def test_manifest_layering_preserves_other_template_entries(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "a.txt").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "a.txt").write_text("content", encoding="utf-8")

        _ = self._run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )
        result = self._run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        assert result.returncode == 0
        manifest = json.loads((dst_dir / ".copier-managed-files.json").read_text(encoding="utf-8"))
        srcs = [t["src"] for t in manifest["templates"]]
        assert "https://github.com/org/base-template" in srcs
        assert "https://github.com/org/child-template" in srcs

    def test_manifest_child_update_does_not_overwrite_base(self, tmp_path: Path) -> None:
        expected_num_manifests_in_project = 2
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "a.txt").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "a.txt").write_text("content", encoding="utf-8")

        _ = self._run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )
        _ = self._run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )
        result = self._run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        assert result.returncode == 0
        manifest = json.loads((dst_dir / ".copier-managed-files.json").read_text(encoding="utf-8"))
        assert len(manifest["templates"]) == expected_num_manifests_in_project
        base = next(t for t in manifest["templates"] if "base" in t["src"])
        assert "a.txt" in base["managed_files"]

    def test_manifest_is_valid_json(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()

        result = self._run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert result.returncode == 0
        raw = (dst_dir / ".copier-managed-files.json").read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert "templates" in parsed
