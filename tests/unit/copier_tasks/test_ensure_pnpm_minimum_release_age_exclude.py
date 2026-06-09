import subprocess
from pathlib import Path

import yaml
from faker import Faker

from .helpers import run_copier_task

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _PROJECT_ROOT / "src" / "copier_tasks" / "ensure_pnpm_minimum_release_age_exclude.py"


class TestEnsurePnpmMinimumReleaseAgeExcludeViaSubprocess:
    def _run_script(
        self,
        *,
        patterns: str,
        target_dir: Path,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return run_copier_task(_SCRIPT_PATH, "--patterns", patterns, "--target-dir", str(target_dir), env=env)

    def test_When_pnpm_not_on_path__Then_exits_nonzero_with_error(self, tmp_path: Path, faker: Faker) -> None:
        _ = (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - frontend\n", encoding="utf-8")

        result = self._run_script(patterns=faker.name(), target_dir=tmp_path, env={"PATH": ""})

        assert result.returncode != 0
        assert "pnpm" in result.stdout

    def test_When_target_dir_has_no_workspace_file__Then_exits_0_and_reports_skipping(
        self, tmp_path: Path, faker: Faker
    ) -> None:
        result = self._run_script(patterns=faker.name(), target_dir=tmp_path)

        assert result.returncode == 0
        assert "not found" in result.stdout
        assert not (tmp_path / "pnpm-workspace.yaml").exists()

    def test_When_workspace_has_existing_patterns__Then_new_patterns_appended(
        self, tmp_path: Path, faker: Faker
    ) -> None:
        existing = faker.name()
        new = faker.name()
        workspace = tmp_path / "pnpm-workspace.yaml"
        _ = workspace.write_text(f"minimumReleaseAgeExclude: {existing}\n", encoding="utf-8")

        result = self._run_script(patterns=new, target_dir=tmp_path)

        assert result.returncode == 0
        parsed = yaml.safe_load(workspace.read_text(encoding="utf-8"))
        assert parsed["minimumReleaseAgeExclude"] == f"{existing},{new}"

    def test_When_patterns_provided__Then_sets_value_in_workspace(self, tmp_path: Path, faker: Faker) -> None:
        scoped = f"{faker.name()}/{faker.name()}"
        plain = faker.name()
        workspace = tmp_path / "pnpm-workspace.yaml"
        _ = workspace.write_text("packages:\n  - frontend\n", encoding="utf-8")

        result = self._run_script(patterns=f"{scoped}, {plain}", target_dir=tmp_path)

        assert result.returncode == 0
        parsed = yaml.safe_load(workspace.read_text(encoding="utf-8"))
        assert parsed["minimumReleaseAgeExclude"] == f"{scoped},{plain}"
