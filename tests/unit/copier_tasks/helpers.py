import os
import subprocess
import sys
from pathlib import Path

import coverage

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_new_script_path_root = PROJECT_ROOT / "src" / "copier_base_template" / "copier_tasks"
# in child templates, the scripts are sometimes symlinked directly into `src/copier_tasks`.  # TODO: consider just moving these task scripts into copier_template_resources in the child template and only having the tests be in the base template
SCRIPT_PATH_ROOT = _new_script_path_root if _new_script_path_root.exists() else PROJECT_ROOT / "src" / "copier_tasks"


def _coverage_command_prefix() -> list[str]:
    """Return the prefix that makes the child process record coverage, or an empty list.

    The task scripts only ever run as subprocesses, so pytest-cov sees nothing of them and reports
    every one at 0% -- which is why the repo's CI passes `--no-cov` wholesale. pytest-cov has no
    subprocess hook installed in this environment, so the child is launched under `coverage run`
    explicitly instead. `--parallel-mode` writes a per-process data file that the parent's combine
    step picks up, so concurrent tests cannot clobber each other's data.
    """
    active = coverage.Coverage.current()
    if active is None:
        return []
    config_file = active.config.config_file
    if config_file is None:
        return [sys.executable, "-m", "coverage", "run", "--parallel-mode"]
    return [sys.executable, "-m", "coverage", "run", "--parallel-mode", f"--rcfile={config_file}"]


def _coverage_environment(base: dict[str, str] | None) -> dict[str, str] | None:
    """Point the child's data file at the parent's, so `coverage combine` finds it."""
    active = coverage.Coverage.current()
    if active is None:
        return base
    environment = dict(os.environ) if base is None else dict(base)
    environment["COVERAGE_FILE"] = str(Path(active.config.data_file).resolve())
    return environment


def run_copier_task(
    script_path: Path,
    *args: str,
    env: dict[str, str] | None = None,
    # bounded so a runaway traversal fails the test rather than wedging the runner
    timeout: float = 60,
) -> subprocess.CompletedProcess[str]:
    prefix = _coverage_command_prefix()
    if len(prefix) == 0:
        command = [sys.executable, str(script_path), *args]
    else:
        command = [*prefix, str(script_path), *args]
    return subprocess.run(  # noqa: S603 -- these are our own scripts
        command,
        check=False,
        capture_output=True,
        text=True,
        env=_coverage_environment(env),
        timeout=timeout,
    )
