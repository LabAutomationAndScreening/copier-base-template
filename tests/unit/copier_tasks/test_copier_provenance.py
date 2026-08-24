import json
import subprocess
from pathlib import Path
from typing import NotRequired
from typing import TypedDict

import pytest
from faker import Faker

from .helpers import SCRIPT_PATH_ROOT
from .helpers import run_copier_task

_SCRIPT_PATH = SCRIPT_PATH_ROOT / "copier_provenance.py"


# The manifest shape is declared here rather than imported from the task module: the scripts live at a
# different import path in child templates (see helpers.SCRIPT_PATH_ROOT), and the test should assert
# against the JSON contract independently of the implementation's own definition.
class _TemplateEntry(TypedDict):
    src: str
    parent_src: NotRequired[str]
    managed_files: list[str]


class _Manifest(TypedDict):
    templates: list[_TemplateEntry]


def _read_manifest(repo_dir: Path) -> _Manifest:
    manifest: _Manifest = json.loads((repo_dir / ".config" / ".copier-managed-files.json").read_text(encoding="utf-8"))
    return manifest


expected_hash_comment = """\
# ============== WARNING ==============================================================================
# File is managed by a copier template. See .config/.copier-managed-files.json for details.
#
# You are welcome to make changes to this file in your repo if they are custom to your project,
# but if the change should be shared with other projects, please backport it to the template repo.
# ====================================================================================================="""

expected_batch_comment = """\
REM ============== WARNING ==============================================================================
REM File is managed by a copier template. See .config/.copier-managed-files.json for details.
REM
REM You are welcome to make changes to this file in your repo if they are custom to your project,
REM but if the change should be shared with other projects, please backport it to the template repo.
REM ====================================================================================================="""

expected_block_comment = """\
/*
 * ============== WARNING ==============================================================================
 * File is managed by a copier template. See .config/.copier-managed-files.json for details.
 *
 * You are welcome to make changes to this file in your repo if they are custom to your project,
 * but if the change should be shared with other projects, please backport it to the template repo.
 * =====================================================================================================
 */"""

expected_jinja_comment = """\
{#
 ============== WARNING ==============================================================================
 File is managed by a copier template. See .config/.copier-managed-files.json for details.

 You are welcome to make changes to this file in your repo if they are custom to your project,
 but if the change should be shared with other projects, please backport it to the template repo.
 =====================================================================================================
#}"""

expected_markdown_comment = """\
<!--
============== WARNING ==============================================================================
File is managed by a copier template. See .config/.copier-managed-files.json for details.

You are welcome to make changes to this file in your repo if they are custom to your project,
but if the change should be shared with other projects, please backport it to the template repo.
=====================================================================================================
-->"""


def _run_script(
    *,
    src_template_dir: Path,
    dst_dir: Path,
    template_src: str = "",
) -> subprocess.CompletedProcess[str]:
    args = [str(src_template_dir), str(dst_dir)]
    if template_src != "":
        args += ["--template-src", template_src]
    result = run_copier_task(_SCRIPT_PATH, *args)
    assert result.returncode == 0, result.stderr
    return result


