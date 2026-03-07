"""
This script performs a series of security probes against both the WSGI and ASGI versions of `ServeStatic` to check
for vulnerabilities. The results are printed in a report format, indicating whether each probe passed or failed
for both WSGI and ASGI implementations.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from servestatic import ServeStatic, ServeStaticASGI


@dataclass
class ProbeOutcome:
    expected: str
    wsgi_ok: bool | None
    asgi_ok: bool | None
    wsgi_detail: str
    asgi_detail: str


def fallback_wsgi_app(environ, start_response):
    status = "404 Not Found"
    headers = [("Content-Type", "text/plain; charset=utf-8")]
    start_response(status, headers)
    return [b"fallback"]


async def fallback_asgi_app(scope, receive, send):
    if scope["type"] != "http":
        msg = "fallback_asgi_app only supports HTTP"
        raise RuntimeError(msg)

    await send({
        "type": "http.response.start",
        "status": 404,
        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
    })
    await send({"type": "http.response.body", "body": b"fallback"})


def prepare_fixture() -> tuple[Path, Path, str, bool]:
    temp_root = Path(tempfile.mkdtemp(prefix="servestatic-security-"))
    static_root = temp_root / "static"
    static_root.mkdir(parents=True, exist_ok=True)
    (static_root / "with-index").mkdir(parents=True, exist_ok=True)

    (static_root / "app.js").write_text("console.log('ServeStatic security test app');\n", encoding="utf-8")
    (static_root / "app.js.gz").write_bytes(b"not-a-real-gzip-payload\n")
    (static_root / "with-index" / "index.html").write_text("<h1>index</h1>\n", encoding="utf-8")

    outside_marker = "OUTSIDE_FILE_MARKER"
    outside_file = temp_root / "outside-secret.txt"
    outside_file.write_text(outside_marker, encoding="utf-8")

    symlink_created = False
    symlink_path = static_root / "link-outside.txt"
    try:
        os.symlink(outside_file, symlink_path)
        symlink_created = True
    except (OSError, NotImplementedError):
        symlink_created = False

    return temp_root, static_root, outside_marker, symlink_created


def check_sync_probes(
    client: httpx.Client, outside_secret: str, symlink_created: bool
) -> dict[str, tuple[bool | None, str]]:
    outcomes: dict[str, tuple[bool | None, str]] = {}

    response = client.get("/static/app.js")
    ok = response.status_code == 200 and outside_secret.encode() not in response.content
    outcomes["baseline_static"] = (ok, f"status={response.status_code}")

    response = client.get("/static/%2e%2e/outside-secret.txt")
    ok = not (response.status_code == 200 and outside_secret.encode() in response.content)
    outcomes["path_traversal_encoded_dotdot"] = (ok, f"status={response.status_code}")

    response = client.get("/static/..\\outside-secret.txt")
    ok = not (response.status_code == 200 and outside_secret.encode() in response.content)
    outcomes["path_traversal_backslash"] = (ok, f"status={response.status_code}")

    response = client.get("/static/app.js.gz")
    ok = response.status_code != 200 or b"not-a-real-gzip-payload" not in response.content
    outcomes["direct_compressed_variant_request"] = (ok, f"status={response.status_code}")

    response = client.get("/static/app.js", headers={"Range": "bytes=999999-1000000"})
    ok = response.status_code == 416 and response.headers.get("Content-Range", "").startswith("bytes */")
    outcomes["invalid_range_request_handling"] = (
        ok,
        f"status={response.status_code}, content-range={response.headers.get('Content-Range')}",
    )

    response = client.get("/static/with-index/index.html?v=1%0d%0aInjected: yes", follow_redirects=False)
    location = response.headers.get("Location", "")
    ok = (
        response.status_code == 302
        and "v=1%0d%0aInjected:" in location
        and "\r" not in location
        and "\n" not in location
    )
    outcomes["redirect_query_header_injection_resistance"] = (
        ok,
        f"status={response.status_code}, location={location!r}",
    )

    response = client.get("/static/app.js%00.txt")
    ok = response.status_code != 200
    outcomes["null_byte_encoded_path"] = (ok, f"status={response.status_code}")

    if symlink_created:
        response = client.get("/static/link-outside.txt")
        ok = not (response.status_code == 200 and outside_secret.encode() in response.content)
        outcomes["symlink_escape_from_static_root"] = (ok, f"status={response.status_code}")
    else:
        outcomes["symlink_escape_from_static_root"] = (None, "skipped (symlink unavailable)")

    return outcomes


async def check_async_probes(
    client: httpx.AsyncClient, outside_secret: str, symlink_created: bool
) -> dict[str, tuple[bool | None, str]]:
    outcomes: dict[str, tuple[bool | None, str]] = {}

    response = await client.get("/static/app.js")
    ok = response.status_code == 200 and outside_secret.encode() not in response.content
    outcomes["baseline_static"] = (ok, f"status={response.status_code}")

    response = await client.get("/static/%2e%2e/outside-secret.txt")
    ok = not (response.status_code == 200 and outside_secret.encode() in response.content)
    outcomes["path_traversal_encoded_dotdot"] = (ok, f"status={response.status_code}")

    response = await client.get("/static/..\\outside-secret.txt")
    ok = not (response.status_code == 200 and outside_secret.encode() in response.content)
    outcomes["path_traversal_backslash"] = (ok, f"status={response.status_code}")

    response = await client.get("/static/app.js.gz")
    ok = response.status_code != 200 or b"not-a-real-gzip-payload" not in response.content
    outcomes["direct_compressed_variant_request"] = (ok, f"status={response.status_code}")

    response = await client.get("/static/app.js", headers={"Range": "bytes=999999-1000000"})
    ok = response.status_code == 416 and response.headers.get("Content-Range", "").startswith("bytes */")
    outcomes["invalid_range_request_handling"] = (
        ok,
        f"status={response.status_code}, content-range={response.headers.get('Content-Range')}",
    )

    response = await client.get("/static/with-index/index.html?v=1%0d%0aInjected: yes", follow_redirects=False)
    location = response.headers.get("Location", "")
    ok = (
        response.status_code == 302
        and "v=1%0d%0aInjected:" in location
        and "\r" not in location
        and "\n" not in location
    )
    outcomes["redirect_query_header_injection_resistance"] = (
        ok,
        f"status={response.status_code}, location={location!r}",
    )

    response = await client.get("/static/app.js%00.txt")
    ok = response.status_code != 200
    outcomes["null_byte_encoded_path"] = (ok, f"status={response.status_code}")

    if symlink_created:
        response = await client.get("/static/link-outside.txt")
        ok = not (response.status_code == 200 and outside_secret.encode() in response.content)
        outcomes["symlink_escape_from_static_root"] = (ok, f"status={response.status_code}")
    else:
        outcomes["symlink_escape_from_static_root"] = (None, "skipped (symlink unavailable)")

    return outcomes


def status_label(value: bool | None) -> str:
    if value is None:
        return "SKIP"
    return "PASS" if value else "FAIL"


def print_report(results: dict[str, ProbeOutcome]) -> None:
    print("# ServeStatic Security Probe Report")
    print()
    print("| Probe | Expected | WSGI | ASGI |")
    print("|---|---|---|---|")
    for probe_name, result in results.items():
        print(
            f"| {probe_name} | {result.expected} | {status_label(result.wsgi_ok)} ({result.wsgi_detail}) | "
            f"{status_label(result.asgi_ok)} ({result.asgi_detail}) |"
        )

    findings = []
    for probe_name, result in results.items():
        if result.wsgi_ok is False or result.asgi_ok is False:
            findings.append(probe_name)

    print()
    if findings:
        print("Potential Findings:")
        for finding in findings:
            print(f"- {finding}")
    else:
        print("No exploitable issues detected by this probe set.")


def run_probe() -> int:
    _temp_root, static_root, outside_secret, symlink_created = prepare_fixture()

    wsgi_app = ServeStatic(
        fallback_wsgi_app,
        root=static_root,
        prefix="/static/",
        index_file=True,
        autorefresh=True,
    )
    asgi_app = ServeStaticASGI(
        fallback_asgi_app,
        root=static_root,
        prefix="/static/",
        index_file=True,
        autorefresh=True,
    )

    with httpx.Client(
        transport=httpx.WSGITransport(app=wsgi_app, raise_app_exceptions=False),
        base_url="http://testserver",
        headers={"Accept-Encoding": "identity"},
    ) as wsgi_client:
        wsgi_results = check_sync_probes(wsgi_client, outside_secret, symlink_created)

    async def _run_asgi() -> dict[str, tuple[bool | None, str]]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi_app, raise_app_exceptions=False),
            base_url="http://testserver",
            headers={"Accept-Encoding": "identity"},
        ) as asgi_client:
            return await check_async_probes(asgi_client, outside_secret, symlink_created)

    asgi_results = asyncio.run(_run_asgi())

    expected_by_probe = {
        "baseline_static": "serves known static file",
        "path_traversal_encoded_dotdot": "must not escape static root",
        "path_traversal_backslash": "must reject backslash traversal",
        "direct_compressed_variant_request": "must not serve compressed variants directly",
        "invalid_range_request_handling": "must return 416 for invalid ranges",
        "redirect_query_header_injection_resistance": "must preserve query without CRLF header injection",
        "null_byte_encoded_path": "must not serve null-byte-encoded path",
        "symlink_escape_from_static_root": "should not allow symlink breakout",
    }

    combined: dict[str, ProbeOutcome] = {}
    for probe_name, expected in expected_by_probe.items():
        wsgi_ok, wsgi_detail = wsgi_results[probe_name]
        asgi_ok, asgi_detail = asgi_results[probe_name]
        combined[probe_name] = ProbeOutcome(expected, wsgi_ok, asgi_ok, wsgi_detail, asgi_detail)

    print_report(combined)

    failures = [name for name, result in combined.items() if result.wsgi_ok is False or result.asgi_ok is False]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run_probe())
