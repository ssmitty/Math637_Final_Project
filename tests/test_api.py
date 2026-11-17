"""Check HTTP failures, quota waits, pacing, and credential handling."""

from urllib.error import URLError

import pytest

from energy_pipeline.api import ApiClient, ApiError, NoRedirects, Response


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.delays: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        self.now += seconds


def client_for(responses: list, *, attempts: int = 5) -> tuple[ApiClient, Clock, list]:
    clock = Clock()
    calls = []
    iterator = iter(responses)

    def transport(request, timeout):
        calls.append(request)
        result = next(iterator)
        if isinstance(result, Exception):
            raise result
        return result

    client = ApiClient(
        "test-private-key", attempts=attempts, transport=transport,
        sleep=clock.sleep, clock=clock.time,
    )
    return client, clock, calls


def test_auth_header_pagination_and_pacing() -> None:
    response = Response(200, {}, b"{}")
    client, clock, calls = client_for([response, response])
    client.get("/v1/observations", {"after": 96, "limit": 96})
    client.get("/v1/weather/forecast")
    assert calls[0].get_header("Authorization") == "Bearer test-private-key"
    assert calls[0].full_url.endswith("?after=96&limit=96")
    assert clock.now >= 2.1


def test_retry_after_is_honored() -> None:
    client, clock, calls = client_for([
        Response(429, {"Retry-After": "61"}, b"{}"), Response(200, {}, b"{}"),
    ])
    client.get("/v1/observations")
    assert len(calls) == 2
    assert clock.now >= 61


def test_last_attempt_rate_limit_survives_next_cycle() -> None:
    client, clock, _ = client_for([
        Response(429, {"retry-after": "3600"}, b"{}"), Response(200, {}, b"{}"),
    ], attempts=1)
    with pytest.raises(ApiError):
        client.get("/v1/observations")
    client.get("/v1/observations")
    assert clock.now >= 3600


@pytest.mark.parametrize("failure", [URLError("offline"), Response(503, {}, b"{}")])
def test_temporary_failures_retry(failure) -> None:
    client, _, calls = client_for([failure, Response(200, {}, b"{}")])
    client.get("/v1/observations")
    assert len(calls) == 2


def test_retries_are_bounded_and_logs_do_not_contain_credentials(caplog) -> None:
    client, _, calls = client_for([Response(503, {}, b"test-private-key")] * 3,
                                 attempts=3)
    with pytest.raises(ApiError) as error:
        client.get("/v1/observations")
    assert len(calls) == 3
    assert error.value.retryable
    assert "test-private-key" not in str(error.value) + caplog.text


@pytest.mark.parametrize("status", [400, 401, 403, 404, 302])
def test_permanent_errors_do_not_retry(status: int) -> None:
    client, _, calls = client_for([Response(status, {}, b"{}")])
    with pytest.raises(ApiError) as error:
        client.get("/v1/observations")
    assert not error.value.retryable
    assert len(calls) == 1


def test_key_is_required() -> None:
    with pytest.raises(ValueError, match="ENERGY_API_KEY"):
        ApiClient("")


def test_redirects_are_rejected() -> None:
    result = NoRedirects().redirect_request(
        None, None, 302, "", {}, "https://other"
    )
    assert result is None
