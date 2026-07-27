"""Offline URL, DNS, redirect, peer, response, timeout, and audit safety tests."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator

import pytest
from platform_clients.network_safety import (
    AssetInspectionSafety,
    NetworkFailureCode,
    NetworkLimits,
    NetworkRequestContext,
    NetworkSafetyError,
    NetworkSafetyPolicy,
    NetworkSafetySubsystem,
    NetworkTimeouts,
    PlaywrightRequestSafety,
    PublishingIntegrationSafety,
    RecordingNetworkSafetyAuditor,
    ScrapyRequestSafety,
    SequenceDnsResolver,
    SystemDnsResolver,
    bounded_body,
    validate_html_response_headers,
    with_browser_navigation_timeout,
    with_connection_timeout,
    with_total_timeout,
)

pytestmark = pytest.mark.anyio
PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:4700:4700::1111"


def context(*, admin: bool = False) -> NetworkRequestContext:
    return NetworkRequestContext(
        component="test-scanner",
        request_id="request-1",
        project_id="project-1",
        administrator_port_access=admin,
    )


async def failure(
    safety: NetworkSafetySubsystem,
    url: str,
    expected: NetworkFailureCode,
    *,
    request_context: NetworkRequestContext | None = None,
) -> NetworkSafetyError:
    with pytest.raises(NetworkSafetyError) as caught:
        await safety.prepare(url, request_context or context())
    assert caught.value.code is expected
    return caught.value


async def test_only_http_https_without_credentials_are_accepted() -> None:
    resolver = SequenceDnsResolver({"example.com": [[PUBLIC_V4, PUBLIC_V6]]})
    safety = NetworkSafetySubsystem(resolver)

    approved = await safety.prepare("HTTPS://Example.COM./path?q=1#fragment", context())

    assert approved.url == "https://example.com/path?q=1"
    assert {str(address) for address in approved.addresses} == {PUBLIC_V4, PUBLIC_V6}
    await failure(safety, "ftp://example.com/file", NetworkFailureCode.SCHEME_NOT_ALLOWED)
    await failure(
        safety,
        "https://user:password@example.com/private",  # pragma: allowlist secret
        NetworkFailureCode.CREDENTIALS_NOT_ALLOWED,
    )


@pytest.mark.parametrize(
    "address",
    [
        "0.0.0.0",  # noqa: S104 - security rejection fixture
        "10.0.0.1",
        "100.64.0.1",
        "127.0.0.1",
        "169.254.1.1",
        "172.16.0.1",
        "192.168.0.1",
        "192.0.2.1",
        "224.0.0.1",
        "240.0.0.1",
    ],
)
async def test_blocks_non_global_ipv4_classes(address: str) -> None:
    await failure(
        NetworkSafetySubsystem(SequenceDnsResolver({})),
        f"http://{address}/",
        NetworkFailureCode.ADDRESS_BLOCKED,
    )


@pytest.mark.parametrize(
    "address",
    [
        "::",
        "::1",
        "::ffff:127.0.0.1",
        "64:ff9b::7f00:1",
        "2002:7f00:1::",
        "fc00::1",
        "fd12:3456::1",
        "fe80::1",
        "ff02::1",
        "2001:db8::1",
    ],
)
async def test_blocks_non_global_ipv6_classes(address: str) -> None:
    await failure(
        NetworkSafetySubsystem(SequenceDnsResolver({})),
        f"https://[{address}]/",
        NetworkFailureCode.ADDRESS_BLOCKED,
    )


@pytest.mark.parametrize("encoded", ["2130706433", "0177.0.0.1", "0x7f000001", "127.1"])
async def test_blocks_legacy_encoded_ipv4_forms(encoded: str) -> None:
    await failure(
        NetworkSafetySubsystem(SequenceDnsResolver({})),
        f"http://{encoded}/",
        NetworkFailureCode.ENCODED_IP_BLOCKED,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://localhost.localdomain/",
        "http://service.internal/",
        "http://printer.lan/",
    ],
)
async def test_blocks_localhost_and_internal_only_suffixes(url: str) -> None:
    await failure(
        NetworkSafetySubsystem(SequenceDnsResolver({})),
        url,
        NetworkFailureCode.HOSTNAME_BLOCKED,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.170.2/v2/credentials",
        "http://100.100.100.200/latest/meta-data/",
        "http://[fd00:ec2::254]/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
    ],
)
async def test_blocks_cloud_metadata_addresses_and_names(url: str) -> None:
    await failure(
        NetworkSafetySubsystem(SequenceDnsResolver({})),
        url,
        NetworkFailureCode.METADATA_ENDPOINT_BLOCKED,
    )


async def test_resolves_every_a_and_aaaa_and_rejects_mixed_scope_answers() -> None:
    accepted_resolver = SequenceDnsResolver({"dual.example": [[PUBLIC_V4, PUBLIC_V6]]})
    accepted = await NetworkSafetySubsystem(accepted_resolver).prepare(
        "https://dual.example/", context()
    )
    assert len(accepted.addresses) == 2

    mixed_resolver = SequenceDnsResolver({"mixed.example": [[PUBLIC_V4, "127.0.0.1"]]})
    await failure(
        NetworkSafetySubsystem(mixed_resolver),
        "https://mixed.example/",
        NetworkFailureCode.DNS_MIXED_SCOPE,
    )


async def test_dns_transport_failures_are_typed_and_audited() -> None:
    auditor = RecordingNetworkSafetyAuditor()
    resolver = SequenceDnsResolver({"failed.example": [OSError("resolver detail")]})
    safety = NetworkSafetySubsystem(resolver, auditor=auditor)

    await failure(
        safety,
        "https://failed.example/",
        NetworkFailureCode.DNS_RESOLUTION_FAILED,
    )
    assert auditor.events[0].failure_code is NetworkFailureCode.DNS_RESOLUTION_FAILED


async def test_system_resolver_collects_all_a_and_aaaa_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeLoop:
        async def getaddrinfo(self, *_args: object, **kwargs: object) -> list[tuple[object, ...]]:
            if kwargs["family"] == socket.AF_INET:
                return [
                    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (PUBLIC_V4, 443))
                ]
            return [
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    (PUBLIC_V6, 443, 0, 0),
                )
            ]

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    addresses = await SystemDnsResolver().resolve("dual.example", 443)

    assert {str(address) for address in addresses} == {PUBLIC_V4, PUBLIC_V6}


async def test_revalidates_dns_before_connection_and_detects_rebinding() -> None:
    resolver = SequenceDnsResolver(
        {"rebind.example": [[PUBLIC_V4, PUBLIC_V6], [PUBLIC_V4, "127.0.0.1"]]}
    )
    safety = NetworkSafetySubsystem(resolver)
    approved = await safety.prepare("https://rebind.example/", context())

    with pytest.raises(NetworkSafetyError) as caught:
        await safety.revalidate_before_connection(approved, context())
    assert caught.value.code is NetworkFailureCode.DNS_REBINDING
    assert resolver.calls == [("rebind.example", 443), ("rebind.example", 443)]


async def test_peer_address_must_match_the_pinned_dns_set() -> None:
    resolver = SequenceDnsResolver({"peer.example": [[PUBLIC_V4]]})
    safety = NetworkSafetySubsystem(resolver)
    approved = await safety.prepare("https://peer.example/", context())

    with pytest.raises(NetworkSafetyError) as caught:
        await safety.revalidate_before_connection(approved, context(), peer_address="1.1.1.1")
    assert caught.value.code is NetworkFailureCode.PEER_ADDRESS_MISMATCH


async def test_every_redirect_is_resolved_and_redirect_count_is_bounded() -> None:
    resolver = SequenceDnsResolver({"public.example": [[PUBLIC_V4]], "next.example": [[PUBLIC_V6]]})
    safety = NetworkSafetySubsystem(
        resolver, policy=NetworkSafetyPolicy(limits=NetworkLimits(max_redirects=1))
    )
    initial = await safety.prepare("https://public.example/start", context())
    redirected = await safety.prepare_redirect(
        initial, "https://next.example/final", redirect_count=0, context=context()
    )
    assert redirected.hostname == "next.example"
    assert resolver.calls[-1] == ("next.example", 443)

    with pytest.raises(NetworkSafetyError) as limited:
        await safety.prepare_redirect(redirected, "/again", redirect_count=1, context=context())
    assert limited.value.code is NetworkFailureCode.REDIRECT_LIMIT_EXCEEDED

    with pytest.raises(NetworkSafetyError) as blocked:
        await safety.prepare_redirect(
            initial, "http://127.0.0.1/admin", redirect_count=0, context=context()
        )
    assert blocked.value.code is NetworkFailureCode.ADDRESS_BLOCKED


async def test_nonstandard_ports_require_both_configuration_and_admin_context() -> None:
    resolver = SequenceDnsResolver({"ports.example": [[PUBLIC_V4]]})
    policy = NetworkSafetyPolicy(administrator_ports=frozenset({8443}))
    safety = NetworkSafetySubsystem(resolver, policy=policy)

    await failure(safety, "https://ports.example:8443/", NetworkFailureCode.PORT_BLOCKED)
    approved = await safety.prepare("https://ports.example:8443/", context(admin=True))
    assert approved.port == 8443


def test_rejects_large_headers_large_bodies_and_non_html_before_processing() -> None:
    limits = NetworkLimits(max_response_header_bytes=1024, max_response_body_bytes=2048)
    validated = validate_html_response_headers(
        {"Content-Type": "text/html; charset=utf-8", "Content-Length": "1024"}, limits
    )
    assert validated.content_type == "text/html"

    with pytest.raises(NetworkSafetyError) as non_html:
        validate_html_response_headers({"Content-Type": "image/png"}, limits)
    assert non_html.value.code is NetworkFailureCode.CONTENT_TYPE_NOT_HTML
    with pytest.raises(NetworkSafetyError) as large_headers:
        validate_html_response_headers(
            {"Content-Type": "text/html", "X-Large": "x" * 2_000}, limits
        )
    assert large_headers.value.code is NetworkFailureCode.RESPONSE_HEADERS_TOO_LARGE
    with pytest.raises(NetworkSafetyError) as large_declared_body:
        validate_html_response_headers(
            {"Content-Type": "text/html", "Content-Length": "2049"}, limits
        )
    assert large_declared_body.value.code is NetworkFailureCode.RESPONSE_BODY_TOO_LARGE
    with pytest.raises(NetworkSafetyError) as ambiguous:
        validate_html_response_headers(
            [("Content-Type", "text/html"), ("content-type", "image/png")], limits
        )
    assert ambiguous.value.code is NetworkFailureCode.RESPONSE_HEADERS_INVALID


async def test_streamed_body_size_and_read_timeout_are_enforced() -> None:
    limits = NetworkLimits(
        max_response_body_bytes=1024,
        timeouts=NetworkTimeouts(
            connect_seconds=0.1,
            read_seconds=0.1,
            total_seconds=0.2,
            browser_navigation_seconds=0.1,
        ),
    )

    async def too_large() -> AsyncIterator[bytes]:
        yield b"a" * 800
        yield b"b" * 300

    with pytest.raises(NetworkSafetyError) as oversized:
        _ = b"".join([chunk async for chunk in bounded_body(too_large(), limits)])
    assert oversized.value.code is NetworkFailureCode.RESPONSE_BODY_TOO_LARGE

    async def slow() -> AsyncIterator[bytes]:
        await asyncio.sleep(0.2)
        yield b"late"

    with pytest.raises(NetworkSafetyError) as timed_out:
        _ = [chunk async for chunk in bounded_body(slow(), limits)]
    assert timed_out.value.code is NetworkFailureCode.READ_TIMEOUT


async def test_connection_and_browser_navigation_timeout_codes_are_typed() -> None:
    limits = NetworkLimits(
        timeouts=NetworkTimeouts(
            connect_seconds=0.1,
            read_seconds=0.1,
            total_seconds=0.2,
            browser_navigation_seconds=0.1,
        )
    )

    async def slow_operation() -> str:
        await asyncio.sleep(0.3)
        return "late"

    with pytest.raises(NetworkSafetyError) as connection:
        await with_connection_timeout(slow_operation(), limits)
    assert connection.value.code is NetworkFailureCode.CONNECTION_TIMEOUT
    with pytest.raises(NetworkSafetyError) as browser:
        await with_browser_navigation_timeout(slow_operation(), limits)
    assert browser.value.code is NetworkFailureCode.BROWSER_NAVIGATION_TIMEOUT

    with pytest.raises(NetworkSafetyError) as total:
        await with_total_timeout(slow_operation(), limits)
    assert total.value.code is NetworkFailureCode.TOTAL_TIMEOUT


async def test_blocked_requests_emit_sanitized_audit_events() -> None:
    auditor = RecordingNetworkSafetyAuditor()
    safety = NetworkSafetySubsystem(SequenceDnsResolver({}), auditor=auditor)

    await failure(
        safety,
        "https://user:password@localhost/private?token=secret",  # pragma: allowlist secret
        NetworkFailureCode.CREDENTIALS_NOT_ALLOWED,
    )

    assert len(auditor.events) == 1
    event = auditor.events[0]
    assert event.action == "network.request_blocked"
    assert event.failure_code is NetworkFailureCode.CREDENTIALS_NOT_ALLOWED
    assert event.safe_url == "https://localhost/"
    assert "password" not in event.safe_url
    assert "secret" not in event.safe_url


async def test_response_policy_blocks_are_audited_through_consumer_adapter() -> None:
    auditor = RecordingNetworkSafetyAuditor()
    safety = NetworkSafetySubsystem(
        SequenceDnsResolver({"content.example": [[PUBLIC_V4]]}), auditor=auditor
    )
    adapter = ScrapyRequestSafety(safety)
    request_context = adapter.context(request_id="request-2")
    approved = await adapter.initial("https://content.example/image", request_context)

    with pytest.raises(NetworkSafetyError) as caught:
        await adapter.html_response(approved, {"Content-Type": "image/png"}, request_context)
    assert caught.value.code is NetworkFailureCode.CONTENT_TYPE_NOT_HTML
    assert auditor.events[-1].failure_code is NetworkFailureCode.CONTENT_TYPE_NOT_HTML


async def test_consumer_adapters_share_identical_policy_with_distinct_audit_components() -> None:
    resolver = SequenceDnsResolver({"shared.example": [[PUBLIC_V4]]})
    safety = NetworkSafetySubsystem(resolver)

    adapters = (
        ScrapyRequestSafety(safety),
        PlaywrightRequestSafety(safety),
        AssetInspectionSafety(safety),
        PublishingIntegrationSafety(safety),
    )
    for adapter in adapters:
        request_context = adapter.context(request_id="request-1")
        approved = await adapter.initial("https://shared.example/", request_context)
        approved = await adapter.before_connection(approved, request_context)
        headers = await adapter.html_response(
            approved, {"Content-Type": "text/html"}, request_context
        )
        assert headers.content_type == "text/html"
    assert [adapter.component for adapter in adapters] == [
        "scrapy",
        "playwright",
        "asset-inspection",
        "publishing",
    ]
