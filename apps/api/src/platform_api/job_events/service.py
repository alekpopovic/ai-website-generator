"""Reliable PostgreSQL catch-up plus Redis Stream wakeups for job events."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, cast
from uuid import UUID

from fastapi import Request
from sqlalchemy import select

from platform_api.auth.security import AccessTokenClaims
from platform_api.config import Settings
from platform_api.database import DatabaseManager
from platform_api.errors import ApiError, DependencyUnavailableError
from platform_api.logging import get_logger
from platform_api.persistence.models import JobEvent, Project, RefreshToken, User
from platform_api.resources import ApplicationResources

from .schemas import JobEventPollResponse, JobEventResponse

_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
_SAFE_PAYLOAD_KEYS = frozenset(
    {
        "workflow_attempt",
        "stage",
        "completed",
        "failed",
        "total",
        "processed",
        "percent",
        "paused",
        "campaign_status",
        "succeeded_targets",
        "failed_targets",
        "failure_code",
        "message",
    }
)


@dataclass(frozen=True, slots=True)
class EventPrincipal:
    """One independently validated access-token principal for a long response."""

    user_id: UUID
    session_id: UUID
    expires_at: int


class JobEventStreamLimiter:
    """Distributed leased stream limit with a deterministic process-local fallback."""

    _process_local: ClassVar[dict[UUID, set[str]]] = {}
    _process_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __init__(self, resources: ApplicationResources, settings: Settings) -> None:
        self._redis = resources.redis
        self._prefix = settings.redis.key_prefix
        self._limit = settings.redis.job_event_max_streams_per_user
        self._lease_seconds = settings.redis.job_event_stream_lease_seconds

    @asynccontextmanager
    async def lease(self, user_id: UUID) -> AsyncIterator[StreamLease]:
        lease = StreamLease(self, user_id, secrets.token_urlsafe(18))
        await lease.acquire()
        try:
            yield lease
        finally:
            await lease.close()

    async def _acquire(self, user_id: UUID, member: str) -> None:
        if self._redis is None:
            async with self._process_lock:
                members = self._process_local.setdefault(user_id, set())
                if len(members) >= self._limit:
                    raise ApiError(429, "job_event_stream_limit", "Too many active event streams.")
                members.add(member)
            return
        now = int(time.time())
        key = f"{self._prefix}:job-event-leases:{user_id}"
        script = (
            "redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',ARGV[1]);"
            "local n=redis.call('ZCARD',KEYS[1]);"
            "if n>=tonumber(ARGV[3]) then return 0 end;"
            "redis.call('ZADD',KEYS[1],ARGV[2],ARGV[4]);"
            "redis.call('EXPIRE',KEYS[1],ARGV[5]); return 1"
        )
        try:
            accepted = await self._redis.eval(
                script,
                1,
                key,
                now,
                now + self._lease_seconds,
                self._limit,
                member,
                self._lease_seconds,
            )
        except Exception as error:
            raise DependencyUnavailableError("Redis job event stream limiter") from error
        if int(accepted) != 1:
            raise ApiError(429, "job_event_stream_limit", "Too many active event streams.")

    async def _renew(self, user_id: UUID, member: str) -> None:
        if self._redis is None:
            return
        key = f"{self._prefix}:job-event-leases:{user_id}"
        await self._redis.zadd(key, {member: int(time.time()) + self._lease_seconds}, xx=True)
        await self._redis.expire(key, self._lease_seconds)

    async def _release(self, user_id: UUID, member: str) -> None:
        if self._redis is None:
            async with self._process_lock:
                members = self._process_local.get(user_id)
                if members is not None:
                    members.discard(member)
                    if not members:
                        self._process_local.pop(user_id, None)
            return
        await self._redis.zrem(f"{self._prefix}:job-event-leases:{user_id}", member)


class StreamLease:
    def __init__(self, limiter: JobEventStreamLimiter, user_id: UUID, member: str) -> None:
        self._limiter = limiter
        self._user_id = user_id
        self._member = member

    async def acquire(self) -> None:
        await self._limiter._acquire(self._user_id, self._member)

    async def renew(self) -> None:
        await self._limiter._renew(self._user_id, self._member)

    async def close(self) -> None:
        await self._limiter._release(self._user_id, self._member)


class JobEventService:
    """Serve authorized event catch-up without retaining a database transaction."""

    def __init__(self, resources: ApplicationResources, settings: Settings) -> None:
        if resources.database is None:
            raise DependencyUnavailableError("database")
        self._database: DatabaseManager = resources.database
        self._redis = resources.redis
        self._settings = settings
        self._limiter = JobEventStreamLimiter(resources, settings)

    async def authorize(self, principal: EventPrincipal, project_id: UUID, job_id: UUID) -> None:
        if principal.expires_at <= int(time.time()):
            raise ApiError(401, "access_token_expired", "The access token has expired.")
        async with self._database.session() as session:
            valid = await session.scalar(
                select(User.id)
                .join(Project, Project.owner_id == User.id)
                .join(JobEvent, JobEvent.project_id == Project.id)
                .join(RefreshToken, RefreshToken.id == principal.session_id)
                .where(
                    User.id == principal.user_id,
                    User.status == "active",
                    Project.id == project_id,
                    JobEvent.job_id == job_id,
                    RefreshToken.user_id == principal.user_id,
                    RefreshToken.status == "active",
                    RefreshToken.expires_at > datetime.now(UTC),
                )
                .limit(1)
            )
        if valid is None:
            raise ApiError(404, "job_event_stream_not_found", "The job event stream was not found.")

    async def poll(
        self,
        principal: EventPrincipal,
        project_id: UUID,
        job_id: UUID,
        *,
        after: int,
        limit: int,
    ) -> JobEventPollResponse:
        await self.authorize(principal, project_id, job_id)
        events = await self._events_after(project_id, job_id, after=after, limit=limit)
        next_id = events[-1].sequence if events else after
        return JobEventPollResponse(
            events=events,
            next_event_id=next_id,
            terminal=bool(events and events[-1].status in _TERMINAL),
        )

    async def acquire_stream(self, user_id: UUID) -> StreamLease:
        """Reserve a stream slot before response headers are sent."""
        lease = StreamLease(self._limiter, user_id, secrets.token_urlsafe(18))
        await lease.acquire()
        return lease

    async def stream(
        self,
        request: Request,
        principal: EventPrincipal,
        project_id: UUID,
        job_id: UUID,
        *,
        after: int,
        lease: StreamLease,
    ) -> AsyncIterator[str]:
        heartbeat = self._settings.redis.job_event_heartbeat_seconds
        recheck = self._settings.redis.job_event_authorization_recheck_seconds
        last_authorized = 0.0
        cursor = after
        try:
            while not await request.is_disconnected():
                now = time.monotonic()
                if now - last_authorized >= recheck:
                    try:
                        await self.authorize(principal, project_id, job_id)
                    except ApiError:
                        return
                    await lease.renew()
                    last_authorized = now
                events = await self._events_after(project_id, job_id, after=cursor, limit=100)
                for event in events:
                    cursor = event.sequence
                    yield encode_sse(event)
                if events and events[-1].status in _TERMINAL:
                    return
                yield ": heartbeat\n\n"
                await self._wait_for_event(job_id, cursor, heartbeat)
        finally:
            await lease.close()

    async def _events_after(
        self, project_id: UUID, job_id: UUID, *, after: int, limit: int
    ) -> tuple[JobEventResponse, ...]:
        async with self._database.session() as session:
            rows = tuple(
                (
                    await session.scalars(
                        select(JobEvent)
                        .where(
                            JobEvent.project_id == project_id,
                            JobEvent.job_id == job_id,
                            JobEvent.sequence > after,
                        )
                        .order_by(JobEvent.sequence.asc())
                        .limit(limit)
                    )
                ).all()
            )
        return tuple(public_event(row) for row in rows)

    async def _wait_for_event(self, job_id: UUID, cursor: int, wait_seconds: float) -> None:
        if self._redis is None:
            await asyncio.sleep(wait_seconds)
            return
        stream = f"{self._settings.redis.key_prefix}:job-events:{job_id}"
        try:
            await self._redis.xread(
                {stream: f"{cursor}-0"}, count=1, block=max(1, int(wait_seconds * 1_000))
            )
        except Exception as error:
            get_logger().warning(
                "job_event_redis_wait_failed", error_type=type(error).__name__, job_id=str(job_id)
            )
            await asyncio.sleep(min(wait_seconds, 1.0))


def public_event(event: JobEvent) -> JobEventResponse:
    payload = cast(Mapping[str, Any], event.payload)
    return JobEventResponse(
        id=event.id,
        job_id=event.job_id,
        job_type=cast(Any, event.job_type),
        sequence=event.sequence,
        event_type=event.event_type,
        status=cast(Any, event.status),
        payload=sanitize_payload(payload),
        created_at=event.created_at,
    )


def sanitize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only explicitly public progress fields and bounded scalar values."""
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in _SAFE_PAYLOAD_KEYS:
            continue
        if isinstance(value, (bool, int, float)) or value is None:
            result[key] = value
        elif isinstance(value, str):
            result[key] = value[:500]
    return result


def parse_event_id(value: str | None) -> int:
    if value is None or value == "":
        return 0
    candidate = value.split("-", 1)[0]
    try:
        parsed = int(candidate)
    except ValueError as error:
        raise ApiError(
            400, "last_event_id_invalid", "Last-Event-ID must be a non-negative integer."
        ) from error
    if parsed < 0:
        raise ApiError(
            400, "last_event_id_invalid", "Last-Event-ID must be a non-negative integer."
        )
    return parsed


def encode_sse(event: JobEventResponse) -> str:
    body = json.dumps(event.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
    return f"id: {event.sequence}\nevent: job-event\ndata: {body}\n\n"


def decode_principal(resources: ApplicationResources, authorization: str | None) -> EventPrincipal:
    if authorization is None or not authorization.startswith("Bearer "):
        raise ApiError(401, "authentication_required", "Access token is required.")
    if resources.access_tokens is None:
        raise DependencyUnavailableError("authentication configuration")
    try:
        claims: AccessTokenClaims = resources.access_tokens.decode(authorization[7:])
    except ValueError as error:
        raise ApiError(401, "access_token_invalid", "Access token is invalid.") from error
    return EventPrincipal(claims.sub, claims.sid, claims.exp)
