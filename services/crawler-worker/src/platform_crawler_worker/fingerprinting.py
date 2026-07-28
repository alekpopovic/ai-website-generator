"""Deterministic, non-ML page fingerprints and campaign grouping."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import UUID

from lxml import etree, html  # type: ignore[import-untyped]

from platform_crawler_worker.models import PageFingerprints

FINGERPRINT_ALGORITHM = "normalized-html-simhash"
FINGERPRINT_VERSION = 1
SIMHASH_DISTANCE = 6

_REMOVED_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})
_NOISE_MARKERS = re.compile(
    r"(?:analytics|beacon|cookie[-_ ]?(?:banner|consent)|google-tag|gtm|pixel|tracking)", re.I
)
_TIMESTAMP = re.compile(
    r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}(?:[T\s]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\b",
    re.I,
)
_CLOCK_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b", re.I)
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I
)
_LONG_TOKEN = re.compile(r"\b(?:[0-9a-f]{20,}|[A-Za-z0-9_-]{32,})\b")
_UNIX_TIME = re.compile(r"\b1[5-9]\d{8,11}\b")
_RANDOM_ID = re.compile(r"^(?:[a-z_-]*\d{6,}|[0-9a-f]{12,}|[a-z0-9_-]*[0-9a-f]{16,})$", re.I)
_DYNAMIC_ATTRIBUTE = re.compile(r"(?:csrf|nonce|token|timestamp|request[-_]?id|trace[-_]?id)", re.I)
_SPACE = re.compile(r"\s+")
_PATH_DYNAMIC = re.compile(r"(?:(?<=/)|^)(?:\d{4,}|[0-9a-f]{12,}|[0-9a-f-]{36})(?=/|$)", re.I)


def _sha256(value: str | bytes) -> str:
    encoded = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(encoded).hexdigest()


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _TIMESTAMP.sub(" <timestamp> ", normalized)
    normalized = _CLOCK_TIME.sub(" <time> ", normalized)
    normalized = _UUID.sub(" <dynamic> ", normalized)
    normalized = _UNIX_TIME.sub(" <timestamp> ", normalized)
    normalized = _LONG_TOKEN.sub(" <dynamic> ", normalized)
    return _SPACE.sub(" ", normalized).strip()


def _stable_attributes(element: etree._Element, *, template: bool) -> str:
    values: list[str] = []
    for name, raw_value in sorted(element.attrib.items()):
        folded_name = name.casefold()
        if (
            folded_name.startswith("on")
            or _DYNAMIC_ATTRIBUTE.search(folded_name)
            or folded_name in {"value", "integrity"}
        ):
            continue
        normalized = _normalize_text(raw_value)
        if not normalized or _RANDOM_ID.fullmatch(normalized):
            continue
        if folded_name == "class":
            tokens = sorted(
                token for token in normalized.split() if not _RANDOM_ID.fullmatch(token)
            )
            normalized = " ".join(tokens)
        if template and folded_name not in {"class", "role", "type"}:
            continue
        if folded_name in {"href", "src", "action"}:
            normalized = _normalize_link_shape(normalized, "https://local.invalid/")
        values.append(f"{folded_name}={normalized}")
    return ";".join(values)


def _remove_noise(root: etree._Element) -> None:
    for comment in root.xpath("//comment()"):
        parent = comment.getparent()
        if parent is not None:
            parent.remove(comment)
    for element in tuple(root.iter()):
        if not isinstance(element.tag, str):
            continue
        tag = etree.QName(element).localname.casefold()
        marker = " ".join(element.attrib.get(name, "") for name in ("id", "class", "data-testid"))
        if tag in _REMOVED_TAGS or _NOISE_MARKERS.search(marker):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)


def _structure(element: etree._Element, *, template: bool) -> str:
    if not isinstance(element.tag, str):
        return ""
    tag = etree.QName(element).localname.casefold()
    attributes = _stable_attributes(element, template=template)
    opening = f"{tag}[{attributes}]" if attributes else tag
    text_slot = "#" if template and _normalize_text(element.text or "") else ""
    children = "".join(_structure(child, template=template) for child in element)
    tail_slot = "#" if template and _normalize_text(element.tail or "") else ""
    return f"<{opening}>{text_slot}{children}</{tag}>{tail_slot}"


def _normalize_link_shape(value: str, response_url: str) -> str:
    try:
        parsed = urlsplit(urljoin(response_url, value))
    except ValueError:
        return "invalid"
    path = _PATH_DYNAMIC.sub("<id>", parsed.path)
    query_keys = sorted(
        field.partition("=")[0].casefold() for field in parsed.query.split("&") if field
    )
    relation = "internal" if parsed.hostname == urlsplit(response_url).hostname else "external"
    return urlunsplit((relation, "", path, "&".join(query_keys), ""))


def _simhash(text: str) -> str:
    tokens = re.findall(r"[\w'-]+", text, flags=re.UNICODE)
    counts = Counter(tokens)
    vector = [0] * 64
    for token, weight in sorted(counts.items()):
        value = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], "big")
        for bit in range(64):
            vector[bit] += weight if value & (1 << bit) else -weight
    result = sum(1 << bit for bit, score in enumerate(vector) if score >= 0)
    return f"{result:016x}"


def compute_page_fingerprints(
    body: bytes, *, normalized_url: str, response_url: str
) -> PageFingerprints:
    """Create bounded deterministic fingerprints without executing page content."""
    try:
        root = html.fromstring(body)
    except (etree.ParserError, ValueError):
        root = html.fromstring(b"<html><body></body></html>")
    _remove_noise(root)
    visible_text = _normalize_text(" ".join(root.itertext()))
    dom_structure = _structure(root, template=False)
    dom_template = _structure(root, template=True)
    headings = "\n".join(
        f"{etree.QName(element).localname.casefold()}:{_normalize_text(' '.join(element.itertext()))}"
        for element in root.xpath("//h1|//h2|//h3|//h4|//h5|//h6")
    )
    links = "\n".join(
        _normalize_link_shape(href, response_url)
        for href in root.xpath("//a[@href]/@href")
        if isinstance(href, str) and len(href) <= 2_048
    )
    visible_hash = _sha256(visible_text)
    dom_hash = _sha256(dom_structure)
    heading_hash = _sha256(headings)
    link_hash = _sha256(links)
    content_hash = _sha256("|".join((visible_hash, dom_hash, heading_hash, link_hash)))
    return PageFingerprints(
        algorithm=FINGERPRINT_ALGORITHM,
        version=FINGERPRINT_VERSION,
        normalized_url_sha256=_sha256(normalized_url),
        visible_text_sha256=visible_hash,
        dom_structure_sha256=dom_hash,
        heading_sequence_sha256=heading_hash,
        link_structure_sha256=link_hash,
        response_body_sha256=_sha256(body),
        semantic_simhash=_simhash(visible_text),
        dom_template_sha256=_sha256(dom_template),
        normalized_content_sha256=content_hash,
        normalized_text_length=len(visible_text),
    )


@dataclass(frozen=True, slots=True)
class FingerprintRecord:
    id: UUID
    normalized_url: str
    normalized_content_sha256: str
    semantic_simhash: str
    dom_template_sha256: str
    normalized_text_length: int


@dataclass(frozen=True, slots=True)
class DeduplicationAssignment:
    page_id: UUID
    exact_duplicate_of_id: UUID | None
    near_duplicate_of_id: UUID | None
    template_representative_id: UUID
    exact_group_key: str
    near_group_key: str
    template_group_key: str


class _DisjointSet:
    def __init__(self, records: tuple[FingerprintRecord, ...]) -> None:
        self.parent = {record.id: record.id for record in records}

    def find(self, value: UUID) -> UUID:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: UUID, right: UUID) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root, key=str)] = min(left_root, right_root, key=str)


def group_fingerprints(
    records: tuple[FingerprintRecord, ...], *, maximum_simhash_distance: int = SIMHASH_DISTANCE
) -> tuple[DeduplicationAssignment, ...]:
    """Build deterministic exact, near-content, and template groups."""
    ordered = tuple(sorted(records, key=lambda item: (item.normalized_url, str(item.id))))
    exact_groups: dict[str, list[FingerprintRecord]] = defaultdict(list)
    template_groups: dict[str, list[FingerprintRecord]] = defaultdict(list)
    for record in ordered:
        exact_groups[record.normalized_content_sha256].append(record)
        template_groups[record.dom_template_sha256].append(record)

    near_sets = _DisjointSet(ordered)
    bands: dict[tuple[int, int], list[FingerprintRecord]] = defaultdict(list)
    candidate_pairs: set[tuple[UUID, UUID]] = set()
    for record in ordered:
        value = int(record.semantic_simhash, 16)
        for band in range(8):
            key = (band, (value >> (band * 8)) & 0xFF)
            for candidate in bands[key]:
                pair = tuple(sorted((record.id, candidate.id), key=str))
                candidate_pairs.add((pair[0], pair[1]))
            bands[key].append(record)
    by_id = {record.id: record for record in ordered}
    for left_id, right_id in sorted(candidate_pairs, key=lambda pair: (str(pair[0]), str(pair[1]))):
        left, right = by_id[left_id], by_id[right_id]
        shorter, longer = sorted((left.normalized_text_length, right.normalized_text_length))
        similar_length = longer == 0 or shorter / longer >= 0.7
        distance = (int(left.semantic_simhash, 16) ^ int(right.semantic_simhash, 16)).bit_count()
        if similar_length and distance <= maximum_simhash_distance:
            near_sets.union(left.id, right.id)

    near_groups: dict[UUID, list[FingerprintRecord]] = defaultdict(list)
    for record in ordered:
        near_groups[near_sets.find(record.id)].append(record)
    near_representative = {
        member.id: members[0] for members in near_groups.values() for member in members
    }
    exact_representative = {
        member.id: members[0] for members in exact_groups.values() for member in members
    }
    template_representative = {
        member.id: members[0] for members in template_groups.values() for member in members
    }
    assignments: list[DeduplicationAssignment] = []
    for record in ordered:
        exact = exact_representative[record.id]
        near = near_representative[record.id]
        template = template_representative[record.id]
        assignments.append(
            DeduplicationAssignment(
                page_id=record.id,
                exact_duplicate_of_id=exact.id if exact.id != record.id else None,
                near_duplicate_of_id=(
                    near.id if near.id != record.id and exact.id == record.id else None
                ),
                template_representative_id=template.id,
                exact_group_key=record.normalized_content_sha256,
                near_group_key=near.normalized_content_sha256,
                template_group_key=record.dom_template_sha256,
            )
        )
    return tuple(assignments)
