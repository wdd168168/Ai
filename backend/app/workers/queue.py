"""任务队列：配置了 Redis 就走 RQ（后台 worker 容器执行），否则进程内直接跑。"""
from __future__ import annotations

import logging
from typing import Any

from ..config import settings

log = logging.getLogger("queue")


def enqueue(func_path: str, *args: Any) -> dict:
    """func_path 形如 'app.workers.tasks.cold_start'。返回 {queued, job_id} 或 {queued: False}。"""
    if settings.QUEUE_BACKEND != "redis":
        return {"queued": False}
    try:
        from redis import Redis
        from rq import Queue

        q = Queue(connection=Redis.from_url(settings.REDIS_URL))
        job = q.enqueue(func_path, *args, job_timeout=1800)
        return {"queued": True, "job_id": job.id}
    except Exception as e:
        log.warning("入队失败，改为同步执行: %s", e)
        return {"queued": False}
