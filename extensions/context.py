# adapted from https://github.com/copier-org/copier-template-extensions#context-hook-extension
from typing import Any
from typing import override

from copier_template_extensions import ContextHook


class ContextUpdater(ContextHook):
    update = False

    @override
    def hook(self, context: dict[Any, Any]) -> dict[Any, Any]:
        # These are duplicated in the install-ci-tooling.py script in this repository
        context["uv_version"] = "0.9.6"
        context["pre_commit_version"] = "4.3.0"
        # These also in pyproject.toml
        context["copier_version"] = "9.10.3"
        context["copier_template_extensions_version"] = "0.3.3"
        #######
        context["pnpm_version"] = "10.20.0"
        # These are duplicated in the pyproject.toml of this repository
        context["pyright_version"] = "1.1.407"
        context["pytest_version"] = "8.4.2"
        context["pytest_randomly_version"] = "4.0.1"
        context["pytest_cov_version"] = "7.0.0"
        #######
        context["sphinx_version"] = "8.1.3"
        context["pulumi_version"] = "3.205.0"
        context["pulumi_aws_version"] = "7.10.0"
        context["pulumi_aws_native_version"] = "1.37.0"
        context["pulumi_command_version"] = "1.1.3"
        context["pulumi_github_version"] = "6.8.0"
        context["pulumi_okta_version"] = "6.1.0"
        context["boto3_version"] = "1.40.57"
        context["ephemeral_pulumi_deploy_version"] = "0.0.5"
        context["pydantic_version"] = "2.12.3"
        context["pyinstaller_version"] = "6.16.0"
        context["setuptools_version"] = "80.7.1"
        context["strawberry_graphql_version"] = "0.284.1"
        context["fastapi_version"] = "0.120.2"
        context["fastapi_offline_version"] = "1.7.4"
        context["uvicorn_version"] = "0.38.0"
        context["lab_auto_pulumi_version"] = "0.1.17"
        context["ariadne_codegen_version"] = "0.15.2"
        context["pytest_mock_version"] = "3.15.1"
        context["uuid_utils_version"] = "0.11.0"
        context["syrupy_version"] = "5.0.0"
        context["structlog_version"] = "25.5.0"
        #######
        context["node_version"] = "24.7.0"
        context["nuxt_ui_version"] = "^4.1.0"
        context["nuxt_version"] = "^4.2.0"
        context["nuxt_icon_version"] = "^2.1.0"
        context["typescript_version"] = "^5.9.3"
        context["playwright_version"] = "^1.56.0"
        context["vue_version"] = "^3.5.22"
        context["vue_tsc_version"] = "^3.1.2"
        context["vue_devtools_api_version"] = "^8.0.0"
        context["vue_router_version"] = "^4.6.0"
        context["dotenv_cli_version"] = "^11.0.0"
        context["faker_version"] = "^10.1.0"
        context["vitest_version"] = "^3.2.4"
        context["eslint_version"] = "^9.38.0"
        context["nuxt_eslint_version"] = "^1.10.0"
        context["zod_version"] = "^4.1.12"
        context["zod_from_json_schema_version"] = "^0.5.1"
        context["types_node_version"] = "^24.9.2"
        context["nuxt_apollo_version"] = "5.0.0-alpha.15"
        context["graphql_codegen_cli_version"] = "^6.0.0"
        context["graphql_codegen_typescript_version"] = "^5.0.0"
        context["graphql_codegen_typescript_operations_version"] = "^5.0.0"
        context["tailwindcss_version"] = "^4.1.11"
        context["iconify_vue_version"] = "^5.0.0"
        context["iconify_json_lucide_version"] = "^1.2.71"
        context["nuxt_fonts_version"] = "^0.11.4"
        context["nuxtjs_color_mode_version"] = "^3.5.2"
        context["vue_test_utils_version"] = "^2.4.6"
        context["nuxt_test_utils_version"] = "3.19.1"
        context["vue_eslint_parser_version"] = "^10.1.3"
        context["happy_dom_version"] = "^20.0.2"
        context["node_kiota_bundle_version"] = "1.0.0-preview.99"
        #######
        # These are duplicated in the CI files for this repository
        context["gha_checkout"] = "v5.0.0"
        context["gha_setup_python"] = "v6.0.0"
        context["gha_cache"] = "v4.2.4"
        context["gha_linux_runner"] = "ubuntu-24.04"
        #######
        context["gha_upload_artifact"] = "v5.0.0"
        context["gha_download_artifact"] = "v6.0.0"
        context["gha_github_script"] = "v7.0.1"
        context["gha_setup_buildx"] = "v3.11.1"
        context["buildx_version"] = "v0.27.0"
        context["gha_docker_build_push"] = "v6.18.0"
        context["gha_configure_aws_credentials"] = "v5.1.0"
        context["gha_amazon_ecr_login"] = "v2.0.1"
        context["gha_setup_node"] = "v6.0.0"
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
