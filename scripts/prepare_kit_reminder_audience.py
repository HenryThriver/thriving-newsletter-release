#!/usr/bin/env python3
"""Build a Kit reminder tag while excluding confirmed Resend subscribers.

The process keeps subscriber addresses in runner memory only. Its sole output is
an aggregate receipt that is safe to retain in a public workflow run.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TAG_NAME = "TWA Last Chance 2026-07-21"
SCHEMA_VERSION = "kit-reminder-audience-receipt/v1"


def normalize_email(value: Any) -> str:
    return value.strip().casefold() if isinstance(value, str) else ""


def _require_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError(f"{label} returned an invalid list")
    return value


class JsonApi:
    def __init__(self, base_url: str, api_key: str, header_name: str, *, interval: float = 0.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.header_name = header_name
        self.interval = interval
        self._last_request = 0.0

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.interval:
            delay = self.interval - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                self.header_name: self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:  # nosec B310
                self._last_request = time.monotonic()
                raw = response.read()
        except Exception as error:
            raise RuntimeError(f"{method} {path.split('?')[0]} failed") from error
        if not raw:
            return {}
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{method} {path.split('?')[0]} returned invalid JSON")
        return parsed


class ResendClient:
    def __init__(self, api_key: str):
        self.api = JsonApi("https://api.resend.com", api_key, "Authorization")
        self.api.api_key = f"Bearer {api_key}"

    def confirmed_emails(self, segment_id: str, topic_id: str) -> set[str]:
        contacts: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            query = urlencode({"limit": 100, **({"after": after} if after else {})})
            page = self.api.request("GET", f"/segments/{segment_id}/contacts?{query}")
            records = _require_list(page.get("data", []), "Resend contacts")
            contacts.extend(records)
            if not page.get("has_more"):
                break
            after = str(records[-1].get("id") or "") if records else ""
            if not after:
                raise RuntimeError("Resend contacts pagination returned no cursor")

        effective: set[str] = set()
        for contact in contacts:
            if contact.get("unsubscribed"):
                continue
            contact_id = str(contact.get("id") or "")
            email = normalize_email(contact.get("email"))
            if not contact_id or not email:
                raise RuntimeError("Resend returned a malformed contact")
            after = None
            target: dict[str, Any] | None = None
            while True:
                query = urlencode({"limit": 100, **({"after": after} if after else {})})
                page = self.api.request("GET", f"/contacts/{contact_id}/topics?{query}")
                topics = _require_list(page.get("data", []), "Resend topics")
                target = next((topic for topic in topics if topic.get("id") == topic_id), None)
                if target or not page.get("has_more"):
                    break
                after = str(topics[-1].get("id") or "") if topics else ""
                if not after:
                    raise RuntimeError("Resend topics pagination returned no cursor")
            if target is None:
                raise RuntimeError("Resend omitted the required topic for a confirmed contact")
            if target.get("subscription") == "opt_in":
                effective.add(email)
        return effective


class KitClient:
    def __init__(self, api_key: str):
        # Kit API keys are limited to 120 requests per rolling minute. A modest
        # interval keeps the one-time tag sync below that boundary.
        self.api = JsonApi("https://api.kit.com/v4", api_key, "X-Kit-Api-Key", interval=0.55)

    def _paginated(self, path: str, key: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            separator = "&" if "?" in path else "?"
            query = urlencode({"per_page": 1000, **({"after": after} if after else {})})
            page = self.api.request("GET", f"{path}{separator}{query}")
            records.extend(_require_list(page.get(key, []), f"Kit {key}"))
            pagination = page.get("pagination", {})
            if not isinstance(pagination, dict):
                raise RuntimeError("Kit returned invalid pagination")
            if not pagination.get("has_next_page"):
                break
            after = str(pagination.get("end_cursor") or "")
            if not after:
                raise RuntimeError("Kit pagination returned no cursor")
        return records

    def active_subscribers(self) -> list[dict[str, Any]]:
        return self._paginated("/subscribers?status=active", "subscribers")

    def ensure_tag(self, name: str) -> dict[str, Any]:
        response = self.api.request("POST", "/tags", {"name": name})
        tag = response.get("tag")
        if not isinstance(tag, dict) or not tag.get("id") or tag.get("name") != name:
            raise RuntimeError("Kit did not return the requested tag")
        return tag

    def tag_subscribers(self, tag_id: int) -> list[dict[str, Any]]:
        return self._paginated(f"/tags/{tag_id}/subscribers", "subscribers")

    def add(self, tag_id: int, subscriber_id: int) -> None:
        self.api.request("POST", f"/tags/{tag_id}/subscribers/{subscriber_id}", {})

    def remove(self, tag_id: int, subscriber_id: int) -> None:
        self.api.request("DELETE", f"/tags/{tag_id}/subscribers/{subscriber_id}")


@dataclass(frozen=True)
class SyncPlan:
    active_kit_count: int
    confirmed_resend_count: int
    overlap_excluded_count: int
    eligible_count: int
    add_ids: tuple[int, ...]
    remove_ids: tuple[int, ...]


def build_plan(
    active_kit: Iterable[dict[str, Any]],
    confirmed_resend: set[str],
    current_tag: Iterable[dict[str, Any]],
) -> SyncPlan:
    kit_by_email: dict[str, int] = {}
    for subscriber in active_kit:
        email = normalize_email(subscriber.get("email_address"))
        subscriber_id = subscriber.get("id")
        if not email or not isinstance(subscriber_id, int):
            raise RuntimeError("Kit returned a malformed active subscriber")
        if email in kit_by_email:
            raise RuntimeError("Kit returned duplicate active subscriber addresses")
        kit_by_email[email] = subscriber_id

    if not kit_by_email:
        raise RuntimeError("Kit returned no active subscribers")
    if not confirmed_resend:
        raise RuntimeError("Resend returned no confirmed subscribers")

    overlap = set(kit_by_email).intersection(confirmed_resend)
    if not overlap:
        raise RuntimeError("Audience sync found no Kit/Resend overlap; refusing to tag everyone")
    desired_ids = {subscriber_id for email, subscriber_id in kit_by_email.items() if email not in confirmed_resend}
    if not desired_ids:
        raise RuntimeError("Audience sync produced zero eligible subscribers")

    current_ids: set[int] = set()
    for subscriber in current_tag:
        subscriber_id = subscriber.get("id")
        if not isinstance(subscriber_id, int):
            raise RuntimeError("Kit returned a malformed tagged subscriber")
        current_ids.add(subscriber_id)

    return SyncPlan(
        active_kit_count=len(kit_by_email),
        confirmed_resend_count=len(confirmed_resend),
        overlap_excluded_count=len(overlap),
        eligible_count=len(desired_ids),
        add_ids=tuple(sorted(desired_ids - current_ids)),
        remove_ids=tuple(sorted(current_ids - desired_ids)),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-eligible", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    resend_key = os.environ.get("RESEND_API_KEY", "")
    kit_key = os.environ.get("KIT_API_KEY", "")
    segment_id = os.environ.get("RESEND_SEGMENT_CONFIRMED_ID", "")
    topic_id = os.environ.get("RESEND_TOPIC_GENERAL_ID", "")
    if not all((resend_key, kit_key, segment_id, topic_id)):
        raise RuntimeError("Required protected environment configuration is missing")

    resend = ResendClient(resend_key)
    kit = KitClient(kit_key)
    confirmed = resend.confirmed_emails(segment_id, topic_id)
    active = kit.active_subscribers()
    # Validate that the two providers overlap before allowing even the
    # reversible Kit-tag creation mutation.
    plan = build_plan(active, confirmed, [])
    tag = {"id": 0, "name": TAG_NAME}
    if args.apply:
        tag = kit.ensure_tag(TAG_NAME)
        current = kit.tag_subscribers(int(tag["id"]))
        plan = build_plan(active, confirmed, current)

    if args.expected_eligible:
        tolerance = max(2, round(args.expected_eligible * 0.15))
        if abs(plan.eligible_count - args.expected_eligible) > tolerance:
            raise RuntimeError("Eligible audience differs from the approved expectation")

    if args.apply:
        for subscriber_id in plan.add_ids:
            kit.add(int(tag["id"]), subscriber_id)
        for subscriber_id in plan.remove_ids:
            kit.remove(int(tag["id"]), subscriber_id)

    receipt = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "mode": "applied" if args.apply else "dry-run",
        "tagId": int(tag["id"]),
        "tagName": TAG_NAME,
        "activeKitSubscribers": plan.active_kit_count,
        "confirmedResendSubscribers": plan.confirmed_resend_count,
        "overlapExcluded": plan.overlap_excluded_count,
        "eligibleRecipients": plan.eligible_count,
        "taggedNow": len(plan.add_ids) if args.apply else 0,
        "untaggedNow": len(plan.remove_ids) if args.apply else 0,
    }
    serialized = json.dumps(receipt, indent=2) + "\n"
    if "@" in serialized:
        raise RuntimeError("Aggregate receipt contains address-like data")
    args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
