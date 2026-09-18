import json
from pathlib import Path

from .helpers import SCRIPT_PATH_ROOT
from .helpers import run_copier_task

_SCRIPT_PATH = SCRIPT_PATH_ROOT / "copier_renames.py"
_COVERAGERC_RENAME = {"from": ".config/.coveragerc", "to": "backend/.coveragerc", "when": "has_backend"}


def _declare_renames(template_repo: Path, renames: list[dict[str, str]]) -> None:
    (template_repo / ".config").mkdir(parents=True, exist_ok=True)
    _ = (template_repo / ".config" / "copier-renames.json").write_text(
        json.dumps({"renames": renames}), encoding="utf-8"
    )


def _answer(dst_dir: Path, *, has_backend: bool, at_root: bool = False) -> None:
    if at_root:
        answers = dst_dir / ".copier-answers.yml"
    else:
        (dst_dir / ".config").mkdir(parents=True, exist_ok=True)
        answers = dst_dir / ".config" / ".copier-answers.yml"
    _ = answers.write_text(f"has_backend: {str(has_backend).lower()}\n", encoding="utf-8")


class TestWhenRenamesTaskRuns:
    def test_Given_when_answer_true__Then_file_moved_and_reported(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        _declare_renames(tmp_path, [_COVERAGERC_RENAME])
        dst_dir = tmp_path / "destination"
        (dst_dir / ".config").mkdir(parents=True)
        (dst_dir / "backend").mkdir()
        _answer(dst_dir, has_backend=True)
        body = "[run]\nbranch = True\n"
        _ = (dst_dir / ".config" / ".coveragerc").write_text(body, encoding="utf-8")

        result = run_copier_task(_SCRIPT_PATH, str(template_dir), str(dst_dir))

        assert result.returncode == 0, result.stderr
        assert "Moved .config/.coveragerc to backend/.coveragerc" in result.stdout
        assert not (dst_dir / ".config" / ".coveragerc").exists()
        assert (dst_dir / "backend" / ".coveragerc").read_text(encoding="utf-8") == body

    def test_Given_answers_file_at_repo_root__Then_answer_still_found(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        _declare_renames(tmp_path, [_COVERAGERC_RENAME])
        dst_dir = tmp_path / "destination"
        (dst_dir / ".config").mkdir(parents=True)
        (dst_dir / "backend").mkdir()
        _answer(dst_dir, has_backend=True, at_root=True)
        _ = (dst_dir / ".config" / ".coveragerc").write_text("[run]\n", encoding="utf-8")

        result = run_copier_task(_SCRIPT_PATH, str(template_dir), str(dst_dir))

        assert result.returncode == 0, result.stderr
        assert (dst_dir / "backend" / ".coveragerc").exists()

    def test_Given_target_already_exists__Then_fresh_render_replaces_it(self, tmp_path: Path) -> None:
        # On a copier update the source path holds the freshly rendered file and the target holds the
        # copy from the previous update. The fresh one wins, as it did with the shell `mv` this replaces.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        _declare_renames(tmp_path, [_COVERAGERC_RENAME])
        dst_dir = tmp_path / "destination"
        (dst_dir / ".config").mkdir(parents=True)
        (dst_dir / "backend").mkdir()
        _answer(dst_dir, has_backend=True)
        fresh = "[run]\nbranch = True\n"
        _ = (dst_dir / ".config" / ".coveragerc").write_text(fresh, encoding="utf-8")
        _ = (dst_dir / "backend" / ".coveragerc").write_text("[run]\nstale = 1\n", encoding="utf-8")

        result = run_copier_task(_SCRIPT_PATH, str(template_dir), str(dst_dir))

        assert result.returncode == 0, result.stderr
        assert (dst_dir / "backend" / ".coveragerc").read_text(encoding="utf-8") == fresh

    def test_Given_when_answer_false__Then_file_left_in_place(self, tmp_path: Path) -> None:
        # A stray backend/ directory on disk must not trigger the move; only the answer counts.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        _declare_renames(tmp_path, [_COVERAGERC_RENAME])
        dst_dir = tmp_path / "destination"
        (dst_dir / ".config").mkdir(parents=True)
        (dst_dir / "backend" / ".venv").mkdir(parents=True)
        _answer(dst_dir, has_backend=False)
        body = "[run]\n"
        _ = (dst_dir / ".config" / ".coveragerc").write_text(body, encoding="utf-8")

        result = run_copier_task(_SCRIPT_PATH, str(template_dir), str(dst_dir))

        assert result.returncode == 0, result.stderr
        assert "Skipped .config/.coveragerc to backend/.coveragerc" in result.stdout
        assert (dst_dir / ".config" / ".coveragerc").read_text(encoding="utf-8") == body
        assert not (dst_dir / "backend" / ".coveragerc").exists()

    def test_Given_answer_missing_from_answers_file__Then_conditional_rename_left_in_place(
        self, tmp_path: Path
    ) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        _declare_renames(tmp_path, [_COVERAGERC_RENAME])
        dst_dir = tmp_path / "destination"
        (dst_dir / ".config").mkdir(parents=True)
        _ = (dst_dir / ".config" / ".copier-answers.yml").write_text("other_answer: true\n", encoding="utf-8")
        body = "[run]\n"
        _ = (dst_dir / ".config" / ".coveragerc").write_text(body, encoding="utf-8")

        result = run_copier_task(_SCRIPT_PATH, str(template_dir), str(dst_dir))

        assert result.returncode == 0, result.stderr
        assert (dst_dir / ".config" / ".coveragerc").read_text(encoding="utf-8") == body

    def test_Given_no_answers_file__Then_conditional_rename_left_in_place(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        _declare_renames(tmp_path, [_COVERAGERC_RENAME])
        dst_dir = tmp_path / "destination"
        (dst_dir / ".config").mkdir(parents=True)
        body = "[run]\n"
        _ = (dst_dir / ".config" / ".coveragerc").write_text(body, encoding="utf-8")

        result = run_copier_task(_SCRIPT_PATH, str(template_dir), str(dst_dir))

        assert result.returncode == 0, result.stderr
        assert (dst_dir / ".config" / ".coveragerc").read_text(encoding="utf-8") == body

    def test_Given_source_absent__Then_nothing_happens(self, tmp_path: Path) -> None:
        # A second run after the move, or a project that never had the file.
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        _declare_renames(tmp_path, [_COVERAGERC_RENAME])
        dst_dir = tmp_path / "destination"
        (dst_dir / "backend").mkdir(parents=True)
        _answer(dst_dir, has_backend=True)
        body = "[run]\n"
        _ = (dst_dir / "backend" / ".coveragerc").write_text(body, encoding="utf-8")

        result = run_copier_task(_SCRIPT_PATH, str(template_dir), str(dst_dir))

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert (dst_dir / "backend" / ".coveragerc").read_text(encoding="utf-8") == body

    def test_Given_no_renames_file__Then_task_is_a_no_op(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        dst_dir = tmp_path / "destination"
        dst_dir.mkdir()
        _ = (dst_dir / "a.txt").write_text("a\n", encoding="utf-8")

        result = run_copier_task(_SCRIPT_PATH, str(template_dir), str(dst_dir))

        assert result.returncode == 0, result.stderr
        assert sorted(p.name for p in dst_dir.iterdir()) == ["a.txt"]
