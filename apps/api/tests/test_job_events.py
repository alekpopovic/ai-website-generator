"""Unit coverage for safe, resumable job-event delivery primitives."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from platform_api.errors import ApiError
from platform_api.job_events.schemas import JobEventResponse
from platform_api.job_events.service import encode_sse, parse_event_id, sanitize_payload


def test_last_event_id_accepts_sse_and_redis_forms() -> None:
    assert parse_event_id(None) == 0
    assert parse_event_id("42") == 42
    assert parse_event_id("42-0") == 42


@pytest.mark.parametrize("value", ["-1", "not-an-id", "1.5"])
def test_last_event_id_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ApiError) as raised:
        parse_event_id(value)
    assert raised.value.code == "last_event_id_invalid"


def test_payload_allowlist_removes_sensitive_and_unbounded_values() -> None:
    payload = sanitize_payload(
        {
            "completed": 8,
            "message": "x" * 900,
            "prompt": "private prompt",
            "raw_html": "<main>private</main>",
            "model_internals": {"thoughts": "private"},
            "object_key": "private/key",
        }
    )
    assert payload == {"completed": 8, "message": "x" * 500}


def test_sse_encoding_uses_monotonic_sequence_and_one_json_record() -> None:
    event = JobEventResponse(
        id=uuid4(),
        job_id=uuid4(),
        job_type="generation",
        sequence=17,
        event_type="generation.rendering",
        status="running",
        payload={"completed": 2},
        created_at=datetime(2026, 7, 28, tzinfo=UTC),
    )
    encoded = encode_sse(event)
    assert encoded.startswith("id: 17\nevent: job-event\ndata: {")
    assert encoded.endswith("\n\n")
    assert "private" not in encoded


def test_openapi_exposes_sse_and_polling_routes(app: object) -> None:
    schema = app.openapi()  # type: ignore[attr-defined]
    path = "/api/v1/projects/{project_id}/jobs/{job_id}/events"
    assert path in schema["paths"]
    assert f"{path}/poll" in schema["paths"]
    assert schema["paths"][path]["get"]["operationId"] == "streamJobEvents"
