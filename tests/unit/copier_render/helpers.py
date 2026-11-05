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

The copy enumerates the files git knows about rather than walking the tree, so what a render sees is
what a checkout contains: an ignored virtualenv or cache never costs copy time, and a developer's
untracked local files (editor state, shell rc files an environment drops in the root) neither reach
the render nor break the copy by being unreadable.
"""

import shutil
import subprocess
from pathlib import Path

import copier
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COPIER_DATA_DIR = PROJECT_ROOT / "tests" / "copier_data"


def _copy_checkout(destination: Path) -> None:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],  # noqa: S607 -- git resolves from PATH by design; the devcontainer and CI both provide it
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    for relative_path in listed.stdout.split("\0"):
        if relative_path == "":
            continue
        source_path = PROJECT_ROOT / relative_path
        # A path staged for deletion is still listed while it is gone from the working tree.
        if not source_path.is_symlink() and not source_path.exists():
            continue
        target_path = destination / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_symlink():
            target_path.symlink_to(source_path.readlink())
            continue
        _ = shutil.copy2(source_path, target_path)


def render_child_template(tmp_path: Path, *, data_file: str = "data1.yaml", **overrides: object) -> Path:
    """Instantiate this template from the current working tree and return the rendered directory."""
    source = tmp_path / "template-source"
    rendered = tmp_path / "rendered"
    _copy_checkout(source)
    data: dict[str, object] = yaml.safe_load((COPIER_DATA_DIR / data_file).read_text(encoding="utf-8"))
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
