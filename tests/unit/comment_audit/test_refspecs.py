from pathlib import Path

import pytest

from .helpers import commit_file
from .helpers import git
from .helpers import make_repo
from .helpers import run_gate

_EXIT_ALLOWED = 0


def _repo_with_commented_side_branch(tmp_path: Path, *, mode: str = "block") -> Path:
    """Leave main checked out and clean, with an unpushed `other` branch that adds a comment."""
    repo = make_repo(tmp_path, mode=mode)
    _ = git(repo, "switch", "-c", "other")
    _ = commit_file(repo, "mod.py", "# restates the code\nx = 1\n")
    _ = git(repo, "switch", "main")
    return repo


class TestPushShapes:
    @pytest.mark.parametrize(
        "command",
        [
            "git push",
            "git push origin",
            "git push origin main",
            "git push origin HEAD",
            "git push -u origin main",
            "git push --force-with-lease origin main",
            "git push origin other",
            "git push origin other:main",
            "git push origin HEAD:refs/heads/elsewhere",
            "git push --all origin",
            "git push -o ci.skip origin main",
            "git push origin :stale",
            "git push --delete origin stale",
        ],
    )
    def test_When_head_adds_no_comments__Then_any_push_shape_allowed(self, tmp_path: Path, command: str) -> None:
        repo = _repo_with_commented_side_branch(tmp_path)

        result = run_gate(command, cwd=repo, project_dir=repo)

        assert result.returncode == _EXIT_ALLOWED, result.stderr
