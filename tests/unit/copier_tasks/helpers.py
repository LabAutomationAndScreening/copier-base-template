import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH_ROOT = PROJECT_ROOT / "src" / "copier_base_template" / "copier_tasks"


def run_copier_task(
    script_path: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- these are our own scripts
        [sys.executable, str(script_path), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
