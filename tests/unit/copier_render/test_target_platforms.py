"""Guards the platform questions and runner constants this template propagates to child templates.

Child templates build their CI matrices and release asset lists from these, and a release list that
silently disagreed with the CI matrix is what motivated the questions in the first place.
"""

import ast
import importlib.util
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from faker import Faker
from jinja2.sandbox import SandboxedEnvironment

from .helpers import render_child_template

ALL_PLATFORMS = ["linux-x64", "linux-arm64", "windows-x64", "windows-arm64"]
OPERATING_SYSTEMS = {"linux", "windows"}
# A platform whose id is not the gating one, so a `when` matching any selection fails the same way an
# inverted one does.
OTHER_PLATFORM = {"linux-arm64": "windows-arm64", "windows-arm64": "linux-arm64"}


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
        ("legacy_answer", "expected_platforms"),
        [
            (True, ["linux-x64", "windows-x64"]),
            (False, ["linux-x64"]),
        ],
    )
    def test_Given_project_answered_the_superseded_question__Then_its_platforms_are_carried_over(
        self, child_copier_questions: dict[str, object], legacy_answer: bool, expected_platforms: list[str]
    ) -> None:
        # On update, copier still exposes an answer whose question no longer exists when it computes a
        # new question's default. Without this fallback a project that answered use_windows_in_ci: true
        # would take the bare default and silently stop building and releasing for Windows.
        question = child_copier_questions["target_platforms"]
        assert isinstance(question, dict)
        rendered = SandboxedEnvironment().from_string(str(question["default"])).render(use_windows_in_ci=legacy_answer)
        assert ast.literal_eval(rendered) == expected_platforms

    def test_Given_a_new_project__Then_the_platform_default_does_not_require_the_superseded_answer(
        self, child_copier_questions: dict[str, object]
    ) -> None:
        # `copier copy` has no previous answers at all, so the expression has to tolerate the name
        # being undefined rather than only a falsy value.
        question = child_copier_questions["target_platforms"]
        assert isinstance(question, dict)
        rendered = SandboxedEnvironment().from_string(str(question["default"])).render()
        assert ast.literal_eval(rendered) == ["linux-x64"]

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
        condition = SandboxedEnvironment().from_string(str(question["when"]))

        assert condition.render(target_platforms=[]) == "False"
        assert condition.render(target_platforms=[OTHER_PLATFORM[gating_platform]]) == "False"
        assert condition.render(target_platforms=[gating_platform]) == "True"

    def test_Given_child_template__Then_platform_ids_encode_their_os(
        self, child_copier_questions: dict[str, object]
    ) -> None:
        # `os` is derived from the platform id prefix rather than answered, so a project cannot claim a
        # Windows runner is Linux. That only holds while every id starts with a known os.
        question = child_copier_questions["target_platforms"]
        assert isinstance(question, dict)
        choices = question["choices"]
        assert isinstance(choices, dict)

        assert [platform for platform in choices.values() if str(platform).split("-")[0] not in OPERATING_SYSTEMS] == []


