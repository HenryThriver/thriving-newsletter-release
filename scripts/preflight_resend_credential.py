#!/usr/bin/env python3
"""Fail safely and early when the protected Resend credential cannot read audiences."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Mapping
from http.client import HTTPResponse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class PreflightError(RuntimeError):
    """A deliberately sanitized preflight failure safe for workflow logs."""


def preflight(
    environment: Mapping[str, str],
    *,
    opener: Callable[..., HTTPResponse] = urlopen,
) -> None:
    api_key = environment.get("RESEND_API_KEY", "").strip()
    segment_id = environment.get("RESEND_SEGMENT_CONFIRMED_ID", "").strip()

    if not api_key:
        raise PreflightError(
            "RESEND_API_KEY is missing from the newsletter-production environment."
        )
    if not UUID_PATTERN.fullmatch(segment_id):
        raise PreflightError(
            "RESEND_SEGMENT_CONFIRMED_ID is missing or malformed in the "
            "newsletter-production environment."
        )

    request = Request(
        f"https://api.resend.com/segments/{segment_id}",
        method="GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
    )

    try:
        with opener(request, timeout=15) as response:
            if not 200 <= response.status < 300:
                raise PreflightError(
                    "Resend credential preflight received an unexpected provider status."
                )
    except HTTPError as error:
        # Never read or print the response body: provider errors may include
        # identifiers or other private release data.
        error.close()
        raise PreflightError(
            "Resend rejected the protected credential or it cannot read the "
            "configured Confirmed segment. Replace RESEND_API_KEY from Henry's "
            "Private 1Password vault before releasing."
        ) from None
    except URLError:
        raise PreflightError(
            "Resend credential preflight could not reach the provider. Retry before releasing."
        ) from None


def main() -> int:
    try:
        preflight(os.environ)
    except PreflightError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Resend credential preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
