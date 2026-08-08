from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .db import LibraryDB, WorkFilter
from .downloader import DownloadSettings, run_download
from .exporter import export_txt, export_zip
from .automation_log import append_log
from .automation_browser import request_stop
from .purchase import SKIP_PURCHASE_TAGS, PurchaseCandidate, run_purchase
from .scanner import ScanSettings, load_fixture, normalize_works, scan_with_browser

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "runtime" / "library.sqlite3"
DATA_ROOT = ROOT / "data"
EXPORT_ROOT = ROOT / "exports"
RETRYABLE_DOWNLOAD_STATUSES = frozenset({"下载失败", "购买失败", "页面异常", "余额不足", "金币超限"})


def _is_client_disconnect(exc: BaseException) -> bool:
    """判断 HTTP 客户端断开，避免把响应写失败当成下载批次失败。"""
    if isinstance(exc, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
        return True
    return getattr(exc, "winerror", None) in {10053, 10054} or getattr(exc, "errno", None) in {10053, 10054}


# 版块顶部的 typeid 过滤项是网站预设标签；列表页只会显示当前页出现过的标签，
# 因此管理页使用这份从 fid=3 顶部菜单核对出的完整预设集合。
FORUM_TAG_PRESETS = [
    {"typeid": "1", "name": "催眠纯爱"}, {"typeid": "2", "name": "催眠NTR"},
    {"typeid": "3", "name": "改造变化"}, {"typeid": "213", "name": "女主视角"},
    {"typeid": "4", "name": "性转相关"}, {"typeid": "6", "name": "常识改变"},
    {"typeid": "192", "name": "母系乱伦"}, {"typeid": "124", "name": "清水无肉"},
    {"typeid": "5", "name": "其他XP"}, {"typeid": "37", "name": "翻译小说"},
    {"typeid": "191", "name": "AI辅助"}, {"typeid": "19", "name": "绘画or游戏"},
    {"typeid": "123", "name": "2025【怪物】征文"}, {"typeid": "212", "name": "2025【巢】征文"},
    {"typeid": "233", "name": "2026新春征文"}, {"typeid": "255", "name": "第1届站娘大赛"},
    {"typeid": "122", "name": "版务"},
]
PAGE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>怪物派趣 · 帖子库</title>
<style>
:root{--bg:#edf1f5;--surface:#fff;--ink:#14191f;--muted:#7a838d;--line:#d4dbe2;--blue:#285987;--blue-dark:#1d4c78;--chip:#d9eaf6;--chip-text:#274861;--stripe:#f0f4f8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,system-ui,"Microsoft YaHei",sans-serif;font-size:14px}main{max-width:1200px;margin:12px auto 32px;padding:0 12px}.card{background:var(--surface);border:1px solid #e0e5ea;border-radius:12px;box-shadow:0 2px 7px rgba(31,45,61,.08);margin-bottom:14px;padding:14px}.topbar{display:flex;justify-content:space-between;align-items:center;min-height:68px;padding:12px 14px}.brand h1{margin:0 0 2px;font-size:21px;letter-spacing:-.3px}.hint{color:var(--muted);font-size:12px;line-height:1.5}.account{display:flex;align-items:center;gap:9px;color:#27313a}.avatar{width:34px;height:34px;border-radius:50%;background:linear-gradient(145deg,#6d777d,#1e2930);display:grid;place-items:center;color:#fff;font-weight:700;font-size:12px}.account-name{font-weight:700;font-size:13px}.account-sub{font-size:11px;color:var(--muted);margin-top:2px}.chevron{font-size:16px;color:#606b74;margin-left:3px}.more{font-size:22px;line-height:1;color:#53606b;margin-left:6px}.section-title{font-size:15px;font-weight:700;margin:0 0 14px}.scan-layout{display:grid;grid-template-columns:minmax(0,1fr) 325px;gap:26px;align-items:end}.scan-controls{display:flex;align-items:flex-end;gap:14px;flex-wrap:wrap}.field{display:flex;flex-direction:column;gap:5px;min-width:0}.field>label{font-size:13px;font-weight:600;color:#262d33}.scan-controls .field:first-child{width:285px}.scan-controls .field:nth-child(2){width:72px}.forum-field{width:100%}.control{width:100%;height:31px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);font:inherit;padding:5px 9px;outline:none;box-shadow:inset 0 1px 1px rgba(0,0,0,.03)}.control:focus{border-color:#6a9bc2;box-shadow:0 0 0 2px #dcecf8}.url-control{height:47px;resize:none;line-height:1.25;padding-right:36px}.url-wrap{position:relative}.copy-icon{position:absolute;right:9px;top:14px;color:#697681;font-size:17px;cursor:pointer}.actions{display:flex;align-items:center;gap:7px;margin-top:13px;flex-wrap:wrap}.button{height:31px;border-radius:6px;border:1px solid #7893a9;padding:0 11px;background:#fff;color:#244e72;font:inherit;cursor:pointer;display:inline-flex;align-items:center;gap:6px}.button:hover{background:#f1f6fa}.button.primary{background:var(--blue);border-color:var(--blue);color:#fff;box-shadow:0 1px 2px rgba(34,79,115,.2)}.button.primary:hover{background:var(--blue-dark)}.button .icon{font-size:14px;line-height:1}.message{min-height:16px;margin-top:6px;color:#a04f2e;font-size:12px}.filter-card{padding-bottom:16px}.filter-row{display:grid;grid-template-columns:165px 1fr;gap:12px;align-items:center;margin-bottom:12px}.filter-row.compact{grid-template-columns:165px 1fr}.filter-row.triple{grid-template-columns:165px 165px 165px 1fr;gap:12px}.filter-label{font-size:13px;font-weight:600;color:#333b43}.filter-row>.control{width:100%}.tag-editor{min-height:32px;border:1px solid var(--line);border-radius:6px;padding:4px 7px;display:flex;align-items:center;gap:5px;flex-wrap:wrap;background:#fff}.tag-editor:focus-within{border-color:#6a9bc2;box-shadow:0 0 0 2px #dcecf8}.tag-editor input{border:0;outline:0;min-width:120px;flex:1;height:22px;padding:0 3px;font:inherit}.chip{display:inline-flex;align-items:center;gap:5px;background:var(--chip);color:var(--chip-text);border-radius:14px;padding:4px 8px;font-size:12px;line-height:1}.chip button{border:0;background:transparent;color:#42627a;padding:0;cursor:pointer;font-size:14px;line-height:1}.quick-tags{display:flex;gap:5px;flex-wrap:wrap;margin:-3px 0 12px 177px}.quick-tag{border:0;background:#f2f5f7;color:#64717c;border-radius:12px;padding:3px 8px;font-size:11px;cursor:pointer}.quick-tag:hover{background:#e5eef5;color:#315979}.filter-row.triple .field{width:165px}.filter-row.triple .filter-label{align-self:center}.filter-row.triple .field label{font-size:12px;color:#333b43;margin-bottom:1px}.filter-row.triple{grid-template-columns:165px 165px 165px 1fr}.filter-row.triple>.filter-label{grid-column:1 / -1;margin-bottom:-7px}.table-card{padding:14px 14px 0;overflow:hidden}.table-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:7px}.summary{font-size:13px;color:#5b6670}.table-wrap{overflow:auto;margin:0 -14px}table{border-collapse:collapse;width:100%;min-width:920px;table-layout:fixed}th,td{border-bottom:1px solid #dce2e7;text-align:left;padding:8px 9px;vertical-align:middle;white-space:nowrap}th{font-size:12px;font-weight:700;color:#333c45;background:#fff;height:34px}td{font-size:13px;color:#1f2a33;height:38px}tbody tr:nth-child(even){background:var(--stripe)}tbody tr:hover{background:#e6f0f8}th:first-child,td:first-child{width:42px;text-align:center}th:nth-child(2),td:nth-child(2){width:42px}th:nth-child(3),td:nth-child(3){width:auto;min-width:360px}th:nth-child(4),td:nth-child(4){width:135px;white-space:normal}th:nth-child(5),td:nth-child(5){width:70px;text-align:right}th:nth-child(6),td:nth-child(6){width:70px;text-align:right}th:nth-child(7),td:nth-child(7){width:58px;text-align:right}th:nth-child(8),td:nth-child(8){width:110px}th:nth-child(9),td:nth-child(9){width:84px}.title-link{color:#101820;text-decoration:underline;text-decoration-color:#71808d;text-underline-offset:2px;display:block;overflow:hidden;text-overflow:ellipsis}.tag-text{color:#5e6973;white-space:normal;line-height:1.15}.status{display:inline-flex;padding:4px 8px;border-radius:12px;font-size:11px;background:#e8edf2;color:#5b6670}.status.done{background:#d8f0e0;color:#32714d}.status.update{background:#fcebc8;color:#8c6422}.status.fail{background:#fde0df;color:#9a403d}.empty{padding:25px;text-align:center;color:#77828c}.check{width:14px;height:14px;accent-color:var(--blue)}@media(max-width:760px){main{margin-top:6px;padding:0 8px}.scan-layout{grid-template-columns:1fr;gap:14px}.filter-row,.filter-row.compact{grid-template-columns:1fr;gap:6px}.quick-tags{margin-left:0}.filter-row.triple{grid-template-columns:1fr}.filter-row.triple>.filter-label{grid-column:auto}.topbar{align-items:flex-start}.account{display:none}}
</style>
</head>
<body><main>
<header class="card topbar"><div class="brand"><h1>帖子库</h1><div class="hint">扫描最新排名、筛选帖子；购买可在下方“购买设置”中预览或启动。</div></div></header>
<section class="card"><h2 class="section-title">扫描设置</h2><div class="scan-layout"><div><div class="scan-controls"><div class="field"><label for="sort">排序</label><select class="control" id="sort"><option value="views">查看最新排序</option><option value="replies">回复数降序</option></select></div><div class="field"><label for="pages">扫描页数</label><input class="control" id="pages" type="number" min="1" max="200" value="20"></div></div><div class="actions"><button class="button primary" onclick="scan()"><span class="icon">☷</span>扫描并更新帖子库</button><button class="button" onclick="loadWorks()"><span class="icon">⟳</span>刷新结果</button></div><div id="scanMessage" class="message"></div></div><div class="field forum-field"><label for="forum_url">版块地址</label><div class="url-wrap"><textarea class="control url-control" id="forum_url">https://monster-nest.com/forum.php?mod=forumdisplay&amp;fid=3</textarea><span class="copy-icon" onclick="copyUrl()" title="复制地址">▣</span></div></div></div></section>
<section class="card filter-card"><h2 class="section-title">结果筛选</h2><div class="filter-row compact"><div class="field"><label for="status">状态</label><select class="control" id="status"><option value="">全部</option><option>未下载</option><option>已下载</option><option>有更新</option><option>下载失败</option><option>金币超限</option><option>余额不足</option><option>页面异常</option></select></div><div class="field"><label for="author">作者</label><input class="control" id="author" placeholder="作者"></div></div><div class="filter-row"><div class="filter-label">标签</div><div class="tag-editor" id="include_editor"><span id="include_tag_picker" hidden></span><input id="include_tags" placeholder="包含标签" onkeydown="tagKey(event,'include')"></div></div><div class="quick-tags" id="quick_tags"></div><div class="filter-row"><div class="filter-label">排除标签</div><div class="tag-editor" id="exclude_editor"><input id="exclude_tags" placeholder="排除标签" onkeydown="tagKey(event,'exclude')"></div></div><div class="filter-row triple"><div class="filter-label">其他条件</div><div class="field"><label for="exclude_keyword">排除关键词</label><input class="control" id="exclude_keyword"></div><div class="field"><label for="min_views">最低查看数</label><input class="control" id="min_views" type="number" min="0" value="0"></div><div class="field"><label for="min_replies">最低回复数</label><input class="control" id="min_replies" type="number" min="0" value="0"></div></div><div class="actions"><button class="button primary" onclick="loadWorks()"><span class="icon">⌕</span>应用筛选</button><button class="button" onclick="notReady('下载')"><span class="icon">⇩</span>下载勾选帖子</button><button class="button" onclick="notReady('导出')"><span class="icon">⇩</span>导出勾选作品</button></div></section>
<section class="card table-card"><div class="table-head"><div class="summary" id="summary">共 0 条</div><div class="hint">按住 Shift 可连续选择</div></div><div class="table-wrap"><table><thead><tr><th><input class="check" type="checkbox" id="all" onclick="toggleAll(this)" title="全选"></th><th>排名</th><th>标题</th><th>标签</th><th>查看</th><th>回复</th><th>金币</th><th>作者</th><th>状态</th></tr></thead><tbody id="rows"></tbody></table></div></section>
</main>
<script>
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const tagState={include:[],exclude:[]};
function renderTags(kind){const editor=$(kind+'_editor'),input=$(kind+'_tags');editor.querySelectorAll('.chip').forEach(x=>x.remove());tagState[kind].forEach((tag,i)=>{const chip=document.createElement('span');chip.className='chip';chip.innerHTML=`${esc(tag)} <button type="button" aria-label="移除${esc(tag)}" onclick="removeTag('${kind}',${i})">×</button>`;editor.insertBefore(chip,input);});input.value=tagState[kind].join(',');}
function addTag(kind,value){const tag=String(value||'').trim();if(!tag)return;if(!tagState[kind].includes(tag))tagState[kind].push(tag);$(kind+'_tags').value='';renderTags(kind);}
function removeTag(kind,index){tagState[kind].splice(index,1);renderTags(kind);}
function tagKey(event,kind){if(event.key==='Enter'||event.key===','){event.preventDefault();addTag(kind,event.target.value.replace(/,$/,''));}}
function params(){return new URLSearchParams(Object.entries({status:$('status').value,include_tags:tagState.include.join(','),exclude_tags:tagState.exclude.join(','),title_keyword:'',exclude_keyword:$('exclude_keyword').value,min_views:$('min_views').value,min_replies:$('min_replies').value,author:$('author').value}));}
let lastPickedIndex=-1;
async function loadWorks(){const r=await fetch('/api/works?'+params()),d=await r.json();$('summary').textContent=`共 ${d.works.length} 条`;$('rows').innerHTML=d.works.length?d.works.map((w,i)=>{const s=String(w.download_status||'');const cls=s==='已下载'?'done':s.includes('失败')?'fail':s==='有更新'?'update':'';return `<tr><td><input class="check pick" type="checkbox" value="${esc(w.thread_id)}" onclick="pickRange(event,${i})"></td><td>${esc(w.current_rank)}</td><td><a class="title-link" href="${esc(w.url)}" target="_blank" rel="noreferrer">${esc(w.title||'(无标题)')}</a></td><td class="tag-text">${esc((w.tags||[]).join('、'))}</td><td>${esc(w.views)}</td><td>${esc(w.replies)}</td><td>${esc(w.price)}</td><td>${esc(w.author_name)}</td><td><span class="status ${cls}">${esc(s)}</span></td></tr>`}).join(''):'<tr><td colspan="9" class="empty">暂无匹配帖子</td></tr>';lastPickedIndex=-1;$('all').checked=false;}
async function loadTags(){const r=await fetch('/api/tags'),d=await r.json();$('quick_tags').innerHTML=d.tags.slice(0,6).map(t=>`<button class="quick-tag" type="button" onclick="addTag('include','${esc(t.name)}')">${esc(t.name)}</button>`).join('');}
async function scan(){const m=$('scanMessage');m.textContent='正在连接已登录浏览器并扫描，请稍候…';try{const r=await fetch('/api/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sort_type:$('sort').value,pages:$('pages').value,forum_url:$('forum_url').value})}),d=await r.json();if(!r.ok)throw Error(d.error||'扫描失败');m.textContent=`扫描完成：${d.scanned_count} 条，数据库现有 ${d.total_count} 条`;await loadWorks();}catch(e){m.textContent='扫描失败：'+e.message;}}
function pickRange(event,index){const picks=[...document.querySelectorAll('.pick')];if(event.shiftKey&&lastPickedIndex>=0){const start=Math.min(lastPickedIndex,index),end=Math.max(lastPickedIndex,index);for(let i=start;i<=end;i++)picks[i].checked=event.target.checked;}lastPickedIndex=index;const all=$('all');all.checked=picks.length>0&&picks.every(x=>x.checked);all.indeterminate=picks.some(x=>x.checked)&&!all.checked;}
function toggleAll(x){document.querySelectorAll('.pick').forEach(e=>e.checked=x.checked);x.indeterminate=false;lastPickedIndex=-1}function copyUrl(){navigator.clipboard?.writeText($('forum_url').value);$('scanMessage').textContent='版块地址已复制';}function notReady(name){alert(`${name}功能将在后续阶段接入。`)}
loadTags();loadWorks();
</script></body></html>'''

# 参考图中的筛选器把标签建议放在标签输入框内；这些小幅覆盖保持页面结构清晰，
# 同时让旧的标签选择器标识继续存在，避免外部脚本/测试失去兼容性。
PAGE = PAGE.replace('<div class="tag-editor" id="include_editor"><span id="include_tag_picker" hidden></span><input id="include_tags"', '<div class="tag-editor" id="include_editor"><span id="include_tag_picker" hidden></span><span class="tag-suggestions" id="quick_tags"></span><input id="include_tags"')
PAGE = PAGE.replace('<div class="quick-tags" id="quick_tags"></div>', '')
PAGE = PAGE.replace('<div class="filter-row triple"><div class="filter-label">其他条件</div>', '<div class="filter-row triple">')
PAGE = PAGE.replace('d.tags.slice(0,6)', 'd.tags.slice(0,4)')
PAGE = PAGE.replace('</style>', '.filter-row.compact{grid-template-columns:165px 305px 1fr}.filter-row.triple{grid-template-columns:165px 165px 165px;gap:12px}.tag-suggestions{display:flex;gap:5px;flex-wrap:wrap}.quick-tag{background:var(--chip);color:var(--chip-text)}.quick-tag::after{content:" ×"}.filter-row.triple .filter-label{display:none}</style>')
PAGE = PAGE.replace('<span class="tag-suggestions" id="quick_tags"></span><input id="include_tags" placeholder="包含标签" onkeydown="tagKey(event,\'include\')">', '<span class="tag-suggestions" id="quick_tags" hidden></span><input id="include_tags" type="hidden"><select class="tag-select" id="include_tag_select" aria-label="选择包含标签" onchange="selectTag(\'include\',this.value)"><option value="">选择预设标签</option></select>')
PAGE = PAGE.replace('<input id="exclude_tags" placeholder="排除标签" onkeydown="tagKey(event,\'exclude\')">', '<input id="exclude_tags" type="hidden"><select class="tag-select" id="exclude_tag_select" aria-label="选择排除标签" onchange="selectTag(\'exclude\',this.value)"><option value="">选择预设标签</option></select>')
PAGE = PAGE.replace('</style>', '.tag-select{margin-left:auto;flex:0 0 150px;min-width:145px;height:24px;border:0;background:transparent;color:#687783;font:inherit;outline:0;cursor:pointer}.tag-select:focus{color:#244e72}.tag-select option{color:#18232d;background:#fff}#quick_tags{display:none}.purchase-state{margin-top:3px;color:#78848e;font-size:11px}.section-title-row{display:flex;align-items:center;justify-content:space-between}.purchase-controls{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.purchase-controls label{display:flex;align-items:center;gap:6px;color:#39434c;font-size:13px}.compact-control{width:82px;height:29px}.check-label{cursor:pointer}.check-label input{accent-color:var(--blue)}</style>')
PAGE = PAGE.replace('<section class="card filter-card"><h2 class="section-title">结果筛选</h2>', '<section class="card purchase-card"><div class="section-title-row"><h2 class="section-title">购买设置</h2><span class="hint">默认仅预览，不会扣除金币</span></div><div class="purchase-controls"><label>购买数量 <input class="control compact-control" id="purchase_count" type="number" min="1" max="100" value="2"></label><label>单篇最高金币 <input class="control compact-control" id="max_price" type="number" min="0" max="10000" value="3"></label><label>最低剩余金币 <input class="control compact-control" id="min_balance" type="number" min="0" max="1000000" value="0"></label><label class="check-label"><input id="auto_purchase" type="checkbox"> 自动购买至最低余额</label><label class="check-label"><input id="purchase_execute" type="checkbox"> 确认后实际购买</label><button class="button primary" onclick="purchase()"><span class="icon">◈</span>开始购买当前筛选</button></div><div id="purchaseMessage" class="message"></div></section><section class="card filter-card"><h2 class="section-title">结果筛选</h2>')
PAGE = PAGE.replace('<section class="card filter-card"><h2 class="section-title">结果筛选</h2>', '<section class="card download-card"><div class="section-title-row"><h2 class="section-title">下载设置</h2><div class="download-heading-actions"><span class="hint">自动购买；按成功完成篇数计数</span><button class="button primary" id="auto_download" type="button" onclick="downloadPosts(\'auto\')"><span class="icon">▶</span>自动下载</button></div></div><div class="purchase-controls"><label>本次下载篇数 <input class="control compact-control" id="download_count" type="number" min="1" max="100" value="2"></label><label>单篇最高金币 <input class="control compact-control" id="download_max_price" type="number" min="0" max="10000" value="3"></label><label>最低保留余额 <input class="control compact-control" id="download_min_balance" type="number" min="0" max="1000000" value="0"></label><label>单帖最多页数 <input class="control compact-control" id="download_max_pages" type="number" min="1" max="100" value="6"></label><input id="minimum_length" type="hidden" value="200"><input id="download_execute" type="hidden" value="1"></div><div class="hint download-rule">自动下载忽略当前筛选并固定按查看数降序；单帖达到页数上限后直接保存为已下载。</div></section><section class="card filter-card"><h2 class="section-title">结果筛选</h2>')
PAGE = PAGE.replace('<div class="field"><label for="author">作者</label><input class="control" id="author" placeholder="作者"></div>', '<div class="field"><label for="title_keyword">标题关键词</label><input class="control" id="title_keyword" placeholder="标题关键词"></div><div class="field"><label for="author">作者</label><select class="control" id="author"><option value="">全部作者</option></select></div>')
PAGE = PAGE.replace('<button class="button" onclick="notReady(\'下载\')"><span class="icon">⇩</span>下载勾选帖子</button><button class="button" onclick="notReady(\'导出\')"><span class="icon">⇩</span>导出勾选作品</button>', '<button class="button" onclick="downloadPosts(\'selected\')"><span class="icon">⇩</span>下载勾选帖子</button><button class="button" onclick="downloadPosts(\'redownload\')"><span class="icon">↻</span>重新抓取勾选正文</button><button class="button" onclick="downloadPosts(\'current\')"><span class="icon">⇩</span>下载当前筛选结果</button><select class="control action-select" id="export_format" aria-label="导出格式"><option value="zip">ZIP</option><option value="txt">TXT</option></select><button class="button" onclick="exportWorks(\'selected\')"><span class="icon">⇩</span>导出勾选作品</button><button class="button" onclick="exportWorks(\'current\')"><span class="icon">⇩</span>导出当前筛选结果</button>')
PAGE = PAGE.replace('</style>', '.action-select{width:72px;height:31px}.action-message{flex-basis:100%;min-height:16px;color:#a04f2e;font-size:12px}</style>')
PAGE = PAGE.replace('<button class="button" onclick="exportWorks(\'current\')"><span class="icon">⇩</span>导出当前筛选结果</button>', '<button class="button" onclick="exportWorks(\'current\')"><span class="icon">⇩</span>导出当前筛选结果</button><span id="actionMessage" class="action-message"></span>')
PAGE = PAGE.replace('<section class="card table-card">', '<section class="card runs-card"><div class="section-title-row"><h2 class="section-title">最近运行</h2><button class="button" type="button" onclick="loadRuns()">刷新记录</button></div><div id="runRows" class="run-rows">暂无运行记录</div></section><section class="card table-card">')
PAGE = PAGE.replace('</style>', '.run-rows{display:grid;gap:6px}.run-row{display:grid;grid-template-columns:90px 1fr 145px 110px;gap:10px;padding:7px 9px;border-radius:6px;background:#f4f7f9;color:#56636e;font-size:12px}.run-row strong{color:#26333d}.run-row .ok{color:#32714d}.run-row .bad{color:#9a403d}@media(max-width:760px){.run-row{grid-template-columns:1fr 1fr}}</style>')
PAGE = PAGE.replace('</style>', '.run-detail{display:block;margin-top:3px;color:#9a5a35;white-space:normal;line-height:1.35}</style>')
PAGE = PAGE.replace('</style>', '.download-heading-actions{display:flex;align-items:center;gap:10px}.download-rule{margin-top:9px}.download-card .section-title{margin-bottom:0}@media(max-width:760px){.download-heading-actions{align-items:flex-end;flex-direction:column}}</style>')
PAGE = PAGE.replace('</body>', '<script>window.selectTag=function(kind,value){if(!value)return;addTag(kind,value);const picker=$(kind+"_tag_select");if(picker)picker.value="";};window.loadTags=async function(){const r=await fetch("/api/tags"),d=await r.json();for(const kind of ["include","exclude"]){const picker=$(kind+"_tag_select");if(!picker)continue;picker.innerHTML="<option value=\"\">选择预设标签</option>"+d.tags.map(t=>`<option value="${esc(t.name)}">${esc(t.name)}</option>`).join("");}const quick=$("quick_tags");if(quick)quick.innerHTML="";};loadTags();</script></body>')
PAGE = PAGE.replace('picker.innerHTML="<option value="">选择预设标签</option>"', 'picker.innerHTML=\'<option value="">选择预设标签</option>\'')
PAGE = PAGE.replace('</body>', '<script>window.loadAuthors=async function(){const r=await fetch("/api/authors"),d=await r.json(),picker=$("author");picker.innerHTML=\'<option value="">全部作者</option>\'+d.authors.map(a=>`<option value="${esc(a.name)}">${esc(a.name)}（${esc(a.count)}）</option>`).join("");};loadAuthors();</script></body>')
PAGE = PAGE.replace('<span class="status ${cls}">${esc(s)}</span>', '<span class="status ${cls}">${esc(s)}</span><div class="purchase-state">购买：${esc(w.purchase_status||"未购买")}</div>')
PAGE = PAGE.replace('</body>', '<script>const filterValues=()=>Object.fromEntries(params().entries());window.purchase=async function(){const message=$("purchaseMessage"),button=document.querySelector(".purchase-card button");const execute=$("purchase_execute").checked;const auto_purchase=$("auto_purchase").checked;const count=Math.max(1,Math.min(100,Number($("purchase_count").value)||2));const max_price=Math.max(0,Math.min(10000,Number($("max_price").value)||0));const min_balance=Math.max(0,Math.min(1000000,Number($("min_balance").value)||0));const thread_ids=[...document.querySelectorAll(".pick:checked")].map(x=>x.value);if(execute&&!window.confirm(`确认${auto_purchase?"自动":"按数量"}购买，单篇不超过 ${max_price} 金币，并保留至少 ${min_balance} 金币？`))return;button.disabled=true;message.textContent=execute?"正在执行购买，请保持浏览器登录…":"正在预览价格，请稍候…";try{const r=await fetch("/api/purchase",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({count,max_price,min_balance,auto_purchase,execute,thread_ids,filters:filterValues()})});const d=await r.json();if(!r.ok)throw Error(d.error||"购买流程失败");const rows=(d.results||[]).filter(x=>x.thread_id);const bought=Number(d.bought||0);const stopped=rows.find(x=>x.status==="余额保留");message.textContent=`${execute?"购买完成":"预览完成"}：处理 ${rows.length} 篇，实际购买 ${bought} 篇${stopped?"，已达到最低余额":""}。`;await loadWorks();}catch(e){message.textContent="购买失败："+e.message;}finally{button.disabled=false;}};</script></body>')
PAGE = PAGE.replace('${esc(w.price)}', '${esc(Number(w.price||0)>0?w.price:(w.purchase_status===\'免费\'?\'免费\':\'未探测\'))}')
PAGE = PAGE.replace('${esc(w.purchase_status||"未购买")}', '${esc(w.purchase_status===\'未购买\'&&Number(w.price||0)===0?\'未探测\':(w.purchase_status||\'未购买\'))}')
PAGE = PAGE.replace("title_keyword:''", "title_keyword:$('title_keyword').value")
PAGE = PAGE.replace('</body>', '<script>const selectedIds=()=>[...document.querySelectorAll(".pick:checked")].map(x=>x.value);window.downloadPosts=async function(mode){const message=$("actionMessage"),execute=true,thread_ids=selectedIds();if((mode==="selected"||mode==="redownload")&&!thread_ids.length){message.textContent="请先勾选帖子";return;}const count=mode==="redownload"?Math.max(1,Math.min(100,thread_ids.length)):Math.max(1,Math.min(100,Number($("download_count").value)||2)),max_price=Math.max(0,Math.min(10000,Number($("download_max_price").value)||0)),min_balance=Math.max(0,Math.min(1000000,Number($("download_min_balance").value)||0)),max_pages_per_work=Math.max(1,Math.min(100,Number($("download_max_pages").value)||6));const scope=mode==="auto"?"忽略当前筛选并按查看数降序自动下载":mode==="redownload"?"重新抓取勾选帖子的正文":mode==="current"?"下载当前筛选结果":"下载勾选帖子";if(!window.confirm(`确认${scope}，共处理 ${count} 篇？单篇不超过 ${max_price} 金币，至少保留 ${min_balance} 金币；单帖最多抓取 ${max_pages_per_work} 页。`))return;message.textContent=mode==="auto"?"正在按查看数自动购买和下载，请保持浏览器登录…":mode==="redownload"?"正在重新购买、抓取和清洗，请保持浏览器登录…":"正在购买、抓取和清洗，请保持浏览器登录…";try{const r=await fetch("/api/download",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({mode,thread_ids,filters:filterValues(),count,max_price,min_balance,max_pages_per_work,minimum_length:Number($("minimum_length").value)||200,execute})});const d=await r.json();if(!r.ok)throw Error(d.error||"下载流程失败");message.textContent=`下载完成：成功 ${d.downloaded}，跳过 ${d.skipped}，失败 ${d.failed}，停止原因：${d.stop_reason}`;await loadWorks();}catch(e){message.textContent="下载失败："+e.message;}};window.exportWorks=async function(mode){const message=$("actionMessage"),thread_ids=selectedIds();if(mode==="selected"&&!thread_ids.length){message.textContent="请先勾选已下载作品";return;}message.textContent="正在生成导出文件…";try{const r=await fetch("/api/export",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({mode,thread_ids,filters:filterValues(),format:$("export_format").value})});const d=await r.json();if(!r.ok)throw Error(d.error||"导出失败");message.textContent=`已导出 ${d.exported} 篇：${d.path}`;}catch(e){message.textContent="导出失败："+e.message;}};</script></body>')
PAGE = PAGE.replace("const cls=s==='已下载'?'done':s.includes('失败')?'fail':s==='有更新'?'update':'';", "const cls=s==='已下载'?'done':(s.includes('失败')||['金币超限','余额不足','页面异常'].includes(s))?'fail':s==='有更新'?'update':'';")
PAGE = PAGE.replace('</body>', '<script>window.loadRuns=async function(){const box=$("runRows");try{const r=await fetch("/api/runs?limit=5"),d=await r.json();box.innerHTML=d.runs.length?d.runs.map(x=>{const details=(x.results||[]).filter(y=>y.thread_id&&!["已抓取","待下载"].includes(y.status)).map(y=>`${y.thread_id}：${y.reason||y.status}`).join("；");return `<div class="run-row"><strong>${esc(x.sort_type==="auto_download"?"自动下载":x.sort_type==="redownload"?"重新抓取":x.sort_type==="download"?"下载":x.sort_type==="views"?"查看扫描":"回复扫描")}</strong><span>${esc(x.stop_reason||"运行中")}${details?`<small class="run-detail" title="${esc(details)}">${esc(details)}</small>`:""}</span><span>成功 ${esc(x.downloaded_count||x.scanned_count||0)} / 失败 ${esc(x.failed_count||0)}</span><span class="${String(x.stop_reason||"").includes("异常")?"bad":"ok"}">${esc((x.finished_at||x.started_at||"").replace("T"," ").slice(0,16))}</span></div>`}).join(""):"暂无运行记录";}catch(e){box.textContent="运行记录加载失败："+e.message;}};loadRuns();setInterval(loadRuns,3000);</script></body>')
PAGE = PAGE.replace('await loadWorks();}catch(e){message.textContent="下载失败："', 'await loadWorks();await loadRuns();}catch(e){message.textContent="下载失败："')
PAGE = PAGE.replace('购买可在下方“购买设置”中预览或启动。', '选择查看数或回复数排序后，可按批次自动购买、抓取和保存。')
PAGE = PAGE.replace('查看最新排序', '查看数降序')
PAGE = PAGE.replace('</body>', '<script>(()=>{const input=$("download_max_pages"),key="library.max_pages_per_work";const saved=Number(localStorage.getItem(key));if(input&&saved>=1&&saved<=100)input.value=String(saved);input?.addEventListener("change",()=>localStorage.setItem(key,String(Math.max(1,Math.min(100,Number(input.value)||6)))));})();</script></body>')
PAGE = PAGE.replace('</header>', '<div class="actions service-actions"><button class="button" type="button" onclick="stopTask()">停止当前任务</button><button class="button danger" type="button" onclick="shutdownService()">关闭服务</button></div></header>')
PAGE = PAGE.replace('</body>', '<script>async function stopTask(){const m=$("actionMessage")||$("scanMessage");if(!confirm("确认停止当前购买/下载任务？"))return;try{const r=await fetch("/api/stop-task",{method:"POST"}),d=await r.json();if(m)m.textContent=d.stopped?"已请求停止当前任务":"当前没有正在运行的任务";}catch(e){if(m)m.textContent="停止任务失败："+e.message;}}async function shutdownService(){if(!confirm("确认关闭管理服务？关闭后页面将无法继续操作。"))return;try{const r=await fetch("/api/shutdown",{method:"POST"}),d=await r.json();document.body.innerHTML="<main><section class=\\"card\\"><h2>服务已关闭</h2><p>管理服务已停止，可以关闭此页面。</p></section></main>";}catch(e){document.body.innerHTML="<main><section class=\\"card\\"><h2>服务已关闭</h2><p>管理服务已停止或连接已断开。</p></section></main>";}}</script></body>')
PAGE = PAGE.replace('</style>', '.service-actions{margin-top:0}.button.danger{color:#9a403d;border-color:#c98e8a}.button.danger:hover{background:#fff0ef}</style>')
PAGE = PAGE.replace('<button class="button primary" id="auto_download" type="button" onclick="downloadPosts(\'auto\')"><span class="icon">▶</span>自动下载</button>', '<button class="button primary" id="auto_download" type="button" onclick="downloadPosts(\'auto\')"><span class="icon">▶</span>自动下载</button><button class="button" id="retry_failed" type="button" onclick="downloadPosts(\'retry_failed\')"><span class="icon">↻</span>重试所有失败</button>')
PAGE = PAGE.replace('const count=mode==="redownload"?Math.max(1,Math.min(100,thread_ids.length)):Math.max(1,Math.min(100,Number', 'const count=mode==="redownload"?Math.max(1,Math.min(100,thread_ids.length)):mode==="retry_failed"?0:Math.max(1,Math.min(100,Number')
PAGE = PAGE.replace('const scope=mode==="auto"?"忽略当前筛选并按查看数降序自动下载":mode==="redownload"?"重新抓取勾选帖子的正文":mode==="current"?"下载当前筛选结果":"下载勾选帖子";', 'const scope=mode==="auto"?"忽略当前筛选并按查看数降序自动下载":mode==="redownload"?"重新抓取勾选帖子的正文":mode==="retry_failed"?"重试所有失败帖子":mode==="current"?"下载当前筛选结果":"下载勾选帖子";')
PAGE = PAGE.replace('message.textContent=mode==="auto"?"正在按查看数自动购买和下载，请保持浏览器登录…":mode==="redownload"?"正在重新购买、抓取和清洗，请保持浏览器登录…":"正在购买、抓取和清洗，请保持浏览器登录…";', 'message.textContent=mode==="auto"?"正在按查看数自动购买和下载，请保持浏览器登录…":mode==="redownload"?"正在重新购买、抓取和清洗，请保持浏览器登录…":mode==="retry_failed"?"正在重试所有失败帖子，请保持浏览器登录…":"正在购买、抓取和清洗，请保持浏览器登录…";')
PAGE = PAGE.replace('if(!window.confirm(`确认${scope}，共处理 ${count} 篇？单篇不超过 ${max_price} 金币，至少保留 ${min_balance} 金币；单帖最多抓取 ${max_pages_per_work} 页。`))return;', 'if(!window.confirm(mode==="retry_failed"?`确认${scope}？将逐个重试全部失败帖子，仅在余额不足时停止；单帖最多抓取 ${max_pages_per_work} 页。`:`确认${scope}，共处理 ${count} 篇？单篇不超过 ${max_price} 金币，至少保留 ${min_balance} 金币；单帖最多抓取 ${max_pages_per_work} 页。`))return;')
PAGE = PAGE.replace('x.sort_type==="redownload"?"重新抓取":x.sort_type==="download"', 'x.sort_type==="redownload"?"重新抓取":x.sort_type==="retry_failed"?"重试失败":x.sort_type==="download"')
# 用户要求隐藏独立购买面板但不要删除；可见流程统一从“下载”启动自动购买。
PAGE = PAGE.replace('<section class="card purchase-card">', '<section class="card purchase-card" hidden>')


def select_rows(db_path: Path, filters: dict[str, Any] | None = None, thread_ids: list[Any] | None = None) -> list[dict[str, Any]]:
    with LibraryDB(db_path) as db:
        rows = db.list_works(WorkFilter.from_mapping(filters or {}))
    wanted = {str(item) for item in (thread_ids or []) if str(item).strip()}
    return [row for row in rows if not wanted or str(row.get("thread_id")) in wanted]


def persist_download_results(db_path: Path, results: list[dict[str, Any]]) -> tuple[int, int, int, str]:
    downloaded = failed = skipped = 0
    stop_reason = "正常完成"
    with LibraryDB(db_path) as db:
        for result in results:
            thread_id = str(result.get("thread_id") or "")
            if not thread_id:
                continue
            status = str(result.get("status") or "页面异常")
            if status == "已抓取":
                if result.get("force_refetch"):
                    db.replace_posts(thread_id, result.get("posts", []))
                else:
                    for post in result.get("posts", []):
                        db.upsert_post(post)
                db.mark_downloaded(thread_id, local_path=str(result.get("local_path") or ""), content_hash=str(result.get("content_hash") or ""))
                if result.get("purchase_status"):
                    db.update_purchase_result(thread_id, status=str(result["purchase_status"]), price=result.get("price"))
                downloaded += 1
            elif status == "金币超限":
                if not result.get("force_refetch"):
                    for post in result.get("posts", []):
                        db.upsert_post(post)
                db.update_download_result(thread_id, status=status, price=result.get("price"), purchase_status=str(result.get("purchase_status") or ""))
                skipped += 1
            elif status in {"余额不足", "页面异常", "购买失败", "下载失败"}:
                if not result.get("force_refetch"):
                    for post in result.get("posts", []):
                        db.upsert_post(post)
                db.update_download_result(thread_id, status=status, price=result.get("price"), purchase_status=str(result.get("purchase_status") or ""))
                failed += 1
                if status == "余额不足":
                    stop_reason = "金币不足"
            else:
                skipped += 1
    return downloaded, failed, skipped, stop_reason


def summarize_run_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for result in results:
        item = {key: value for key, value in result.items() if key not in {"posts", "post_html", "raw_html"}}
        item["post_count"] = len(result.get("posts", []))
        summaries.append(item)
    return summaries


class Handler(BaseHTTPRequestHandler):
    db_path = DB_PATH

    def _send(self, body: str | bytes, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/": self._send(PAGE); return
        if parsed.path == "/api/works":
            values = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
            with LibraryDB(self.db_path) as db: works = db.list_works(WorkFilter.from_mapping(values))
            self._send(json.dumps({"works": works}, ensure_ascii=False), content_type="application/json; charset=utf-8"); return
        if parsed.path == "/api/tags":
            counts: dict[str, int] = {}
            with LibraryDB(self.db_path) as db:
                for work in db.list_works():
                    for tag in work.get("tags", []): counts[tag] = counts.get(tag, 0) + 1
            tags = [{**preset, "count": counts.get(preset["name"], 0)} for preset in FORUM_TAG_PRESETS]
            self._send(json.dumps({"tags": tags}, ensure_ascii=False), content_type="application/json; charset=utf-8"); return
        if parsed.path == "/api/authors":
            with LibraryDB(self.db_path) as db: authors = db.list_authors()
            self._send(json.dumps({"authors": authors}, ensure_ascii=False), content_type="application/json; charset=utf-8"); return
        if parsed.path == "/api/runs":
            limit = int(parse_qs(parsed.query).get("limit", ["20"])[-1] or 20)
            with LibraryDB(self.db_path) as db: runs = db.list_runs(limit=limit)
            self._send(json.dumps({"runs": runs}, ensure_ascii=False), content_type="application/json; charset=utf-8"); return
        self._send("Not Found", 404, "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/stop-task":
            stopped = request_stop()
            self._send(json.dumps({"stopped": stopped}, ensure_ascii=False), content_type="application/json; charset=utf-8")
            return
        if path == "/api/shutdown":
            self._send(json.dumps({"stopping": True}, ensure_ascii=False), content_type="application/json; charset=utf-8")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/api/download":
            run_id: int | None = None
            try:
                size = int(self.headers.get("Content-Length", "0")); data = json.loads(self.rfile.read(size) or b"{}")
                mode = str(data.get("mode") or "selected")
                thread_ids = data.get("thread_ids") if isinstance(data.get("thread_ids"), list) else []
                if mode in {"selected", "redownload"} and not thread_ids:
                    self._send(json.dumps({"error": "请先勾选至少一篇帖子"}, ensure_ascii=False), 400, "application/json; charset=utf-8"); return
                raw_filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
                if mode == "auto":
                    with LibraryDB(self.db_path) as db: rows = db.list_works()
                    rows.sort(key=lambda row: (-int(row.get("views") or 0), -int(row.get("replies") or 0), str(row.get("thread_id") or "")))
                elif mode == "retry_failed":
                    with LibraryDB(self.db_path) as db: rows = [row for row in db.list_works() if str(row.get("download_status") or "") in RETRYABLE_DOWNLOAD_STATUSES]
                else:
                    rows = select_rows(self.db_path, raw_filters, thread_ids if mode in {"selected", "redownload"} else None)
                retry_all = mode == "retry_failed"
                count = len(rows) if retry_all else max(1, min(100, int(data.get("count") or len(rows) or 1)))
                execute = bool(data.get("execute", False))
                max_price = 1_000_000 if retry_all else max(0, min(10000, int(data.get("max_price") or 0)))
                min_balance = 0 if retry_all else max(0, min(1000000, int(data.get("min_balance") or 0)))
                settings = DownloadSettings(count=max(1, count), max_price=max_price, min_balance=min_balance, max_pages_per_work=max(1, min(100, int(data.get("max_pages_per_work") or 6))), minimum_length=max(0, min(100000, int(data.get("minimum_length") or 200))), execute=execute, force=retry_all or mode == "redownload", data_root=DATA_ROOT)
                with LibraryDB(self.db_path) as db:
                    for row in rows:
                        if not settings.force and row.get("download_status") != "已下载" and not row.get("local_path"):
                            row["existing_posts"] = db.list_posts(str(row.get("thread_id") or ""))
                    run_id = db.start_run("auto_download" if mode == "auto" else ("redownload" if mode == "redownload" else ("retry_failed" if mode == "retry_failed" else "download")), {"mode": mode, "count": count, "max_price": settings.max_price, "min_balance": settings.min_balance, "max_pages_per_work": settings.max_pages_per_work, "minimum_length": settings.minimum_length, "execute": execute, "filters": {} if mode in {"auto", "retry_failed"} else raw_filters, "thread_ids": [] if mode in {"auto", "retry_failed"} else thread_ids})
                streamed_results: list[dict[str, Any]] = []
                persisted_thread_ids: set[str] = set()
                streamed_counts = {"downloaded": 0, "failed": 0, "skipped": 0}
                streamed_stop = "正常完成"
                def on_download_result(result: dict[str, Any]) -> None:
                    nonlocal streamed_stop
                    streamed_results.append(result)
                    d_count, f_count, s_count, reason = persist_download_results(self.db_path, [result])
                    if result.get("thread_id"):
                        persisted_thread_ids.add(str(result["thread_id"]))
                    streamed_counts["downloaded"] += d_count; streamed_counts["failed"] += f_count; streamed_counts["skipped"] += s_count
                    if reason != "正常完成": streamed_stop = reason
                    with LibraryDB(self.db_path) as live_db:
                        live_db.finish_run(run_id, downloaded_count=streamed_counts["downloaded"], failed_count=streamed_counts["failed"], skipped_count=streamed_counts["skipped"], stop_reason=streamed_stop, results=summarize_run_results(streamed_results))
                results = run_download(rows, settings, on_result=on_download_result if execute else None)
                if execute:
                    downloaded = streamed_counts["downloaded"]; failed = streamed_counts["failed"]; skipped = streamed_counts["skipped"]; stop_reason = streamed_stop
                    remaining = [result for result in results if str(result.get("thread_id") or "") not in persisted_thread_ids]
                    if remaining:
                        extra = persist_download_results(self.db_path, remaining)
                        downloaded += extra[0]; failed += extra[1]; skipped += extra[2]
                        streamed_results.extend(remaining)
                        if extra[3] != "正常完成": stop_reason = extra[3]
                    if stop_reason == "正常完成" and downloaded >= count:
                        stop_reason = "达到本次下载篇数"
                else:
                    downloaded, failed, skipped, stop_reason = 0, 0, len(results), "预览完成"
                with LibraryDB(self.db_path) as db:
                    db.finish_run(run_id, downloaded_count=downloaded, failed_count=failed, skipped_count=skipped, stop_reason=stop_reason, results=summarize_run_results(results))
                self._send(json.dumps({"results": results, "execute": execute, "mode": mode, "queued": len(results), "downloaded": downloaded, "failed": failed, "skipped": skipped, "stop_reason": stop_reason}, ensure_ascii=False), content_type="application/json; charset=utf-8")
            except Exception as exc:
                if _is_client_disconnect(exc):
                    append_log("client_disconnect", path=path, run_id=run_id, error=repr(exc))
                    # 任务结果已经由逐帖回调写入；这里只是客户端没有继续接收 HTTP 响应。
                    # 不能把未返回给客户端的数据库行批量改成失败。
                    return
                append_log("app_error", path=path, run_id=run_id, error=repr(exc))
                if run_id is not None:
                    # 单帖结果已经在回调中逐帖写回；批次异常时不再凭“没有返回”
                    # 推断其他帖子失败，避免把未访问的整批记录覆盖成页面异常。
                    streamed_results = locals().get("streamed_results", [])
                    streamed_counts = locals().get("streamed_counts", {})
                    with LibraryDB(self.db_path) as db:
                        db.finish_run(run_id, downloaded_count=int(streamed_counts.get("downloaded", 0)), failed_count=int(streamed_counts.get("failed", 0)), skipped_count=int(streamed_counts.get("skipped", 0)), stop_reason=f"页面异常：{type(exc).__name__}", results=summarize_run_results(streamed_results))
                try:
                    self._send(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), 500, "application/json; charset=utf-8")
                except Exception as response_exc:
                    append_log("error_response_send_failed", path=path, run_id=run_id, error=repr(response_exc))
            return
        if path == "/api/export":
            try:
                size = int(self.headers.get("Content-Length", "0")); data = json.loads(self.rfile.read(size) or b"{}")
                mode = str(data.get("mode") or "selected")
                thread_ids = data.get("thread_ids") if isinstance(data.get("thread_ids"), list) else []
                if mode == "selected" and not thread_ids:
                    self._send(json.dumps({"error": "请先勾选至少一篇已下载作品"}, ensure_ascii=False), 400, "application/json; charset=utf-8"); return
                raw_filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
                rows = select_rows(self.db_path, raw_filters, thread_ids if mode == "selected" else None)
                directories = [row["local_path"] for row in rows if row.get("local_path") and Path(str(row["local_path"])).exists()]
                if not directories:
                    self._send(json.dumps({"error": "当前范围没有可导出的已下载作品"}, ensure_ascii=False), 400, "application/json; charset=utf-8"); return
                export_format = str(data.get("format") or "zip").lower()
                if export_format not in {"txt", "zip"}: raise ValueError("导出格式只支持 txt 或 zip")
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                destination = EXPORT_ROOT / f"作品导出_{stamp}.{export_format}"
                target = export_txt(directories, destination) if export_format == "txt" else export_zip(directories, destination)
                self._send(json.dumps({"exported": len(directories), "path": str(target), "format": export_format, "mode": mode}, ensure_ascii=False), content_type="application/json; charset=utf-8")
            except Exception as exc:
                self._send(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), 500, "application/json; charset=utf-8")
            return
        if path == "/api/purchase":
            try:
                size = int(self.headers.get("Content-Length", "0")); data = json.loads(self.rfile.read(size) or b"{}")
                count = max(1, min(100, int(data.get("count") or 2)))
                max_price = max(0, min(10000, int(data.get("max_price") or 0)))
                execute = bool(data.get("execute", False))
                auto_purchase = bool(data.get("auto_purchase", False))
                min_balance = max(0, min(1000000, int(data.get("min_balance") or 0)))
                raw_filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
                requested_ids = {str(item) for item in (data.get("thread_ids") or []) if str(item).strip()}
                with LibraryDB(self.db_path) as db:
                    rows = db.list_works(WorkFilter.from_mapping(raw_filters))
                if requested_ids:
                    rows = [row for row in rows if str(row.get("thread_id")) in requested_ids]
                rows = [row for row in rows if not SKIP_PURCHASE_TAGS.intersection(row.get("tags", [])) and row.get("download_status") != "已下载" and row.get("purchase_status") != "已购买"]
                if auto_purchase:
                    rows.sort(key=lambda row: (-int(row.get("views") or 0), int(row.get("current_rank") or 0), str(row.get("thread_id") or "")))
                candidate_limit = min(len(rows), 100 if auto_purchase else max(count * 4, count))
                candidates = [PurchaseCandidate(thread_id=row["thread_id"], url=row["url"], title=row.get("title", ""), price=int(row.get("price") or 0), purchase_status=str(row.get("purchase_status") or "未购买")) for row in rows[:candidate_limit]]
                results = run_purchase(candidates, max_price=max_price, execute=execute, count=(100 if auto_purchase else count), auto_purchase=auto_purchase, min_balance=min_balance) if candidates else []
                bought = 0
                with LibraryDB(self.db_path) as db:
                    for result in results:
                        thread_id = str(result.get("thread_id") or "")
                        if not thread_id: continue
                        db.update_purchase_result(thread_id, status=str(result.get("status") or ""), price=result.get("price"))
                        if result.get("purchased"): bought += 1
                self._send(json.dumps({"results": results, "bought": bought, "execute": execute, "auto_purchase": auto_purchase, "min_balance": min_balance}, ensure_ascii=False), content_type="application/json; charset=utf-8")
            except Exception as exc:
                self._send(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), 500, "application/json; charset=utf-8")
            return
        if path != "/api/scan": self._send(json.dumps({"error":"Not Found"}), 404, "application/json; charset=utf-8"); return
        try:
            size = int(self.headers.get("Content-Length", "0")); data = json.loads(self.rfile.read(size) or b"{}")
            settings = ScanSettings(sort_type=str(data.get("sort_type") or "views"), pages=int(data.get("pages") or 20), forum_url=str(data.get("forum_url") or ScanSettings().forum_url))
            works = normalize_works(scan_with_browser(settings), settings)
            with LibraryDB(self.db_path) as db:
                run_id = db.start_run(settings.sort_type, {"pages": settings.pages, "forum_url": settings.forum_url}); count = db.upsert_many(works, sort_type=settings.sort_type); db.finish_run(run_id, scanned_count=count, stop_reason="正常完成"); total = db.count()
            self._send(json.dumps({"scanned_count": count, "total_count": total}, ensure_ascii=False), content_type="application/json; charset=utf-8")
        except Exception as exc: self._send(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), 500, "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args: Any) -> None: print("[library] " + fmt % args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="帖子扫描与筛选工具（第一阶段）"); parser.add_argument("--db", default=str(DB_PATH)); sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    scan = sub.add_parser("scan"); scan.add_argument("--sort", choices=("views", "replies"), default="views"); scan.add_argument("--pages", type=int, default=20); scan.add_argument("--forum-url", default=ScanSettings().forum_url); scan.add_argument("--fixture")
    serve = sub.add_parser("serve"); serve.add_argument("--host", default="127.0.0.1"); serve.add_argument("--port", type=int, default=8765); serve.add_argument("--open", action="store_true")
    purchase = sub.add_parser("purchase", help="按当前排名购买（默认 dry-run）"); purchase.add_argument("--count", type=int, default=2); purchase.add_argument("--max-price", type=int, default=3); purchase.add_argument("--auto", action="store_true", help="按排名购买至最低剩余金币"); purchase.add_argument("--min-balance", type=int, default=0, help="自动购买时保留的最低金币"); purchase.add_argument("--execute", action="store_true", help="确认后才真正提交购买")
    download = sub.add_parser("download", help="按当前排名抓取作者楼层（默认 dry-run）"); download.add_argument("--count", type=int, default=1); download.add_argument("--thread-id", action="append", default=[], help="限定 thread_id，可重复传入"); download.add_argument("--max-price", type=int, default=3); download.add_argument("--min-balance", type=int, default=0); download.add_argument("--max-pages-per-work", type=int, default=6); download.add_argument("--data-root", default="data"); download.add_argument("--execute", action="store_true", help="确认后才访问并保存正文")
    export = sub.add_parser("export", help="导出已保存作品"); export.add_argument("--status", default="已下载"); export.add_argument("--format", choices=("txt", "zip"), default="txt"); export.add_argument("--output", required=True)
    args = parser.parse_args(argv); db_path = Path(args.db)
    if args.command == "init":
        with LibraryDB(db_path): pass
        print(f"数据库已初始化：{db_path}"); return 0
    if args.command == "scan":
        settings = ScanSettings(sort_type=args.sort, pages=args.pages, forum_url=args.forum_url); raw = load_fixture(args.fixture, settings) if args.fixture else scan_with_browser(settings); works = normalize_works(raw, settings)
        with LibraryDB(db_path) as db:
            run_id = db.start_run(settings.sort_type, {"pages": settings.pages, "forum_url": settings.forum_url}); count = db.upsert_many(works, sort_type=settings.sort_type); db.finish_run(run_id, scanned_count=count, stop_reason="正常完成"); print(json.dumps({"scanned_count": count, "total_count": db.count()}, ensure_ascii=False))
        return 0
    if args.command == "purchase":
        with LibraryDB(db_path) as db:
            rows = db.list_works()
            eligible = [r for r in rows if not SKIP_PURCHASE_TAGS.intersection(r.get("tags", [])) and r.get("download_status") != "已下载" and r.get("purchase_status") != "已购买"]
            if args.auto:
                eligible.sort(key=lambda row: (-int(row.get("views") or 0), int(row.get("current_rank") or 0), str(row.get("thread_id") or "")))
            candidate_limit = 100 if args.auto else max(args.count * 4, args.count)
            candidates = [PurchaseCandidate(thread_id=r["thread_id"], url=r["url"], title=r["title"], price=int(r.get("price") or 0), purchase_status=str(r.get("purchase_status") or "未购买")) for r in eligible[:candidate_limit]]
        results = run_purchase(candidates, max_price=args.max_price, execute=args.execute, count=(100 if args.auto else args.count), auto_purchase=args.auto, min_balance=args.min_balance)
        with LibraryDB(db_path) as db:
            bought = 0
            for result in results:
                if not result.get("thread_id"): continue
                status = str(result.get("status") or "")
                db.update_purchase_result(result["thread_id"], status=status, price=result.get("price"))
                if result.get("purchased"): bought += 1
            print(json.dumps({"results": results, "bought": bought, "execute": args.execute}, ensure_ascii=False))
        return 0
    if args.command == "download":
        with LibraryDB(db_path) as db: rows = db.list_works()
        if args.thread_id:
            wanted = set(args.thread_id); rows = [row for row in rows if row["thread_id"] in wanted]
        settings = DownloadSettings(count=max(1, args.count), max_price=max(0, args.max_price), min_balance=max(0, args.min_balance), max_pages_per_work=max(1, min(100, args.max_pages_per_work)), data_root=Path(args.data_root), execute=args.execute)
        results = run_download(rows, settings)
        if args.execute:
            persist_download_results(db_path, results)
        print(json.dumps({"results": results, "execute": args.execute}, ensure_ascii=False)); return 0
    if args.command == "export":
        with LibraryDB(db_path) as db: rows = db.list_works(WorkFilter(status=args.status))
        directories = [row["local_path"] for row in rows if row.get("local_path")]
        target = export_txt(directories, args.output) if args.format == "txt" else export_zip(directories, args.output)
        print(json.dumps({"exported": len(directories), "path": str(target), "format": args.format}, ensure_ascii=False)); return 0
    Handler.db_path = db_path; server = ThreadingHTTPServer((args.host, args.port), Handler); url = f"http://{args.host}:{args.port}/"; print(f"筛选页面：{url}")
    if args.open: threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
    return 0


if __name__ == "__main__": raise SystemExit(main())
