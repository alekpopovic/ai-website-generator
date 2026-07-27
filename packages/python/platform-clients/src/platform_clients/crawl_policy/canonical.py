"""Deterministic URL canonicalization and conservative crawl-trap detection."""

from __future__ import annotations

import fnmatch
import posixpath
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from platform_clients.crawl_policy.models import CrawlDecisionCode, CrawlPolicyConfig

_DOWNLOAD_SUFFIXES = frozenset(
    {
        ".7z",
        ".apk",
        ".avi",
        ".bin",
        ".csv",
        ".dmg",
        ".doc",
        ".docx",
        ".exe",
        ".gz",
        ".iso",
        ".mov",
        ".mp3",
        ".mp4",
        ".msi",
        ".pdf",
        ".ppt",
        ".pptx",
        ".rar",
        ".tar",
        ".tgz",
        ".wav",
        ".xls",
        ".xlsx",
        ".zip",
    }
)
_LOGOUT = re.compile(r"(?:^|/)(?:log[-_]?out|sign[-_]?out)(?:/|$)", re.I)
_ADMIN = re.compile(r"(?:^|/)(?:admin|administrator|wp-admin|wp-login)(?:/|$|\.)", re.I)
_ACCOUNT = re.compile(
    r"(?:^|/)(?:account|my-account|login|signin|sign-in|signup|sign-up|register|password-reset)(?:/|$)",
    re.I,
)
_CART = re.compile(r"(?:^|/)(?:cart/(?:add|remove|update)|checkout)(?:/|$)", re.I)
_CALENDAR = re.compile(r"(?:^|/)(?:calendar|events)/(?:19|20|21)\d{2}(?:/\d{1,2})?", re.I)


def canonicalize_url(value: str, config: CrawlPolicyConfig) -> str:
    """Normalize a public HTTP URL without performing DNS or network access."""
    if not value or value != value.strip() or "\\" in value or len(value) > 8_192:
        raise ValueError("invalid URL")
    parsed = urlsplit(value)
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("only absolute HTTP and HTTPS URLs are crawlable")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are forbidden")
    try:
        hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").casefold()
        port = parsed.port
    except (UnicodeError, ValueError) as error:
        raise ValueError("invalid URL hostname or port") from error
    if not hostname:
        raise ValueError("invalid URL hostname")
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        rendered_host = f"{rendered_host}:{port}"
    raw_path = re.sub(r"/{2,}", "/", parsed.path or "/")
    normalized_path = posixpath.normpath(raw_path)
    if raw_path.endswith("/") and normalized_path != "/":
        normalized_path += "/"
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path
    path = quote(normalized_path, safe="/%:@!$&'()*+,;=-._~")
    query_items = []
    for key, value_part in parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=500):
        folded = key.casefold()
        if folded in config.tracking_parameters or any(
            folded.startswith(prefix.casefold()) for prefix in config.tracking_parameter_prefixes
        ):
            continue
        query_items.append((key, value_part))
    query_items.sort(key=lambda item: (item[0].casefold(), item[0], item[1]))
    return urlunsplit((scheme, rendered_host, path, urlencode(query_items, doseq=True), ""))


def exclusion_reason(url: str, config: CrawlPolicyConfig) -> CrawlDecisionCode | None:
    parsed = urlsplit(url)
    path = parsed.path
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if _LOGOUT.search(path):
        return CrawlDecisionCode.LOGOUT
    if _ADMIN.search(path):
        return CrawlDecisionCode.ADMIN_AREA
    if _ACCOUNT.search(path):
        return CrawlDecisionCode.ACCOUNT_ACTION
    if _CART.search(path) or any(key.casefold() in {"add-to-cart", "remove_item"} for key in query):
        return CrawlDecisionCode.CART_MUTATION
    if any(path.casefold().endswith(suffix) for suffix in _DOWNLOAD_SUFFIXES):
        return CrawlDecisionCode.FILE_DOWNLOAD
    if (
        _CALENDAR.search(path)
        or sum(key.casefold() in {"date", "day", "month", "year"} for key in query) >= 2
    ):
        return CrawlDecisionCode.CALENDAR_TRAP
    if any(
        fnmatch.fnmatchcase(url, pattern) or fnmatch.fnmatchcase(path, pattern)
        for pattern in config.exclude_patterns
    ):
        return CrawlDecisionCode.EXCLUDE_PATTERN
    if config.include_patterns and not any(
        fnmatch.fnmatchcase(url, pattern) or fnmatch.fnmatchcase(path, pattern)
        for pattern in config.include_patterns
    ):
        return CrawlDecisionCode.INCLUDE_PATTERN_MISS
    return None
