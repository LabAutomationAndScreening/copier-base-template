from pathlib import Path

from .helpers import commit_file
from .helpers import git
from .helpers import make_repo
from .helpers import run_list


class TestReportedLineNumbers:
    def test_When_added_line_starts_with_plus_plus__Then_later_comment_keeps_its_line(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        _ = commit_file(repo, "main.c", "++i;\n// why\n")

        listing = run_list(repo)

        assert [(c["file"], c["start"]) for c in listing["comments"]] == [("main.c", 2)]

    def test_When_old_last_line_had_no_newline__Then_comment_after_it_keeps_its_line(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        _ = commit_file(repo, "mod.py", "x = 1")
        _ = git(repo, "push", "origin", "main")
        _ = commit_file(repo, "mod.py", "x = 2\n# why\n")

        listing = run_list(repo)

        assert [(c["file"], c["start"]) for c in listing["comments"]] == [("mod.py", 2)]
