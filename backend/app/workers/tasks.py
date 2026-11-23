"""RQ 任务包装（同步入口，供 worker 容器执行）。"""
from __future__ import annotations

import asyncio


def rebuild_style(account_id: int) -> dict:
    from . import jobs

    return asyncio.run(jobs.rebuild_style_job(account_id))


def import_style(account_id: int, texts: list[str]) -> dict:
    from . import jobs

    return asyncio.run(jobs.import_style_job(account_id, texts))


def pull_history(account_id: int, limit: int = 300) -> dict:
    from . import jobs

    return asyncio.run(jobs.pull_history_job(account_id, limit))


def cold_start(contact_id: int) -> dict:
    from . import jobs

    return asyncio.run(jobs.cold_start_job(contact_id))


def run_proactive(task_id: int) -> dict:
    from . import jobs

    return asyncio.run(jobs.run_proactive_task(task_id))
