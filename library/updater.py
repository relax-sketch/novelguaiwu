from __future__ import annotations

from typing import Any, Mapping


def work_changed(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    return any(str(previous.get(key) or "") != str(current.get(key) or "") for key in ("replies", "last_reply_time", "page_count"))


def posts_changed(previous: list[Mapping[str, Any]], current: list[Mapping[str, Any]]) -> bool:
    old = {str(post.get("remote_post_id")): str(post.get("content_hash") or "") for post in previous}
    new = {str(post.get("remote_post_id")): str(post.get("content_hash") or "") for post in current}
    return old != new


def resolve_download_status(*, was_downloaded: bool, content_changed: bool) -> str:
    if was_downloaded and content_changed: return "有更新"
    if was_downloaded: return "已下载"
    return "未下载"
