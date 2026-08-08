from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Iterable

MARKER = "__LIBRARY_QA_RESULT__"


def browser_program(works: Iterable[dict[str, Any]], output_dir: str | Path) -> str:
    config = json.dumps({"works": list(works), "output_dir": str(output_dir)}, ensure_ascii=False)
    return f'''\
import json as _json
import time as _time
_cfg=_json.loads({config!r}); _marker={MARKER!r}; _started=False
def _goto(url):
    global _started
    if _started: goto_url(url)
    else: new_tab(url); _started=True
    wait_for_load(); _time.sleep(0.8)
def _page(url,page):
    sep='&' if '?' in url else '?'; return url+sep+'page='+str(page)
def _state():
    return _json.loads(js("JSON.stringify((()=>{{const rows=Array.from(document.querySelectorAll('div[id^=\\\"post_\\\"]')).filter(x=>/^post_\\d+$/.test(x.id));return {{ids:rows.map(x=>x.id),authors:rows.map(x=>{{const a=x.querySelector('.authi a.xw1');return (a?.href?.match(/[?&]uid=(\\d+)/)||[])[1]||''}}),text:rows.reduce((n,x)=>n+(x.innerText||'').length,0)}}}})())"))
for item in _cfg['works']:
    first=_page(item['url'],1); last=_page(item['url'],int(item.get('page_count') or 1))
    _goto(first); js("document.querySelectorAll('img').forEach(x=>x.remove())"); _time.sleep(0.2); first_state=_state(); first_path=str(_cfg['output_dir'])+'/'+str(item['thread_id'])+'_first.png'; capture_screenshot(first_path)
    _goto(last); js("document.querySelectorAll('img').forEach(x=>x.remove())"); _time.sleep(0.2); last_state=_state(); last_path=str(_cfg['output_dir'])+'/'+str(item['thread_id'])+'_last.png'; capture_screenshot(last_path)
    print(_marker+_json.dumps({{'thread_id':item['thread_id'],'page_count':item.get('page_count',1),'first':first_state,'last':last_state,'first_screenshot':first_path,'last_screenshot':last_path}},ensure_ascii=False),flush=True)
'''


def capture_work_screenshots(works: Iterable[dict[str, Any]], output_dir: str | Path = "runtime/screenshots") -> list[dict[str, Any]]:
    target = Path(output_dir); target.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["uv", "run", "browser-harness"], input=browser_program(works, target), text=True, encoding="utf-8", cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=1800)
    if proc.returncode: raise RuntimeError(f"browser-harness 退出码 {proc.returncode}: {proc.stderr[-1000:]}")
    return [json.loads(line[len(MARKER):]) for line in proc.stdout.splitlines() if line.startswith(MARKER)]
