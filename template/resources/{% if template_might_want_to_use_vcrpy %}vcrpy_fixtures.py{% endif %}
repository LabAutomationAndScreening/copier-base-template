from typing import cast

import pytest
from pydantic import JsonValue
from vcr import VCR
from vcr.request import Request


def pytest_recording_configure(
    vcr: VCR,
    config: pytest.Config,  # noqa: ARG001 # the config argument MUST be present (even when unused) or pytest-recording throws an error
):
    vcr.match_on = cast("tuple[str]", vcr.match_on)  # type: ignore[reportUnknownMemberType] # I know vcr.match_on is unknown, that's why I'm casting and isinstance-ing it...not sure if there's a different approach pyright prefers
    assert isinstance(vcr.match_on, tuple), (
        f"vcr.match_on is not a tuple, it is a {type(vcr.match_on)} with value {vcr.match_on}"
    )
    vcr.match_on += ("body",)  # body is not included by default, but it seems relevant

    def before_record_request(request: Request) -> Request | None:
        request_headers_to_filter = ("User-Agent",)
        for header in request_headers_to_filter:
            if header in request.headers:
                del request.headers[header]

        return request

    vcr.before_record_request = before_record_request

    def before_record_response(response: dict[str, JsonValue]) -> dict[str, JsonValue]:
        headers_to_filter = [
            "Transfer-Encoding",
            "Date",
            "Server",
        ]  # none of these headers in the response matter for unit testing, so might as well make the cassette files smaller
        headers = response["headers"]
        assert isinstance(headers, dict), (
            f"Expected response['headers'] to be a dict, got {type(headers)} with value {headers}"
        )
        for header in headers_to_filter:
            if header in headers:
                del headers[header]
        return response

    vcr.before_record_response = before_record_response
