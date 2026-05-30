"""
mm.common.http — HTTP utilities for the Mapping Momentum pipeline.

Provides ``fetch_bytes`` and ``fetch_json`` as thin wrappers around
``urllib`` so the rest of the codebase never imports ``urllib`` directly.
Both functions raise ``HTTPError`` on non-2xx responses or connection
failures.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

_USER_AGENT = (
    "mapping-momentum/1.0 "
    "(github.com/taskarcenteratuw/mapping-momentum)"
)


class HTTPError(OSError):
    """Raised when an HTTP request returns a non-2xx response or the
    connection fails."""


def fetch_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> bytes:
    """Fetch the response body from *url* as raw bytes.

    Parameters
    ----------
    url:
        The URL to request (GET).
    headers:
        Optional additional request headers.  ``User-Agent`` is always
        set automatically.
    timeout:
        Socket timeout in seconds (default: 30).

    Raises
    ------
    HTTPError
        If the server returns a non-2xx status code or the connection
        fails.
    """
    all_headers: dict[str, str] = {"User-Agent": _USER_AGENT}
    if headers:
        all_headers.update(headers)
    req = urllib.request.Request(url, headers=all_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        raise HTTPError(
            f"HTTP {exc.code} from {url}: {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPError(
            f"Request failed for {url}: {exc.reason}"
        ) from exc


def fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> Any:
    """Fetch JSON from *url* and return the decoded Python object.

    Parameters
    ----------
    url:
        The URL to request (GET).
    headers:
        Optional additional request headers.
    timeout:
        Socket timeout in seconds (default: 30).

    Raises
    ------
    HTTPError
        If the server returns a non-2xx status code or the connection
        fails.
    json.JSONDecodeError
        If the response body is not valid JSON.
    """
    raw = fetch_bytes(url, headers=headers, timeout=timeout)
    return json.loads(raw)
