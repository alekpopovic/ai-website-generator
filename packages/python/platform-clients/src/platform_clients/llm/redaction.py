"""Prompt redaction and bounded-input policy without content logging."""

import re
from dataclasses import dataclass

_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[^\s,;]{4,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
)


@dataclass(frozen=True, slots=True)
class PromptPolicy:
    max_prompt_bytes: int
    max_image_bytes: int
    max_total_image_bytes: int

    def prepare_text(self, value: str) -> str:
        if not value or any(ord(character) == 0 for character in value):
            raise ValueError("prompt text must be non-empty and contain no NUL characters")
        if len(value.encode("utf-8")) > self.max_prompt_bytes:
            raise ValueError("prompt exceeds the configured byte limit")
        redacted = value
        for pattern in _PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted

    def prepare_many(self, values: tuple[str, ...]) -> tuple[str, ...]:
        prepared = tuple(self.prepare_text(value) for value in values)
        if sum(len(value.encode("utf-8")) for value in prepared) > self.max_prompt_bytes:
            raise ValueError("combined prompt exceeds the configured byte limit")
        return prepared

    def validate_images(self, images: tuple[bytes, ...]) -> None:
        if any(not image or len(image) > self.max_image_bytes for image in images):
            raise ValueError("image is empty or exceeds the per-image byte limit")
        if sum(map(len, images)) > self.max_total_image_bytes:
            raise ValueError("images exceed the combined byte limit")
