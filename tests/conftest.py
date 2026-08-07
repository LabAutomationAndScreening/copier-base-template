import pytest

# pytest only rewrites asserts in the modules it collects as tests (plus conftest and registered plugins), so
# an assert reached through fixtures.py/helpers.py reports a bare AssertionError with no diff unless its
# module is registered here, so a new top-level test package needs adding to this list. The subpackages are
# named individually rather than registering `tests`, which is already imported by the time this conftest runs
# and would only warn.
pytest.register_assert_rewrite("tests.unit")
