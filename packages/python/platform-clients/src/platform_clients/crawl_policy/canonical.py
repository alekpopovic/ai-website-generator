"""Deterministic URL canonicalization and conservative crawl-trap detection."""

from __future__ import annotations

import fnmatch
import re
from collections import Counter
from urllib.parse import quote_from_bytes, unquote_to_bytes, urlsplit, urlunsplit

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
_PAGINATION_PATH = re.compile(r"(?:^|/)(?:page|p)/(\d+)(?:/|$)", re.I)
_SESSION_PATH = re.compile(r"(?:;|/)(?:jsessionid|phpsessid|sessionid)=", re.I)
_HEX_ESCAPE = re.compile(rb"%([0-9a-fA-F]{2})")
_UNRESERVED = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_SESSION_KEYS = frozenset({"jsessionid", "phpsessid", "session", "session_id", "sessionid", "sid"})
_FACET_KEYS = frozenset(
    {"attribute", "brand", "category", "color", "facet", "filter", "material", "size", "sort"}
)
_PAGINATION_KEYS = frozenset({"offset", "p", "page", "paged", "start"})


def _normalize_percent_encoded(value: str, *, safe: bytes) -> str:
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("URL contains invalid Unicode") from error

    def replace(match: re.Match[bytes]) -> bytes:
        octet = int(match.group(1), 16)
        return bytes((octet,)) if octet in _UNRESERVED else f"%{octet:02X}".encode()

    normalized = _HEX_ESCAPE.sub(replace, raw)
    if re.search(rb"%(?![0-9A-Fa-f]{2})", normalized):
        raise ValueError("URL contains malformed percent encoding")
    return quote_from_bytes(normalized, safe=(safe + b"%").decode("ascii"))


def _remove_dot_segments(path: str) -> str:
    """Apply RFC 3986 dot-segment removal while preserving empty segments and case."""
    pending = path
    output = ""
    while pending:
        if pending.startswith("../"):
            pending = pending[3:]
        elif pending.startswith("./"):
            pending = pending[2:]
        elif pending.startswith("/./"):
            pending = "/" + pending[3:]
        elif pending == "/.":
            pending = "/"
        elif pending.startswith("/../"):
            pending = "/" + pending[4:]
            output = output[: output.rfind("/")] if "/" in output else ""
        elif pending == "/..":
            pending = "/"
            output = output[: output.rfind("/")] if "/" in output else ""
        elif pending in {".", ".."}:
            pending = ""
        else:
            next_slash = pending.find("/", 1 if pending.startswith("/") else 0)
            if next_slash < 0:
                output += pending
                pending = ""
            else:
                output += pending[:next_slash]
                pending = pending[next_slash:]
    return output or "/"


def _query_pairs(query: str) -> list[tuple[str, str, bool]]:
    if not query:
        return []
    pairs: list[tuple[str, str, bool]] = []
    for field in query.split("&"):
        key, separator, value = field.partition("=")
        normalized_key = _normalize_percent_encoded(key, safe=b"!$'()*+,;:@/?")
        normalized_value = _normalize_percent_encoded(value, safe=b"!$'()*+,;:@/?")
        pairs.append((normalized_key, normalized_value, bool(separator)))
    return pairs


def query_permutation_key(url: str) -> tuple[tuple[str, str, bool], ...]:
    """Return an ordering-independent query signature for trap detection."""
    return tuple(sorted(_query_pairs(urlsplit(url).query)))


def canonicalize_url(value: str, config: CrawlPolicyConfig) -> str:
    """Normalize a public HTTP URL without performing DNS or network access."""
    if (
        not value
        or value != value.strip()
        or "\\" in value
        or len(value) > 8_192
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
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
    path = _remove_dot_segments(
        _normalize_percent_encoded(parsed.path or "/", safe=b"/:@!$&'()*+,;=")
    )
    query_items: list[tuple[str, str, bool]] = []
    for key, value_part, has_equals in _query_pairs(parsed.query):
        try:
            folded = unquote_to_bytes(key).decode("utf-8").casefold()
        except UnicodeDecodeError:
            folded = key.casefold()
        if folded in config.tracking_parameters or any(
            folded.startswith(prefix.casefold()) for prefix in config.tracking_parameter_prefixes
        ):
            continue
        query_items.append((key, value_part, has_equals))
    if config.query_parameter_ordering == "sorted":
        query_items.sort(key=lambda item: (item[0].casefold(), item[0], item[1], item[2]))
    query = "&".join(
        f"{key}={value}" if has_equals else key for key, value, has_equals in query_items
    )
    return urlunsplit((scheme, rendered_host, path, query, ""))


def exclusion_reason(url: str, config: CrawlPolicyConfig) -> CrawlDecisionCode | None:
    parsed = urlsplit(url)
    path = parsed.path
    pairs = _query_pairs(parsed.query)
    query: list[tuple[str, str]] = [(key.casefold(), value) for key, value, _ in pairs]
    keys = [key for key, _ in query]
    if _LOGOUT.search(path):
        return CrawlDecisionCode.LOGOUT
    if _ADMIN.search(path):
        return CrawlDecisionCode.ADMIN_AREA
    if _ACCOUNT.search(path):
        return CrawlDecisionCode.ACCOUNT_ACTION
    if _CART.search(path) or any(key in {"add-to-cart", "remove_item"} for key in keys):
        return CrawlDecisionCode.CART_MUTATION
    if any(path.casefold().endswith(suffix) for suffix in _DOWNLOAD_SUFFIXES):
        return CrawlDecisionCode.FILE_DOWNLOAD
    if _CALENDAR.search(path) or sum(key in {"date", "day", "month", "year"} for key in keys) >= 2:
        return CrawlDecisionCode.CALENDAR_TRAP
    if _SESSION_PATH.search(path) or any(key in _SESSION_KEYS for key in keys):
        return CrawlDecisionCode.SESSION_ID
    if len(pairs) > config.maximum_query_parameters:
        return CrawlDecisionCode.QUERY_PERMUTATION
    counts = Counter(keys)
    if sum(key in _FACET_KEYS or key.startswith(("filter_", "facet_")) for key in keys) > 4:
        return CrawlDecisionCode.FACET_EXPLOSION
    if any(count > 3 for count in counts.values()):
        return CrawlDecisionCode.QUERY_PERMUTATION
    page_match = _PAGINATION_PATH.search(path)
    if page_match is not None and int(page_match.group(1)) > 100:
        return CrawlDecisionCode.PAGINATION_TRAP
    for key, value in query:
        if key in _PAGINATION_KEYS and value.isdecimal():
            limit = 5_000 if key in {"offset", "start"} else 100
            if int(value) > limit:
                return CrawlDecisionCode.PAGINATION_TRAP
    segments = [segment.casefold() for segment in path.split("/") if segment]
    segment_counts = Counter(segments)
    if any(count > 3 for count in segment_counts.values()) or any(
        segments[index : index + width]
        == segments[index + width : index + (2 * width)]
        == segments[index + (2 * width) : index + (3 * width)]
        for width in range(1, min(4, len(segments) // 3 + 1))
        for index in range(0, len(segments) - (3 * width) + 1)
    ):
        return CrawlDecisionCode.REPEATED_PATH_SEGMENT
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
