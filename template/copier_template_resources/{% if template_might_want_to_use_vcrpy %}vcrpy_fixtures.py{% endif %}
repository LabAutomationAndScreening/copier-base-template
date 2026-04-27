import difflib
import logging
import os
import traceback
from typing import Any
from typing import cast

import pytest
from vcr import VCR
from vcr import matchers as _vcr_matchers
from vcr.request import Request as VCRRequest
from vcr.util import read_body as _vcr_read_body  # pyright: ignore[reportUnknownVariableType] # vcrpy is untyped

logger = logging.getLogger(__name__)

UNREACHABLE_IP_ADDRESS = "192.0.2.1"  # RFC 5737 TEST-NET-1
IGNORED_HOSTS = [
    "testserver",  # Skip recording any requests to our own server - let them run live
    UNREACHABLE_IP_ADDRESS,  # allow this through VCR in order to be able to test network failure handling
]
ALLOWED_HOSTS: list[str] = []

CUSTOM_IGNORED_HOSTS: tuple[str, ...] = ()

IGNORED_HOSTS.extend(CUSTOM_IGNORED_HOSTS)
if (
    os.name == "nt"
):  # on Windows (in CI), the network calls happen at a lower level socket connection even to our FastAPI test client, and can get automatically blocked. This disables that automatic network guard, which isn't great...but since it's still in place on Linux, any actual problems would hopefully get caught before pushing to CI.
    ALLOWED_HOSTS.extend(["127.0.0.1", "localhost", "::1"])


@pytest.fixture(autouse=True)
def vcr_config() -> dict[str, list[str]]:
    cfg: dict[str, list[str]] = {
        "ignore_hosts": IGNORED_HOSTS,
        "filter_headers": ["User-Agent"],
    }
    if ALLOWED_HOSTS:
        cfg["allowed_hosts"] = ALLOWED_HOSTS
    return cfg


def _read_body_as_str(request: VCRRequest) -> str:
    raw = _vcr_read_body(request)  # pyright: ignore[reportUnknownVariableType] # vcrpy is untyped
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)  # pyright: ignore[reportUnknownArgumentType] # vcrpy is untyped


def _logging_body_matcher(r1: VCRRequest, r2: VCRRequest) -> None:
    try:
        _vcr_matchers.body(r1, r2)  # pyright: ignore[reportUnknownMemberType] # vcrpy is untyped
    except AssertionError as err:
        tb_frames = traceback.extract_tb(err.__traceback__)
        if (
            not tb_frames or f"{os.sep}vcr{os.sep}" not in tb_frames[-1].filename
        ):  # if the assertion error came from something else in pytest, just rethrow it. Only log the diff if the assertion error came from within VCRpy itself
            raise
        try:
            b1 = _read_body_as_str(r1)
            b2 = _read_body_as_str(r2)
            diff = "\n".join(
                difflib.unified_diff(
                    b2.splitlines(),
                    b1.splitlines(),
                    fromfile="cassette",
                    tofile="actual",
                    lineterm="",
                )
            )
        except Exception:
            logger.exception("Error while logging VCR body mismatch")
            raise err from None  # if there's some failure generating the diff, just raise the original error unchanged
        # TODO: figure out why Body is the only VCRpy matcher that doesn't include an error message of the diff, and see about creating an issue in VCRpy repo itself
        raise AssertionError(f"Request body mismatch:\n{diff}") from err


def pytest_recording_configure(
    config: pytest.Config,  # noqa: ARG001 # the config argument MUST be present (even when unused) or pytest-recording throws an error
    vcr: VCR,
):
    vcr.match_on = cast(tuple[str, ...], vcr.match_on)  # pyright: ignore[reportUnknownMemberType] # I know vcr.match_on is unknown, that's why I'm casting and isinstance-ing it...not sure if there's a different approach pyright prefers
    assert isinstance(vcr.match_on, tuple), (
        f"vcr.match_on is not a tuple, it is a {type(vcr.match_on)} with value {vcr.match_on}"
    )

    vcr.register_matcher("logging_body", _logging_body_matcher)  # pyright: ignore[reportUnknownMemberType] # vcrpy is not fully typed
    vcr.match_on += ("logging_body",)  # body is not included by default, but it seems relevant

    def before_record_response(response: dict[str, str | dict[str, Any]]) -> dict[str, str | dict[str, Any]]:
        headers_to_filter = (
            "Transfer-Encoding",
            "Date",
            "Server",
        )  # none of these headers in the response matter for unit testing, so might as well make the cassette files smaller
        headers = response["headers"]
        assert isinstance(headers, dict), (
            f"Expected response['headers'] to be a dict, got {type(headers)} with value {headers}"
        )
        for header in headers_to_filter:
            if header in headers:
                del headers[header]
            if (
                header.lower() in headers
            ):  # some headers are lowercased by the server in the response (e.g. Date, Server)
                del headers[header.lower()]
        return response

    vcr.before_record_response = before_record_response
