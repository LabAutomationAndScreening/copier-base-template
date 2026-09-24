from pathlib import Path

import pytest

from .helpers import commit_file
from .helpers import load_comment_audit
from .helpers import make_repo
from .helpers import run_gate

_EXIT_BLOCKED = 2

comment_audit = load_comment_audit()


class TestIsGitPush:
    @pytest.mark.parametrize(
        "command",
        [
            "git push",
            "git push origin main",
            "FOO=1 git push",
            "git -C /repo push",
            "git -C /repo -C sub push origin main",
            "git -c core.hooksPath=/dev/null push",
            "git --git-dir /repo/.git push",
            "git --git-dir=/repo/.git push",
            "git --work-tree /repo push",
            "git --no-pager push",
        ],
    )
    def test_When_git_subcommand_is_push__Then_detected(self, command: str) -> None:
        assert comment_audit.is_git_push(command)

    @pytest.mark.parametrize(
        "command",
        [
            'git commit -m "git push"',
            "git -C /push commit",
            "git log --grep push",
            "echo git push",
            "git push --help",
            "git -C /repo push -h",
        ],
    )
    def test_When_git_subcommand_is_not_push__Then_not_detected(self, command: str) -> None:
        assert not comment_audit.is_git_push(command)


class TestGateWithGlobalOptions:
    def test_When_dash_C_targets_repo_with_unaudited_comment__Then_push_blocked(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        _ = commit_file(repo, "mod.py", "# restates the code\nx = 1\n")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        result = run_gate(f"git -C {repo} push", cwd=elsewhere, project_dir=repo)

        assert result.returncode == _EXIT_BLOCKED
        assert "mod.py" in result.stderr

    def test_When_relative_dash_C_targets_repo__Then_resolved_against_payload_cwd(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        _ = commit_file(repo, "mod.py", "# restates the code\nx = 1\n")

        result = run_gate("git -C repo push", cwd=tmp_path, project_dir=repo)

        assert result.returncode == _EXIT_BLOCKED
        assert "mod.py" in result.stderr

    def test_When_git_dir_given__Then_block_mode_fails_closed(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)

        result = run_gate(f"git --git-dir {repo}/.git push", cwd=tmp_path, project_dir=repo)

        assert result.returncode == _EXIT_BLOCKED
