"""Thin consumer adapters ensuring every outbound integration uses the same policy."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping

from platform_clients.network_safety.models import (
    ApprovedUrl,
    NetworkRequestContext,
    ValidatedResponseHeaders,
)
from platform_clients.network_safety.policy import NetworkSafetySubsystem


class OutboundRequestSafetyAdapter:
    """Shared shape used by Scrapy, Playwright, assets, redirects, and publishing connectors."""

    component = "outbound"

    def __init__(self, safety: NetworkSafetySubsystem) -> None:
        self._safety = safety

    def context(
        self,
        *,
        request_id: str | None = None,
        project_id: str | None = None,
        administrator_port_access: bool = False,
    ) -> NetworkRequestContext:
        return NetworkRequestContext(
            component=self.component,
            request_id=request_id,
            project_id=project_id,
            administrator_port_access=administrator_port_access,
        )

    async def initial(self, url: str, context: NetworkRequestContext) -> ApprovedUrl:
        return await self._safety.prepare(url, context)

    async def redirect(
        self,
        previous: ApprovedUrl,
        location: str,
        redirect_count: int,
        context: NetworkRequestContext,
    ) -> ApprovedUrl:
        return await self._safety.prepare_redirect(
            previous,
            location,
            redirect_count=redirect_count,
            context=context,
        )

    async def before_connection(
        self,
        approved: ApprovedUrl,
        context: NetworkRequestContext,
        *,
        peer_address: str | None = None,
    ) -> ApprovedUrl:
        return await self._safety.revalidate_before_connection(
            approved, context, peer_address=peer_address
        )

    async def html_response(
        self,
        approved: ApprovedUrl,
        headers: Mapping[str, str] | Iterable[tuple[str, str]],
        context: NetworkRequestContext,
    ) -> ValidatedResponseHeaders:
        return await self._safety.validate_html_response(approved, headers, context)

    async def body(
        self,
        approved: ApprovedUrl,
        source: AsyncIterable[bytes],
        context: NetworkRequestContext,
    ) -> AsyncIterator[bytes]:
        async for chunk in self._safety.stream_bounded_body(approved, source, context):
            yield chunk


class ScrapyRequestSafety(OutboundRequestSafetyAdapter):
    component = "scrapy"


class PlaywrightRequestSafety(OutboundRequestSafetyAdapter):
    component = "playwright"


class AssetInspectionSafety(OutboundRequestSafetyAdapter):
    component = "asset-inspection"


class PublishingIntegrationSafety(OutboundRequestSafetyAdapter):
    component = "publishing"
