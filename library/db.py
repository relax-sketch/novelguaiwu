from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

STATUSES = ("未下载", "下载中", "已下载", "有更新", "下载失败", "金币超限", "余额不足", "页面异常")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = value.replace("，", ",").split(",")
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(str(v).strip() for v in value if str(v).strip()))


@dataclass(slots=True)
class Work:
    thread_id: str
    url: str
    title: str = ""
    author_id: str = ""
    author_name: str = ""
    tags: list[str] = field(default_factory=list)
    views: int = 0
    replies: int = 0
    publish_time: str = ""
    last_reply_time: str = ""
    page_count: int = 0
    current_rank: int = 0
    sort_type: str = "views"
    price: int = 0
    purchase_status: str = "未购买"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Work":
        thread_id = str(data.get("thread_id") or data.get("tid") or "").strip()
        if not thread_id:
            raise ValueError("扫描结果缺少 thread_id")
        return cls(
            thread_id=thread_id,
            url=str(data.get("url") or ""),
            title=str(data.get("title") or "").strip(),
            author_id=str(data.get("author_id") or "").strip(),
            author_name=str(data.get("author_name") or "").strip(),
            tags=_tags(data.get("tags")),
            views=max(0, int(data.get("views") or 0)),
            replies=max(0, int(data.get("replies") or 0)),
            publish_time=str(data.get("publish_time") or ""),
            last_reply_time=str(data.get("last_reply_time") or ""),
            page_count=max(0, int(data.get("page_count") or 0)),
            current_rank=max(0, int(data.get("current_rank") or 0)),
            sort_type=str(data.get("sort_type") or "views"),
            price=max(0, int(data.get("price") or 0)),
            purchase_status=str(data.get("purchase_status") or "未购买"),
        )


@dataclass(slots=True)
class WorkFilter:
    status: str = ""
    include_tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)
    title_keyword: str = ""
    exclude_keyword: str = ""
    min_views: int = 0
    min_replies: int = 0
    author: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "WorkFilter":
        return cls(
            status=str(data.get("status") or "").strip(),
            include_tags=_tags(data.get("include_tags")),
            exclude_tags=_tags(data.get("exclude_tags")),
            title_keyword=str(data.get("title_keyword") or "").strip(),
            exclude_keyword=str(data.get("exclude_keyword") or "").strip(),
            min_views=max(0, int(data.get("min_views") or 0)),
            min_replies=max(0, int(data.get("min_replies") or 0)),
            author=str(data.get("author") or "").strip(),
        )


SCHEMA = """
CREATE TABLE IF NOT EXISTS works (
 id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL UNIQUE, url TEXT NOT NULL,
 title TEXT NOT NULL DEFAULT '', author_id TEXT NOT NULL DEFAULT '', author_name TEXT NOT NULL DEFAULT '',
 tags_json TEXT NOT NULL DEFAULT '[]', views INTEGER NOT NULL DEFAULT 0, replies INTEGER NOT NULL DEFAULT 0,
 publish_time TEXT NOT NULL DEFAULT '', last_reply_time TEXT NOT NULL DEFAULT '', page_count INTEGER NOT NULL DEFAULT 0,
 current_rank INTEGER NOT NULL DEFAULT 0, sort_type TEXT NOT NULL DEFAULT 'views', rank_updated_at TEXT NOT NULL DEFAULT '',
 price INTEGER NOT NULL DEFAULT 0, purchase_status TEXT NOT NULL DEFAULT '未购买', download_status TEXT NOT NULL DEFAULT '未下载',
 has_update INTEGER NOT NULL DEFAULT 0, content_hash TEXT NOT NULL DEFAULT '', local_path TEXT NOT NULL DEFAULT '',
 last_scanned_at TEXT NOT NULL DEFAULT '', last_downloaded_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_works_status ON works(download_status);
CREATE INDEX IF NOT EXISTS idx_works_rank ON works(sort_type, current_rank);
CREATE TABLE IF NOT EXISTS posts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL, remote_post_id TEXT NOT NULL UNIQUE,
 floor_number INTEGER NOT NULL DEFAULT 0, page_number INTEGER NOT NULL DEFAULT 0, author_id TEXT NOT NULL DEFAULT '',
 posted_at TEXT NOT NULL DEFAULT '', edited_at TEXT NOT NULL DEFAULT '', post_type TEXT NOT NULL DEFAULT '正文',
 raw_html TEXT NOT NULL DEFAULT '', clean_text TEXT NOT NULL DEFAULT '', content_hash TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, sort_type TEXT NOT NULL, filter_config TEXT NOT NULL DEFAULT '{}',
 started_at TEXT NOT NULL, finished_at TEXT NOT NULL DEFAULT '', scanned_count INTEGER NOT NULL DEFAULT 0,
 downloaded_count INTEGER NOT NULL DEFAULT 0, skipped_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0,
 stop_reason TEXT NOT NULL DEFAULT '', result_json TEXT NOT NULL DEFAULT '[]'
);
"""


class LibraryDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        columns = {str(row["name"]) for row in self.connection.execute("PRAGMA table_info(runs)").fetchall()}
        if "result_json" not in columns:
            self.connection.execute("ALTER TABLE runs ADD COLUMN result_json TEXT NOT NULL DEFAULT '[]'")
        # 完整本地快照是最终判定：后续扫描只更新排名/元数据，不把作品重新放回下载队列。
        self.connection.execute("UPDATE works SET download_status='已下载',has_update=0 WHERE local_path<>''")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "LibraryDB":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start_run(self, sort_type: str, filter_config: Mapping[str, Any] | None = None) -> int:
        cur = self.connection.execute("INSERT INTO runs(sort_type,filter_config,started_at) VALUES(?,?,?)", (sort_type, json.dumps(filter_config or {}, ensure_ascii=False), utc_now()))
        self.connection.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, **counts: Any) -> None:
        values = {k: v for k, v in counts.items() if k in {"scanned_count", "downloaded_count", "skipped_count", "failed_count", "stop_reason"}}
        if "results" in counts:
            values["result_json"] = json.dumps(counts["results"] or [], ensure_ascii=False)
        values["finished_at"] = utc_now()
        assignment = ",".join(f"{k}=?" for k in values)
        self.connection.execute(f"UPDATE runs SET {assignment} WHERE id=?", (*values.values(), run_id))
        self.connection.commit()

    def upsert_work(self, work: Work | Mapping[str, Any], *, scanned_at: str | None = None) -> dict[str, Any]:
        item = work if isinstance(work, Work) else Work.from_mapping(work)
        scanned_at = scanned_at or utc_now()
        old = self.connection.execute("SELECT * FROM works WHERE thread_id=?", (item.thread_id,)).fetchone()
        old_status = str(old["download_status"] if old else "未下载")
        changed = bool(old and any(str(old[key] or "") != str(getattr(item, attr) or "") for key, attr in (("replies", "replies"), ("last_reply_time", "last_reply_time"), ("page_count", "page_count"))))
        was_downloaded = bool(old and (old_status == "已下载" or str(old["local_path"] or "")))
        has_update = False if was_downloaded else bool(changed and old_status == "有更新")
        status = "已下载" if was_downloaded else old_status
        params = (item.thread_id, item.url, item.title, item.author_id, item.author_name, json.dumps(item.tags, ensure_ascii=False), item.views, item.replies, item.publish_time, item.last_reply_time, item.page_count, item.current_rank, item.sort_type, scanned_at, item.price, item.purchase_status, status, int(has_update), scanned_at)
        self.connection.execute("""INSERT INTO works(thread_id,url,title,author_id,author_name,tags_json,views,replies,publish_time,last_reply_time,page_count,current_rank,sort_type,rank_updated_at,price,purchase_status,download_status,has_update,last_scanned_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(thread_id) DO UPDATE SET url=excluded.url,title=excluded.title,author_id=excluded.author_id,author_name=excluded.author_name,tags_json=excluded.tags_json,views=excluded.views,replies=excluded.replies,publish_time=excluded.publish_time,last_reply_time=excluded.last_reply_time,page_count=excluded.page_count,current_rank=excluded.current_rank,sort_type=excluded.sort_type,rank_updated_at=excluded.rank_updated_at,price=CASE WHEN excluded.price>0 THEN excluded.price ELSE works.price END,purchase_status=CASE WHEN works.purchase_status IN ('已购买','免费') THEN works.purchase_status ELSE excluded.purchase_status END,download_status=CASE WHEN works.local_path<>'' OR works.download_status='已下载' THEN '已下载' ELSE works.download_status END,has_update=CASE WHEN works.local_path<>'' OR works.download_status='已下载' THEN 0 ELSE excluded.has_update END,last_scanned_at=excluded.last_scanned_at""", params)
        self.connection.commit()
        return {"thread_id": item.thread_id, "changed": changed, "download_status": status}

    def upsert_many(self, works: Iterable[Work | Mapping[str, Any]], *, sort_type: str) -> int:
        count = 0
        for rank, raw in enumerate(works, start=1):
            item = raw if isinstance(raw, Work) else Work.from_mapping(raw)
            item.current_rank, item.sort_type = rank, sort_type
            self.upsert_work(item)
            count += 1
        return count

    def list_works(self, filters: WorkFilter | Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        query = WorkFilter.from_mapping(filters) if isinstance(filters, Mapping) else (filters or WorkFilter())
        rows = self.connection.execute("SELECT * FROM works ORDER BY current_rank,id").fetchall()
        result = []
        include, exclude = set(query.include_tags), set(query.exclude_tags)
        for row in rows:
            tags, title, author = _tags(row["tags_json"]), str(row["title"] or ""), str(row["author_name"] or "")
            if query.status and row["download_status"] != query.status: continue
            if include and not include.intersection(tags): continue
            if exclude and exclude.intersection(tags): continue
            if query.title_keyword and query.title_keyword.casefold() not in title.casefold(): continue
            if query.exclude_keyword and query.exclude_keyword.casefold() in title.casefold(): continue
            if int(row["views"] or 0) < query.min_views or int(row["replies"] or 0) < query.min_replies: continue
            if query.author and query.author.casefold() not in author.casefold(): continue
            item = dict(row); item.pop("tags_json", None); item["tags"] = tags; item["has_update"] = bool(item["has_update"]); result.append(item)
        return result

    def count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM works").fetchone()[0])

    def list_authors(self) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT author_name,COUNT(*) AS work_count FROM works WHERE TRIM(author_name)<>'' GROUP BY author_name ORDER BY author_name COLLATE NOCASE").fetchall()
        return [{"name": str(row["author_name"]), "count": int(row["work_count"])} for row in rows]

    def update_purchase_result(self, thread_id: str, *, status: str, price: int | None = None) -> None:
        """写入购买探测/购买结果；不改变已下载内容的状态。"""
        if status == "已购买或免费":
            status = "免费" if not price else "已购买"
        if status == "待购买":
            status = "未购买"
        if price is None:
            self.connection.execute("UPDATE works SET purchase_status=? WHERE thread_id=?", (status, thread_id))
        else:
            download_status = "金币超限" if status == "金币超限" else None
            if download_status:
                self.connection.execute("UPDATE works SET price=?,purchase_status=?,download_status=? WHERE thread_id=?", (price, status, download_status, thread_id))
            else:
                self.connection.execute("UPDATE works SET price=?,purchase_status=? WHERE thread_id=?", (price, status, thread_id))
        self.connection.commit()

    def upsert_post(self, post: Mapping[str, Any]) -> None:
        values = (str(post.get("thread_id") or ""), str(post.get("remote_post_id") or ""), int(post.get("floor_number") or 0), int(post.get("page_number") or 0), str(post.get("author_id") or ""), str(post.get("posted_at") or ""), str(post.get("edited_at") or ""), str(post.get("post_type") or "正文"), str(post.get("raw_html") or ""), str(post.get("clean_text") or ""), str(post.get("content_hash") or ""))
        self._upsert_post_values(values)
        self.connection.commit()

    def _upsert_post_values(self, values: tuple[Any, ...]) -> None:
        self.connection.execute("""INSERT INTO posts(thread_id,remote_post_id,floor_number,page_number,author_id,posted_at,edited_at,post_type,raw_html,clean_text,content_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(remote_post_id) DO UPDATE SET thread_id=excluded.thread_id,floor_number=excluded.floor_number,page_number=excluded.page_number,author_id=excluded.author_id,posted_at=excluded.posted_at,edited_at=excluded.edited_at,post_type=excluded.post_type,raw_html=excluded.raw_html,clean_text=excluded.clean_text,content_hash=excluded.content_hash""", values)

    def replace_posts(self, thread_id: str, posts: Iterable[Mapping[str, Any]]) -> None:
        """在一次事务中替换某帖正文记录；新抓取失败时不会调用此方法。"""
        values_list = [
            (str(post.get("thread_id") or thread_id), str(post.get("remote_post_id") or ""), int(post.get("floor_number") or 0), int(post.get("page_number") or 0), str(post.get("author_id") or ""), str(post.get("posted_at") or ""), str(post.get("edited_at") or ""), str(post.get("post_type") or "正文"), str(post.get("raw_html") or ""), str(post.get("clean_text") or ""), str(post.get("content_hash") or ""))
            for post in posts
        ]
        with self.connection:
            self.connection.execute("DELETE FROM posts WHERE thread_id=?", (thread_id,))
            for values in values_list:
                self._upsert_post_values(values)

    def list_posts(self, thread_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM posts WHERE thread_id=? ORDER BY floor_number,id", (thread_id,)).fetchall()]

    def mark_downloaded(self, thread_id: str, *, local_path: str, content_hash: str) -> None:
        self.connection.execute("UPDATE works SET download_status='已下载',has_update=0,content_hash=?,local_path=?,last_downloaded_at=? WHERE thread_id=?", (content_hash, local_path, utc_now(), thread_id))
        self.connection.commit()

    def update_download_result(self, thread_id: str, *, status: str, price: int | None = None, purchase_status: str = "") -> None:
        """把抓取流程结果归一化写回作品状态。"""
        download_status = {
            "金币超限": "金币超限",
            "余额不足": "余额不足",
            "页面异常": "页面异常",
            "购买失败": "下载失败",
            "下载失败": "下载失败",
        }.get(status, status if status in STATUSES else "页面异常")
        updates: list[str] = ["download_status=?"]
        values: list[Any] = [download_status]
        if price is not None:
            updates.append("price=?"); values.append(max(0, int(price)))
        if purchase_status:
            updates.append("purchase_status=?"); values.append(purchase_status)
        values.append(thread_id)
        self.connection.execute(f"UPDATE works SET {','.join(updates)} WHERE thread_id=?", values)
        self.connection.commit()

    def list_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (max(1, min(200, int(limit))),)).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["filter_config"] = json.loads(item.get("filter_config") or "{}")
            except json.JSONDecodeError:
                item["filter_config"] = {}
            try:
                item["results"] = json.loads(item.pop("result_json", "[]") or "[]")
            except json.JSONDecodeError:
                item["results"] = []
            result.append(item)
        return result
