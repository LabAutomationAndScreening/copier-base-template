"""Renders this template into a throwaway directory so generated file contents can be asserted.

The sibling ``copier_validators`` style of harness passes ``pretend=True``, which is enough to fire
answer validation but discards every rendered byte: copier computes the content, hands it to
``_render_allowed``, and drops it on return (see ``Worker._render_file``). Nothing on the returned
``Worker`` retains it, so asserting generated content requires a real render to disk.

The source is a git-free copy of the working tree rather than the repository itself. Pointing copier
at the repository would make it clone, and for a dirty tree it reconstructs the source by running
`git add -A` against the real work tree from inside that clone (`copier._vcs.clone`). That leaves
`template/{% if install_claude_cli %}.claude{% endif %}` dangling here and the render dies on
`FileNotFoundError`. A clean tree skips that path entirely, so the breakage only shows up when there
are uncommitted edits -- i.e. exactly when a test is being driven red-green.
"""

import shutil
from pathlib import Path
from typing import Any

import copier
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COPIER_DATA_DIR = PROJECT_ROOT / "tests" / "copier_data"
# Copying the tree costs ~0.1s; these are the directories that would make it cost orders more.
_IGNORED_SOURCE_DIRS = shutil.ignore_patterns(
    ".git",
    ".venv",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    "coverage-report-pytest",
    "tmp",
)


def render_child_template(tmp_path: Path, *, data_file: str = "data1.yaml", **overrides: Any) -> Path:
    """Instantiate this template from the current working tree and return the rendered directory."""
    source = tmp_path / "template-source"
    rendered = tmp_path / "rendered"
    shutil.copytree(PROJECT_ROOT, source, symlinks=True, ignore=_IGNORED_SOURCE_DIRS)
    data: dict[str, Any] = yaml.safe_load((COPIER_DATA_DIR / data_file).read_text(encoding="utf-8"))
    data.update(overrides)
    _ = copier.run_copy(
        str(source),
        str(rendered),
        data=data,
        defaults=True,
        unsafe=True,
        quiet=True,
    )
    return rendered
