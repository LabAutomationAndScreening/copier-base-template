import json
import os
import random
import string
import subprocess
from pathlib import Path

from pydantic import JsonValue

from copier_base_template.openapi import openapi_schema_simplifier

KIOTA_IMAGE = "mcr.microsoft.com/openapi/kiota:1.32.4"
KIOTA_TIMEOUT_SECONDS = 180


def _random_identifier() -> str:
    alphabet = string.ascii_lowercase + string.digits
    length = random.randint(8, 24)  # arbitrary bounds
    return random.choice(string.ascii_lowercase) + "".join(random.choice(alphabet) for _ in range(length - 1))


# kiota PascalCases a schema into its class/interface name, so start uppercase to keep it stable for assertions
THING_SCHEMA = _random_identifier().capitalize()


def _doc_with_property(*, field_name: str, field_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Compat Test", "version": "1.0.0"},
        "servers": [{"url": "http://localhost"}],
        "paths": {
            "/thing": {
                "post": {
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{THING_SCHEMA}"}}},
                    },
                    "responses": {"204": {"description": "ok"}},
                }
            }
        },
        "components": {
            "schemas": {THING_SCHEMA: {"type": "object", "properties": {field_name: field_schema}}},
        },
    }


def _run_kiota(*, openapi_doc: dict[str, JsonValue], work_dir: Path, language: str) -> Path:
    openapi_path = work_dir / "openapi.json"
    output_dir = work_dir / "output"
    output_dir.mkdir()
    _ = openapi_path.write_text(json.dumps(openapi_doc))
    _ = subprocess.run(  # noqa: S603 # fixed argument list, no shell, image/flags are constants
        [  # noqa: S607 # docker is resolved from PATH by design in this dev/CI environment
            "docker",
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-v",
            f"{output_dir}:/app/output",
            "-v",
            f"{openapi_path}:/app/openapi.json",
            KIOTA_IMAGE,
            "generate",
            "-l",
            language,
            "-c",
            "BackendClient",
            "-n",
            "client",
            "-d",
            "openapi.json",
            "--exclude-backward-compatible",
            "--clean-output",
            "--additional-data",
            "false",
        ],
        check=True,
        capture_output=True,
        timeout=KIOTA_TIMEOUT_SECONDS,
    )
    return output_dir


def _generate_typescript_models(*, openapi_doc: dict[str, JsonValue], work_dir: Path) -> str:
    output_dir = _run_kiota(openapi_doc=openapi_doc, work_dir=work_dir, language="typescript")
    return (output_dir / "models" / "index.ts").read_text()


def _generate_python_models(*, openapi_doc: dict[str, JsonValue], work_dir: Path) -> str:
    output_dir = _run_kiota(openapi_doc=openapi_doc, work_dir=work_dir, language="python")
    return "\n".join(path.read_text() for path in sorted(output_dir.rglob("*.py")))


class TestCollapseSafety:
    def test_Given_typed_member_has_a_branch_constraint__When_collapsed__Then_anyof_left_untouched(self):
        field: dict[str, JsonValue] = {
            "anyOf": [{"type": "string", "enum": ["a", "b"]}, {"type": "integer"}, {"type": "null"}]
        }
        document: dict[str, JsonValue] = {"value": field}

        openapi_schema_simplifier.collapse_nullable_anyof(document)

        assert "anyOf" in field
        assert "type" not in field


class TestKiotaGeneration:
    def test_Given_nullable_integer__When_collapsed_and_generated__Then_no_member1_wrapper(self, tmp_path: Path):
        field_name = _random_identifier()
        doc = _doc_with_property(
            field_name=field_name,
            field_schema={"anyOf": [{"type": "integer"}, {"type": "null"}], "default": random.randint(-1000, 1000)},
        )
        openapi_schema_simplifier.collapse_nullable_anyof(doc)

        models = _generate_typescript_models(openapi_doc=doc, work_dir=tmp_path)

        assert f"export interface {THING_SCHEMA} extends Parsable" in models
        assert "Member1" not in models

    def test_Given_nullable_integer__When_collapsed_and_generated_as_python__Then_no_member1_wrapper(
        self, tmp_path: Path
    ):
        field_name = _random_identifier()
        doc = _doc_with_property(
            field_name=field_name,
            field_schema={"anyOf": [{"type": "integer"}, {"type": "null"}], "default": random.randint(-1000, 1000)},
        )
        openapi_schema_simplifier.collapse_nullable_anyof(doc)

        models = _generate_python_models(openapi_doc=doc, work_dir=tmp_path)

        assert f"class {THING_SCHEMA}(" in models
        assert "member1" not in models.lower()

    def test_Given_nullable_datetime__When_collapsed_and_generated__Then_typed_as_date(self, tmp_path: Path):
        field_name = _random_identifier()
        doc = _doc_with_property(
            field_name=field_name,
            field_schema={"anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]},
        )
        openapi_schema_simplifier.collapse_nullable_anyof(doc)

        models = _generate_typescript_models(openapi_doc=doc, work_dir=tmp_path)

        assert f"{field_name}?: Date | null" in models

    def test_Given_nullable_union_of_two_types__When_collapsed_and_generated__Then_both_types_present(
        self, tmp_path: Path
    ):
        field_name = _random_identifier()
        doc = _doc_with_property(
            field_name=field_name,
            field_schema={"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}]},
        )
        openapi_schema_simplifier.collapse_nullable_anyof(doc)

        models = _generate_typescript_models(openapi_doc=doc, work_dir=tmp_path)

        assert f"{field_name}?: number | string | null" in models

    def test_Given_nullable_datetime__When_collapsed_and_generated_as_python__Then_typed_as_datetime(
        self, tmp_path: Path
    ):
        field_name = _random_identifier()
        doc = _doc_with_property(
            field_name=field_name,
            field_schema={"anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]},
        )
        openapi_schema_simplifier.collapse_nullable_anyof(doc)

        models = _generate_python_models(openapi_doc=doc, work_dir=tmp_path)

        assert f"{field_name}: Optional[datetime.datetime]" in models

    def test_Given_nullable_union_of_two_types__When_collapsed_and_generated_as_python__Then_both_types_present(
        self, tmp_path: Path
    ):
        field_name = _random_identifier()
        doc = _doc_with_property(
            field_name=field_name,
            field_schema={"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}]},
        )
        openapi_schema_simplifier.collapse_nullable_anyof(doc)

        models = _generate_python_models(openapi_doc=doc, work_dir=tmp_path)

        assert "integer: Optional[int]" in models
        assert "string: Optional[str]" in models
        assert "member1" not in models.lower()
