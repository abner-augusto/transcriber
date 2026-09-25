"""Job execution and progress adapters. Celery and Redis imports stay lazy."""

from collections.abc import AsyncIterator, Callable, Mapping
from typing import Protocol

from models import Job
from models.job import JobType


class JobRunner(Protocol):
    def submit(self, job: Job) -> str | None: ...


class ProgressBus(Protocol):
    def publish(self, meeting_id: str, event: dict) -> None: ...
    def subscribe(self, meeting_id: str) -> AsyncIterator[dict]: ...
    def check(self) -> None: ...


TASK_NAMES = {
    JobType.PROCESS_MEETING: "tasks.process_meeting.process_meeting_task",
    JobType.REDIARIZE: "tasks.reprocess_task.rediarize_task",
    JobType.REIDENTIFY: "tasks.reprocess_task.reidentify_task",
    JobType.REAPPLY_VOCABULARY: "tasks.reprocess_task.reapply_vocabulary_task",
}


class CeleryJobRunner:
    """Submit Jobs to the current Celery adapter."""

    def submit(self, job: Job) -> str:
        from tasks.celery_app import celery_app

        result = celery_app.send_task(
            TASK_NAMES[job.job_type], args=[job.meeting_id, job.id]
        )
        return result.id


class InlineJobRunner:
    """Run plain task bodies in-process, or record submissions with explicit handlers."""

    def __init__(self, handlers: Mapping[JobType, Callable[[str, str], object]] | None = None):
        self._handlers = handlers
        self.submitted: list[tuple[str, str, JobType]] = []

    def submit(self, job: Job) -> None:
        self.submitted.append((job.meeting_id, job.id, job.job_type))
        handler = self._handlers.get(job.job_type) if self._handlers is not None else self._task_body(job.job_type)
        if handler is not None:
            handler(job.meeting_id, job.id)
        return None

    @staticmethod
    def _task_body(job_type: JobType) -> Callable[[str, str], object]:
        if job_type == JobType.PROCESS_MEETING:
            from tasks.process_meeting import process_meeting_task
            return process_meeting_task
        from tasks.reprocess_task import (
            reapply_vocabulary_task,
            rediarize_task,
            reidentify_task,
        )
        return {
            JobType.REDIARIZE: rediarize_task,
            JobType.REIDENTIFY: reidentify_task,
            JobType.REAPPLY_VOCABULARY: reapply_vocabulary_task,
        }[job_type]


class InMemoryProgressBus:
    """Small async pub/sub adapter for tests and synchronous local execution."""

    def __init__(self):
        self._subscribers: dict[str, set[object]] = {}

    def publish(self, meeting_id: str, event: dict) -> None:
        for queue in tuple(self._subscribers.get(meeting_id, ())):
            queue.put_nowait(dict(event))

    def check(self) -> None:
        return None

    async def subscribe(self, meeting_id: str) -> AsyncIterator[dict]:
        import asyncio

        queue: asyncio.Queue = asyncio.Queue()
        subscribers = self._subscribers.setdefault(meeting_id, set())
        subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(meeting_id, None)

    def subscriber_count(self, meeting_id: str) -> int:
        return len(self._subscribers.get(meeting_id, ()))


class RedisProgressBus:
    """Redis pub/sub adapter preserving the existing ``meeting:{id}`` channel."""

    def __init__(self, redis_url: str | None = None):
        if redis_url is None:
            from config import settings
            redis_url = settings.redis_url
        self.redis_url = redis_url
        self._client = None

    @staticmethod
    def _channel(meeting_id: str) -> str:
        return f"meeting:{meeting_id}"

    def publish(self, meeting_id: str, event: dict) -> None:
        import json
        import redis

        if self._client is None:
            self._client = redis.Redis.from_url(self.redis_url)
        self._client.publish(self._channel(meeting_id), json.dumps(event))

    def check(self) -> None:
        import redis

        client = redis.Redis.from_url(self.redis_url)
        try:
            client.ping()
        finally:
            client.close()

    async def subscribe(self, meeting_id: str) -> AsyncIterator[dict]:
        import json
        import redis.asyncio as aioredis

        client = aioredis.from_url(self.redis_url)
        pubsub = client.pubsub()
        channel = self._channel(meeting_id)
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield json.loads(message["data"])
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            finally:
                await client.aclose()
