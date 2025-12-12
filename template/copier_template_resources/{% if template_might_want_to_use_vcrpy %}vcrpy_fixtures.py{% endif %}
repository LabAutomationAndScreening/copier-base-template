import os
from typing import cast

import pytest
from pydantic import JsonValue
from vcr import VCR

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


def pytest_recording_configure(
    config: pytest.Config,  # noqa: ARG001 # the config argument MUST be present (even when unused) or pytest-recording throws an error
    vcr: VCR,
):
    vcr.match_on = cast(tuple[str, ...], vcr.match_on)  # pyright: ignore[reportUnknownMemberType] # I know vcr.match_on is unknown, that's why I'm casting and isinstance-ing it...not sure if there's a different approach pyright prefers
    assert isinstance(vcr.match_on, tuple), (
        f"vcr.match_on is not a tuple, it is a {type(vcr.match_on)} with value {vcr.match_on}"
    )
    vcr.match_on += ("body",)  # body is not included by default, but it seems relevant

    def before_record_response(response: dict[str, JsonValue]) -> dict[str, JsonValue]:
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
