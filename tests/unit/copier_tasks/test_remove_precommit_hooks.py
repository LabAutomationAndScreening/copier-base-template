import shutil
import subprocess
import sys
from pathlib import Path


class RemovePrecommitHooksViaSubprocess:
    def test_When_run_with_matching_hook__Then_hook_removed(self, tmp_path: Path) -> None:
        project_root = Path(__file__).resolve().parents[3]
        source_config = project_root / ".pre-commit-config.yaml"
        config_path = tmp_path / ".pre-commit-config.yaml"
        _ = shutil.copyfile(source_config, config_path)
        original = config_path.read_text(encoding="utf-8")
        assert "id: check-json5" in original
        assert "id: trailing-whitespace" in original

        script_path = project_root / "src" / "copier_tasks" / "remove_precommit_hooks.py"
        result = subprocess.run(  # noqa: S603 # this is our own script
            [
                sys.executable,
                str(script_path),
                "--hook-id-regex",
                r"^\s*-\s+id:\s+check-json5\s*$",
                "--target-file",
                str(config_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "Removed 1 matching hook" in result.stdout

        updated = config_path.read_text(encoding="utf-8")
        assert "id: check-json5" not in updated
        assert "id: trailing-whitespace" in updated
