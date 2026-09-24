from pathlib import Path

import pytest

from .helpers import commit_file
from .helpers import git
from .helpers import make_repo
from .helpers import run_gate

_EXIT_ALLOWED = 0
_EXIT_BLOCKED = 2


def _repo_with_commented_side_branch(tmp_path: Path, *, mode: str = "block") -> Path:
    """Leave main checked out and clean, with an unpushed `other` branch that adds a comment."""
    repo = make_repo(tmp_path, mode=mode)
    _ = git(repo, "switch", "-c", "other")
    _ = commit_file(repo, "mod.py", "# restates the code\nx = 1\n")
    _ = git(repo, "switch", "main")
    return repo


class TestPushOutsideAllowlist:
    @pytest.mark.parametrize(
        "command",
        [
            "git push origin other:main",
            "git push origin other",
            "git push origin +other:main",
            "git push --all origin",
            "git push --mirror origin",
            "git push origin 'refs/heads/*:refs/heads/*'",
            "git push origin does-not-exist",
            "git push origin HEAD:refs/heads/elsewhere",
            "git push -o ci.skip origin main",
            "git push origin :stale",
            "git push --delete origin stale",
            "git push origin main other",
        ],
    )
    def test_When_block_mode_and_push_is_not_the_current_branch__Then_push_blocked(
        self, tmp_path: Path, command: str
    ) -> None:
        repo = _repo_with_commented_side_branch(tmp_path)

        result = run_gate(command, cwd=repo, project_dir=repo)

        assert result.returncode == _EXIT_BLOCKED

    def test_When_warn_mode_and_push_is_not_the_current_branch__Then_allowed_with_warning(self, tmp_path: Path) -> None:
        repo = _repo_with_commented_side_branch(tmp_path, mode="warn")

        result = run_gate("git push origin other", cwd=repo, project_dir=repo)

        assert result.returncode == _EXIT_ALLOWED
        assert "comment-gate" in result.stdout


class TestPushOfCurrentBranch:
    @pytest.mark.parametrize(
        "command",
        [
            "git push",
            "git push origin",
            "git push origin main",
            "git push origin HEAD",
            "git push -u origin main",
            "git push --set-upstream origin main",
            "git push --force origin main",
            "git push --force-with-lease origin main",
            "git push --force-with-lease=main:abc123 origin main",
            "git push --no-verify origin main",
        ],
    )
    def test_When_push_sends_only_the_current_branch__Then_audited_as_head(self, tmp_path: Path, command: str) -> None:
        repo = _repo_with_commented_side_branch(tmp_path)

        result = run_gate(command, cwd=repo, project_dir=repo)

        assert result.returncode == _EXIT_ALLOWED, result.stderr
