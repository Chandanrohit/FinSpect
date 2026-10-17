from __future__ import annotations

import time
from typing import Any

import requests


class EdgarAPIError(Exception):
    """Raised when an SEC EDGAR request fails."""


class EdgarClient:
    """
    Low-level HTTP client for the SEC EDGAR APIs.

    This class is responsible only for:
    - making HTTP requests
    - SEC headers
    - timeouts (Ususally ERROR 403 and 404)
    - basic rate limiting and it is mentioned that per 10 request/sec is offered by SEC API
    - HTTP error handling
    - returning JSON/text (For forther quadrant readable)

    It does NOT decide which financial data is relevant.
    """

    DATA_BASE_URL = "https://data.sec.gov"
    SEC_BASE_URL = "https://www.sec.gov"

    def __init__(
        self,
        user_agent: str,
        timeout: float = 60.0,
        min_request_interval: float = 0.1,
    ) -> None:
        if not user_agent.strip():
            raise ValueError(
                "A descriptive SEC User-Agent is required."
            )

        self.timeout = timeout
        self.min_request_interval = min_request_interval

        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )

        self._last_request_time = 0.0

    def _wait_for_rate_limit(self) -> None:
        """
        Ensure a minimum delay between requests.
        """

        elapsed = time.monotonic() - self._last_request_time

        if elapsed < self.min_request_interval: 
            time.sleep(
                self.min_request_interval - elapsed
            )

    def _request(
        self,
        method: str,
        url: str,
    ) -> requests.Response:
        """
        Perform a controlled HTTP request.
        """

        self._wait_for_rate_limit()

        try:
            response = self.session.request(
                method=method,
                url=url,
                timeout=self.timeout,
            )

            self._last_request_time = time.monotonic()

        except requests.RequestException as exc:
            raise EdgarAPIError(
                f"SEC request failed: {exc}"
            ) from exc

        if not response.ok:
            raise EdgarAPIError(
                f"SEC returned HTTP {response.status_code}: "
                f"{response.reason}"
            )

        return response

    def get_json(self, url: str) -> dict[str, Any]:
        """
        GET a URL and parse the response as JSON.
        """

        response = self._request(
            method="GET",
            url=url,
        )

        try:
            return response.json()

        except ValueError as exc:
            raise EdgarAPIError(
                "SEC response was not valid JSON."
            ) from exc

    def get_text(self, url: str) -> str:
        """
        GET a URL and return the response as text.
        """

        response = self._request(
            method="GET",
            url=url,
        )

        return response.text