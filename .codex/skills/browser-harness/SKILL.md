---
name: browser-harness
description: "Use the project-pinned Browser Harness for browser automation, scraping, testing, and site work."
---

# Browser Harness（本项目）

本项目连接独立的 Chrome profile 和 CDP 端口，默认使用有头、无图模式，避免接管日常 Chrome 时出现远程调试授权弹窗。启动器位于 `library/automation_browser.py`。

本项目所有浏览器调用必须使用项目锁定版本：

```powershell
uv run browser-harness
```

不要调用 PATH 中的全局 `browser-harness`。

## 本地 Chrome 连接

首次使用时以可见窗口完成一次登录（登录阶段允许图片）：

```powershell
uv run python -m library.automation_browser --with-images --url https://monster-nest.com/
```

关闭该窗口后，扫描、购买和下载命令会自动以相同 profile 启动有头无图模式。需要时可显式设置 `LIBRARY_BROWSER_HEADLESS=1` 使用 headless。

Browser Harness 连接专用 Chrome 的流程：

1. 确认默认专用端口 `9333` 可访问：`Invoke-RestMethod http://127.0.0.1:9333/json/version`。
2. 执行 `uv run browser-harness --doctor`，应看到 `active browser connections - 1`。
3. 用以下只读命令确认当前页面：

```powershell
@'
print(page_info())
'@ | uv run browser-harness
```

不要点击 Microsoft Store 的 `chrome:` 协议弹窗；不要为本地任务启动云端浏览器；不要在未确认登录态时继续访问需要登录的页面。专用 profile 的第一次登录仍需用户自己处理密码、MFA 或验证码。

## 页面操作约束

- 第一次导航使用 `new_tab(url)`，导航后调用 `wait_for_load()`。
- 页面状态优先用 `js(...)` 读取；坐标点击前先截图，点击后再截图确认。
- 遇到登录墙、密码、MFA、授权确认或账号选择时停止并交给用户。
- 扫描和 dry-run 只读；购买/下载只有在用户明确执行并确认后才提交表单。禁止发帖。

## 诊断

```powershell
uv run browser-harness --doctor
Get-ChildItem -Path "$env:LOCALAPPDATA\Google\Chrome\User Data" -Filter DevToolsActivePort -Recurse -ErrorAction SilentlyContinue
```

如果专用 Chrome 正在运行但 `active browser connections` 为 0，先检查 `BU_CDP_URL`、`BU_NAME`、`BH_HOME` 是否来自同一项目，不要删除其他项目的 daemon 状态。
