"""Offline crawler activity, subprocess protocol, and parser tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from platform_crawler_worker.activities import CrawlActivities
from platform_crawler_worker.parsing import extract_html_metadata, parse_sitemap
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
    title, description, language, links = extract_html_metadata(
        body, response_url="https://fixture.example/"
    )
    assert title == "Northstar Studio Fixture"
    assert description is None
    assert language == "en"
    assert "https://fixture.example/pricing/" in links
    assert all(link.startswith("https://fixture.example/") for link in links)


async def test_fixture_urlset_and_sitemap_indexes_are_bounded() -> None:
    urlset = parse_sitemap((FIXTURE_SITE / "sitemap.xml").read_bytes())
    assert len(urlset.urls) == 10
    assert not urlset.child_sitemaps

    index = parse_sitemap(
        b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<sitemap><loc>https://fixture.example/child.xml</loc></sitemap></sitemapindex>"
    )
    assert index.child_sitemaps == ("https://fixture.example/child.xml",)
    with pytest.raises(ValueError, match="forbidden"):
        parse_sitemap(b'<!DOCTYPE x [<!ENTITY y SYSTEM "file:///etc/passwd">]><urlset/>')
