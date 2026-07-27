"""Bounded HTML metadata/link extraction and sitemap parsing."""

from __future__ import annotations

from urllib.parse import urljoin

from lxml import etree  # type: ignore[import-untyped]
from parsel import Selector

from platform_crawler_worker.models import SitemapDocument


def _clean(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized[:maximum] or None


def extract_html_metadata(
    body: bytes, *, response_url: str
) -> tuple[str | None, str | None, str | None, tuple[str, ...]]:
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
    return title, description, language, tuple(links)


def parse_sitemap(body: bytes, *, maximum_urls: int = 10_000) -> SitemapDocument:
    """Parse bounded sitemap XML with entities and external resources disabled."""
    if len(body) > 10 * 1_024 * 1_024:
        raise ValueError("sitemap exceeds 10 MiB")
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
    locations = tuple(
        value.strip()
        for value in root.xpath('//*[local-name()="loc"]/text()')
        if isinstance(value, str) and value.strip()
    )
    if len(locations) > maximum_urls:
        raise ValueError("sitemap URL limit exceeded")
    if root_name == "sitemapindex":
        return SitemapDocument(urls=(), child_sitemaps=locations)
    if root_name == "urlset":
        return SitemapDocument(urls=locations, child_sitemaps=())
    raise ValueError("unsupported sitemap root element")
