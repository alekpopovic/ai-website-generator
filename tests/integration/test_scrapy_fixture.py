"""Opt-in reachability contract for the local fixture used by Scrapy integration runs."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx2
import pytest
from platform_crawler_worker.parsing import extract_html_metadata, parse_sitemap

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_local_fixture_exposes_crawlable_html_robots_and_sitemap() -> None:
    base_url = os.environ.get("INTEGRATION_FIXTURE_WEBSITE_URL")
    if base_url is None:
        pytest.skip("INTEGRATION_FIXTURE_WEBSITE_URL is not configured")
    async with httpx2.AsyncClient(timeout=5, follow_redirects=False) as client:
        robots = await client.get(f"{base_url.rstrip('/')}/robots.txt")
        sitemap = await client.get(f"{base_url.rstrip('/')}/sitemap.xml")
        home = await client.get(f"{base_url.rstrip('/')}/")
    assert robots.status_code == 200 and "Sitemap:" in robots.text
    assert len(parse_sitemap(sitemap.content).urls) >= 6
    title, _, language, links = extract_html_metadata(home.content, response_url=str(home.url))
    assert title == "Northstar Studio Fixture"
    assert language == "en"
    assert len(links) >= 5

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).parents[1] / "support" / "run_fixture_scrapy.py"),
        base_url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(process.communicate(), timeout=45)
    assert process.returncode == 0
    summaries = [json.loads(line) for line in stdout.splitlines() if b'"event": "summary"' in line]
    assert summaries and summaries[-1]["pages"] >= 6
    assert "Northstar Studio Fixture" in summaries[-1]["titles"]
