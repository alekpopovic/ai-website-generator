"""Offline crawler activity, subprocess protocol, and parser tests."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from platform_clients.object_storage import (
    Bucket,
    InMemoryObjectStorage,
    ObjectLocation,
    UploadRequest,
)
from platform_crawler_worker.activities import CrawlActivities
from platform_crawler_worker.fingerprinting import (
    FingerprintRecord,
    compute_page_fingerprints,
    group_fingerprints,
)
from platform_crawler_worker.parsing import extract_html_metadata, parse_sitemap
from platform_crawler_worker.repository import CrawlRepository
from platform_crawler_worker.runner import FakeCrawlerRunner, SubprocessCrawlerRunner
from platform_workflows.commands import CrawlTargetInput
from temporalio.testing import ActivityEnvironment

pytestmark = pytest.mark.anyio
FIXTURE_SITE = Path(__file__).parents[3] / "tests" / "fixtures" / "websites" / "site"


async def test_fake_crawler_activity_heartbeats_compact_progress() -> None:
    fake = FakeCrawlerRunner(progress_values=(1, 3))
    environment = ActivityEnvironment()
    heartbeats: list[tuple[object, ...]] = []
    environment.on_heartbeat = lambda *details: heartbeats.append(details)
    command = CrawlTargetInput(campaign_id=str(uuid4()), scan_target_id=str(uuid4()))

    result = await environment.run(CrawlActivities(fake).crawl_scan_target, command)

    assert result.record_id == command.scan_target_id
    assert fake.commands == [command]
    assert heartbeats == [
        ({"stage": "crawl-scan-target", "completed": 1},),
        ({"stage": "crawl-scan-target", "completed": 3},),
    ]


async def test_subprocess_output_accepts_only_bounded_progress_json() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b'{"event":"progress","completed":2}\n')
    reader.feed_data(b"hostile unstructured output\n")
    reader.feed_data(b"x" * 5_000 + b"\n")
    reader.feed_eof()
    completed: list[int] = []

    async def progress(value: int) -> None:
        completed.append(value)

    await SubprocessCrawlerRunner(maximum_line_bytes=128)._read_progress(reader, progress)
    assert completed == [2]


async def test_subprocess_cancellation_terminates_child(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self.finished = asyncio.Event()
            self.terminated = False
            self.killed = False

        async def wait(self) -> int:
            await self.finished.wait()
            return -15

        def terminate(self) -> None:
            self.terminated = True
            self.finished.set()

        def kill(self) -> None:
            self.killed = True
            self.finished.set()

    process = FakeProcess()

    async def create(*args: object, **kwargs: object) -> Any:
        del args, kwargs
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    command = CrawlTargetInput(campaign_id=str(uuid4()), scan_target_id=str(uuid4()))
    task = asyncio.create_task(SubprocessCrawlerRunner().crawl(command))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.terminated
    assert not process.killed


async def test_fixture_html_metadata_and_internal_links_are_extracted() -> None:
    body = (FIXTURE_SITE / "index.html").read_bytes()
    metadata = extract_html_metadata(body, response_url="https://fixture.example/")
    assert metadata.title == "Northstar Studio Fixture"
    assert metadata.description is None
    assert metadata.language == "en"
    assert "https://fixture.example/pricing/" in metadata.links
    assert all(link.startswith("https://fixture.example/") for link in metadata.links)


async def test_fixture_urlset_and_sitemap_indexes_are_bounded() -> None:
    urlset = parse_sitemap((FIXTURE_SITE / "sitemap.xml").read_bytes())
    assert len(urlset.urls) == 10
    assert not urlset.child_sitemaps

    index = parse_sitemap(
        b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<sitemap><loc>https://fixture.example/child.xml</loc></sitemap></sitemapindex>"
    )
    assert index.child_sitemaps[0].original_url == "https://fixture.example/child.xml"
    with pytest.raises(ValueError, match="forbidden"):
        parse_sitemap(b'<!DOCTYPE x [<!ENTITY y SYSTEM "file:///etc/passwd">]><urlset/>')


async def test_sitemap_gzip_lastmod_and_decompression_limits() -> None:
    xml = (
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url>'
        b"<loc>https://fixture.example/Page%2fOne</loc><lastmod>2026-07-27T22:15:00Z</lastmod>"
        b"</url></urlset>"
    )
    document = parse_sitemap(gzip.compress(xml), maximum_bytes=2_000)
    assert document.urls[0].original_url == "https://fixture.example/Page%2fOne"
    assert document.urls[0].last_modified_at == datetime(2026, 7, 27, 22, 15, tzinfo=UTC)
    with pytest.raises(ValueError, match="size limit"):
        parse_sitemap(gzip.compress(b" " * 4_000), maximum_bytes=1_024)


async def test_canonical_and_hreflang_metadata_is_bounded_and_resolved() -> None:
    metadata = extract_html_metadata(
        b'<html lang="en"><head><link rel="alternate canonical" href="../Preferred" />'
        b'<link rel="alternate" hreflang="fr" href="/fr/page" /></head></html>',
        response_url="https://example.com/products/current",
    )
    assert metadata.canonical_link == "https://example.com/Preferred"
    assert metadata.hreflang_links == (("fr", "https://example.com/fr/page"),)


async def test_dynamic_noise_is_removed_without_erasing_semantic_structure() -> None:
    first = f"""<html><head><script>analytics('one')</script></head><body>
        <main id="render-123456"><h1>Release notes</h1>
        <p>Updated 2026-07-27T22:15:00Z</p>
        <input name="csrf" value="{"0" * 32}" /></main></body></html>""".encode()
    second = f"""<html><head><script>analytics('two')</script></head><body>
        <main id="render-987654"><h1>Release notes</h1>
        <p>Updated 2026-07-28T09:30:00Z</p>
        <input name="csrf" value="{"a" * 32}" /></main></body></html>""".encode()
    left = compute_page_fingerprints(
        first, normalized_url="https://example.test/a", response_url="https://example.test/a"
    )
    right = compute_page_fingerprints(
        second, normalized_url="https://example.test/b", response_url="https://example.test/b"
    )
    assert left.response_body_sha256 != right.response_body_sha256
    assert left.normalized_content_sha256 == right.normalized_content_sha256
    assert left.heading_sequence_sha256 == right.heading_sequence_sha256


async def test_repeated_fixture_articles_share_a_template() -> None:
    paths = sorted(path for path in (FIXTURE_SITE / "blog").glob("*/index.html"))
    fingerprints = [
        compute_page_fingerprints(
            path.read_bytes(),
            normalized_url=f"https://fixture.example/blog/{path.parent.name}/",
            response_url=f"https://fixture.example/blog/{path.parent.name}/",
        )
        for path in paths
    ]
    assert len(fingerprints) == 3
    assert len({item.dom_template_sha256 for item in fingerprints}) == 1
    assert len({item.visible_text_sha256 for item in fingerprints}) == 3


async def test_grouping_selects_stable_exact_near_and_template_representatives() -> None:
    base = "A bounded deterministic fingerprint should ignore runtime noise and preserve meaning. "
    pages = (
        ("https://example.test/z", f"<main><h1>Guide</h1><p>{base * 8}</p></main>"),
        ("https://example.test/a", f"<main><h1>Guide</h1><p>{base * 8}</p></main>"),
        (
            "https://example.test/m",
            f"<main><h1>Guide</h1><p>{base * 7}One sentence changed.</p></main>",
        ),
    )
    records = []
    for index, (url, body) in enumerate(pages, start=1):
        fingerprint = compute_page_fingerprints(body.encode(), normalized_url=url, response_url=url)
        records.append(
            FingerprintRecord(
                id=UUID(int=index),
                normalized_url=url,
                normalized_content_sha256=fingerprint.normalized_content_sha256,
                semantic_simhash=fingerprint.semantic_simhash,
                dom_template_sha256=fingerprint.dom_template_sha256,
                normalized_text_length=fingerprint.normalized_text_length,
            )
        )
    assignments = {item.page_id: item for item in group_fingerprints(tuple(records))}
    assert assignments[UUID(int=1)].exact_duplicate_of_id == UUID(int=2)
    assert assignments[UUID(int=3)].near_duplicate_of_id == UUID(int=2)
    assert all(item.template_representative_id == UUID(int=2) for item in assignments.values())
    assert group_fingerprints(tuple(reversed(records))) == tuple(assignments.values())


async def test_backfill_download_verifies_and_bounds_gzip_artifact() -> None:
    storage = InMemoryObjectStorage()
    location = ObjectLocation(Bucket.SCAN_ARTIFACTS, "scans/test/page/raw.html.gz")
    body = b"<html><body><main><h1>Retained source</h1></main></body></html>"
    compressed = gzip.compress(body)

    async def chunks() -> AsyncIterator[bytes]:
        yield compressed

    await storage.upload(
        location,
        chunks(),
        UploadRequest(
            expected_sha256=hashlib.sha256(compressed).hexdigest(),
            content_type="text/html",
            content_encoding="gzip",
        ),
    )
    repository = CrawlRepository(cast(Any, object()), storage)
    assert await repository._download_gzip_html(location.key) == body
