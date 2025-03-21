# adapted from https://github.com/copier-org/copier-templates-extensions#context-hook-extension
from typing import Any
from typing import override

from copier_templates_extensions import ContextHook


class ContextUpdater(ContextHook):
    update = False

    @override
    def hook(self, context: dict[Any, Any]) -> dict[Any, Any]:
        # These are duplicated in the install-ci-tooling.sh script in this repository
        context["uv_version"] = "0.6.6"
        context["pre_commit_version"] = "4.1.0"
        # These also in pyproject.toml
        context["copier_version"] = "9.5.0"
        context["copier_templates_extension_version"] = "0.3.0"
        #######
        context["pnpm_version"] = "10.6.3"
        # These are duplicated in the pyproject.toml of this repository
        context["pyright_version"] = "1.1.397"
        context["pytest_version"] = "8.3.4"
        context["pytest_randomly_version"] = "3.16.0"
        context["pytest_cov_version"] = "6.0.0"
        #######
        context["sphinx_version"] = "8.1.3"
        context["pulumi_version"] = "3.156.0"
        context["pulumi_aws_version"] = "6.72.0"
        context["pulumi_aws_native_version"] = "1.26.0"
        context["pulumi_command_version"] = "1.0.2"
        context["pulumi_github"] = "6.7.0"
        context["boto3_version"] = "1.37.11"
        context["ephemeral_pulumi_deploy_version"] = "0.0.4"
        context["pydantic_version"] = "2.10.6"
        context["pyinstaller_version"] = "6.12.0"
        context["setuptools_version"] = "76.0.0"
        context["strawberry_graphql_version"] = "0.262.5"
        context["fastapi_version"] = "0.115.11"
        context["uvicorn_version"] = "0.34.0"
        #######
        context["nuxt_ui_version"] = "^3.0.0"
        context["nuxt_version"] = "^3.16.0"
        context["typescript_version"] = "^5.8.2"
        #######
        # These are duplicated in the CI files for this repository
        context["gha_checkout"] = "v4.2.2"
        context["gha_setup_python"] = "v5.4.0"
        context["gha_cache"] = "v4.2.2"
        context["gha_linux_runner"] = "ubuntu-24.04"
        #######
        context["gha_upload_artifact"] = "v4.6.2"
        context["gha_download_artifact"] = "v4.2.1"
        context["gha_setup_buildx"] = "v3.10.0"
        context["buildx_version"] = "v0.22.0"
        context["gha_docker_build_push"] = "v6.15.0"
        context["gha_configure_aws_credentials"] = "v4.1.0"
        context["gha_setup_node"] = "v4.3.0"
        context["gha_mutex"] = "1ebad517141198e08d47cf72f3c0975316620a65 # v1.0.0-alpha.10"
        context["gha_windows_runner"] = "windows-2022"
        #######
        context["debian_release_name"] = "bookworm"
        context["alpine_image_version"] = "3.20"
        # These also in the tests/data.yml files in this repository and in copier.yaml
        context["py312_version"] = "3.12.7"  # ReadTheDocs does not yet support 3.12.8
        context["py313_version"] = "3.13.2"
        #######
        # Kludge to allow for the same docker-compose file in child and grandchild templates
        context["aws_region_for_stack"] = "us-east-1"
        # Kludge to be able to stop symlinked jinja files from being updated in child templates when the variable is really meant for the instantiated grandchild template
        context["is_child_of_copier_base_template"] = True
        return context
