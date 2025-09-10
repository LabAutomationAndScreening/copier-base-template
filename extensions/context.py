# adapted from https://github.com/copier-org/copier-template-extensions#context-hook-extension
from typing import Any
from typing import override

from copier_template_extensions import ContextHook


class ContextUpdater(ContextHook):
    update = False

    @override
    def hook(self, context: dict[Any, Any]) -> dict[Any, Any]:
        # These are duplicated in the install-ci-tooling.py script in this repository
        context["uv_version"] = "0.8.15"
        context["pre_commit_version"] = "4.3.0"
        # These also in pyproject.toml
        context["copier_version"] = "9.10.1"
        context["copier_template_extensions_version"] = "0.3.3"
        #######
        context["pnpm_version"] = "10.15.1"
        # These are duplicated in the pyproject.toml of this repository
        context["pyright_version"] = "1.1.405"
        context["pytest_version"] = "8.4.2"
        context["pytest_randomly_version"] = "3.16.0"
        context["pytest_cov_version"] = "6.3.0"
        #######
        context["sphinx_version"] = "8.1.3"
        context["pulumi_version"] = "3.193.0"
        context["pulumi_aws_version"] = "7.7.0"
        context["pulumi_aws_native_version"] = "1.33.0"
        context["pulumi_command_version"] = "1.1.0"
        context["pulumi_github_version"] = "6.7.3"
        context["pulumi_okta_version"] = "5.2.0"
        context["boto3_version"] = "1.40.25"
        context["ephemeral_pulumi_deploy_version"] = "0.0.5"
        context["pydantic_version"] = "2.11.7"
        context["pyinstaller_version"] = "6.15.0"
        context["setuptools_version"] = "80.7.1"
        context["strawberry_graphql_version"] = "0.282.0"
        context["fastapi_version"] = "0.116.1"
        context["fastapi_offline_version"] = "1.7.4"
        context["uvicorn_version"] = "0.35.0"
        context["lab_auto_pulumi_version"] = "0.1.16"
        context["ariadne_codegen_version"] = "0.15.2"
        #######
        context["node_version"] = "24.7.0"
        context["nuxt_ui_version"] = "^3.3.3"
        context["nuxt_version"] = "^4.1.0"
        context["nuxt_icon_version"] = "^2.0.0"
        context["typescript_version"] = "^5.8.2"
        context["dot_env_cli_version"] = "^9.0.0"
        context["playwright_version"] = "^1.55.0"
        context["vue_version"] = "^3.5.21"
        context["vue_tsc_version"] = "^3.0.6"
        context["vue_devtools_api_version"] = "^8.0.0"
        context["vue_router_version"] = "^4.5.1"
        context["dotenv_cli_version"] = "^10.0.0"
        context["faker_version"] = "^10.0.0"
        context["vitest_version"] = "^3.2.4"
        context["eslint_version"] = "^9.35.0"
        context["nuxt_eslint_version"] = "^1.9.0"
        context["zod_version"] = "^4.1.5"
        context["zod_from_json_schema_version"] = "^0.5.0"
        context["types_node_version"] = "^24.3.1"
        context["nuxt_apollo_version"] = "5.0.0-alpha.15"
        context["graphql_codegen_cli_version"] = "^6.0.0"
        context["graphql_codegen_typescript_version"] = "^5.0.0"
        context["graphql_codegen_typescript_operations_version"] = "^5.0.0"
        #######
        # These are duplicated in the CI files for this repository
        context["gha_checkout"] = "v5.0.0"
        context["gha_setup_python"] = "v6.0.0"
        context["gha_cache"] = "v4.2.4"
        context["gha_linux_runner"] = "ubuntu-24.04"
        #######
        context["gha_upload_artifact"] = "v4.6.2"
        context["gha_download_artifact"] = "v5.0.0"
        context["gha_github_script"] = "v7.0.1"
        context["gha_setup_buildx"] = "v3.11.1"
        context["buildx_version"] = "v0.27.0"
        context["gha_docker_build_push"] = "v6.16.0"
        context["gha_configure_aws_credentials"] = "v5.0.0"
        context["gha_amazon_ecr_login"] = "v2.0.1"
        context["gha_setup_node"] = "v5.0.0"
        context["gha_action_gh_release"] = "v2.2.1"
        context["gha_mutex"] = "1ebad517141198e08d47cf72f3c0975316620a65 # v1.0.0-alpha.10"
        context["gha_pypi_publish"] = "v1.13.0"
        context["gha_sleep"] = "v2.0.3"
        context["gha_windows_runner"] = "windows-2025"
        #######
        context["debian_release_name"] = "bookworm"
        context["alpine_image_version"] = "3.22"
        context["nginx_image_version"] = "1.29.1"
        # These also in the tests/data.yml files in this repository and in copier.yaml
        context["py312_version"] = "3.12.7"  # ReadTheDocs does not yet support 3.12.8
        context["py313_version"] = "3.13.2"
        #######
        # Kludge to allow for the same docker-compose file in child and grandchild templates
        context["aws_region_for_stack"] = "us-east-1"
        # Kludge to be able to stop symlinked jinja files from being updated in child templates when the variable is really meant for the instantiated grandchild template
        context["is_child_of_copier_base_template"] = True
        return context
