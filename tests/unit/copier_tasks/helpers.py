import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_new_script_path_root = PROJECT_ROOT / "src" / "copier_base_template" / "copier_tasks"
# in child templates, the scripts are sometimes symlinked directly into `src/copier_tasks`.  # TODO: consider just moving these task scripts into copier_template_resources in the child template and only having the tests be in the base template
SCRIPT_PATH_ROOT = _new_script_path_root if _new_script_path_root.exists() else PROJECT_ROOT / "src" / "copier_tasks"


def run_copier_task(
    script_path: Path,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: float = 60,
) -> subprocess.CompletedProcess[str]:
    """Run a copier task script. The timeout turns a runaway traversal into a failure, not a wedged runner."""
    return subprocess.run(  # noqa: S603 -- these are our own scripts
        [sys.executable, str(script_path), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