class TestJinjaTemplateMatching:
    def test_jinja_base_suffix_stripped_when_matching(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "README.md.jinja-base").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "some content\nmore\nstuff"
        _ = (dst_dir / "README.md").write_text(file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = (dst_dir / "README.md").read_text(encoding="utf-8")
        assert content == file_content + "\n" + expected_markdown_comment + "\n"

    def test_jinja_template_file_gets_jinja_comment(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "README.md.jinja.jinja-base").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "some content\nmore\nstuff"
        _ = (dst_dir / "README.md.jinja").write_text(file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = (dst_dir / "README.md.jinja").read_text(encoding="utf-8")
        assert content == expected_jinja_comment + "\n" + file_content

    def test_jinja_if_check_filename_matched(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        template_file = template_dir / "{% if is_python_template %}.coveragerc.jinja{% endif %}.jinja-base"
        template_file.touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "some content\nmore\nstuff"
        _ = (dst_dir / ".coveragerc.jinja").write_text(file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = (dst_dir / ".coveragerc.jinja").read_text(encoding="utf-8")
        assert content == expected_jinja_comment + "\n" + file_content

    def test_symlinked_template_directory_traversed(self, tmp_path: Path) -> None:
        # Simulates base-template's template/template/.claude → ../../.claude symlink pattern.
        real_dir = tmp_path / "real_claude"
        real_dir.mkdir()
        (real_dir / "config.yaml").touch()

        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / ".claude").symlink_to(real_dir, target_is_directory=True)

        dst_dir = tmp_path / "destination"
        dst_claude = dst_dir / ".claude"
        dst_claude.mkdir(parents=True)
        _ = (dst_claude / "config.yaml").write_text("key: value\n", encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = (dst_claude / "config.yaml").read_text(encoding="utf-8")
        assert content.startswith(expected_hash_comment)

    def test_jinja_if_check_directory_matched(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        cond_dir = template_dir / "{% if has_backend %}backend{% endif %}" / "src"
        cond_dir.mkdir(parents=True)
        (cond_dir / "__init__.py").touch()

        dst_dir = tmp_path / "destination"
        backend_src = dst_dir / "backend" / "src"
        backend_src.mkdir(parents=True)
        file_content = "x = 1\n"
        _ = (backend_src / "__init__.py").write_text(file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = (backend_src / "__init__.py").read_text(encoding="utf-8")
        assert content.startswith(expected_hash_comment)


class TestDestinationSymlinks:
    def test_symlink_cycle_in_destination_does_not_prevent_stamping(self, tmp_path: Path) -> None:
        # Two links back to the root rather than one: a single link is bounded by the kernel's ELOOP
        # limit, so it would terminate on its own and catch no regression.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "README.md.jinja-base").touch()

        dst_dir = tmp_path / "destination"
        node_modules = dst_dir / "node_modules"
        node_modules.mkdir(parents=True)
        (node_modules / "pkg-a").symlink_to(dst_dir, target_is_directory=True)
        (node_modules / "pkg-b").symlink_to(dst_dir, target_is_directory=True)
        file_content = "some content\n"
        _ = (dst_dir / "README.md").write_text(file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = (dst_dir / "README.md").read_text(encoding="utf-8")
        assert content == file_content + "\n" + expected_markdown_comment + "\n"

    def test_broken_symlink_at_managed_path_is_skipped(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "config.yaml.jinja-base").touch()
        (template_dir / "keep.yaml.jinja-base").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        broken = dst_dir / "config.yaml"
        broken.symlink_to(dst_dir / "does-not-exist.yaml")
        _ = (dst_dir / "keep.yaml").write_text("key: value\n", encoding="utf-8")
        assert broken.is_symlink()

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        manifest = _read_manifest(dst_dir)

        assert (dst_dir / "keep.yaml").read_text(encoding="utf-8").startswith(expected_hash_comment)
        assert manifest["templates"][0]["managed_files"] == ["keep.yaml"]


class TestFileExtensionComments:
    @pytest.mark.parametrize(
        ("filename", "expected_location", "expected_comment"),
        [
            # hash top (default for unknown types)
            ("script.py", "top", expected_hash_comment),
            ("config.yaml", "top", expected_hash_comment),
            ("config.yml", "top", expected_hash_comment),
            # hash bottom (shebang-sensitive extension default)
            ("deploy.sh", "bottom", expected_hash_comment),
            # batch bottom (REM comments, @echo off at top)
            ("sh.bat", "bottom", expected_batch_comment),
            # block top (JS / TS / CSS)
            ("eslint.config.mjs", "top", expected_block_comment),
            ("config.js", "top", expected_block_comment),
            ("module.cjs", "top", expected_block_comment),
            ("config.ts", "top", expected_block_comment),
            ("module.mts", "top", expected_block_comment),
            ("module.cts", "top", expected_block_comment),
            ("styles.css", "top", expected_block_comment),
            # markdown top (HTML-like)
            ("component.vue", "top", expected_markdown_comment),
            ("index.html", "top", expected_markdown_comment),
            ("icon.svg", "top", expected_markdown_comment),
            # markdown bottom
            ("README.md", "bottom", expected_markdown_comment),
            # none — by extension (no comment syntax available)
            ("data.json", "none", ""),
            ("biome.jsonc", "top", expected_block_comment),
            # none — by filename (extensionless dotfiles with structured content)
            (".copier-answers.yml", "none", ""),
            (".coveragerc", "bottom", expected_hash_comment),
            (".python-version", "none", ""),
            (".prettierrc", "none", ""),
        ],
        ids=[
            "py-hash-top",
            "yaml-hash-top",
            "yml-hash-top",
            "sh-hash-bottom",
            "bat-batch-bottom",
            "mjs-block-top",
            "js-block-top",
            "cjs-block-top",
            "ts-block-top",
            "mts-block-top",
            "cts-block-top",
            "css-block-top",
            "vue-markdown-top",
            "html-markdown-top",
            "svg-markdown-top",
            "md-markdown-bottom",
            "json-none",
            "jsonc-block-top",
            "copier-answers-none",
            "coveragerc-hash-bottom",
            "python-version-none",
            "prettierrc-none",
        ],
    )
    def test_comment_format_by_file_type(
        self,
        filename: str,
        expected_location: str,
        expected_comment: str,
        tmp_path: Path,
    ) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / filename).touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "some content\nmore\nstuff"
        _ = (dst_dir / filename).write_text(file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = (dst_dir / filename).read_text(encoding="utf-8")

        if expected_location == "none":
            assert content == file_content
        elif expected_location == "bottom":
            assert content == file_content + "\n" + expected_comment + "\n"
        else:
            assert content == expected_comment + "\n" + file_content

    @pytest.mark.parametrize(
        ("template_filename", "expected_location", "expected_comment"),
        [
            ("hash_comment.txt", "top", expected_hash_comment),
            ("testme.md", "bottom", expected_markdown_comment),
        ],
        ids=["existing-hash-top", "existing-markdown-bottom"],
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

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert (dst_dir / template_filename).read_text(encoding="utf-8") == file_content

    def test_non_template_file_is_not_marked(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "template.txt").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "some content\nmore\nstuff"
        non_template = dst_dir / "pre-existing-file-non-template-file.txt"
        _ = non_template.write_text(file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert non_template.read_text(encoding="utf-8") == file_content


class TestShebangHandling:
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

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = (dst_dir / "script.py").read_text(encoding="utf-8")
        if expected_location == "bottom":
            assert content == file_content + "\n" + expected_hash_comment + "\n"
        else:
            assert content == expected_hash_comment + "\n" + file_content

    def test_comment_location_migrated_when_wrong(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "test.sh").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "some content\nmore\nstuff"
        # Force the existing comment at the top (wrong location for .sh)
        _ = (dst_dir / "test.sh").write_text(expected_hash_comment + "\n" + file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = (dst_dir / "test.sh").read_text(encoding="utf-8")
        assert content == file_content + "\n" + expected_hash_comment + "\n"


class TestExistingUserCommentsPreserved:
    @pytest.mark.parametrize(
        ("filenames", "user_comment", "expected_marker"),
        [
            (("module.ts", "module.ts"), "/*\n * SPDX-License-Identifier: MIT\n */", expected_block_comment),
            (("page.jinja.jinja-base", "page.jinja"), "{#\n a hand-written jinja note\n#}", expected_jinja_comment),
            (("index.html", "index.html"), "<!--\n a hand-written html note\n-->", expected_markdown_comment),
        ],
        ids=["block-license-preserved", "jinja-note-preserved", "markdown-note-preserved"],
    )
    def test_non_marker_leading_comment_is_not_stripped(
        self,
        filenames: tuple[str, str],
        user_comment: str,
        expected_marker: str,
        tmp_path: Path,
        faker: Faker,
    ) -> None:
        template_filename, dst_filename = filenames
        body = faker.sentence()
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / template_filename).touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = user_comment + "\n" + body + "\n"
        _ = (dst_dir / dst_filename).write_text(file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = (dst_dir / dst_filename).read_text(encoding="utf-8")
        assert content == expected_marker + "\n" + file_content

    @pytest.mark.parametrize(
        ("filenames", "expected_marker"),
        [
            (("module.ts", "module.ts"), expected_block_comment),
            (("page.jinja.jinja-base", "page.jinja"), expected_jinja_comment),
        ],
        ids=["block-marker-not-duplicated", "jinja-marker-not-duplicated"],
    )
    def test_existing_marker_is_replaced_not_duplicated(
        self,
        filenames: tuple[str, str],
        expected_marker: str,
        tmp_path: Path,
        faker: Faker,
    ) -> None:
        template_filename, dst_filename = filenames
        body = faker.sentence()
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / template_filename).touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = expected_marker + "\n" + body + "\n"
        _ = (dst_dir / dst_filename).write_text(file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = (dst_dir / dst_filename).read_text(encoding="utf-8")
        assert content == file_content


class TestManifest:
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

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )

        manifest = _read_manifest(dst_dir)
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

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )
        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )

        manifest = _read_manifest(dst_dir)
        assert len(manifest["templates"]) == 1

    def test_manifest_layering_preserves_other_template_entries(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "a.txt").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "a.txt").write_text("content", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )
        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        manifest = _read_manifest(dst_dir)
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

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )
        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )
        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        manifest = _read_manifest(dst_dir)
        assert len(manifest["templates"]) == expected_num_manifests_in_project
        base = next(t for t in manifest["templates"] if "base" in t["src"])
        assert "a.txt" in base["managed_files"]

    def test_manifest_src_matches_template_src_argument(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/my-template",
        )

        manifest = _read_manifest(dst_dir)
        entry = manifest["templates"][0]
        assert entry["src"] == "https://github.com/org/my-template"

    def test_manifest_structure_is_valid(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "a.txt").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "a.txt").write_text("content", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/my-template",
        )

        manifest = _read_manifest(dst_dir)
        assert isinstance(manifest["templates"], list)
        for entry in manifest["templates"]:
            assert isinstance(entry["src"], str)
            assert isinstance(entry["managed_files"], list)
            assert all(isinstance(f, str) for f in entry["managed_files"])

    def test_manifest_parent_src_discovered_from_config_copier_answers(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        config_dir = tmp_path / ".config"
        config_dir.mkdir()
        _ = (config_dir / ".copier-answers.yml").write_text(
            "_src_path: https://github.com/org/parent-template\n",
            encoding="utf-8",
        )

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        manifest = _read_manifest(dst_dir)
        entry = manifest["templates"][0]
        assert "parent_src" in entry
        assert entry["parent_src"] == "https://github.com/org/parent-template"

    def test_manifest_parent_src_falls_back_to_root_copier_answers(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        _ = (tmp_path / ".copier-answers.yml").write_text(
            "_src_path: https://github.com/org/parent-template\n",
            encoding="utf-8",
        )

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        manifest = _read_manifest(dst_dir)
        entry = manifest["templates"][0]
        assert "parent_src" in entry
        assert entry["parent_src"] == "https://github.com/org/parent-template"

    def test_manifest_no_parent_src_when_no_copier_answers(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/root-template",
        )

        manifest = _read_manifest(dst_dir)
        entry = manifest["templates"][0]
        assert entry["src"] == "https://github.com/org/root-template"
        assert "parent_src" not in entry

    def test_ancestor_files_attributed_to_ancestor_template(self, tmp_path: Path) -> None:
        # Simulate child template updating a grandchild project.
        # The child template's own manifest lists base-template as managing "shared.py".
        # "app.py" is child-specific. Expect two manifest entries with correct attribution.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "shared.py").touch()
        (template_dir / "app.py").touch()

        # Ancestor manifest (child template's .copier-managed-files.json in the template clone root)
        _ = (tmp_path / ".copier-managed-files.json").write_text(
            json.dumps(
                {
                    "templates": [
                        {"src": "https://github.com/org/base-template", "managed_files": ["shared.py"]},
                    ]
                }
            ),
            encoding="utf-8",
        )

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "shared.py").write_text("x = 1\n", encoding="utf-8")
        _ = (dst_dir / "app.py").write_text("y = 2\n", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        manifest = _read_manifest(dst_dir)
        srcs = {t["src"]: t for t in manifest["templates"]}
        assert "https://github.com/org/base-template" in srcs
        assert "https://github.com/org/child-template" in srcs
        assert srcs["https://github.com/org/base-template"]["managed_files"] == ["shared.py"]
        assert srcs["https://github.com/org/child-template"]["managed_files"] == ["app.py"]
        # shared.py header references the base template URL
        shared_content = (dst_dir / "shared.py").read_text(encoding="utf-8")
        assert "https://github.com/org/base-template" in shared_content
        assert "https://github.com/org/child-template" not in shared_content
        # app.py header references the child template URL
        app_content = (dst_dir / "app.py").read_text(encoding="utf-8")
        assert "https://github.com/org/child-template" in app_content

    def test_ancestor_jinja_suffix_resolved_for_attribution(self, tmp_path: Path) -> None:
        # Ancestor manifest records "template/README.md.jinja" (base stamped child template with the
        # .jinja-base-stripped name). Final-dest has "README.md" (jinja-rendered). The
        # attribution lookup must strip both the "template/" prefix and ".jinja" suffix.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "README.md.jinja").touch()  # child template file (will render to README.md)

        _ = (tmp_path / ".copier-managed-files.json").write_text(
            json.dumps(
                {
                    "templates": [
                        {"src": "https://github.com/org/base-template", "managed_files": ["template/README.md.jinja"]},
                    ]
                }
            ),
            encoding="utf-8",
        )

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "README.md").write_text("# hello\n", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        manifest = _read_manifest(dst_dir)
        srcs = {t["src"]: t for t in manifest["templates"]}
        assert "README.md" in srcs["https://github.com/org/base-template"]["managed_files"]
        assert "README.md" not in srcs["https://github.com/org/child-template"]["managed_files"]

    def test_full_chain_base_child_final_attribution(self, tmp_path: Path) -> None:
        # Full 3-level chain: base stamps child (step 1), child stamps grandchild (step 2).
        # Files from base's template must end up under base in grandchild's manifest.
        base_tmpl = tmp_path / "base_tmpl"
        child_repo = tmp_path / "child_repo"
        final_repo = tmp_path / "final_repo"

        # Base template structure: config.yaml and template/README.md.jinja.jinja-base
        (base_tmpl / "template").mkdir(parents=True)
        (base_tmpl / "template" / "config.yaml").touch()
        (base_tmpl / "template" / "template").mkdir()
        (base_tmpl / "template" / "template" / "README.md.jinja.jinja-base").touch()

        # Child repo (as rendered by copier from base): config.yaml at root, README.md.jinja in template/
        (child_repo / "template").mkdir(parents=True)
        _ = (child_repo / "config.yaml").write_text("cfg", encoding="utf-8")
        _ = (child_repo / "template" / "README.md.jinja").write_text("# readme\n", encoding="utf-8")
        _ = (child_repo / "template" / "child_only.py").write_text("x = 1\n", encoding="utf-8")

        # Step 1: base stamps child — populates child's .config/.copier-managed-files.json
        _ = _run_script(
            src_template_dir=base_tmpl / "template",
            dst_dir=child_repo,
            template_src="https://github.com/org/base-template",
        )
        child_manifest = _read_manifest(child_repo)
        base_entry = next(t for t in child_manifest["templates"] if "base" in t["src"])
        assert "template/README.md.jinja" in base_entry["managed_files"]

        # Grandchild repo (as rendered by copier from child): README.md (rendered from .jinja) + child_only.py
        (final_repo).mkdir(parents=True)
        _ = (final_repo / "README.md").write_text("# rendered\n", encoding="utf-8")
        _ = (final_repo / "child_only.py").write_text("x = 1\n", encoding="utf-8")

        # Step 2: child stamps grandchild — must attribute README.md to base, child_only.py to child
        _ = _run_script(
            src_template_dir=child_repo / "template",
            dst_dir=final_repo,
            template_src="https://github.com/org/child-template",
        )
        final_manifest = _read_manifest(final_repo)
        srcs = {t["src"]: t for t in final_manifest["templates"]}
        assert "README.md" in srcs["https://github.com/org/base-template"]["managed_files"]
        assert "child_only.py" in srcs["https://github.com/org/child-template"]["managed_files"]
        assert "README.md" not in srcs["https://github.com/org/child-template"]["managed_files"]
