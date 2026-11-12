"""Local development report: banking route names and JSON structure only.

Never saves headers, cookies, query values, request values, response values,
or PDF bytes. Authentication endpoints are excluded before reading a body.
This is a diagnostic helper, not a downloader.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent
HOST = "banking.renault-bank-direkt.de"
AUTH = re.compile(r"services_auth|portal-oauth|oauth|(?:^|/)(?:login|logout|token|authenticate)(?:/|$)", re.I)


def identifier(value: str) -> str:
    if (re.search(r"\d{5,}", value)
            or re.fullmatch(r"[0-9a-f-]{16,}", value, re.I)
            or len(value) > 100):
        return "{id}"
    return value


def route(url: str):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != HOST or AUTH.search(parts.path):
        return None
    return {
        "path": "/".join(identifier(part) for part in parts.path.split("/")),
        "query_keys": sorted({identifier(key) for key, _ in parse_qsl(parts.query)}),
    }


def schema(value, depth=0):
    if depth >= 10:
        return "nested"
    if isinstance(value, dict):
        return {identifier(str(k)): schema(v, depth + 1)
                for k, v in list(value.items())[:100]}
    if isinstance(value, list):
        return {"array_length": len(value),
                "sample_structure": schema(value[0], depth + 1) if value else None}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def main():
    cfg = json.loads((APP / "config.json").read_text())
    out = APP / "Diagnostics" / "technical-structure.json"
    entries = []
    seen = set()
    done = threading.Event()

    def save():
        out.parent.mkdir(parents=True, exist_ok=True)
        temporary = out.with_suffix(".tmp")
        temporary.write_text(json.dumps({"kind": "renault-technical-structure",
                                         "requests": entries}, indent=2), encoding="utf-8")
        temporary.replace(out)

    def response_received(response):
        location = route(response.url)
        if location is None or len(entries) >= 200:
            return
        content_type = response.header_value("content-type") or ""
        if "json" not in content_type and "pdf" not in content_type:
            return
        request = response.request
        entry = {**location, "method": request.method, "status": response.status,
                 "type": "pdf" if "pdf" in content_type else "json"}
        # Payloads are transformed to their schema in memory; their values
        # are never printed or written. A PDF body is never read.
        try:
            payload = request.post_data
            if payload:
                entry["request_structure"] = schema(json.loads(payload))
        except (ValueError, TypeError):
            entry["request_structure"] = "non-json (not captured)"
        if entry["type"] == "json":
            try:
                size = int(response.header_value("content-length") or 0)
                if size > 2_000_000:
                    entry["response_structure"] = "too large (not captured)"
                else:
                    entry["response_structure"] = schema(response.json())
            except Exception:
                entry["response_structure"] = "unavailable"
        key = json.dumps(entry, sort_keys=True)
        if key not in seen:
            seen.add(key)
            entries.append(entry)
            save()
            print(f"Technical request {len(entries)} captured.", flush=True)

    def wait_for_enter():
        try:
            input()
        finally:
            done.set()

    with sync_playwright() as p:
        # Observe the existing session without applying Playwright's context
        # defaults (including Browser.setDownloadBehavior). Some CDP browsers
        # cannot change context settings; this report needs none of them.
        browser = p.chromium.connect_over_cdp(cfg["cdp_url"], no_defaults=True)
        pages = [page for context in browser.contexts for page in context.pages
                 if urlsplit(page.url).hostname == HOST]
        if not pages:
            raise SystemExit("Open the Renault sign-in window and sign in first.")
        page = pages[-1]
        for context in browser.contexts:
            context.on("response", response_received)
        print("Open the Postfach, change one document tab and download one PDF.")
        print("Then return here and press Enter. Authentication requests are excluded.")
        threading.Thread(target=wait_for_enter, daemon=True).start()
        try:
            while not done.is_set():
                page.wait_for_timeout(250)
        except KeyboardInterrupt:
            pass
        finally:
            for context in browser.contexts:
                context.remove_listener("response", response_received)
            save()
        # Do not close the person's browser or its tabs.
    print(f"Saved {len(entries)} technical request structures to {out}")


if __name__ == "__main__":
    main()
