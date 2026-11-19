import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]
_ROOT_RULES_DIR = _REPO_ROOT / ".claude" / "rules"
_GENERATED_RULES_DIR = _REPO_ROOT / "template" / "template" / ".claude" / "rules"

# These describe this repository itself: copier.yaml excludes them from rendering, and nothing links them for generated projects.
_RULES_FOR_THIS_REPOSITORY_ONLY = {"base-template.md"}

_JINJA_TAG = re.compile(r"\{%.*?%\}")


def test_When_matching_rules_to_links_with_template_tags_stripped__Then_every_shared_rule_has_a_link() -> None:
    shared_rules = {path.name for path in _ROOT_RULES_DIR.glob("*.md")} - _RULES_FOR_THIS_REPOSITORY_ONLY
    linked_names = {_JINJA_TAG.sub("", path.name) for path in _GENERATED_RULES_DIR.iterdir()}

    unlinked_rules = sorted(shared_rules - linked_names)

    assert shared_rules != set()
    assert unlinked_rules == []


def test_When_resolving_each_shared_rule_link_with_template_tags_stripped__Then_it_points_to_the_root_rule_of_that_name() -> (
    None
):
    links = [
        path
        for path in _GENERATED_RULES_DIR.iterdir()
        if _JINJA_TAG.sub("", path.name) not in _RULES_FOR_THIS_REPOSITORY_ONLY
    ]

    wrong_links = [
        path.name
        for path in links
        if not path.is_symlink() or path.resolve() != (_ROOT_RULES_DIR / _JINJA_TAG.sub("", path.name)).resolve()
    ]

    assert links != []
    assert wrong_links == []
