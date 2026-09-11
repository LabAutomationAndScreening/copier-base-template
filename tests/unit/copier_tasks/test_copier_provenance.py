import json
import os
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
    templates_suffix: str | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [str(src_template_dir), str(dst_dir)]
    if template_src != "":
        args += ["--template-src", template_src]
    if templates_suffix is not None:
        args += ["--templates-suffix", templates_suffix]
    result = run_copier_task(_SCRIPT_PATH, *args)
    assert result.returncode == 0, result.stderr
    return result


def _run_script_expecting_failure(
    *,
    src_template_dir: Path,
    dst_dir: Path,
    template_src: str,
) -> subprocess.CompletedProcess[str]:
    """Run the task expecting it to report unstampable files and exit 1, having still done its work."""
    result = run_copier_task(_SCRIPT_PATH, str(src_template_dir), str(dst_dir), "--template-src", template_src)
    assert result.returncode == 1, f"expected a reported failure, got rc={result.returncode}: {result.stderr}"
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

    def test_raw_wrapped_jinja_filename_matched(self, tmp_path: Path) -> None:
        # base-template names a grandchild-template file `{% raw %}...{% endraw %}` so the inner Jinja
        # survives into the child template verbatim. The destination name is the un-raw'd text, so only
        # the raw markers are removed — the inner if-check must NOT be resolved at this level.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "{% raw %}{% if is_open_source %}LICENSE{% endif %}{% endraw %}").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "Apache License\n"
        dst_file = dst_dir / "{% if is_open_source %}LICENSE{% endif %}"
        _ = dst_file.write_text(file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert dst_file.read_text(encoding="utf-8") == expected_hash_comment + "\n" + file_content

    def test_raw_wrapped_jinja_filename_does_not_swallow_its_directory(self, tmp_path: Path) -> None:
        # Regression: the empty span between `{% raw %}` and `{% if` used to collapse the whole path to
        # its parent directory, so the file was silently never tracked nor stamped.
        template_dir = tmp_path / "template"
        nested = template_dir / "docs"
        nested.mkdir(parents=True)
        (nested / "{% raw %}{% if is_open_source %}LICENSE{% endif %}{% endraw %}").touch()

        dst_dir = tmp_path / "destination"
        dst_docs = dst_dir / "docs"
        dst_docs.mkdir(parents=True)
        dst_file = dst_docs / "{% if is_open_source %}LICENSE{% endif %}"
        _ = dst_file.write_text("Apache License\n", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )

        manifest = _read_manifest(dst_dir)
        assert manifest["templates"][0]["managed_files"] == ["docs/{% if is_open_source %}LICENSE{% endif %}"]

    def test_raw_wrapped_jinja_filename_keeps_inner_suffix_stripping(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "{% raw %}{% if is_open_source %}NOTICE.md{% endif %}{% endraw %}.jinja-base").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        file_content = "# notice\n"
        dst_file = dst_dir / "{% if is_open_source %}NOTICE.md{% endif %}"
        _ = dst_file.write_text(file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert dst_file.read_text(encoding="utf-8") == file_content + "\n" + expected_markdown_comment + "\n"

    def test_retained_if_check_filename_uses_real_extension_for_comment_format(self, tmp_path: Path) -> None:
        # Mirrors base-template's template/.github/{% raw %}{% if is_open_source %}CODE_OF_CONDUCT.md...
        # The destination keeps the if-check, so Path.suffix reads ".md{% endif %}" and the markdown
        # format would be missed, stamping a markdown file with `#` comments.
        template_dir = tmp_path / "template"
        nested = template_dir / ".github"
        nested.mkdir(parents=True)
        (nested / "{% raw %}{% if is_open_source %}CODE_OF_CONDUCT.md{% endif %}{% endraw %}").touch()

        dst_dir = tmp_path / "destination"
        dst_github = dst_dir / ".github"
        dst_github.mkdir(parents=True)
        file_content = "# Code of Conduct\n"
        dst_file = dst_github / "{% if is_open_source %}CODE_OF_CONDUCT.md{% endif %}"
        _ = dst_file.write_text(file_content, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert dst_file.read_text(encoding="utf-8") == file_content + "\n" + expected_markdown_comment + "\n"

    def test_trailing_jinja_is_literal_when_the_active_suffix_is_jinja_base(self, tmp_path: Path) -> None:
        # base-template ships template/template/Taskfile.yaml.jinja. Its _templates_suffix is
        # .jinja-base, so that trailing .jinja is literal content: copier renders the name unchanged
        # and the child template ends up with template/Taskfile.yaml.jinja. Stripping .jinja anyway
        # made the task probe template/Taskfile.yaml, which does not exist, so the file was never
        # tracked nor stamped. Taskfile.yaml, .pre-commit-config.yaml and .github/dependabot.yml are
        # all missing from the base entry of the nuxt template's manifest for this reason.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "Taskfile.yaml.jinja").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        dst_file = dst_dir / "Taskfile.yaml.jinja"
        file_content = "version: '3'\n"
        _ = dst_file.write_text(file_content, encoding="utf-8")
        # The over-stripped spelling must not be picked up instead.
        decoy = dst_dir / "Taskfile.yaml"
        _ = decoy.write_text(file_content, encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            templates_suffix=".jinja-base",
        )

        assert dst_file.read_text(encoding="utf-8") == expected_jinja_comment + "\n" + file_content
        assert decoy.read_text(encoding="utf-8") == file_content
        entry = _read_manifest(dst_dir)["templates"][0]
        assert entry["managed_files"] == ["Taskfile.yaml.jinja"]

    def test_jinja_suffix_still_stripped_when_it_is_the_active_suffix(self, tmp_path: Path) -> None:
        # The child template's own _templates_suffix is .jinja, so there the suffix is real.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "Taskfile.yaml.jinja").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        dst_file = dst_dir / "Taskfile.yaml"
        file_content = "version: '3'\n"
        _ = dst_file.write_text(file_content, encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
            templates_suffix=".jinja",
        )

        entry = _read_manifest(dst_dir)["templates"][0]
        assert entry["managed_files"] == ["Taskfile.yaml"]

    def test_both_suffixes_stripped_when_none_is_declared(self, tmp_path: Path) -> None:
        # Existing child templates invoke the task without the flag, so the permissive behavior has
        # to stay the default until they opt in.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "a.yaml.jinja").touch()
        (template_dir / "b.yaml.jinja-base").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "a.yaml").write_text("a: 1\n", encoding="utf-8")
        _ = (dst_dir / "b.yaml").write_text("b: 2\n", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        entry = _read_manifest(dst_dir)["templates"][0]
        assert entry["managed_files"] == ["a.yaml", "b.yaml"]

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


class TestWhenTaskRunAgainstDestination:
    def test_Given_symlink_cycle__Then_managed_file_stamped(self, tmp_path: Path) -> None:
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

    def test_Given_broken_symlink_at_managed_path__Then_path_skipped(self, tmp_path: Path) -> None:
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


class TestByteFidelity:
    """Stamping must not rewrite anything about a file other than inserting the marker."""

    def _stamp(self, tmp_path: Path, filename: str, raw: bytes) -> Path:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / filename).touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        dst_file = dst_dir / filename
        _ = dst_file.write_bytes(raw)

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)
        return dst_file

    def test_crlf_line_endings_preserved(self, tmp_path: Path) -> None:
        # sh.bat and deployment/deploy.bat are CRLF on purpose; text-mode writes silently
        # converted them to LF, so every stamped .bat file came back as a whole-file diff.
        dst_file = self._stamp(tmp_path, "run.bat", b"@echo off\r\nrem hi\r\n")

        raw = dst_file.read_bytes()
        assert b"REM ============== WARNING" in raw
        assert raw.replace(b"\r\n", b"").count(b"\n") == 0, "file gained bare LF line endings"

    def test_lf_line_endings_not_converted_to_crlf(self, tmp_path: Path) -> None:
        dst_file = self._stamp(tmp_path, "script.sh", b"echo hi\n")

        raw = dst_file.read_bytes()
        assert b"# ============== WARNING" in raw
        assert b"\r" not in raw

    def test_crlf_stamping_is_idempotent(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "run.bat").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        dst_file = dst_dir / "run.bat"
        _ = dst_file.write_bytes(b"@echo off\r\nrem hi\r\n")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)
        after_first = dst_file.read_bytes()
        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert dst_file.read_bytes() == after_first

    def test_non_ascii_content_preserved(self, tmp_path: Path) -> None:
        # The file was opened without an explicit encoding, so a non-UTF-8 locale would mangle this.
        body = "s = 'café 中文 🙂'\n"
        dst_file = self._stamp(tmp_path, "unicode.py", body.encode("utf-8"))

        content = dst_file.read_text(encoding="utf-8")
        assert content == expected_hash_comment + "\n" + body


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


