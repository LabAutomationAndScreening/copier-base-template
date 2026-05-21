import subprocess
import sys
import uuid
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _PROJECT_ROOT / "src" / "copier_tasks" / "ensure_pnpm_minimum_release_age_exclude.py"


def _pkg() -> str:
    return uuid.uuid4().hex[:8]


def _scoped_pkg() -> str:
    return f"@{uuid.uuid4().hex[:4]}/{uuid.uuid4().hex[:6]}"


class TestEnsurePnpmMinimumReleaseAgeExcludeViaSubprocess:
    def _run_script(self, *, patterns: str, target_file: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 -- this is our own script
            [
                sys.executable,
                str(_SCRIPT_PATH),
                "--patterns",
                patterns,
                "--target-file",
                str(target_file),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_When_target_file_does_not_exist__Then_exits_0_and_reports_skipping(self, tmp_path: Path) -> None:
        pkg = _pkg()
        nonexistent = tmp_path / "pnpm-workspace.yaml"

        result = self._run_script(patterns=pkg, target_file=nonexistent)

        assert result.returncode == 0
        assert "not found" in result.stdout

    def test_When_section_present_with_missing_pattern__Then_inserts_missing_entry(self, tmp_path: Path) -> None:
        expected_num_excludes = 2
        existing = _pkg()
        new = _pkg()
        workspace = tmp_path / "pnpm-workspace.yaml"
        _ = workspace.write_text(f'minimumReleaseAgeExclude:\n  - "{existing}"\n', encoding="utf-8")

        result = self._run_script(patterns=f"{existing}, {new}", target_file=workspace)

        raw = workspace.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw)
        assert result.returncode == 0
        assert len(parsed["minimumReleaseAgeExclude"]) == expected_num_excludes
        assert existing in parsed["minimumReleaseAgeExclude"]
        assert new in parsed["minimumReleaseAgeExclude"]
        assert f'  - "{new}"' in raw

    def test_When_all_patterns_already_present__Then_file_unchanged_and_no_output(self, tmp_path: Path) -> None:
        pkg_a = _pkg()
        scoped = _scoped_pkg()
        workspace = tmp_path / "pnpm-workspace.yaml"
        original = f'minimumReleaseAgeExclude:\n  - "{pkg_a}"\n  - "{scoped}"\n'
        _ = workspace.write_text(original, encoding="utf-8")

        result = self._run_script(patterns=f"{pkg_a}, {scoped}", target_file=workspace)

        assert result.returncode == 0
        assert workspace.read_text(encoding="utf-8") == original
        assert result.stdout == ""

    def test_When_pattern_present_unquoted__Then_no_duplicate_added(self, tmp_path: Path) -> None:
        pkg = _pkg()
        workspace = tmp_path / "pnpm-workspace.yaml"
        original = f"minimumReleaseAgeExclude:\n  - {pkg}\n"
        _ = workspace.write_text(original, encoding="utf-8")

        result = self._run_script(patterns=pkg, target_file=workspace)

        assert result.returncode == 0
        assert workspace.read_text(encoding="utf-8") == original
        assert result.stdout == ""

    def test_When_section_absent__Then_appends_block_with_double_quoted_entries(self, tmp_path: Path) -> None:
        scoped = _scoped_pkg()
        plain = _pkg()
        workspace = tmp_path / "pnpm-workspace.yaml"
        _ = workspace.write_text("packages:\n  - frontend\n", encoding="utf-8")

        result = self._run_script(patterns=f"{scoped}, {plain}", target_file=workspace)

        raw = workspace.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw)
        assert result.returncode == 0
        assert parsed["minimumReleaseAgeExclude"] == [scoped, plain]
        assert parsed["packages"] == ["frontend"]
        assert f'  - "{scoped}"' in raw
        assert f'  - "{plain}"' in raw