class TestChildContextHook:
    """Exercises the derivations the child renders its CI matrix and release asset list from.

    They are asserted by running the rendered hook rather than by matching its source text, because
    the failure this whole question set exists to prevent -- a release asset list that disagrees with
    the CI matrix -- is a wrong value, not a missing name.
    """

    @staticmethod
    @pytest.fixture(name="child_context_hook", scope="class")
    def _child_context_hook(tmp_path_factory: pytest.TempPathFactory) -> Callable[[dict[str, object]], None]:
        child = render_child_template(tmp_path_factory.mktemp("child_context"))
        module_path = child / "extensions" / "context.py"
        spec = importlib.util.spec_from_file_location("rendered_child_context", module_path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        updater = module.ContextUpdater(SandboxedEnvironment())

        def run_hook(context: dict[str, object]) -> None:
            _ = updater.hook(context)

        return run_hook

    def test_Given_arm64_labels_answered__Then_they_are_what_those_platforms_run_on(
        self, child_context_hook: Callable[[dict[str, object]], None], faker: Faker
    ) -> None:
        linux_label = faker.slug()
        windows_label = faker.slug()
        context: dict[str, object] = {
            "target_platforms": ALL_PLATFORMS,
            "linux_arm64_runner_label": linux_label,
            "windows_arm64_runner_label": windows_label,
        }

        child_context_hook(context)

        runner_for_platform = context["runner_for_platform"]
        assert isinstance(runner_for_platform, dict)

        assert runner_for_platform["linux-arm64"] == linux_label
        assert runner_for_platform["windows-arm64"] == windows_label

    def test_Given_arm64_labels_unanswered__Then_those_platforms_run_on_the_hosted_defaults(
        self, child_context_hook: Callable[[dict[str, object]], None]
    ) -> None:
        # The labels are only asked when their platform is selected, so the mapping still has to
        # resolve for a project that selected arm64 through a data file that predates the question.
        context: dict[str, object] = {"target_platforms": ALL_PLATFORMS}

        child_context_hook(context)

        runner_for_platform = context["runner_for_platform"]
        assert isinstance(runner_for_platform, dict)

        assert runner_for_platform["linux-arm64"] == context["gha_linux_arm64_runner"]
        assert runner_for_platform["windows-arm64"] == context["gha_windows_arm64_runner"]

    def test_Then_x64_platforms_run_on_the_pinned_labels(
        self, child_context_hook: Callable[[dict[str, object]], None], faker: Faker
    ) -> None:
        # Unlike arm64, these are not answerable, so an answer must not be able to move them.
        context: dict[str, object] = {
            "target_platforms": ALL_PLATFORMS,
            "linux_arm64_runner_label": faker.slug(),
            "windows_arm64_runner_label": faker.slug(),
        }

        child_context_hook(context)

        runner_for_platform = context["runner_for_platform"]
        assert isinstance(runner_for_platform, dict)

        assert runner_for_platform["linux-x64"] == context["gha_linux_runner"]
        assert runner_for_platform["windows-x64"] == context["gha_windows_runner"]

    def test_Then_every_platforms_os_is_derived_from_its_id(
        self, child_context_hook: Callable[[dict[str, object]], None]
    ) -> None:
        context: dict[str, object] = {"target_platforms": ALL_PLATFORMS}

        child_context_hook(context)

        assert context["os_for_platform"] == {
            "linux-x64": "linux",
            "linux-arm64": "linux",
            "windows-x64": "windows",
            "windows-arm64": "windows",
        }

    @pytest.mark.parametrize(
        ("selected_platforms", "expected_windows_platforms"),
        [
            (["linux-x64"], []),
            (["linux-x64", "linux-arm64"], []),
            (["linux-x64", "windows-arm64"], ["windows-arm64"]),
            (ALL_PLATFORMS, ["windows-x64", "windows-arm64"]),
        ],
    )
    def test_Then_only_the_selected_windows_platforms_are_collected(
        self,
        child_context_hook: Callable[[dict[str, object]], None],
        selected_platforms: list[str],
        expected_windows_platforms: list[str],
    ) -> None:
        context: dict[str, object] = {"target_platforms": selected_platforms}

        child_context_hook(context)

        assert context["windows_platforms"] == expected_windows_platforms

    @pytest.mark.parametrize(
        ("selected_platforms", "expected_use_windows_in_ci"),
        [
            (["linux-x64"], False),
            (["linux-arm64"], False),
            (["windows-x64"], True),
            (["windows-arm64"], True),
        ],
    )
    def test_Then_use_windows_in_ci_follows_the_selected_platforms(
        self,
        child_context_hook: Callable[[dict[str, object]], None],
        selected_platforms: list[str],
        expected_use_windows_in_ci: bool,
    ) -> None:
        context: dict[str, object] = {"target_platforms": selected_platforms}

        child_context_hook(context)

        assert context["use_windows_in_ci"] is expected_use_windows_in_ci

    def test_Given_target_platforms_not_yet_answered__Then_use_windows_in_ci_is_left_alone(
        self, child_context_hook: Callable[[dict[str, object]], None]
    ) -> None:
        # The hook also runs while question defaults render, before the questionnaire reaches
        # target_platforms. The legacy use_windows_in_ci answer is what the target_platforms default
        # migrates from, so overriding it during that pass drops every updating Windows project to Linux.
        answered_context: dict[str, object] = {"target_platforms": ["windows-x64"]}
        child_context_hook(answered_context)
        assert answered_context["use_windows_in_ci"] is True
        unanswered_context: dict[str, object] = {"use_windows_in_ci": True}

        child_context_hook(unanswered_context)

        assert unanswered_context["use_windows_in_ci"] is True

    def test_Then_use_windows_in_ci_is_derived_rather_than_answered(
        self, child_copier_questions: dict[str, object]
    ) -> None:
        # Keeping it as a question alongside target_platforms lets the two disagree, which is the
        # class of bug these questions exist to remove.
        assert "use_windows_in_ci" not in child_copier_questions


def test_Given_child_template__Then_generated_fixtures_answer_target_platforms(
    tmp_path: Path,
) -> None:
    # The child's own test fixtures are generated here; a fixture still answering the old question
    # would break the child's CI rather than this repo's.
    child = render_child_template(tmp_path)
    fixtures = sorted((child / "tests" / "copier_data").glob("data*.yaml"))
    answers_by_fixture = {fixture.name: yaml.safe_load(fixture.read_text(encoding="utf-8")) for fixture in fixtures}

    assert fixtures != []
    assert [name for name, answers in answers_by_fixture.items() if "target_platforms" not in answers] == []
    assert [name for name, answers in answers_by_fixture.items() if "use_windows_in_ci" in answers] == []
