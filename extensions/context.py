# adapted from https://github.com/copier-org/copier-template-extensions#context-hook-extension
from typing import Any
from typing import override

from copier_template_extensions import ContextHook


class ContextUpdater(ContextHook):
    update = False

    @override
    def hook(  # noqa: PLR0915 # yes, this is a lot of statements, but it's all just creating the dict
        self, context: dict[Any, Any]
    ) -> dict[Any, Any]:
        # These are duplicated in the install-ci-tooling.py script in this repository
        context["uv_version"] = "0.12.6"
        context["pre_commit_version"] = "4.6.2"
        context["pnpm_version"] = "11.22.0"
        context["task_version"] = "3.53.1"
        # These also in pyproject.toml and the install-ci-tooling.py script in this repository
        context["copier_version"] = "==9.17.1"
        context["copier_template_extensions_version"] = "==0.3.3"
        #######
        # These two move in lockstep, and are consumed from separate files in this repository (.devcontainer/docker-compose.yml and
        # .devcontainer/on-create-command.sh). The dolt image must be the one the pinned beads release tests against,
        # declared in internal/testutil/testdoltcommon.go of gastownhall/beads.
        context["beads_version"] = "1.2.2"
        context["dolt_image_version"] = "2.1.0"
        #######
        # These are duplicated in the pyproject.toml of this repository
        context["pytest_version"] = ">=9.1.1"
        context["pytest_randomly_version"] = ">=4.1.0"
        context["pytest_cov_version"] = ">=7.1.0"
        context["mutmut_version"] = ">=3.7.0"
        context["pyrefly_version"] = ">=1.2.0"
        context["python_faker_version"] = ">=40.37.0"
        #######
        context["sphinx_version"] = "9.0.4"
        context["pulumi_version"] = ">=3.245.0"
        context["pulumi_aws_version"] = ">=7.32.0"
        context["pulumi_aws_native_version"] = ">=1.68.0"
        context["pulumi_command_version"] = ">=1.2.1"
        context["pulumi_github_version"] = ">=6.13.1"
        context["pulumi_okta_version"] = ">=6.6.0"
        context["boto3_version"] = ">=1.42.92"
        context["ephemeral_pulumi_deploy_version"] = ">=0.0.7"
        context["pydantic_version"] = ">=2.13.4"
        context["pyinstaller_version"] = ">=6.22.2"
        context["setuptools_version"] = "80.7.1"
        context["strawberry_graphql_version"] = (
            "==0.298.0"  # problems with strawberry pydantic in later versions...lost the context for exactly why...it was figured out a while ago, but has to do with being able to override resolvers and have the schema still keep the desired nullability
        )
        context["fastapi_version"] = ">=0.141.1"
        context["fastapi_offline_version"] = ">=1.7.7"
        context["starlette_version"] = ">=1.6.0"
        context["uvicorn_version"] = ">=0.52.3"
        context["lab_auto_pulumi_version"] = ">=0.2.3"
        context["ariadne_codegen_version"] = ">=0.18.0"
        context["pytest_mock_version"] = ">=3.15.1"
        context["uuid_utils_version"] = ">=0.16.2"
        context["syrupy_version"] = ">=5.5.3"
        context["structlog_version"] = ">=26.1.0"
        context["httpx_version"] = ">=0.28.1"
        context["httpx2_version"] = ">=2.12.0"
        context["python_kiota_bundle_version"] = ">=1.11.6"
        context["vcrpy_version"] = ">=8.3.0"
        context["pytest_recording_version"] = ">=0.13.4"
        context["pytest_asyncio_version"] = ">=1.4.0"
        context["pytest_timeout_version"] = ">=2.4.0"
        context["pytest_reserial_version"] = ">=0.6.1"
        context["vacuum_openapi_version"] = "0.30.0"
        #######
        context["npm_version"] = "11.13.0"
        context["nvm_version"] = "0.40.5"
        context["nuxt_ui_version"] = "^4.10.0"
        context["nuxt_version"] = "^4.4.6"
        context["nuxt_icon_version"] = "^2.2.1"
        context["typescript_version"] = "^6.0.2"
        context["playwright_version"] = "^1.61.1"
        context["vue_version"] = "^3.5.30"
        context["vue_tsc_version"] = "^3.3.2"
        context["vue_devtools_api_version"] = "^8.1.0"
        context["vue_router_version"] = "^5.1.0"
        context["dotenv_cli_version"] = "^11.0.0"
        context["faker_version"] = "^10.5.0"
        context["vitest_version"] = "^4.1.7"
        context["vitest_eslint_plugin_version"] = "^1.6.17"
        context["eslint_version"] = "^10.5.0"
        context["nuxt_eslint_version"] = "^1.16.0"
        context["zod_version"] = "^4.3.6"
        context["zod_from_json_schema_version"] = "^0.5.1"
        context["nuxt_apollo_version"] = "5.0.0-alpha.15"
        context["graphql_codegen_cli_version"] = "^7.1.2"
        context["graphql_tools_mock_version"] = "^9.1.0"
        context["tailwindcss_version"] = "^4.2.0"
        context["iconify_vue_version"] = "^5.0.0"
        context["iconify_json_lucide_version"] = "^1.2.71"
        context["nuxt_fonts_version"] = "^0.14.0"
        context["nuxtjs_color_mode_version"] = "^4.0.0"
        context["vue_test_utils_version"] = "^2.4.6"
        context["nuxt_test_utils_version"] = "^4.0.3"
        context["vue_eslint_parser_version"] = "^10.4.0"
        context["happy_dom_version"] = "^20.10.1"
        context["node_kiota_bundle_version"] = "1.0.0-preview.103"
        context["labsync_nuxt_common_version"] = "^0.2.3"
        context["tanstack_vue_table_version"] = "^8.21.3"
        context["unplugin_auto_import_version"] = "^21.0.0"
        context["openapi_types_version"] = "^12.1.3"

        #######
        # These are duplicated in the CI files for this repository
        context["default_node_version"] = "24.11.1"
        context["gha_checkout"] = "v7.0.1"
        context["gha_setup_python"] = "v7.0.0"
        context["gha_cache"] = "v6.1.0"
        context["gha_linux_runner"] = "ubuntu-24.04"
        context["gha_setup_node"] = "v6.4.0"
        context["gha_pnpm_setup"] = "v2.0.2"
        context["gha_upload_artifact"] = "v7.0.1"
        #######
        context["gha_download_artifact"] = "v8.0.1"
        context["gha_github_script"] = "v7.0.1"
        context["gha_setup_buildx"] = "v4.0.0"
        context["buildx_version"] = "v0.33.0"
        context["gha_docker_build_push"] = "v7.1.0"
        context["gha_configure_aws_credentials"] = "v6.2.3"
        context["gha_amazon_ecr_login"] = "v2.1.7"
        context["gha_action_gh_release"] = "v3.0.0"
        context["gha_codecov"] = "v7.0.0"
        context["gha_mutex"] = "1ebad517141198e08d47cf72f3c0975316620a65 # v1.0.0-alpha.10"
        context["gha_pypi_publish"] = "v1.14.0"
        context["gha_sleep"] = "v2.0.3"
        context["gha_absaoss_k3d"] = "v2.4.0"
        context["k3d_version"] = "v5.5.0"
        context["gha_azure_setup_helm"] = "v5.0.0"
        context["helm_version"] = "v3.18.3"
        context["gha_azure_setup_kubectl"] = "v5.1.0"
        context["kubectl_version"] = "v1.36.0"
        context["gha_windows_runner"] = (
            "windows-2025-vs2026"  # for some reason, github is starting to redirect all windows-2025 to this new one https://github.com/actions/runner-images/issues/14017
        )
        context["gha_short_timeout_minutes"] = "2"
        context["gha_medium_timeout_minutes"] = "8"
        context["gha_long_timeout_minutes"] = "15"
        context["gha_xlong_timeout_minutes"] = "45"
        context["gha_xxlong_timeout_minutes"] = "90"
        #######
        context["debian_release_name"] = "trixie"
        context["alpine_image_version"] = "3.23"
        context["nginx_image_version"] = "1.30.1"
        #######
        context["kiota_cli_version"] = (
            "1.32.4"  # this is also in tests/unit/openapi/test_openapi_schema_simplifier.py and should be kept in sync with that
        )
        # These also in the tests/data.yml files in this repository and in copier.yaml
        context["py312_version"] = "3.12.7"  # ReadTheDocs does not yet support 3.12.8
        context["py313_version"] = "3.13.9"
        context["py314_version"] = "3.14.0"
        #######
        # Kludge to allow for the same docker-compose file in child and grandchild templates
        context["aws_region_for_stack"] = "us-east-1"
        # Kludge to be able to stop symlinked jinja files from being updated in child templates when the variable is really meant for the instantiated grandchild template
        context["is_child_of_copier_base_template"] = True
        return context
