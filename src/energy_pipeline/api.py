"""Read-only API client with bounded retries and conservative request pacing."""

from dataclasses import dataclass
from http.client import HTTPException
import json
import logging
import math
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE_URL = "https://math637-energy-api.dominique637.workers.dev"
LOGGER = logging.getLogger(__name__)


class ApiError(RuntimeError):
    """Safe diagnostic that never includes authorization headers or bodies."""

    def __init__(self, message: str, *, retryable: bool = False,
                 status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


class NoRedirects(HTTPRedirectHandler):
    """Do not forward a team credential to a redirect destination."""

    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str,
        headers: Any, newurl: str,
    ) -> None:
        return None


def fetch(request: Request, timeout: float) -> Response:
    opener = build_opener(NoRedirects())
    try:
        with opener.open(request, timeout=timeout) as result:
            return Response(result.status, dict(result.headers.items()), result.read())
    except HTTPError as error:
        with error:
            return Response(error.code, dict(error.headers.items()), error.read())


class ApiClient:
    def __init__(
        self, api_key: str, *, attempts: int = 5, timeout: float = 30,
        transport: Callable[[Request, float], Response] = fetch,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Set ENERGY_API_KEY before collecting data")
        if attempts < 1 or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Attempts and timeout must be positive")
        self._key = api_key.strip()
        self._attempts = attempts
        self._timeout = timeout
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self._not_before = 0.0

    def _pace(self) -> None:
        remaining = self._not_before - self._clock()
        if self._last_request is not None:
            remaining = max(
                remaining, 2.1 - (self._clock() - self._last_request)
            )
        if remaining > 0:
            self._sleep(remaining)
        self._last_request = self._clock()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Response:
        if path not in ("/v1/observations", "/v1/weather/forecast"):
            raise ValueError("Unsupported collection endpoint")
        url = BASE_URL + path
        if params:
            url += "?" + urlencode(params)
        request = Request(url, headers={
            "Authorization": "Bearer " + self._key,
            "Accept": "application/json",
            "User-Agent": "Math637-energy-pipeline/0.1",
        })
        for attempt in range(self._attempts):
            self._pace()
            retry_after = 0.0
            try:
                response = self._transport(request, self._timeout)
            except (URLError, TimeoutError, ConnectionError, OSError, HTTPException):
                failure = ApiError("API connection failed", retryable=True)
            else:
                if response.status == 200:
                    return response
                retryable = response.status == 429 or 500 <= response.status < 600
                failure = ApiError(
                    f"API returned HTTP {response.status} for {path}",
                    retryable=retryable, status=response.status,
                )
                if response.status == 429:
                    headers = {k.lower(): v for k, v in response.headers.items()}
                    try:
                        value = float(headers.get("retry-after", "0"))
                        if math.isfinite(value):
                            retry_after = max(0.0, value)
                    except ValueError:
                        pass
                    self._not_before = self._clock() + retry_after
            if not failure.retryable or attempt + 1 == self._attempts:
                raise failure
            delay = max(retry_after, min(60.0, 2.0 ** (attempt + 1)))
            LOGGER.warning("%s; retrying in %.1f seconds", failure, delay)
            self._sleep(delay)
        raise AssertionError("Unreachable retry state")


def decode(response: Response) -> dict[str, Any]:
    try:
        payload = json.loads(response.body)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("API returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("API response must be a JSON object")
    return payload
