from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .automation_browser import run_harness

MARKER = "__LIBRARY_CONTENT_RESULT__"


def browser_program(candidates: Iterable[dict[str, Any]], *, execute: bool, max_price: int = 3, min_balance: int = 0, download_limit: int = 1, max_pages_per_work: int = 6) -> str:
    config = json.dumps({"candidates": list(candidates), "execute": execute, "max_price": max_price, "min_balance": min_balance, "download_limit": download_limit, "max_pages_per_work": max_pages_per_work}, ensure_ascii=False)
    return fr'''
import json as _json
import time as _time
import os as _os
_cfg=_json.loads({config!r}); _marker={MARKER!r}; _started=False; _downloaded=0
_log_path=_os.environ.get('LIBRARY_AUTOMATION_LOG','')
def _log(x):
    if not _log_path: return
    try:
        with open(_log_path,'a',encoding='utf-8') as _fh: _fh.write(_json.dumps(x,ensure_ascii=False)+'\\n'); _fh.flush()
    except Exception: pass
def _emit(x):
    _log({{'event':'browser_result', **x}})
    print(_marker+_json.dumps(x,ensure_ascii=False),flush=True)
def _goto(url):
    global _started
    if _started: goto_url(url)
    else: new_tab(url); _started=True
    try: wait_for_load(timeout=20)
    except Exception: pass
    _time.sleep(0.5)
def _state():
    return _json.loads(js(r"""JSON.stringify((()=>{{
      const rows=Array.from(document.querySelectorAll('div[id^="post_"]')).filter(x=>/^post_\d+$/.test(x.id));
      const first=rows[0]; const author=first?.querySelector('.authi a.xw1'); const buy=document.querySelector('a.viewpay');
      const pageNums=Array.from(document.querySelectorAll('a[href*="page="]')).map(a=>Number((a.href.match(/[?&]page=(\d+)/)||[])[1]||0)).filter(Boolean);
      const title=(document.querySelector('#thread_subject')?.innerText||'').trim();
      const bodyNodes=rows.filter(x=>x.querySelector('[id^="postmessage_"], .t_f'));
      return {{title:title,author_name:(author?.innerText||'').trim(),author_id:(author?.href?.match(/[?&]uid=(\d+)/)||[])[1]||'',buy:buy?.href||'',page_count:Math.max(1,...pageNums),body:(document.body?.innerText||'').slice(0,4000),body_nodes:bodyNodes.length,ready:!!(title&&rows.length&&(bodyNodes.length||buy)),rows:rows.map(x=>{{const a=x.querySelector('.authi a.xw1');const m=x.querySelector('[id^="postmessage_"]')||x.querySelector('.t_f');const clone=m?.cloneNode(true);clone?.querySelectorAll('img').forEach(i=>i.remove());return {{remote_post_id:(x.id.match(/(\d+)$/)||[])[1]||'',author_name:(a?.innerText||'').trim(),author_id:(a?.href?.match(/[?&]uid=(\d+)/)||[])[1]||'',raw_html:clone?.innerHTML||'',post_html:x.outerHTML}};}})}};
    }})())"""))
def _pay():
    return _json.loads(js(r"""JSON.stringify((()=>{{
      const form=document.querySelector('#payform');
      const rows=Array.from(document.querySelectorAll('#payform tr')).map(r=>({{k:(r.querySelector('th')?.innerText||'').trim(),v:(r.querySelector('td')?.innerText||'').trim()}}));
      const b=document.querySelector('#payform button[name="paysubmit"]'); const r=b?.getBoundingClientRect();
      const price=(rows.find(x=>x.k.includes('售价'))?.v||'').match(/\d+/)?.[0]||0;
      const balance=(rows.find(x=>x.k.includes('购买后余额'))?.v||'').match(/-?\d+/)?.[0]||0;
      return {{form:!!form,price:Number(price),balance:Number(balance),button:r?{{x:r.x,y:r.y,w:r.width,h:r.height}}:null,body:(document.body?.innerText||'').slice(0,2000)}};
    }})())"""))
def _load_thread(url, attempts=3, settle=False):
    state={{'rows':[],'buy':'','body':'','ready':False}}
    for attempt in range(1,attempts+1):
        _goto(url)
        for delay in (0.75,1.5,2.25):
            _time.sleep(delay)
            state=_state()
            if state.get('ready'):
                if settle: _time.sleep(2)
                return state,attempt
    return state,attempts
def _load_pay(url, attempts=3):
    pay={{'form':False,'button':None,'price':0,'balance':0,'body':''}}
    for attempt in range(1,attempts+1):
        _goto(url); wait_for_element('#payform',timeout=8); wait_for_element('#payform button[name="paysubmit"]',timeout=6,visible=True)
        pay=_pay()
        if pay.get('form') and pay.get('button'): return pay,attempt
        _time.sleep(attempt)
    return pay,attempts
def _verify_purchase(url, attempts=4):
    state={{'rows':[],'buy':'','body':'','ready':False}}
    for attempt in range(1,attempts+1):
        state=_state(); body=state.get('body') or ''
        if '余额不足' in body: return '余额不足',state,attempt
        if any(marker in body for marker in ('主题购买成功','购买成功')): return '已购买',state,attempt
        if state.get('ready') and not state.get('buy'): return '已购买',state,attempt
        if attempt == 1 and not state.get('rows'): _goto(url)
        _time.sleep(0.75 * attempt)
    return '未确认',state,attempts
for item in _cfg['candidates']:
    if _downloaded>=int(_cfg['download_limit']): break
    state,thread_attempts=_load_thread(item['url'], settle=True)
    if not state['rows']:
        _emit({{'thread_id':item['thread_id'],'status':'页面异常','reason':'主题页重试3次仍未找到帖子楼层','attempts':thread_attempts,'posts':[]}}); continue
    purchase_status=item.get('purchase_status') or '未购买'; detected_price=int(item.get('price') or 0); attempt_log={{'thread':thread_attempts}}
    if state['buy']:
        if not _cfg['execute']:
            _emit({{'thread_id':item['thread_id'],'status':'待购买','title':state['title'],'attempts':thread_attempts,'posts':[]}}); continue
        pay,pay_attempts=_load_pay(state['buy']); attempt_log['pay']=pay_attempts; detected_price=int(pay.get('price') or detected_price or 0)
        if not pay.get('form') or not pay.get('button'):
            _emit({{'thread_id':item['thread_id'],'status':'购买失败','reason':'付款页重试3次仍未出现提交按钮','attempts':{{'thread':thread_attempts,'pay':pay_attempts}},'price':detected_price,'purchase_status':'购买失败','posts':[]}}); continue
        if detected_price>int(_cfg['max_price']):
            _emit({{'thread_id':item['thread_id'],'status':'金币超限','reason':'单篇价格超过设置上限','attempts':{{'thread':thread_attempts,'pay':pay_attempts}},'price':detected_price,'purchase_status':'金币超限','posts':[]}}); continue
        if int(pay.get('balance') or 0)<int(_cfg['min_balance']):
            _emit({{'thread_id':item['thread_id'],'status':'余额不足','reason':'购买后余额将低于最低保留余额','attempts':{{'thread':thread_attempts,'pay':pay_attempts}},'price':detected_price,'balance':pay.get('balance',0),'purchase_status':'余额不足','posts':[]}}); break
        verified='未确认'; verify_attempts=0; purchase_attempts=[]
        for purchase_attempt in range(1,4):
            if purchase_attempt > 1:
                pay,pay_attempts=_load_pay(state['buy']); detected_price=int(pay.get('price') or detected_price)
                if not pay.get('form') or not pay.get('button'):
                    purchase_attempts.append({{'attempt':purchase_attempt,'pay':pay_attempts,'verify':0,'status':'付款按钮未出现'}}); continue
                if int(pay.get('balance') or 0)<int(_cfg['min_balance']):
                    verified='余额不足'; purchase_attempts.append({{'attempt':purchase_attempt,'pay':pay_attempts,'verify':0,'status':'余额不足'}}); break
            button=pay['button']; click_at_xy(button['x']+button['w']/2,pay['button']['y']+pay['button']['h']/2); _time.sleep(1.5)
            try: wait_for_load(timeout=15)
            except Exception as _exc: _log({{'event':'wait_for_load_error','thread_id':item['thread_id'],'attempt':purchase_attempt,'error':repr(_exc)}})
            try: wait_for_network_idle(timeout=10,idle_ms=800)
            except Exception as _exc: _log({{'event':'wait_for_network_idle_error','thread_id':item['thread_id'],'attempt':purchase_attempt,'error':repr(_exc)}})
            verified,state,verify_attempts=_verify_purchase(item['url']); purchase_attempts.append({{'attempt':purchase_attempt,'pay':pay_attempts,'verify':verify_attempts,'status':verified}})
            if verified in ('已购买','余额不足'): break
            _time.sleep(1.0)
        attempt_log['purchase']=purchase_attempts
        if verified=='余额不足':
            _emit({{'thread_id':item['thread_id'],'status':'余额不足','reason':'提交后页面提示余额不足','attempts':attempt_log,'price':detected_price,'purchase_status':'余额不足','posts':[]}}); break
        if verified!='已购买':
            _emit({{'thread_id':item['thread_id'],'status':'购买失败','reason':'付款按钮点击后仍未确认购买，已重试3次','attempts':attempt_log,'price':detected_price,'purchase_status':'购买失败','posts':[]}}); continue
        _time.sleep(2); state=_state()
        purchase_status='已购买'
    elif purchase_status not in ('已购买','免费'):
        purchase_status='已购买' if detected_price>0 or purchase_status in ('购买失败','余额不足','金币超限') else '免费'
    author_id=state['author_id']; existing=item.get('existing_posts') or []; known={{str(p.get('remote_post_id') or '') for p in existing}}
    resume_page=max([int(p.get('page_number') or 1) for p in existing] or [1]); page_limit=max(1,int(_cfg['max_pages_per_work'])); effective_page_count=min(int(state['page_count']),page_limit)
    all_rows=[dict(p,page_number=1) for p in state['rows'] if str(p.get('remote_post_id') or '') not in known]
    failed_reason=''; start_page=max(2,resume_page+1 if existing else 2)
    for page in range(start_page,effective_page_count+1):
        sep='&' if '?' in item['url'] else '?'; page_state,page_attempts=_load_thread(item['url']+sep+'page='+str(page), settle=False)
        if not page_state['rows']:
            failed_reason=f'第{{page}}页重试3次仍无楼层'; break
        all_rows.extend(dict(p,page_number=page) for p in page_state['rows'] if str(p.get('remote_post_id') or '') not in known)
    posts=[{{'thread_id':item['thread_id'],'remote_post_id':p['remote_post_id'],'floor_number':int(p.get('page_number',1))*1000+i+1,'page_number':p.get('page_number',1),'author_id':p['author_id'],'raw_html':p['raw_html'],'post_html':p['post_html']}} for i,p in enumerate(all_rows) if p['author_id']==author_id and p['remote_post_id']]
    if failed_reason:
        _emit({{'thread_id':item['thread_id'],'status':'页面异常','reason':failed_reason,'attempts':{{'thread':thread_attempts}},'price':detected_price,'purchase_status':purchase_status,'posts':posts}}); continue
    if not posts and not existing:
        _emit({{'thread_id':item['thread_id'],'status':'页面异常','reason':'页面已加载但未提取到楼主正文','attempts':{{'thread':thread_attempts}},'posts':[]}}); continue
    success_reason='免费作品正文验证完成' if purchase_status=='免费' else '已购买状态与正文验证完成'
    _emit({{'thread_id':item['thread_id'],'status':'已抓取','reason':success_reason,'attempts':attempt_log,'title':state['title'],'author_name':state['author_name'],'author_id':author_id,'page_count':effective_page_count,'source_page_count':state['page_count'],'page_limit_applied':int(state['page_count'])>page_limit,'price':detected_price,'purchase_status':purchase_status,'posts':posts}})
    _downloaded+=1
'''


def run_content_browser(candidates: Iterable[dict[str, Any]], *, execute: bool, max_price: int = 3, min_balance: int = 0, download_limit: int = 1, max_pages_per_work: int = 6, timeout: int = 1800) -> list[dict[str, Any]]:
    proc = run_harness(browser_program(candidates, execute=execute, max_price=max_price, min_balance=min_balance, download_limit=download_limit, max_pages_per_work=max_pages_per_work), timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"browser-harness 退出码 {proc.returncode}: {proc.stderr[-1000:]}")
    results = [json.loads(line[len(MARKER):]) for line in proc.stdout.splitlines() if line.startswith(MARKER)]
    if not results:
        raise RuntimeError("browser-harness 未返回正文抓取结果")
    return results
