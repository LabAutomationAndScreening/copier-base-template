import subprocess
import sys
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _PROJECT_ROOT / "src" / "copier_tasks" / "ensure_pnpm_minimum_release_age_exclude.py"


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
        nonexistent = tmp_path / "pnpm-workspace.yaml"

        result = self._run_script(patterns="some-pkg", target_file=nonexistent)

        assert result.returncode == 0
        assert "not found" in result.stdout

    def test_When_section_absent__Then_appends_block_with_double_quoted_entries(self, tmp_path: Path) -> None:
        workspace = tmp_path / "pnpm-workspace.yaml"
        _ = workspace.write_text("packages:\n  - frontend\n", encoding="utf-8")

        result = self._run_script(patterns="@acme/*, some-lib", target_file=workspace)

        assert result.returncode == 0
        parsed = yaml.safe_load(workspace.read_text(encoding="utf-8"))
        assert parsed["minimumReleaseAgeExclude"] == ["@acme/*", "some-lib"]
        assert parsed["packages"] == ["frontend"]