class TestStaleMarkersRemoved:
    """A marker written by an older version of this task must be removed, not left to accumulate."""

    def test_marker_in_a_different_comment_format_is_replaced_not_doubled(self, tmp_path: Path) -> None:
        # .jsonc moved from the hash format to the block format. Only the current format's pattern was
        # stripped, so the old marker stayed put and the new one was added alongside it.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "biome.jsonc").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        dst_file = dst_dir / "biome.jsonc"
        body = '{"a": 1}\n'
        _ = dst_file.write_text(expected_hash_comment + "\n" + body, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = dst_file.read_text(encoding="utf-8")
        assert content.count("============== WARNING") == 1
        assert content == expected_block_comment + "\n" + body

    def test_stacked_duplicate_markers_are_all_removed(self, tmp_path: Path) -> None:
        # Stripping was capped at one occurrence, so a file that ever acquired two markers kept one
        # of them permanently.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "settings.py").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        dst_file = dst_dir / "settings.py"
        body = "x = 1\n"
        _ = dst_file.write_text(
            expected_hash_comment + "\n" + expected_hash_comment + "\n" + body,
            encoding="utf-8",
        )

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        content = dst_file.read_text(encoding="utf-8")
        assert content.count("============== WARNING") == 1
        assert content == expected_hash_comment + "\n" + body

    def test_marker_removed_when_file_type_no_longer_takes_one(self, tmp_path: Path) -> None:
        # .python-version and friends moved to the "none" format. The task returned early without
        # stripping, so a marker stamped by an earlier version was stuck in the file forever.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / ".python-version").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        dst_file = dst_dir / ".python-version"
        body = "3.12.7\n"
        _ = dst_file.write_text(expected_hash_comment + "\n" + body, encoding="utf-8")

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert dst_file.read_text(encoding="utf-8") == body

    def test_unchanged_file_is_not_rewritten(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "a.py").touch()
        (template_dir / "c.json").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        stamped = dst_dir / "a.py"
        _ = stamped.write_text(expected_hash_comment + "\n" + "x = 1\n", encoding="utf-8")
        untouched = dst_dir / "c.json"
        _ = untouched.write_text("{}\n", encoding="utf-8")
        for path in (stamped, untouched):
            os.utime(path, (0, 0))

        _ = _run_script(src_template_dir=template_dir, dst_dir=dst_dir)

        assert stamped.stat().st_mtime == 0, "already-correct file was rewritten"
        assert untouched.stat().st_mtime == 0, "file that takes no marker was rewritten"


class TestExclusions:
    """Regenerated files ship in the template but must not be claimed as managed."""

    def test_generated_subtree_is_excluded_at_any_depth(self, tmp_path: Path) -> None:
        # A code generator rewrites these after the copier task runs, so the marker is destroyed and
        # the manifest is left claiming a file nobody maintains by hand.
        template_dir = tmp_path / "template"
        generated = template_dir / "backend" / "tests" / "e2e" / "generated" / "open_api"
        generated.mkdir(parents=True)
        (generated / "backend_client.py").touch()
        (template_dir / "kept.py").touch()

        dst_dir = tmp_path / "destination"
        dst_generated = dst_dir / "backend" / "tests" / "e2e" / "generated" / "open_api"
        dst_generated.mkdir(parents=True)
        client_body = "class BackendClient:\n    pass\n"
        _ = (dst_generated / "backend_client.py").write_text(client_body, encoding="utf-8")
        _ = (dst_dir / "kept.py").write_text("x = 1\n", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        assert (dst_generated / "backend_client.py").read_text(encoding="utf-8") == client_body
        entry = _read_manifest(dst_dir)["templates"][0]
        assert entry["managed_files"] == ["kept.py"]

    def test_generated_directory_is_always_excluded(self, tmp_path: Path) -> None:
        # Every generated tree in these repos lives under a path segment named exactly "generated",
        # and a project regenerates the contents itself, so these are never claimed. No template opts
        # in or out: the exclusion is unconditional.
        template_dir = tmp_path / "template"
        generated = template_dir / "backend" / "tests" / "e2e" / "generated" / "open_api"
        generated.mkdir(parents=True)
        (generated / "backend_client.py").touch()
        (template_dir / "kept.py").touch()

        dst_dir = tmp_path / "destination"
        dst_generated = dst_dir / "backend" / "tests" / "e2e" / "generated" / "open_api"
        dst_generated.mkdir(parents=True)
        client_body = "class BackendClient:\n    pass\n"
        _ = (dst_generated / "backend_client.py").write_text(client_body, encoding="utf-8")
        _ = (dst_dir / "kept.py").write_text("x = 1\n", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        assert (dst_generated / "backend_client.py").read_text(encoding="utf-8") == client_body
        entry = _read_manifest(dst_dir)["templates"][0]
        assert entry["managed_files"] == ["kept.py"]

    def test_marker_already_in_a_generated_file_is_cleaned_up(self, tmp_path: Path) -> None:
        # Existing projects have these files stamped, so the task has to remove its own marker rather
        # than walk away and strand it. This is why "generated" is an exclusion rather than a pruned
        # directory like the tool caches.
        template_dir = tmp_path / "template"
        generated = template_dir / "generated"
        generated.mkdir(parents=True)
        (generated / "client.py").touch()

        dst_dir = tmp_path / "destination"
        dst_generated = dst_dir / "generated"
        dst_generated.mkdir(parents=True)
        dst_file = dst_generated / "client.py"
        body = "class Client:\n    pass\n"
        _ = dst_file.write_text(expected_hash_comment + "\n" + body, encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        assert dst_file.read_text(encoding="utf-8") == body

    @pytest.mark.parametrize("filename", ["generated_client.py", "regenerated.md", "generated.py"])
    def test_generated_as_part_of_a_longer_name_is_still_tracked(self, filename: str, tmp_path: Path) -> None:
        # The rule matches a whole path segment, not a substring, so a hand-maintained file whose name
        # merely contains the word is unaffected. Across 250 generated files in the downstream repo and
        # 20 in the templates, the only segment containing "generated" is exactly "generated".
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / filename).touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / filename).write_text("x = 1\n", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        entry = _read_manifest(dst_dir)["templates"][0]
        assert entry["managed_files"] == [filename]

    @pytest.mark.parametrize(
        "cache_dir",
        [".ruff_cache", "__pycache__", "node_modules", ".pytest_cache", ".venv"],
    )
    def test_tool_cache_directories_are_never_tracked(self, cache_dir: str, tmp_path: Path) -> None:
        # base-template's own template/.ruff_cache is untracked local junk that sits inside the
        # template directory. Walking the filesystem picked it up, so a run from a non-git source
        # would stamp .ruff_cache/.gitignore and CACHEDIR.TAG in the destination.
        template_dir = tmp_path / "template"
        cache = template_dir / cache_dir
        cache.mkdir(parents=True)
        (cache / ".gitignore").touch()
        (template_dir / "kept.py").touch()

        dst_dir = tmp_path / "destination"
        dst_cache = dst_dir / cache_dir
        dst_cache.mkdir(parents=True)
        cache_body = "# generated by a tool\n"
        _ = (dst_cache / ".gitignore").write_text(cache_body, encoding="utf-8")
        _ = (dst_dir / "kept.py").write_text("x = 1\n", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )

        assert (dst_cache / ".gitignore").read_text(encoding="utf-8") == cache_body
        entry = _read_manifest(dst_dir)["templates"][0]
        assert entry["managed_files"] == ["kept.py"]


class TestResilience:
    """One unstampable file must not cost the whole run."""

    def test_undecodable_file_in_a_bottom_format_is_tracked_but_not_stamped(self, tmp_path: Path) -> None:
        # The decode probe only ran for top-location formats, so an undecodable file in a
        # bottom-location format (.md, .sh, .bat, .coveragerc) raised instead of being skipped.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "aaa.py").touch()
        (template_dir / "mmm.md").touch()
        (template_dir / "zzz.py").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "aaa.py").write_text("a = 1\n", encoding="utf-8")
        _ = (dst_dir / "mmm.md").write_bytes(b"\xff\xfe\x00binary\x00")
        _ = (dst_dir / "zzz.py").write_text("z = 1\n", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )

        for name in ("aaa.py", "zzz.py"):
            assert (dst_dir / name).read_text(encoding="utf-8").startswith("# ============== WARNING")
        assert (dst_dir / "mmm.md").read_bytes() == b"\xff\xfe\x00binary\x00"
        entry = _read_manifest(dst_dir)["templates"][0]
        assert entry["managed_files"] == ["aaa.py", "mmm.md", "zzz.py"]

    def test_unreadable_file_does_not_abort_the_run(self, tmp_path: Path) -> None:
        # Files are visited in sorted order and the manifest was only written after the loop, so a
        # raise part-way through left later files unstamped and no manifest on disk at all.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "aaa.py").touch()
        (template_dir / "mmm.py").touch()
        (template_dir / "zzz.py").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "aaa.py").write_text("a = 1\n", encoding="utf-8")
        unreadable = dst_dir / "mmm.py"
        _ = unreadable.write_text("m = 1\n", encoding="utf-8")
        _ = (dst_dir / "zzz.py").write_text("z = 1\n", encoding="utf-8")
        unreadable.chmod(0o000)

        try:
            result = _run_script_expecting_failure(
                src_template_dir=template_dir,
                dst_dir=dst_dir,
                template_src="https://github.com/org/base-template",
            )
        finally:
            unreadable.chmod(0o644)

        assert "mmm.py" in result.stderr
        for name in ("aaa.py", "zzz.py"):
            assert (dst_dir / name).read_text(encoding="utf-8").startswith("# ============== WARNING")
        entry = _read_manifest(dst_dir)["templates"][0]
        assert entry["managed_files"] == ["aaa.py", "mmm.py", "zzz.py"]


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
        # Two templates applied to one repo, each managing its own files. Neither run knows about the
        # other, so each must leave the other's entry alone.
        base_template = tmp_path / "base_template"
        base_template.mkdir()
        (base_template / "a.txt").touch()
        child_template = tmp_path / "child_template"
        child_template.mkdir()
        (child_template / "b.txt").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "a.txt").write_text("content", encoding="utf-8")
        _ = (dst_dir / "b.txt").write_text("content", encoding="utf-8")

        _ = _run_script(
            src_template_dir=base_template,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )
        _ = _run_script(
            src_template_dir=child_template,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        srcs = {t["src"]: t for t in _read_manifest(dst_dir)["templates"]}
        assert srcs["https://github.com/org/base-template"]["managed_files"] == ["a.txt"]
        assert srcs["https://github.com/org/child-template"]["managed_files"] == ["b.txt"]

    def test_manifest_child_update_does_not_overwrite_base(self, tmp_path: Path) -> None:
        expected_num_manifests_in_project = 2
        base_template = tmp_path / "base_template"
        base_template.mkdir()
        (base_template / "a.txt").touch()
        child_template = tmp_path / "child_template"
        child_template.mkdir()
        (child_template / "b.txt").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "a.txt").write_text("content", encoding="utf-8")
        _ = (dst_dir / "b.txt").write_text("content", encoding="utf-8")

        _ = _run_script(
            src_template_dir=base_template,
            dst_dir=dst_dir,
            template_src="https://github.com/org/base-template",
        )
        for _ in range(2):
            _ = _run_script(
                src_template_dir=child_template,
                dst_dir=dst_dir,
                template_src="https://github.com/org/child-template",
            )

        manifest = _read_manifest(dst_dir)
        assert len(manifest["templates"]) == expected_num_manifests_in_project
        base = next(t for t in manifest["templates"] if "base" in t["src"])
        assert base["managed_files"] == ["a.txt"]

    def test_manifest_entries_are_ordered_by_src(self, tmp_path: Path) -> None:
        # Entry order used to follow whichever src happened to own the alphabetically first managed
        # file, so a change of ownership reordered the whole array and produced a huge diff.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "zzz.txt").touch()
        (template_dir / "aaa.txt").touch()

        _ = (tmp_path / ".copier-managed-files.json").write_text(
            json.dumps(
                {
                    "templates": [
                        {"src": "https://github.com/org/zzz-template", "managed_files": ["aaa.txt"]},
                    ]
                }
            ),
            encoding="utf-8",
        )

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "aaa.txt").write_text("content", encoding="utf-8")
        _ = (dst_dir / "zzz.txt").write_text("content", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/aaa-template",
        )

        srcs = [t["src"] for t in _read_manifest(dst_dir)["templates"]]
        assert srcs == sorted(srcs)


