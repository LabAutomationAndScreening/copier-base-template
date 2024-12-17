# adapted from https://github.com/copier-org/copier-templates-extensions#context-hook-extension
from typing import Any
from typing import override

from copier_templates_extensions import ContextHook


class ContextUpdater(ContextHook):
    update = False

    @override
    def hook(self, context: dict[Any, Any]) -> dict[Any, Any]:
        # These are duplicated in the install-ci-tooling.sh script in this repository
        context["uv_version"] = "0.5.9"
        context["pre_commit_version"] = "4.0.1"
        # These also in pyproject.toml
        context["copier_version"] = "9.4.1"
        context["copier_templates_extension_version"] = "0.3.0"
        #######
        # These are duplicated in the pyproject.toml of this repository
        context["pyright_version"] = "1.1.390"
        context["pytest_version"] = "8.3.4"
        context["pytest_randomly_version"] = "3.16.0"
        context["pytest_cov_version"] = "6.0.0"
        #######
        # These are duplicated in the CI files for this repository
        context["gha_checkout"] = "v4.2.2"
        context["gha_setup_python"] = "v5.3.0"
        context["gha_cache"] = "v4.2.0"
        context["gha_upload_artifact"] = "v4.4.3"
        context["gha_mutex"] = "d3d5b354d460d4b6a1e3ee5b7951678658327812 # v1.0.0-alpha.9"
        context["gha_linux_runner"] = "ubuntu-24.04"
        #######
        return context
