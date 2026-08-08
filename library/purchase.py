from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .automation_browser import run_harness

MARKER = "__LIBRARY_PURCHASE_RESULT__"
SKIP_PURCHASE_TAGS = frozenset({"第1届站娘大赛", "版务", "绘画or游戏"})


@dataclass(slots=True)
class PurchaseCandidate:
    thread_id: str
    url: str
    title: str = ""
    price: int = 0
    purchase_status: str = "未购买"


def browser_program(candidates: Iterable[PurchaseCandidate], *, max_price: int, execute: bool, count: int = 2, auto_purchase: bool = False, min_balance: int = 0) -> str:
    config = json.dumps({"candidates": [{"thread_id": candidate.thread_id, "url": candidate.url, "title": candidate.title, "price": candidate.price, "purchase_status": candidate.purchase_status} for candidate in candidates], "max_price": max_price, "execute": execute, "count": max(1, int(count)), "auto_purchase": bool(auto_purchase), "min_balance": max(0, int(min_balance))}, ensure_ascii=False)
    return f'''\
import json as _json
import re as _re
import time as _time
import os as _os
_cfg = _json.loads({config!r})
_marker = {MARKER!r}
_log_path = _os.environ.get('LIBRARY_AUTOMATION_LOG', '')
def _log(value):
    if not _log_path: return
    try:
        with open(_log_path, 'a', encoding='utf-8') as _fh: _fh.write(_json.dumps(value, ensure_ascii=False) + '\\n'); _fh.flush()
    except Exception: pass
def _emit(value):
    _summary={{k:v for k,v in value.items() if k not in ('posts','post_html','raw_html')}}; _summary['post_count']=len(value.get('posts') or [])
    _log({{'event':'browser_result', **_summary}})
    print(_marker + _json.dumps(value, ensure_ascii=False), flush=True)
def _goto(url):
    new_tab(url) if not globals().get('_started') else goto_url(url)
    globals()['_started'] = True
    try: wait_for_load(timeout=20)
    except Exception: pass
    _time.sleep(0.5)
def _thread_state():
    return _json.loads(js(r"""JSON.stringify((()=>{{
      const text=document.body?.innerText||''; const buy=document.querySelector('a.viewpay');
      const posts=Array.from(document.querySelectorAll('div[id^=\\\"post_\\\"]')).filter(x=>/^post_\\d+$/.test(x.id));
      const bodies=posts.filter(x=>x.querySelector('[id^=\\"postmessage_\\"], .t_f'));
      const title=(document.querySelector('#thread_subject')?.innerText||'').trim();
      return {{title:title,buy:buy?{{href:buy.href,text:(buy.innerText||'').trim()}}:null,posts:posts.length,body_nodes:bodies.length,ready:!!(title&&posts.length&&(bodies.length||buy)),hasBalance:/积分[:\\s]+\\d+/.test(text)}};
    }})())"""))
def _pay_state():
    return _json.loads(js(r"""JSON.stringify((()=>{{
      const form=document.querySelector('#payform');
      const rows=Array.from(document.querySelectorAll('#payform tr')).map(r=>{{const k=(r.querySelector('th')?.innerText||'').trim();const v=(r.querySelector('td')?.innerText||'').trim();return {{k:k,v:v}};}});
      const button=document.querySelector('#payform button[name=\\\"paysubmit\\\"]'); const r=button?.getBoundingClientRect();
      const price=rows.find(x=>x.k.includes('售价'))?.v||''; const balance=rows.find(x=>x.k.includes('购买后余额'))?.v||'';
      return {{form:!!form,rows:rows,price:parseInt((price.match(/\\d+/)||['0'])[0],10),balance:parseInt((balance.match(/\\d+/)||['0'])[0],10),button:r?{{x:r.x,y:r.y,w:r.width,h:r.height}}:null}};
    }})())"""))
def _load_thread(url, attempts=3):
    state={{'buy':None,'posts':0,'body_nodes':0,'ready':False}}
    for attempt in range(1,attempts+1):
        _goto(url)
        for delay in (0.75,1.5,2.25):
            _time.sleep(delay)
            candidate=_thread_state(); state=candidate
            if candidate.get('ready'):
                # 主题正文先于购买入口出现，ready 只表示页面主体已经可读。
                # 等待延迟渲染完成后再查一次购买链接，避免收费帖被误判为已购买。
                _time.sleep(2)
                settled=_thread_state(); return settled,attempt
        if state.get('ready'):
            return state,attempt
    return state,attempts
def _load_pay(url, attempts=1):
    pay={{'form':False,'button':None,'price':0,'balance':0}}
    try: _goto(url)
    except Exception as _exc: _log({{'event':'pay_navigation_error','url':str(url),'attempt':1,'error':repr(_exc)}}); return pay,1
    pay=_pay_state()
    return pay,1
def _verify_purchase(url, attempts=4):
    state={{'buy':None,'posts':0,'body_nodes':0,'ready':False}}
    for attempt in range(1,attempts+1):
        state=_thread_state(); body=(js('document.body?.innerText||""') or '')
        if '余额不足' in body: return '余额不足',state,attempt
        if any(marker in body for marker in ('主题购买成功','购买成功')): return '已购买',state,attempt
        if state.get('ready') and not state.get('buy'): return '已购买',state,attempt
        if attempt == 1 and not state.get('posts'): _goto(url)
        _time.sleep(0.75 * attempt)
    return '未确认',state,attempts
_started=False
_bought=0
for item in _cfg['candidates']:
    if _bought >= int(_cfg['count']): break
    known_price=int(item.get('price') or 0); known_status=item.get('purchase_status') or '未购买'; verified='未确认'; price=known_price; purchase_attempts=[]; state={{}}; after={{'posts':0}}
    for purchase_attempt in range(1,4):
        try:
            state,thread_attempts=_load_thread(item['url'])
            if not state.get('posts'):
                purchase_attempts.append({{'attempt':purchase_attempt,'thread':thread_attempts,'status':'主题页楼层未出现'}}); continue
            if not state.get('buy'):
                resolved='已购买' if known_status=='已购买' else ('免费' if known_price==0 and known_status=='未购买' else '购买状态未确认')
                if resolved=='免费':
                    _emit({{'thread_id':item['thread_id'],'status':'免费','price':known_price,'reason':'主题页没有购买链接','attempts':{{'purchase':purchase_attempts,'thread':thread_attempts}},'title':state.get('title',''),'purchased':False}})
                    verified=resolved; break
                if resolved=='购买状态未确认':
                    _emit({{'thread_id':item['thread_id'],'status':'购买状态未确认','price':known_price,'reason':'主题页未确认购买链接，未执行购买','attempts':{{'purchase':purchase_attempts,'thread':thread_attempts}},'title':state.get('title',''),'purchased':False}}); verified=resolved; break
                verified='已购买'; break
            _log({{'event':'pay_start','thread_id':item['thread_id'],'attempt':purchase_attempt,'url':state['buy']['href']}})
            pay,pay_attempts=_load_pay(state['buy']['href']); price=int(pay.get('price') or price)
            if not pay.get('form') or not pay.get('button'):
                purchase_attempts.append({{'attempt':purchase_attempt,'thread':thread_attempts,'pay':pay_attempts,'status':'付款按钮未出现'}}); continue
            if price > int(_cfg['max_price']): verified='金币超限'; purchase_attempts.append({{'attempt':purchase_attempt,'thread':thread_attempts,'pay':pay_attempts,'status':verified}}); break
            if _cfg.get('auto_purchase') and int(pay.get('balance') or 0) < int(_cfg.get('min_balance') or 0): verified='余额保留'; purchase_attempts.append({{'attempt':purchase_attempt,'thread':thread_attempts,'pay':pay_attempts,'status':verified}}); break
            if not _cfg['execute']:
                _emit({{'thread_id':item['thread_id'],'status':'待购买','price':price,'balance':pay.get('balance',0),'purchased':False,'reason':'只读预览','attempts':{{'purchase':purchase_attempts+[{{'attempt':purchase_attempt,'thread':thread_attempts,'pay':pay_attempts}}]}}}}); verified='待购买'; break
            # 坐标点击在付款页可能只移动鼠标而不触发表单提交（尤其是
            # CDP 页面缩放/滚动状态不一致时）。直接调用真实按钮的 DOM
            # click 才能稳定触发原生 submit；按钮不存在时由上面的校验拦截。
            js("document.querySelector('#payform button[name=\\\"paysubmit\\\"]').click()")
            _time.sleep(1.5)
            try: wait_for_load(timeout=15)
            except Exception as _exc: _log({{'event':'wait_for_load_error','thread_id':item['thread_id'],'attempt':purchase_attempt,'error':repr(_exc)}})
            try: wait_for_network_idle(timeout=10,idle_ms=800)
            except Exception as _exc: _log({{'event':'wait_for_network_idle_error','thread_id':item['thread_id'],'attempt':purchase_attempt,'error':repr(_exc)}})
            verified,after,verify_attempts=_verify_purchase(item['url']); purchase_attempts.append({{'attempt':purchase_attempt,'thread':thread_attempts,'pay':pay_attempts,'verify':verify_attempts,'status':verified}})
            if verified in ('已购买','余额不足'): break
        except Exception as _exc:
            _log({{'event':'purchase_attempt_error','thread_id':item['thread_id'],'attempt':purchase_attempt,'error':repr(_exc)}}); purchase_attempts.append({{'attempt':purchase_attempt,'status':'异常','error':repr(_exc)}})
    if verified=='余额不足':
        _emit({{'thread_id':item['thread_id'],'status':'余额不足','price':price,'purchased':False,'reason':'提交后页面提示余额不足','attempts':{{'thread':thread_attempts,'purchase':purchase_attempts}}}}); break
    if verified=='余额保留':
        _emit({{'thread_id':item['thread_id'],'status':'余额保留','price':price,'purchased':False,'reason':'购买后余额将低于最低保留余额','attempts':{{'purchase':purchase_attempts}}}}); break
    if verified in ('金币超限','免费','待购买','购买状态未确认'): continue
    if verified!='已购买':
        _emit({{'thread_id':item['thread_id'],'status':'购买失败','price':price,'purchased':False,'reason':'付款按钮点击后仍未确认购买，已重试3次','attempts':{{'thread':thread_attempts,'purchase':purchase_attempts}}}}); continue
    _bought += 1
    _emit({{'thread_id':item['thread_id'],'status':'已购买','price':price,'purchased':True,'reason':'购买链接已消失','attempts':{{'thread':thread_attempts,'purchase':purchase_attempts}},'post_count':after.get('posts',0)}})
_emit({{'status':'complete','bought':_bought}})
'''


def run_purchase(candidates: Iterable[PurchaseCandidate], *, max_price: int = 3, execute: bool = False, count: int = 2, auto_purchase: bool = False, min_balance: int = 0, timeout: int = 900) -> list[dict[str, Any]]:
    proc = run_harness(browser_program(candidates, max_price=max_price, execute=execute, count=count, auto_purchase=auto_purchase, min_balance=min_balance), timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"browser-harness 退出码 {proc.returncode}: {proc.stderr[-1000:]}")
    results: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        if line.startswith(MARKER):
            results.append(json.loads(line[len(MARKER):]))
    if not results:
        raise RuntimeError("browser-harness 未返回购买结果")
    return results
