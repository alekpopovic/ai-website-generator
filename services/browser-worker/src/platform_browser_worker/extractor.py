"""Deterministic, bounded semantic extraction executed inside the isolated page."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from platform_browser_worker.models import (
    EXTRACTOR_VERSION,
    BrowserCaptureLimits,
    BrowserFailureCode,
    BrowserScanError,
    SemanticSnapshot,
)


def validate_semantic_snapshot(value: Any, limits: BrowserCaptureLimits) -> SemanticSnapshot:
    """Validate hostile browser output before persistence or downstream use."""

    try:
        snapshot = SemanticSnapshot.model_validate(value)
    except (TypeError, ValueError, ValidationError) as error:
        raise BrowserScanError(
            BrowserFailureCode.EXTRACTION_FAILED,
            "Browser semantic extraction returned an invalid bounded snapshot.",
        ) from error
    if snapshot.extractor_version != EXTRACTOR_VERSION:
        raise BrowserScanError(
            BrowserFailureCode.EXTRACTION_FAILED,
            "Browser semantic extraction returned an unexpected extractor version.",
        )
    try:
        payload_size = len(snapshot.canonical_bytes())
    except (TypeError, ValueError) as error:
        raise BrowserScanError(
            BrowserFailureCode.EXTRACTION_FAILED,
            "Browser semantic extraction could not be serialized safely.",
        ) from error
    if (
        len(snapshot.nodes) > limits.maximum_extracted_nodes
        or payload_size > limits.maximum_extraction_bytes
    ):
        raise BrowserScanError(
            BrowserFailureCode.EXTRACTION_TOO_LARGE,
            "Browser semantic extraction exceeded its configured limits.",
        )
    return snapshot


EXTRACTION_SCRIPT = r"""
({ extractorVersion, maximumNodes, maximumPayloadBytes, maximumTextCharacters }) => {
  const root = document.documentElement;
  const body = document.body;
  const encoder = new TextEncoder();
  const semanticSelector = [
    'body', 'header', 'nav', 'main', 'section', 'article', 'aside', 'footer',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'ul', 'ol', 'li', 'a',
    'button', 'form', 'input', 'textarea', 'select', 'img', 'figure'
  ].join(',');
  const sectionSelector = 'body,header,nav,main,section,article,aside,footer';
  const noisePattern = /(?:analytics|advert(?:isement)?|doubleclick|facebook-pixel|google-tag|hotjar|pixel|tracking)/i;
  const cardElements = new Set();
  const round = (value) => Math.round((Number.isFinite(value) ? value : 0) * 100) / 100;
  const text = (value, limit) => String(value || '').replace(/\s+/g, ' ').trim().slice(0, limit);
  const descriptor = (element) => [
    element.id || '',
    typeof element.className === 'string' ? element.className : '',
    element.getAttribute('data-testid') || '',
    element.getAttribute('aria-label') || ''
  ].join(' ');
  const isNoise = (element) => noisePattern.test(descriptor(element));
  const isVisible = (element) => {
    if (!(element instanceof HTMLElement) || element.hidden || element.inert ||
        element.getAttribute('aria-hidden') === 'true' || isNoise(element)) return false;
    const style = getComputedStyle(element);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
    const box = element.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) return false;
    if (element instanceof HTMLImageElement && box.width <= 2 && box.height <= 2) return false;
    return true;
  };
  const childSignature = (element) => {
    const heading = element.querySelector(':scope > h1,:scope > h2,:scope > h3,:scope > h4,:scope > h5,:scope > h6');
    const media = element.querySelector(':scope > img,:scope > figure') ? 'media' : 'none';
    const controls = element.querySelectorAll(':scope > a,:scope > button').length;
    return `${element.tagName.toLowerCase()}|${heading?.tagName.toLowerCase() || 'none'}|${media}|${Math.min(controls, 3)}`;
  };

  for (const parent of body?.querySelectorAll('main,section,article,div,ul,ol') || []) {
    const groups = new Map();
    for (const child of Array.from(parent.children).filter(isVisible)) {
      const signature = childSignature(child);
      const group = groups.get(signature) || [];
      group.push(child);
      groups.set(signature, group);
    }
    for (const group of groups.values()) {
      if (group.length >= 3) for (const child of group) cardElements.add(child);
    }
  }

  const pathFor = (element) => {
    const parts = [];
    let current = element;
    while (current && current.nodeType === Node.ELEMENT_NODE) {
      const tag = current.tagName.toLowerCase();
      let index = 1;
      let sibling = current.previousElementSibling;
      while (sibling) {
        if (sibling.tagName === current.tagName) index += 1;
        sibling = sibling.previousElementSibling;
      }
      parts.push(`${tag}:${index}`);
      if (current === body || current === root) break;
      current = current.parentElement;
    }
    return parts.reverse().join('/');
  };
  const hash = (value) => {
    let result = 0x811c9dc5;
    for (let index = 0; index < value.length; index += 1) {
      result ^= value.charCodeAt(index);
      result = Math.imul(result, 0x01000193);
    }
    return (result >>> 0).toString(16).padStart(8, '0');
  };
  const usedIds = new Map();
  const idCache = new WeakMap();
  const stableId = (element) => {
    const cached = idCache.get(element);
    if (cached) return cached;
    const base = `n-${hash(pathFor(element))}`;
    const collision = usedIds.get(base) || 0;
    usedIds.set(base, collision + 1);
    const value = collision === 0 ? base : `${base}-${collision + 1}`;
    idCache.set(element, value);
    return value;
  };
  const bounds = (element) => {
    const box = element.getBoundingClientRect();
    return {
      x: round(box.left + window.scrollX), y: round(box.top + window.scrollY),
      width: round(box.width), height: round(box.height)
    };
  };
  const implicitRole = (element) => ({
    header: 'banner', nav: 'navigation', main: 'main', section: 'region',
    article: 'article', aside: 'complementary', footer: 'contentinfo',
    a: element.hasAttribute('href') ? 'link' : null, button: 'button', form: 'form',
    input: 'textbox', textarea: 'textbox', select: 'combobox', img: 'img',
    ul: 'list', ol: 'list', li: 'listitem', figure: 'figure'
  })[element.tagName.toLowerCase()] || null;
  const roleFor = (element) => cardElements.has(element)
    ? 'card'
    : text(element.getAttribute('role'), 64) || implicitRole(element);
  const sectionRoots = new Set(Array.from(body?.querySelectorAll(sectionSelector) || []).filter(isVisible));
  for (const element of cardElements) sectionRoots.add(element);
  for (const parent of [body, body?.querySelector('main')].filter(Boolean)) {
    for (const child of Array.from(parent.children)) {
      const box = child.getBoundingClientRect();
      if (isVisible(child) && box.height >= 80) sectionRoots.add(child);
    }
  }
  const nearestSection = (element, includeSelf = false) => {
    let current = includeSelf ? element : element.parentElement;
    while (current) {
      if (sectionRoots.has(current)) return current;
      current = current.parentElement;
    }
    return null;
  };
  const meaningfulText = (element) => {
    if (element instanceof HTMLImageElement) return text(element.getAttribute('alt'), maximumTextCharacters);
    const chunks = [];
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    let current;
    while ((current = walker.nextNode()) && chunks.join(' ').length < maximumTextCharacters * 2) {
      let parent = current.parentElement;
      let allowed = Boolean(parent);
      while (parent && allowed) {
        const tag = parent.tagName.toLowerCase();
        if (['script', 'style', 'template', 'noscript'].includes(tag) || !isVisible(parent)) allowed = false;
        if (parent === element) break;
        parent = parent.parentElement;
      }
      if (allowed) {
        const value = text(current.nodeValue, maximumTextCharacters);
        if (value) chunks.push(value);
      }
    }
    return text(chunks.join(' '), maximumTextCharacters);
  };
  const priority = (element) => {
    const tag = element.tagName.toLowerCase();
    if (['header', 'nav', 'main', 'section', 'article', 'aside', 'footer'].includes(tag)) return 100;
    if (/^h[1-6]$/.test(tag)) return 95;
    if (cardElements.has(element)) return 90;
    if (['form', 'button', 'input', 'textarea', 'select', 'img', 'figure'].includes(tag)) return 80;
    if (['a', 'p', 'ul', 'ol'].includes(tag)) return 60;
    if (tag === 'li') return 40;
    return tag === 'body' ? 110 : 20;
  };
  const candidates = new Set(Array.from(body?.querySelectorAll(semanticSelector) || []));
  if (body) candidates.add(body);
  for (const card of cardElements) candidates.add(card);
  const ranked = Array.from(candidates)
    .filter(isVisible)
    .sort((left, right) => priority(right) - priority(left) ||
      (left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
  const initiallyTruncated = ranked.length > maximumNodes;

  const nodeRecord = (element) => {
    const style = getComputedStyle(element);
    const tag = element.tagName.toLowerCase();
    const section = nearestSection(element);
    const box = bounds(element);
    const nodeText = meaningfulText(element);
    return {
      id: stableId(element), tag, role: roleFor(element),
      aria_label: text(element.getAttribute('aria-label'), maximumTextCharacters) || null,
      text: nodeText, bounds: box, visible: true,
      z_index: text(style.zIndex, 32), display: text(style.display, 64),
      position: text(style.position, 32),
      layout: {
        flex_direction: text(style.flexDirection, 32), flex_wrap: text(style.flexWrap, 32),
        justify_content: text(style.justifyContent, 64), align_items: text(style.alignItems, 64),
        gap: text(style.gap, 64), grid_template_columns: text(style.gridTemplateColumns, 240),
        grid_template_rows: text(style.gridTemplateRows, 240)
      },
      color: text(style.color, 64), background_color: text(style.backgroundColor, 128),
      font_family: text(style.fontFamily, 240), font_size: text(style.fontSize, 32),
      font_weight: text(style.fontWeight, 32), line_height: text(style.lineHeight, 32),
      spacing: {
        margin_top: text(style.marginTop, 32), margin_right: text(style.marginRight, 32),
        margin_bottom: text(style.marginBottom, 32), margin_left: text(style.marginLeft, 32),
        padding_top: text(style.paddingTop, 32), padding_right: text(style.paddingRight, 32),
        padding_bottom: text(style.paddingBottom, 32), padding_left: text(style.paddingLeft, 32)
      },
      border: text(style.border, 240), radius: text(style.borderRadius, 128),
      shadow: text(style.boxShadow, 240), text_align: text(style.textAlign, 32),
      image: element instanceof HTMLImageElement ? {
        rendered_width: box.width, rendered_height: box.height,
        intrinsic_width: Math.max(0, element.naturalWidth || 0),
        intrinsic_height: Math.max(0, element.naturalHeight || 0)
      } : null,
      parent_section_id: section ? stableId(section) : null
    };
  };
  const frequency = (nodes, reader, excluded = new Set()) => {
    const counts = new Map();
    for (const node of nodes) {
      for (const rawValue of reader(node)) {
        const value = text(rawValue, 240);
        if (!value || excluded.has(value)) continue;
        counts.set(value, (counts.get(value) || 0) + 1);
      }
    }
    return Array.from(counts, ([value, count]) => ({ value, count }))
      .sort((left, right) => right.count - left.count || left.value.localeCompare(right.value))
      .slice(0, 20);
  };
  const countsFor = (values) => {
    const result = {};
    for (const value of values) result[value] = (result[value] || 0) + 1;
    return Object.fromEntries(Object.entries(result).sort(([left], [right]) => left.localeCompare(right)));
  };
  const build = (elements, truncated) => {
    const ordered = [...elements].sort((left, right) =>
      left === right ? 0 : (left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
    const nodes = ordered.map(nodeRecord);
    const sections = Array.from(sectionRoots)
      .filter((element) => isVisible(element) && nodes.some((_, index) =>
        ordered[index] === element || element.contains(ordered[index])))
      .sort((left, right) => left === right ? 0 :
        (left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1))
      .map((element) => {
        const parent = nearestSection(element);
        const tag = element.tagName.toLowerCase();
        const heading = element.querySelector(':scope > h1,:scope > h2,:scope > h3,:scope > h4,:scope > h5,:scope > h6');
        return {
          id: stableId(element), tag,
          kind: cardElements.has(element) ? 'card' : (heading ? `semantic-${heading.tagName.toLowerCase()}` :
            (element.matches(sectionSelector) ? `semantic-${tag}` : 'geometry-band')),
          bounds: bounds(element), parent_section_id: parent ? stableId(parent) : null,
          node_count: Math.max(1, ordered.filter((node) => node === element || element.contains(node)).length)
        };
      });
    const transparent = new Set(['rgba(0, 0, 0, 0)', 'transparent']);
    const style_frequencies = {
      colors: frequency(nodes, (node) => [node.color, node.background_color], transparent),
      font_families: frequency(nodes, (node) => [node.font_family]),
      font_sizes: frequency(nodes, (node) => [node.font_size]),
      font_weights: frequency(nodes, (node) => [node.font_weight]),
      line_heights: frequency(nodes, (node) => [node.line_height]),
      spacing: frequency(nodes, (node) => Object.values(node.spacing), new Set(['0px'])),
      radii: frequency(nodes, (node) => [node.radius], new Set(['0px'])),
      shadows: frequency(nodes, (node) => [node.shadow], new Set(['none'])),
      borders: frequency(nodes, (node) => [node.border], new Set(['0px none rgb(0, 0, 0)']))
    };
    const tokenCategories = ['colors', 'font_families', 'font_sizes', 'spacing', 'radii', 'shadows'];
    const design_tokens = tokenCategories.flatMap((category) =>
      style_frequencies[category].slice(0, 8).map((entry, index) => ({
        category, name: `${category.replace(/s$/, '').replace(/_/g, '-')}-${index + 1}`,
        value: entry.value, count: entry.count
      })));
    const layoutValues = nodes.map((node) => node.display === 'grid' ? 'grid' :
      (node.display === 'flex' || node.display === 'inline-flex' ? 'flex' : node.display));
    const headings = nodes.filter((node) => /^h[1-6]$/.test(node.tag)).map((node) => ({
      level: node.tag, text: text(node.text, 80)
    }));
    return {
      extractor_version: extractorVersion, nodes, sections, style_frequencies, design_tokens,
      summary: {
        node_count: nodes.length, section_count: sections.length,
        card_count: nodes.filter((node) => node.role === 'card').length,
        tag_counts: countsFor(nodes.map((node) => node.tag)),
        role_counts: countsFor(nodes.map((node) => node.role).filter(Boolean)),
        layout_counts: countsFor(layoutValues), heading_outline: headings,
        palette: style_frequencies.colors.slice(0, 8).map((entry) => entry.value),
        font_families: style_frequencies.font_families.slice(0, 5).map((entry) => entry.value),
        spacing_scale: style_frequencies.spacing.slice(0, 10).map((entry) => entry.value)
      },
      truncated
    };
  };

  let selectedCount = Math.min(ranked.length, maximumNodes);
  let snapshot = build(ranked.slice(0, selectedCount), initiallyTruncated);
  while (encoder.encode(JSON.stringify(snapshot)).byteLength > maximumPayloadBytes && selectedCount > 1) {
    selectedCount -= Math.max(1, Math.ceil(selectedCount * 0.05));
    snapshot = build(ranked.slice(0, selectedCount), true);
  }
  return snapshot;
}
"""
