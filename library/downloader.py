from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .content import save_snapshot
from .content_browser import run_content_browser
from .purchase import SKIP_PURCHASE_TAGS


@dataclass(slots=True)
class DownloadSettings:
    count: int = 1
    max_price: int = 3
    min_balance: int = 0
    max_pages_per_work: int = 6
    minimum_length: int = 200
    execute: bool = False
    force: bool = False
    data_root: Path = Path("data")


def build_download_queue(rows: Iterable[dict[str, Any]], *, count: int | None = None, force: bool = False) -> list[dict[str, Any]]:
    queue = [
        row
        for row in rows
        if (force or not SKIP_PURCHASE_TAGS.intersection(row.get("tags", [])))
        and (force or (row.get("download_status") != "已下载" and not row.get("local_path")))
    ]
    return queue if count is None else queue[: max(0, count)]


def plan_download(rows: Iterable[dict[str, Any]], settings: DownloadSettings) -> list[dict[str, Any]]:
    return [{"thread_id": row["thread_id"], "title": row.get("title", ""), "url": row.get("url", ""), "price": row.get("price", 0), "purchase_status": row.get("purchase_status", "未购买"), "status": "待下载", "execute": settings.execute, "force": settings.force} for row in build_download_queue(rows, count=settings.count, force=settings.force)]


def run_download(rows: Iterable[dict[str, Any]], settings: DownloadSettings) -> list[dict[str, Any]]:
    """第一版安全入口：dry-run 返回队列；真正抓取必须显式 execute。"""
    queue = build_download_queue(rows, force=settings.force)
    if not settings.execute:
        return plan_download(queue, settings)
    if not queue:
        return []
    candidates = [{"thread_id": row["thread_id"], "url": row["url"], "title": row.get("title", ""), "price": row.get("price", 0), "purchase_status": row.get("purchase_status", "未购买"), "existing_posts": [] if settings.force else row.get("existing_posts", [])} for row in queue]
    results = run_content_browser(candidates, execute=True, max_price=settings.max_price, min_balance=settings.min_balance, download_limit=settings.count, max_pages_per_work=settings.max_pages_per_work)
    saved: list[dict[str, Any]] = []
    for result in results:
        if result.get("status") != "已抓取": saved.append(result); continue
        metadata = next((row for row in queue if row["thread_id"] == result["thread_id"]), {})
        combined: dict[str, dict[str, Any]] = {}
        for post in [*metadata.get("existing_posts", []), *result.get("posts", [])]:
            post_id = str(post.get("remote_post_id") or "")
            if post_id:
                combined[post_id] = dict(post)
        posts = sorted(combined.values(), key=lambda post: (int(post.get("page_number") or 0), int(post.get("floor_number") or 0), str(post.get("remote_post_id") or "")))
        saved_info = save_snapshot(settings.data_root, {**metadata, **result}, posts, minimum_length=settings.minimum_length)
        saved.append({**result, "posts": posts, "force_refetch": settings.force, **saved_info})
    return saved
