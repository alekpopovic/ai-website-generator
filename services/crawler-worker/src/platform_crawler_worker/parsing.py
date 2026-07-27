"""Bounded HTML metadata/link extraction and sitemap parsing."""

from __future__ import annotations

import zlib
from datetime import UTC, date, datetime
from urllib.parse import urljoin

from lxml import etree  # type: ignore[import-untyped]
from parsel import Selector

from platform_crawler_worker.models import HtmlMetadata, SitemapDocument, SitemapEntry


def _clean(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized[:maximum] or None


def extract_html_metadata(body: bytes, *, response_url: str) -> HtmlMetadata:
    selector = Selector(body=body, type="html", base_url=response_url)
    title = _clean(selector.css("title::text").get(), 500)
    description = _clean(
        selector.xpath(
            '//meta[translate(@name, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", '
            '"abcdefghijklmnopqrstuvwxyz")="description"]/@content'
        ).get(),
        1_000,
    )
    language = _clean(selector.css("html::attr(lang)").get(), 35)
    links: list[str] = []
    for href in selector.css("a[href]::attr(href)").getall():
        if len(href) <= 2_048:
            links.append(urljoin(response_url, href))
    canonical_link: str | None = None
    for element in selector.css("link[rel][href]"):
        relation = {token.casefold() for token in (element.attrib.get("rel") or "").split()}
        canonical_href = element.attrib.get("href")
        if "canonical" in relation and canonical_href and len(canonical_href) <= 2_048:
            canonical_link = urljoin(response_url, canonical_href)
            break
    hreflangs: list[tuple[str, str]] = []
    for element in selector.css("link[hreflang][href]")[:50]:
        hreflang = _clean(element.attrib.get("hreflang"), 35)
        alternate_href = element.attrib.get("href")
        if hreflang and alternate_href and len(alternate_href) <= 2_048:
            hreflangs.append((hreflang, urljoin(response_url, alternate_href)))
    return HtmlMetadata(
        title=title,
        description=description,
        language=language,
        links=tuple(links),
        canonical_link=canonical_link,
        hreflang_links=tuple(hreflangs),
    )


def _decompress_gzip(body: bytes, maximum_bytes: int) -> bytes:
    decompressor = zlib.decompressobj(wbits=31)
    try:
        result = decompressor.decompress(body, maximum_bytes + 1)
        if len(result) > maximum_bytes or decompressor.unconsumed_tail:
            raise ValueError("decompressed sitemap size limit exceeded")
        result += decompressor.flush(maximum_bytes + 1 - len(result))
    except zlib.error as error:
        raise ValueError("sitemap gzip stream is invalid") from error
    if len(result) > maximum_bytes or not decompressor.eof:
        raise ValueError("decompressed sitemap size limit exceeded")
    return result


def _last_modified(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    try:
        if "T" not in candidate:
            parsed_date = date.fromisoformat(candidate)
            return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC)
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


def _entries(root: etree._Element) -> tuple[SitemapEntry, ...]:
    entries: list[SitemapEntry] = []
    for element in root.xpath('./*[local-name()="url" or local-name()="sitemap"]'):
        locations = element.xpath('./*[local-name()="loc"]/text()')
        if not locations or not isinstance(locations[0], str) or not locations[0].strip():
            continue
        modified = element.xpath('./*[local-name()="lastmod"]/text()')
        entries.append(
            SitemapEntry(
                original_url=locations[0].strip(),
                last_modified_at=_last_modified(modified[0] if modified else None),
            )
        )
    return tuple(entries)


def parse_sitemap(
    body: bytes, *, maximum_urls: int = 50_000, maximum_bytes: int = 10 * 1_024 * 1_024
) -> SitemapDocument:
    """Parse bounded sitemap XML with entities and external resources disabled."""
    if len(body) > maximum_bytes:
        raise ValueError("sitemap compressed size limit exceeded")
    if body.startswith(b"\x1f\x8b"):
        body = _decompress_gzip(body, maximum_bytes)
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("sitemap document type declarations are forbidden")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, recover=False, huge_tree=False
    )
    try:
        root = etree.fromstring(body, parser=parser)
    except etree.XMLSyntaxError as error:
        raise ValueError("sitemap XML is invalid") from error
    root_name = etree.QName(root).localname
    entries = _entries(root)
    if len(entries) > maximum_urls:
        raise ValueError("sitemap URL limit exceeded")
    if root_name == "sitemapindex":
        return SitemapDocument(urls=(), child_sitemaps=entries)
    if root_name == "urlset":
        return SitemapDocument(urls=entries, child_sitemaps=())
    raise ValueError("unsupported sitemap root element")