class TestManifestPruning:
    """The current run is authoritative for every path it claims."""

    def test_path_claimed_by_this_run_is_removed_from_another_entry(self, tmp_path: Path) -> None:
        # Reproduces the duplicate: the ancestor manifest stops claiming a file, this run picks it up,
        # and the old entry was never pruned, so the file was listed under two srcs at once.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "shared.py").touch()
        (template_dir / "own.py").touch()

        ancestor_manifest = tmp_path / ".copier-managed-files.json"
        _ = ancestor_manifest.write_text(
            json.dumps(
                {
                    "templates": [
                        {"src": "https://github.com/org/base-template", "managed_files": ["template/shared.py"]}
                    ]
                }
            ),
            encoding="utf-8",
        )

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "shared.py").write_text("x = 1\n", encoding="utf-8")
        _ = (dst_dir / "own.py").write_text("y = 2\n", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )
        srcs = {t["src"]: t for t in _read_manifest(dst_dir)["templates"]}
        assert srcs["https://github.com/org/base-template"]["managed_files"] == ["shared.py"]

        # The ancestor template hands shared.py over to the child.
        _ = ancestor_manifest.write_text(
            json.dumps({"templates": [{"src": "https://github.com/org/base-template", "managed_files": []}]}),
            encoding="utf-8",
        )
        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        manifest = _read_manifest(dst_dir)
        appearances = [t["src"] for t in manifest["templates"] if "shared.py" in t["managed_files"]]
        assert appearances == ["https://github.com/org/child-template"]

    def test_entry_left_with_no_files_is_dropped(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "shared.py").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "shared.py").write_text("x = 1\n", encoding="utf-8")
        config_dir = dst_dir / ".config"
        config_dir.mkdir()
        _ = (config_dir / ".copier-managed-files.json").write_text(
            json.dumps(
                {"templates": [{"src": "https://github.com/org/retired-template", "managed_files": ["shared.py"]}]}
            ),
            encoding="utf-8",
        )

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        srcs = [t["src"] for t in _read_manifest(dst_dir)["templates"]]
        assert srcs == ["https://github.com/org/child-template"]

    def test_entry_for_an_unrelated_template_survives_intact(self, tmp_path: Path) -> None:
        # Pruning must only take paths this run actually claimed, or a repo that layers two unrelated
        # templates would lose whichever one did not run last.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "own.py").touch()

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "own.py").write_text("y = 2\n", encoding="utf-8")
        config_dir = dst_dir / ".config"
        config_dir.mkdir()
        _ = (config_dir / ".copier-managed-files.json").write_text(
            json.dumps(
                {
                    "templates": [
                        {
                            "src": "https://github.com/org/other-template",
                            "parent_src": "https://github.com/org/other-parent",
                            "managed_files": ["unrelated.py", "also-unrelated.py"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        srcs = {t["src"]: t for t in _read_manifest(dst_dir)["templates"]}
        other = srcs["https://github.com/org/other-template"]
        assert other["managed_files"] == ["unrelated.py", "also-unrelated.py"]
        assert other.get("parent_src") == "https://github.com/org/other-parent"

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
        # The child template's own manifest lists base-template as managing "template/shared.py",
        # i.e. a file inside the child's template directory, which is what gets handed down.
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
                        {"src": "https://github.com/org/base-template", "managed_files": ["template/shared.py"]},
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

    def test_ancestor_repo_root_file_does_not_claim_a_colliding_grandchild_file(self, tmp_path: Path) -> None:
        # An ancestor entry holds two kinds of path: files it manages in the child template repo
        # itself (its tooling -- pyproject.toml, .github/workflows/ci.yaml) and files under the
        # child's template/ directory, which are the only ones handed down to a grandchild.
        # Attribution used to match either spelling, so a grandchild file was credited to the
        # ancestor purely because a same-named file happened to exist at the child repo's root.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "handed_down.py").touch()
        (template_dir / "Taskfile.yaml").touch()

        _ = (tmp_path / ".copier-managed-files.json").write_text(
            json.dumps(
                {
                    "templates": [
                        {
                            "src": "https://github.com/org/base-template",
                            "managed_files": ["Taskfile.yaml", "template/handed_down.py"],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "handed_down.py").write_text("x = 1\n", encoding="utf-8")
        _ = (dst_dir / "Taskfile.yaml").write_text("version: '3'\n", encoding="utf-8")

        _ = _run_script(
            src_template_dir=template_dir,
            dst_dir=dst_dir,
            template_src="https://github.com/org/child-template",
        )

        srcs = {t["src"]: t for t in _read_manifest(dst_dir)["templates"]}
        assert srcs["https://github.com/org/base-template"]["managed_files"] == ["handed_down.py"]
        assert srcs["https://github.com/org/child-template"]["managed_files"] == ["Taskfile.yaml"]
        # The header has to agree with the manifest, or the two disagree about who owns the file.
        assert "https://github.com/org/child-template" in (dst_dir / "Taskfile.yaml").read_text(encoding="utf-8")

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


_BASE_SRC = "https://github.com/org/base-template"
_CHILD_SRC = "https://github.com/org/child-template"


class TestChainStabilityAcrossTemplateVersions:
    """The three reported symptoms, exercised together over a base -> child -> grandchild chain.

    Each of the three had its own root cause, but they only show up in combination: a repo two levels
    down from the base template, updated more than once. These tests drive the real filename shapes
    the templates use, including the raw-escaped conditional name and the literal trailing .jinja that
    base hands to a child.
    """

    def _build_base_template(self, base_tmpl: Path, *, extra_grandchild_file: str | None = None) -> None:
        child_level = base_tmpl / "template"
        grandchild_level = child_level / "template"
        (grandchild_level / ".github").mkdir(parents=True, exist_ok=True)
        # Child-level: base's own tooling for the child template repo. Never handed down.
        (child_level / "pyproject.toml.jinja-base").touch()
        (child_level / "Taskfile.yaml").touch()
        # Grandchild-level: handed down to projects. The trailing .jinja is literal here.
        (grandchild_level / "Taskfile.yaml.jinja").touch()
        (grandchild_level / "shared.py").touch()
        (grandchild_level / "{% raw %}{% if is_open_source %}LICENSE{% endif %}{% endraw %}").touch()
        if extra_grandchild_file is not None:
            (grandchild_level / extra_grandchild_file).touch()

    def _build_child_repo(self, child_repo: Path, *, extra_template_file: str | None = None) -> None:
        template_dir = child_repo / "template"
        (template_dir / ".github").mkdir(parents=True, exist_ok=True)
        # Rendered from base's child-level template.
        _ = (child_repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        _ = (child_repo / "Taskfile.yaml").write_text("version: '3'\n", encoding="utf-8")
        # Rendered from base's grandchild-level template: names survive for the child to render later.
        _ = (template_dir / "Taskfile.yaml.jinja").write_text("version: '3'\n", encoding="utf-8")
        _ = (template_dir / "shared.py").write_text("shared = 1\n", encoding="utf-8")
        _ = (template_dir / "{% if is_open_source %}LICENSE{% endif %}").write_text("Apache\n", encoding="utf-8")
        # The child template's own contribution.
        _ = (template_dir / "app.py").write_text("app = 1\n", encoding="utf-8")
        if extra_template_file is not None:
            _ = (template_dir / extra_template_file).write_text("added = 1\n", encoding="utf-8")

    def _build_grandchild_repo(self, repo: Path, *, extra_file: str | None = None) -> None:
        repo.mkdir(parents=True, exist_ok=True)
        _ = (repo / "Taskfile.yaml").write_text("version: '3'\n", encoding="utf-8")
        _ = (repo / "shared.py").write_text("shared = 1\n", encoding="utf-8")
        _ = (repo / "LICENSE").write_text("Apache\n", encoding="utf-8")
        _ = (repo / "app.py").write_text("app = 1\n", encoding="utf-8")
        if extra_file is not None:
            _ = (repo / extra_file).write_text("added = 1\n", encoding="utf-8")

    def _stamp_chain(self, base_tmpl: Path, child_repo: Path, grandchild: Path) -> None:
        _ = _run_script(
            src_template_dir=base_tmpl / "template",
            dst_dir=child_repo,
            template_src=_BASE_SRC,
            templates_suffix=".jinja-base",
        )
        _ = _run_script(
            src_template_dir=child_repo / "template",
            dst_dir=grandchild,
            template_src=_CHILD_SRC,
            templates_suffix=".jinja",
        )

    def test_grandchild_attribution_follows_the_real_owner(self, tmp_path: Path) -> None:
        base_tmpl = tmp_path / "base_tmpl"
        child_repo = tmp_path / "child_repo"
        grandchild = tmp_path / "grandchild"
        self._build_base_template(base_tmpl)
        self._build_child_repo(child_repo)
        self._build_grandchild_repo(grandchild)

        self._stamp_chain(base_tmpl, child_repo, grandchild)

        srcs = {t["src"]: t for t in _read_manifest(grandchild)["templates"]}
        # Taskfile.yaml is handed down by base, and must not be stolen by the child template merely
        # because the child repo also has a root Taskfile.yaml of its own.
        assert srcs[_BASE_SRC]["managed_files"] == ["LICENSE", "Taskfile.yaml", "shared.py"]
        assert srcs[_CHILD_SRC]["managed_files"] == ["app.py"]

    def test_no_file_is_claimed_by_two_templates(self, tmp_path: Path) -> None:
        base_tmpl = tmp_path / "base_tmpl"
        child_repo = tmp_path / "child_repo"
        grandchild = tmp_path / "grandchild"
        self._build_base_template(base_tmpl)
        self._build_child_repo(child_repo)
        self._build_grandchild_repo(grandchild)

        self._stamp_chain(base_tmpl, child_repo, grandchild)

        entries = _read_manifest(grandchild)["templates"]
        claimed = [path for t in entries for path in t["managed_files"]]
        assert sorted(claimed) == sorted(set(claimed)), "a file is listed under more than one template"

    def test_every_managed_file_carries_exactly_one_marker(self, tmp_path: Path) -> None:
        base_tmpl = tmp_path / "base_tmpl"
        child_repo = tmp_path / "child_repo"
        grandchild = tmp_path / "grandchild"
        self._build_base_template(base_tmpl)
        self._build_child_repo(child_repo)
        self._build_grandchild_repo(grandchild)

        self._stamp_chain(base_tmpl, child_repo, grandchild)

        for t in _read_manifest(grandchild)["templates"]:
            for rel in t["managed_files"]:
                content = (grandchild / rel).read_text(encoding="utf-8")
                assert content.count("============== WARNING") == 1, f"{rel} has the wrong marker count"
                # The marker has to name the same template the manifest does, or the file and the
                # manifest disagree about who owns it.
                assert t["src"] in content, f"{rel} marker does not name {t['src']}"

    def test_second_update_at_the_same_version_changes_nothing(self, tmp_path: Path) -> None:
        base_tmpl = tmp_path / "base_tmpl"
        child_repo = tmp_path / "child_repo"
        grandchild = tmp_path / "grandchild"
        self._build_base_template(base_tmpl)
        self._build_child_repo(child_repo)
        self._build_grandchild_repo(grandchild)

        self._stamp_chain(base_tmpl, child_repo, grandchild)
        before = {p: p.read_bytes() for p in sorted(grandchild.rglob("*")) if p.is_file()}
        self._stamp_chain(base_tmpl, child_repo, grandchild)
        after = {p: p.read_bytes() for p in sorted(grandchild.rglob("*")) if p.is_file()}

        assert after == before

    def test_template_version_bump_only_adds_the_new_file(self, tmp_path: Path) -> None:
        # The reported symptom was files moving between manifest entries, and markers disappearing,
        # on an update that should only have added something.
        base_tmpl = tmp_path / "base_tmpl"
        child_repo = tmp_path / "child_repo"
        grandchild = tmp_path / "grandchild"
        self._build_base_template(base_tmpl)
        self._build_child_repo(child_repo)
        self._build_grandchild_repo(grandchild)
        self._stamp_chain(base_tmpl, child_repo, grandchild)

        manifest_before = _read_manifest(grandchild)
        markers_before = {
            rel: (grandchild / rel).read_text(encoding="utf-8")
            for t in manifest_before["templates"]
            for rel in t["managed_files"]
        }

        # Base ships a new grandchild-level file, which flows through the child template.
        self._build_base_template(base_tmpl, extra_grandchild_file="added.py")
        self._build_child_repo(child_repo, extra_template_file="added.py")
        self._build_grandchild_repo(grandchild, extra_file="added.py")
        self._stamp_chain(base_tmpl, child_repo, grandchild)

        srcs = {t["src"]: t for t in _read_manifest(grandchild)["templates"]}
        assert srcs[_BASE_SRC]["managed_files"] == ["LICENSE", "Taskfile.yaml", "added.py", "shared.py"]
        assert srcs[_CHILD_SRC]["managed_files"] == ["app.py"]
        # Nothing that was already stamped may have changed.
        for rel, content in markers_before.items():
            assert (grandchild / rel).read_text(encoding="utf-8") == content, f"{rel} changed unexpectedly"
