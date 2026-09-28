import shutil
import subprocess
import tomllib
from pathlib import Path

from faker import Faker

from .helpers import PROJECT_ROOT
from .helpers import SCRIPT_PATH_ROOT
from .helpers import run_copier_task

_SCRIPT_PATH = SCRIPT_PATH_ROOT / "ignore_pyrefly_implicit_reexport.py"


class TestIgnorePyreflyImplicitReexportViaSubprocess:
    def _run_script(self, *, target_file: Path) -> subprocess.CompletedProcess[str]:
        return run_copier_task(_SCRIPT_PATH, "--target-file", str(target_file))

    def test_When_errors_table_lacks_the_setting__Then_implicit_reexport_ignored(
        self, tmp_path: Path, faker: Faker
    ) -> None:
        existing_rule = faker.slug()
        config_path = tmp_path / "pyrefly.toml"
        _ = config_path.write_text(f'preset = "all"\n\n[errors]\n{existing_rule} = "ignore"\n', encoding="utf-8")

        result = self._run_script(target_file=config_path)

        parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))

        assert result.returncode == 0
        assert f"Ignored implicit-reexport in {config_path}" in result.stdout
        assert parsed["errors"] == {existing_rule: "ignore", "implicit-reexport": "ignore"}
        assert parsed["preset"] == "all"

    def test_When_run_on_project_config__Then_only_top_level_errors_table_changes(self, tmp_path: Path) -> None:
        config_path = tmp_path / "pyrefly.toml"
        _ = shutil.copyfile(PROJECT_ROOT / ".config" / "pyrefly.toml", config_path)
        original = tomllib.loads(config_path.read_text(encoding="utf-8"))
        assert "implicit-reexport" not in original["errors"]
        assert len(original["sub-config"]) > 0

        result = self._run_script(target_file=config_path)

        updated = tomllib.loads(config_path.read_text(encoding="utf-8"))

        assert result.returncode == 0
        assert updated["errors"] == {**original["errors"], "implicit-reexport": "ignore"}
        assert updated["sub-config"] == original["sub-config"]
        assert {key: value for key, value in updated.items() if key != "errors"} == {
            key: value for key, value in original.items() if key != "errors"
        }

    def test_When_target_file_does_not_exist__Then_exits_nonzero_and_names_the_path(self, tmp_path: Path) -> None:
        config_path = tmp_path / "pyrefly.toml"

        result = self._run_script(target_file=config_path)

        assert result.returncode == 1
        assert f"{config_path} not found" in result.stdout
        assert not config_path.exists()

    def test_Given_setting_already_added__When_run_again__Then_file_unchanged(
        self, tmp_path: Path, faker: Faker
    ) -> None:
        config_path = tmp_path / "pyrefly.toml"
        _ = config_path.write_text(f'[errors]\n{faker.slug()} = "ignore"\n', encoding="utf-8")
        _ = self._run_script(target_file=config_path)
        after_first_run = config_path.read_text(encoding="utf-8")
        assert 'implicit-reexport = "ignore"' in after_first_run

        result = self._run_script(target_file=config_path)

        assert result.returncode == 0
        assert "already configured" in result.stdout
        assert config_path.read_text(encoding="utf-8") == after_first_run
