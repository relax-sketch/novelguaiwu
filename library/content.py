from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .cleaner import clean_posts


def work_directory(root: str | Path, author: str, title: str) -> Path:
    def safe(value: str) -> str:
        return "".join(c for c in value.strip() if c not in '<>:"/\\|?*')[:120] or "未命名"
    return Path(root) / safe(author) / safe(title)


def clean_filename(author: str, title: str) -> str:
    def safe(value: str) -> str:
        return "".join(c for c in value.strip() if c not in '<>:"/\\|?*')[:120] or "未命名"
    return f"{safe(title)}_{safe(author)}.txt"


def save_snapshot(root: str | Path, metadata: Mapping[str, Any], posts: Iterable[Mapping[str, Any]], *, minimum_length: int = 200) -> dict[str, Any]:
    post_list = list(posts); cleaned, novel_hash = clean_posts(post_list, minimum_length=minimum_length)
    directory = work_directory(root, str(metadata.get("author_name") or metadata.get("author_id") or "未知作者"), str(metadata.get("title") or metadata.get("thread_id") or "未命名"))
    directory.mkdir(parents=True, exist_ok=True)
    raw = "\n".join(str(post.get("raw_html") or "") for post in post_list)
    (directory / "raw.html").write_text(raw, encoding="utf-8")
    clean_path = directory / clean_filename(str(metadata.get("author_name") or metadata.get("author_id") or "未知作者"), str(metadata.get("title") or metadata.get("thread_id") or "未命名"))
    clean_path.write_text("\n\n".join(str(post["clean_text"]) for post in cleaned if post["post_type"] in {"正文", "作者说明"}), encoding="utf-8")
    meta = dict(metadata); meta.update({"local_path": str(directory), "clean_path": str(clean_path), "content_hash": novel_hash, "post_count": len(cleaned), "images_mode": "none"})
    (directory / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"local_path": str(directory), "clean_path": str(clean_path), "content_hash": novel_hash, "post_count": len(cleaned)}
