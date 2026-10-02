from pathlib import Path

from .helpers import commit_file
from .helpers import git
from .helpers import make_repo
from .helpers import run_gate
from .helpers import run_list

_EXIT_BLOCKED = 2


class TestDescendantRemoteRefs:
    def test_When_manual_list_and_stacked_branch_at_head__Then_base_is_fork_point(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        fork_point = git(repo, "rev-parse", "HEAD")
        _ = git(repo, "switch", "-c", "feature")
        _ = commit_file(repo, "mod.py", "# restates the code\nx = 1\n")
        _ = git(repo, "push", "-u", "origin", "feature")
        _ = git(repo, "push", "origin", "feature:stacked")

        listing = run_list(repo)

        assert listing["base"] == fork_point
        assert [c["file"] for c in listing["comments"]] == ["mod.py"]

    def test_When_gate_has_no_upstream_and_remote_ref_at_head__Then_push_blocked(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        _ = git(repo, "switch", "-c", "feature")
        _ = commit_file(repo, "mod.py", "# restates the code\nx = 1\n")
        _ = git(repo, "push", "origin", "feature:other")

        result = run_gate("git push -u origin feature", cwd=repo, project_dir=repo)

        assert result.returncode == _EXIT_BLOCKED
        assert "mod.py" in result.stderr
