"""Guards the platform questions and runner constants this template propagates to child templates.

Child templates build their CI matrices and release asset lists from these, and a release list that
silently disagreed with the CI matrix is what motivated the questions in the first place.
"""

from pathlib import Path

import pytest
import yaml

from .helpers import render_child_template


@pytest.fixture(name="child_copier_questions", scope="module")
def _child_copier_questions(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    child = render_child_template(tmp_path_factory.mktemp("child"))
    questions: dict[str, object] = yaml.safe_load((child / "copier.yml").read_text(encoding="utf-8"))
    return questions


class TestTargetPlatformsQuestion:
    def test_Given_child_template__Then_target_platforms_is_a_multiselect(
        self, child_copier_questions: dict[str, object]
    ) -> None:
        question = child_copier_questions["target_platforms"]
        assert isinstance(question, dict)
        assert question["multiselect"] is True

    def test_Given_child_template__Then_every_supported_platform_is_offered(
        self, child_copier_questions: dict[str, object]
    ) -> None:
        question = child_copier_questions["target_platforms"]
        assert isinstance(question, dict)
        choices = question["choices"]
        assert isinstance(choices, dict)
        assert set(choices.values()) == {"linux-x64", "linux-arm64", "windows-x64", "windows-arm64"}

    @pytest.mark.parametrize(
        ("question_name", "gating_platform"),
        [
            ("linux_arm64_runner_label", "linux-arm64"),
            ("windows_arm64_runner_label", "windows-arm64"),
        ],
    )
    def test_Given_arm_platform_not_selected__Then_its_runner_label_is_not_asked(
        self, child_copier_questions: dict[str, object], question_name: str, gating_platform: str
    ) -> None:
        # The labels are org-specific, so they must be answerable -- but only when that platform is
        # actually selected, otherwise every project is asked about hardware it does not build for.
        question = child_copier_questions[question_name]
        assert isinstance(question, dict)
        assert gating_platform in str(question["when"])


class TestRunnerConstants:
    @pytest.fixture(name="child_context_source", scope="class")
    def _child_context_source(self, tmp_path_factory: pytest.TempPathFactory) -> str:
        child = render_child_template(tmp_path_factory.mktemp("child_context"))
        return (child / "extensions" / "context.py").read_text(encoding="utf-8")

    def test_Given_child_template__Then_platform_to_runner_mapping_is_propagated(
        self, child_context_source: str
    ) -> None:
        # Child templates render `runs-on` from this, so it has to survive the hop from this repo.
        assert "runner_for_platform" in child_context_source

    def test_Given_child_template__Then_use_windows_in_ci_is_derived_not_answered(
        self, child_context_source: str, child_copier_questions: dict[str, object]
    ) -> None:
        # Keeping it as a question alongside target_platforms lets the two disagree, which is the
        # class of bug these questions exist to remove.
        assert "use_windows_in_ci" not in child_copier_questions
        assert 'context["use_windows_in_ci"]' in child_context_source


def test_Given_rendered_child__Then_platform_ids_encode_their_os(
    child_copier_questions: dict[str, object],
) -> None:
    # `os` is derived from the platform id prefix rather than answered, so a project cannot claim a
    # Windows runner is Linux. That only holds while every id starts with a known os.
    question = child_copier_questions["target_platforms"]
    assert isinstance(question, dict)
    choices = question["choices"]
    assert isinstance(choices, dict)
    for platform_id in choices.values():
        assert str(platform_id).split("-")[0] in {"linux", "windows"}


def test_Given_child_template__Then_generated_fixtures_answer_target_platforms(
    tmp_path: Path,
) -> None:
    # The child's own test fixtures are generated here; a fixture still answering the old question
    # would break the child's CI rather than this repo's.
    child = render_child_template(tmp_path)
    for fixture in sorted((child / "tests" / "copier_data").glob("data*.yaml")):
        answers: dict[str, object] = yaml.safe_load(fixture.read_text(encoding="utf-8"))
        assert "target_platforms" in answers, fixture.name
        assert "use_windows_in_ci" not in answers, fixture.name
