import subprocess
import sys
from pathlib import Path

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
