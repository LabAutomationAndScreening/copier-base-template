import subprocess
from pathlib import Path

import yaml
from faker import Faker

from .helpers import SCRIPT_PATH_ROOT
from .helpers import run_copier_task

_SCRIPT_PATH = SCRIPT_PATH_ROOT / "normalize_pnpm_minimum_release_age_exclude.py"


class TestNormalizePnpmMinimumReleaseAgeExcludeViaSubprocess:
    def _run_script(self, *, target_dir: Path) -> subprocess.CompletedProcess[str]:
        return run_copier_task(_SCRIPT_PATH, "--target-dir", str(target_dir))

    def test_When_target_dir_has_no_workspace_file__Then_exits_0_and_reports_skipping(self, tmp_path: Path) -> None:
        result = self._run_script(target_dir=tmp_path)

        assert result.returncode == 0
        assert "not found" in result.stdout
        assert not (tmp_path / "pnpm-workspace.yaml").exists()

    def test_When_value_is_a_comma_delimited_string__Then_rewritten_as_a_list(
        self, tmp_path: Path, faker: Faker
    ) -> None:
        scoped = f"@{faker.word()}/*"
        plain = faker.word()
        workspace = tmp_path / "pnpm-workspace.yaml"
        _ = workspace.write_text(
            f"packages:\n  - 'frontend'\nminimumReleaseAgeExclude: '{scoped},{plain}'\n", encoding="utf-8"
        )

        result = self._run_script(target_dir=tmp_path)

        parsed = yaml.safe_load(workspace.read_text(encoding="utf-8"))

        assert result.returncode == 0
        assert parsed["minimumReleaseAgeExclude"] == [scoped, plain]
        assert parsed["packages"] == ["frontend"]

    def test_When_manifest_has_comments__Then_only_the_setting_line_changes(self, tmp_path: Path, faker: Faker) -> None:
        pattern = f"@{faker.word()}/*"
        leading_comment = f"# {faker.sentence()}"
        workspace = tmp_path / "pnpm-workspace.yaml"
        _ = workspace.write_text(
            f"{leading_comment}\npackages:\n  - 'frontend'\nminimumReleaseAgeExclude: '{pattern}'\nallowBuilds:\n  esbuild: false\n",
            encoding="utf-8",
        )

        result = self._run_script(target_dir=tmp_path)

        contents = workspace.read_text(encoding="utf-8")
        parsed = yaml.safe_load(contents)

        assert result.returncode == 0
        assert contents.startswith(f"{leading_comment}\n")
        assert "allowBuilds:\n  esbuild: false\n" in contents
        assert parsed["minimumReleaseAgeExclude"] == [pattern]

    def test_When_value_carries_a_trailing_comment__Then_comment_is_preserved(
        self, tmp_path: Path, faker: Faker
    ) -> None:
        pattern = f"@{faker.word()}/*"
        comment = f"# {faker.sentence()}"
        workspace = tmp_path / "pnpm-workspace.yaml"
        _ = workspace.write_text(f"minimumReleaseAgeExclude: '{pattern}' {comment}\n", encoding="utf-8")

        result = self._run_script(target_dir=tmp_path)

        contents = workspace.read_text(encoding="utf-8")

        assert result.returncode == 0
        assert contents == f"minimumReleaseAgeExclude: {comment}\n  - '{pattern}'\n"
        assert yaml.safe_load(contents)["minimumReleaseAgeExclude"] == [pattern]

    def test_When_value_is_already_a_list__Then_file_unchanged(self, tmp_path: Path, faker: Faker) -> None:
        pattern = f"@{faker.word()}/*"
        workspace = tmp_path / "pnpm-workspace.yaml"
        original = f"minimumReleaseAgeExclude:\n  - '{pattern}'\n"
        _ = workspace.write_text(original, encoding="utf-8")

        result = self._run_script(target_dir=tmp_path)

        assert result.returncode == 0
        assert "already a list" in result.stdout
        assert workspace.read_text(encoding="utf-8") == original

    def test_When_value_is_an_empty_string__Then_the_setting_is_removed(self, tmp_path: Path) -> None:
        workspace = tmp_path / "pnpm-workspace.yaml"
        _ = workspace.write_text("packages:\n  - 'frontend'\nminimumReleaseAgeExclude: ''\n", encoding="utf-8")
        assert "minimumReleaseAgeExclude" in workspace.read_text(encoding="utf-8")

        result = self._run_script(target_dir=tmp_path)

        contents = workspace.read_text(encoding="utf-8")

        assert result.returncode == 0
        assert "Removed" in result.stdout
        assert "minimumReleaseAgeExclude" not in contents
        assert yaml.safe_load(contents)["packages"] == ["frontend"]

    def test_When_setting_is_absent__Then_file_unchanged(self, tmp_path: Path) -> None:
        workspace = tmp_path / "pnpm-workspace.yaml"
        original = "packages:\n  - 'frontend'\n"
        _ = workspace.write_text(original, encoding="utf-8")

        result = self._run_script(target_dir=tmp_path)

        assert result.returncode == 0
        assert "not set" in result.stdout
        assert workspace.read_text(encoding="utf-8") == original
