from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .automation_browser import run_harness

MARKER = "__LIBRARY_SCAN_RESULT__"


@dataclass(slots=True)
class ScanSettings:
    sort_type: str = "views"
    pages: int = 20
    forum_url: str = "https://monster-nest.com/forum.php?mod=forumdisplay&fid=3"

    def __post_init__(self) -> None:
        if self.sort_type not in {"views", "replies"}:
            raise ValueError("sort_type 必须是 views 或 replies")
        self.pages = max(1, min(int(self.pages), 200))


def load_fixture(path: str | Path, settings: ScanSettings) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    items = payload.get("works", payload) if isinstance(payload, (dict, list)) else []
    if not isinstance(items, list):
        raise ValueError("fixture 必须是数组或包含 works 数组的对象")
    return [dict(item) for item in items[: settings.pages * 50]]


def browser_program(settings: ScanSettings) -> str:
    config = json.dumps({"url": settings.forum_url, "pages": settings.pages, "orderby": settings.sort_type}, ensure_ascii=False)
    return f'''\
import json as _json
import time as _time
from urllib.parse import parse_qsl as _parse_qsl, urlencode as _urlencode, urlsplit as _urlsplit, urlunsplit as _urlunsplit
_cfg = _json.loads({config!r})
_marker = {MARKER!r}
def _emit(value): print(_marker + _json.dumps(value, ensure_ascii=False), flush=True)
def _rows():
    raw = js(r"""JSON.stringify(Array.from(document.querySelectorAll('tbody[id^=\\\"normalthread_\\\"]')).map(row => {{
      const a = row.querySelector('a.s.xst') || row.querySelector('a[href*=\\\"mod=viewthread\\\"]'); const href = a?.href || '';
      const tid = (href.match(/[?&]tid=(\\d+)/) || [])[1] || (row.id.match(/(\\d+)/) || [])[1] || '';
      const num = row.querySelector('td.num');
      const authorCells = row.querySelectorAll('td.by');
      const author = authorCells[0]?.querySelector('a[href*=\\\"mod=space\\\"]');
      const last = authorCells[1]?.querySelector('span');
      const pages = Array.from(row.querySelectorAll('a[href*=\\\"page=\\\"]')).map(x => Number((x.href.match(/[?&]page=(\\d+)/)||[])[1]||0)).filter(Boolean);
      return {{thread_id:tid,url:href,title:(a?.innerText||'').trim(),author_name:(author?.innerText||'').trim(),author_id:(author?.href?.match(/[?&]uid=(\\d+)/)||[])[1]||'',tags:Array.from(row.querySelectorAll('a[href*=\\\"filter=typeid\\\"]')).map(x=>(x.innerText||'').trim()).filter(Boolean),views:Number(row.dataset.views||num?.querySelector('em')?.innerText||0),replies:Number(row.dataset.replies||num?.querySelector('a')?.innerText||0),page_count:Math.max(1,...pages),publish_time:(authorCells[0]?.querySelector('span')?.innerText||authorCells[0]?.querySelector('em')?.innerText||'').trim(),last_reply_time:(last?.getAttribute('title')||last?.innerText||'').trim()}};
    }}).filter(x => x.thread_id && x.url))""")
    return _json.loads(raw)
_started = False
def _goto(url):
    global _started
    if _started: goto_url(url)
    else: new_tab(url); _started = True
    wait_for_load(); _time.sleep(0.7)
all_rows = []
for page in range(1, _cfg['pages'] + 1):
    parts = _urlsplit(_cfg['url']); query = dict(_parse_qsl(parts.query, keep_blank_values=True))
    query.update({{'filter':'reply','orderby':_cfg['orderby'],'page':str(page)}})
    _goto(_urlunsplit((parts.scheme, parts.netloc, parts.path, _urlencode(query), parts.fragment)))
    for row in _rows(): row['page_number'] = page; all_rows.append(row)
_emit({{'status':'ok','works':all_rows}})
'''


def scan_with_browser(settings: ScanSettings, *, timeout: int = 900) -> list[dict[str, Any]]:
    proc = run_harness(browser_program(settings), timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"browser-harness 退出码 {proc.returncode}: {proc.stderr[-1000:]}")
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(MARKER):
            payload = json.loads(line[len(MARKER):])
            if payload.get("status") != "ok": raise RuntimeError(str(payload))
            return list(payload.get("works") or [])
    raise RuntimeError("browser-harness 未返回扫描结果")


def normalize_works(items: Iterable[dict[str, Any]], settings: ScanSettings) -> list[dict[str, Any]]:
    result, seen = [], set()
    for item in items:
        tid = str(item.get("thread_id") or item.get("tid") or "").strip()
        if not tid or tid in seen: continue
        seen.add(tid); value = dict(item); value["thread_id"], value["sort_type"] = tid, settings.sort_type; result.append(value)
    return result
