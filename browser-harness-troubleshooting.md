# browser-harness 安装与 Chrome 连接排障记录

> 说明：本文开头保留 2026-07-01 的全局安装历史；从 2026-07-11 起，推荐按“项目范围安装”使用。项目范围 skill 位于 `.codex/skills/`，不会影响其他项目的 Codex 行为。

记录时间：2026-07-01

## 2026-07-24：后续项目的无人值守推荐方案

### 结论先行

如果目标是定时任务、凌晨任务或其他无人值守自动化，不要接管用户日常使用的 Chrome 默认 profile。推荐为每个项目建立一个持久化的专用 Chrome profile，并使用以下三个环境变量连接：

```text
BU_CDP_URL=http://127.0.0.1:<固定端口>
BU_NAME=<项目唯一名称>
BH_HOME=<项目专用 browser-harness 状态目录>
```

原因：

- Chrome 144+ 对默认 profile 的新 CDP WebSocket 连接会显示 `Allow remote debugging?`，这是浏览器安全确认，不能依靠 CDP 自己绕过。
- 勾选 `chrome://inspect/#remote-debugging` 只代表允许浏览器开放调试端口，不代表永久信任后续每一条连接。
- 重试连接可能生成新的授权弹窗；更新 browser-harness 只能减少重复连接，不能让默认 profile 变成真正无人值守。
- 非默认 `--user-data-dir` 配合 `--remote-debugging-port` 不需要该授权弹窗，适合计划任务。

本方案已在 Windows、Chrome 150、browser-harness 0.1.5 上验证：可见窗口完成一次登录后，关闭并以 headless 模式重启同一专用 profile，登录态仍然有效，整个过程不出现 Chrome Allow 弹窗。

### 推荐目录与命名

每个项目使用不同的 profile、daemon 名称、harness 状态目录和端口。以下仅为示例：

```powershell
$projectName = 'example-project'
$automationRoot = Join-Path $env:LOCALAPPDATA $projectName
$profileRoot = Join-Path $automationRoot 'ChromeProfile'
$harnessHome = Join-Path $automationRoot 'BrowserHarness'
$cdpPort = 9333
$daemonName = 'example-project-auto'
```

不要把 Chrome profile 放进 Git 仓库。profile 包含 Cookie、站点数据和登录态，应只保存在当前用户可访问的本地目录，并加入备份与权限保护策略。

### 第一次启动：使用可见窗口登录

先确保该项目的专用端口没有被占用，然后启动非默认 profile：

```powershell
$chromePath = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$chromeOptions = @(
  '--remote-debugging-port=9333',
  "--user-data-dir=$profileRoot",
  '--profile-directory=Default',
  '--no-first-run',
  '--no-default-browser-check',
  'https://example.com/login'
)
Start-Process -FilePath $chromePath -ArgumentList $chromeOptions
```

用户只需在这个专用窗口完成一次登录。遇到密码、MFA、验证码、授权同意或账号选择时必须停下来让用户处理，不应把密码写进脚本，也不应自动猜测账号。

确认 CDP 已就绪：

```powershell
Invoke-RestMethod 'http://127.0.0.1:9333/json/version'
```

然后在同一个 PowerShell 会话设置连接隔离：

```powershell
$env:BU_CDP_URL = 'http://127.0.0.1:9333'
$env:BU_NAME = 'example-project-auto'
$env:BH_HOME = $harnessHome
```

验证 browser-harness；项目中始终使用锁定版本：

```powershell
@'
print(page_info())
'@ | uv run browser-harness
```

确认登录成功后关闭专用 Chrome。后续定时任务应以相同 `--user-data-dir` 启动，不要创建新的临时 profile。

### 无人值守启动：复用同一 profile

headless 启动示例：

```powershell
$chromeOptions = @(
  '--headless=new',
  '--remote-debugging-port=9333',
  "--user-data-dir=$profileRoot",
  '--profile-directory=Default',
  '--no-first-run',
  '--no-default-browser-check',
  'about:blank'
)
Start-Process -FilePath $chromePath -ArgumentList $chromeOptions -WindowStyle Hidden
```

启动 Chrome 后应轮询 `/json/version`，确认 `webSocketDebuggerUrl` 存在，再运行 browser-harness。不要只判断 `chrome.exe` 是否存在，因为那可能是用户的日常 Chrome，也不要用固定 `Start-Sleep` 代替有上限的就绪检查。

当前项目的 `automation_browser.py` 可以作为后续项目模板，其职责是：

1. 检查专用 CDP endpoint 是否健康。
2. 找不到 endpoint 时启动固定 profile 的 Chrome。
3. 等待 `/json/version` 就绪。
4. 为 browser-harness 子进程注入 `BU_CDP_URL`、`BU_NAME` 和 `BH_HOME`。
5. 浏览器崩溃后，在下一次任务调用前自动重启。

计划任务不应依赖交互式终端里临时设置的环境变量。启动器或任务程序应显式构造子进程环境，例如：

```python
env = os.environ.copy()
env["BU_CDP_URL"] = "http://127.0.0.1:9333"
env["BU_NAME"] = "example-project-auto"
env["BH_HOME"] = str(harness_home)
subprocess.run(
    ["uv", "run", "browser-harness"],
    input=browser_program,
    text=True,
    env=env,
)
```

### 不要依赖复制日常 profile 获取登录态

在 Chrome 完全退出后复制默认 profile 的 `Default` 目录和根目录 `Local State`，虽然能复制普通站点数据，但不保证登录 Cookie 可用。

本次验证中：

- 来源 Cookie 数据库包含目标站点的认证 Cookie。
- 复制后的专用 profile 能读取普通 Cookie。
- Chrome 启动专用 profile 后丢弃了无法解密的认证 Cookie，页面仍显示未登录。
- 在专用可见窗口手动登录一次后，再切换到 headless，同一登录态可以稳定复用。

这是新版 Chrome Cookie/App-Bound Encryption 与 profile 环境绑定造成的实际限制。后续项目应把“专用 profile 第一次可见登录”作为标准初始化流程，不应尝试读取、打印、解密或在日志中暴露 Cookie 值。

### `BU_NAME` 与 `BH_HOME` 必须一起隔离

只设置 `BU_CDP_URL` 仍可能复用默认 browser-harness daemon，导致不同项目争用同一个 session。推荐：

- `BU_NAME`：隔离 daemon 名称和 IPC endpoint。
- `BH_HOME`：隔离 port/pid/log/tmp 等运行状态，避免旧项目留下的 daemon 文件权限冲突。
- `BU_CDP_URL`：明确连接哪个专用 Chrome endpoint。

如果出现类似错误：

```text
PermissionError: ... browser-harness\runtime\bu-<name>.port
```

不要删除其他项目的 daemon 文件。先确认使用了当前项目的 `BH_HOME`，然后在同一组环境变量下执行：

```powershell
$env:BH_HOME = $harnessHome
$env:BU_NAME = $daemonName
uv run browser-harness --reload
```

`--reload` 只停止对应名称的 daemon；下一次 harness 调用会自动重建连接。关闭 Chrome 前，应先通过端口和进程命令行确认目标确实是该项目的专用 profile，避免误杀用户日常浏览器。

### 复制项目后必须修复 `.venv` 启动器

Windows 的 `.venv\Scripts\browser-harness.exe` 可能保存原项目 Python 路径。直接复制整个项目目录后，即使运行 `uv run browser-harness`，堆栈也可能指向旁边的旧项目 `.venv`。

检查：

```powershell
uv run python -c "import sys, browser_harness; print(sys.executable); print(browser_harness.__file__)"
```

若路径不是当前项目，重装项目内 package 和入口：

```powershell
uv sync --reinstall-package browser-harness
uv run browser-harness --version
```

不要把复制来的 `.venv` 当作可移植环境；更稳妥的做法是删除/忽略 `.venv`，由 `uv sync` 在新目录重建。

### 页面操作与动态加载经验

后续项目的页面流程应遵守：

1. 第一次导航使用 `new_tab(url)`；已建立真实工作 tab 后再使用 `goto_url(url)`。
2. 导航后调用 `wait_for_load()`，再等待关键 DOM 条件，而不是只等待固定秒数。
3. 截图前确认页面和 CDP session 稳定；页面切换期间 `Page.captureScreenshot` 可能超时，可在确认仍是同一 tab 后重试一次。
4. 坐标点击遵循“截图 -> 读取坐标 -> 点击 -> 再截图”；能用 DOM 判断状态时优先使用 `js(...)`。
5. `document.readyState` 在某些长期加载资源的 Discuz 页面可能仍是 `loading`，但目标 DOM 已可用，因此应等待具体 selector，而不是死等 `complete`。
6. URL 可能被站点追加签名参数；成功判断应基于域名、路径和关键 DOM，不要要求 URL 字符串完全相等。
7. 保存的旧 URL 可能变成“提示信息”、已删除页或无权限页。缺少关键 selector 时应回到列表重新选择有效目标，不要永久重试同一个失效 URL。
8. CDP target 顺序不等于 Chrome 可见标签顺序。发现页面与用户看到的不一致时，使用 `list_tabs()`、`ensure_real_tab()` 或 `switch_tab(target_id)` 明确附着和激活目标。

调试时先用可见专用 Chrome，不要改回日常默认 profile。可见模式和 headless 模式只应改变启动参数，必须复用相同 `--user-data-dir`、端口约定和环境隔离。

### 推荐验收清单

新项目上线计划任务前至少验证：

- `uv run browser-harness --version` 与 import 路径来自当前项目。
- 专用 profile、`BU_NAME`、`BH_HOME` 和端口不与其他项目重复。
- 可见模式登录成功，且没有 Chrome Allow 弹窗。
- 关闭可见 Chrome 后，以 headless 重启同一 profile，登录态仍有效。
- `page_info()`、关键 DOM 读取和截图均成功。
- dry-run 不执行写操作，并能在任务计划的用户上下文中成功。
- 浏览器关闭或 daemon 失效后，下一次任务可以自愈重启。
- 任务日志不包含密码、API key、Cookie 值或完整敏感页面内容。

### 两种模式不要混用

| 目标 | 推荐方式 | 是否需要 Allow |
| --- | --- | --- |
| 临时接管用户当前 Chrome、复用所有日常标签和扩展 | 默认 profile + `chrome://inspect/#remote-debugging` | Chrome 144+ 通常需要用户确认 |
| 定时任务、凌晨任务、无人值守 | 专用非默认 `--user-data-dir` + 固定 CDP endpoint | 不需要 |
| 无本地桌面、并行任务或希望完全隔离 | Browser Use cloud browser | 不使用本地 Chrome Allow，但需要云端认证/费用 |

以下关于 `chrome://inspect`、Microsoft Store 弹窗和默认 profile 的章节只适用于第一种“有人值守接管日常 Chrome”的历史方案，不应作为无人值守方案使用。

## 背景

目标是在 Windows 上用 `uv` 和 Python 3.12 安装或升级 `browser-harness`，注册 Codex skill，并连接到当前正在使用的 Chrome 浏览器，而不是新开一个独立 profile 的自动化浏览器。

安装命令：

```powershell
uv tool install --python 3.12 --upgrade --force browser-harness
```

注册 skill：

```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.codex\skills\browser-harness"
browser-harness skill > "$env:USERPROFILE\.codex\skills\browser-harness\SKILL.md"
```

本次安装结果：

- `browser-harness` 版本：`0.1.3`
- Python runtime：`3.12.13`
- skill 文件：`C:\Users\Administrator\.codex\skills\browser-harness\SKILL.md`

## 2026-07-11：项目范围安装（推荐）

### 适用目标

将 `browser-harness` 作为某一个项目的 Python 依赖，并将 skill 写入项目的 `.codex/skills/browser-harness/SKILL.md`。这样 Codex 只在该项目中加载该 skill，不会为所有项目强制启用浏览器自动化。

### 前置条件

- 项目的 `pyproject.toml` 必须声明 `requires-python = ">=3.11"`；当前上游 `browser-harness` 0.1.5 要求 Python 3.11 或更高版本。
- 使用 `uv` 管理项目环境。
- 下例固定到已验证的上游 commit `9c95cea713ae4890df7518f0cff27f41427fbf5b`，便于复现；升级时应先在隔离环境测试新的 commit。

### 安装步骤

在项目根目录执行：

```powershell
uv add "browser-harness @ git+https://github.com/browser-use/browser-harness.git@9c95cea713ae4890df7518f0cff27f41427fbf5b"
New-Item -ItemType Directory -Force -Path ".codex\skills\browser-harness"
uv run browser-harness skill | Set-Content -Encoding utf8 ".codex\skills\browser-harness\SKILL.md"
```

随后在项目 skill 的开头补充一条项目约束：所有调用使用 `uv run browser-harness`，不要直接调用 PATH 中的同名全局可执行文件。这样能确保使用项目锁定版本。

不要执行以下全局注册步骤：

```powershell
# 不推荐：会使 skill 对所有项目生效
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.codex\skills\browser-harness"
browser-harness skill > "$env:USERPROFILE\.codex\skills\browser-harness\SKILL.md"
```

### 无需浏览器授权的安装验证

以下验证只检查项目依赖与 CLI，不会调用 `--doctor`、不会打开 Chrome，也不会触发远程调试授权：

```powershell
uv run browser-harness --version
uv run python -c "import browser_harness, importlib.resources as r; print(browser_harness.__file__); print(r.files('browser_harness').joinpath('SKILL.md').is_file())"
```

本项目验证结果：

- 版本：`0.1.5`
- Python：`3.12.11`
- 来源：`browser-use/browser-harness` commit `9c95cea713ae4890df7518f0cff27f41427fbf5b`
- 项目 skill：`.codex/skills/browser-harness/SKILL.md`

### `.venv` 被运行中的服务占用

若 `uv add` 或 `uv sync` 报错，无法替换 `websockets` 的 `.pyd` 文件（Windows `os error 5`），通常是项目服务仍在运行并加载了该文件。

处理方式：先停止使用该项目 `.venv` 的 `run.py` / uvicorn 进程，再执行：

```powershell
uv sync
uv run browser-harness --version
```

如需在不中断服务的情况下先验证锁文件，可在临时环境中执行：

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "<project>-browser-harness-test-venv"
uv sync
uv run browser-harness --version
```

测试结束后删除该临时虚拟环境即可。

### 全局 skill 的移除

如曾按旧流程注册过全局 skill，可移除其目录：

```powershell
Remove-Item -Recurse -Force "$env:USERPROFILE\.codex\skills\browser-harness"
```

这只移除 Codex 的全局触发规则，不会卸载 `browser-harness.exe`。项目仍应通过 `uv run browser-harness` 使用锁定版本。

## 遇到的问题

运行：

```powershell
@'
print(page_info())
'@ | browser-harness
```

或：

```powershell
browser-harness --doctor
```

初始结果显示：

```text
[ok  ] chrome running
[FAIL] daemon alive
[FAIL] active browser connections - 0
```

`page_info()` 报错核心信息：

```text
DevToolsActivePort not found
enable chrome://inspect/#remote-debugging, or set BU_CDP_WS for a remote browser
```

这说明 Chrome 正在运行，但当前 Chrome 实例没有开启远程调试端口，因此 `browser-harness` 无法通过 CDP 接管现有浏览器。

## 容易走偏的现象

### 1. Windows 弹出 Microsoft Store 协议窗口

症状：

```text
获取打开此 'chrome' 链接的应用
你的电脑没有可打开此链接的应用。请尝试在 Microsoft Store 中查找兼容应用。
```

原因：

`browser-harness` 在失败时会尝试打开：

```text
chrome://inspect/#remote-debugging
```

在本机 Windows 环境里，某些唤起方式会把 `chrome://` 当成系统协议 `chrome:`，而不是交给 Chrome 浏览器打开，于是 Windows 弹出 Microsoft Store 查找应用。

处理方式：

不要点击 Microsoft Store。这个弹窗不是远程调试授权。

正确方式是在当前 Chrome 浏览器的地址栏中手动输入或粘贴：

```text
chrome://inspect/#remote-debugging
```

### 2. 出现 Chrome 个人资料选择页

症状：

Chrome 打开 `Who's using Chrome?`，要求选择 profile。

原因：

Chrome 启动时没有明确进入当前使用的 profile，或者被 profile picker 拦截。

处理方式：

选择平时正在使用的 Chrome profile。也可以直接在已经打开的目标 Chrome 窗口中手动进入：

```text
chrome://inspect/#remote-debugging
```

### 3. 出现 `0.0.0.1` 错误页

症状：

浏览器地址栏显示：

```text
0.0.0.1
```

页面提示：

```text
This site can't be reached
ERR_ADDRESS_UNREACHABLE
```

原因：

这是失败重试或错误跳转留下的普通浏览器页面，不代表 `browser-harness` 是否连接成功。

处理方式：

可以忽略或关闭。以 `browser-harness --doctor` 和 `page_info()` 的输出为准。

## 真正根因

当前 Chrome 实例里的远程调试没有勾选。

必须在目标 Chrome 窗口打开：

```text
chrome://inspect/#remote-debugging
```

然后勾选：

```text
Allow remote debugging for this browser instance
```

勾选后页面会显示类似：

```text
Server running at: 127.0.0.1:9222
```

这时 Chrome 会生成：

```text
C:\Users\Administrator\AppData\Local\Google\Chrome\User Data\DevToolsActivePort
```

并监听本地端口：

```text
127.0.0.1:9222
```

## 验证命令

检查 `DevToolsActivePort` 是否存在：

```powershell
Get-ChildItem -Path "$env:LOCALAPPDATA\Google\Chrome\User Data" -Filter DevToolsActivePort -Recurse -ErrorAction SilentlyContinue |
  Select-Object FullName,LastWriteTime,Length
```

检查 Chrome 是否监听本地调试端口：

```powershell
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object {
    $_.OwningProcess -in (Get-Process chrome -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
  } |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

成功时应看到类似：

```text
LocalAddress LocalPort OwningProcess
------------ --------- -------------
127.0.0.1    9222      <chrome-pid>
```

检查 harness 状态：

```powershell
browser-harness --doctor
```

成功结果：

```text
[ok  ] chrome running
[ok  ] daemon alive
[ok  ] active browser connections - 1
```

测试页面信息：

```powershell
@'
print(page_info())
'@ | browser-harness
```

本次成功返回：

```text
{'url': 'chrome-error://chromewebdata/', 'title': '0.0.0.1', ...}
```

这说明 `browser-harness` 已经连接到了当前 Chrome，只是当前活动页面刚好是 `0.0.0.1` 错误页。

## 历史：接管当前 Chrome 的全局流程

1. 安装或升级：

```powershell
uv tool install --python 3.12 --upgrade --force browser-harness
```

2. 注册 skill：

```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.codex\skills\browser-harness"
browser-harness skill > "$env:USERPROFILE\.codex\skills\browser-harness\SKILL.md"
```

3. 在当前 Chrome 手动打开：

```text
chrome://inspect/#remote-debugging
```

4. 勾选：

```text
Allow remote debugging for this browser instance
```

5. 确认页面显示：

```text
Server running at: 127.0.0.1:9222
```

6. 验证：

```powershell
browser-harness --doctor
```

7. 测试连接：

```powershell
@'
print(page_info())
'@ | browser-harness
```

## 注意

- 如果目标是接管当前正在使用的 Chrome，不要启动独立 automation profile。
- `Browser Use cloud auth` 是可选项，本地 Chrome 连接不需要登录云端。
- Microsoft Store 的 `chrome` 链接弹窗不是授权，不要作为故障解决方向。
- 关键判断标准是 Chrome 是否显示 `Server running at: 127.0.0.1:9222`，以及 `browser-harness --doctor` 是否显示 daemon 和 active browser connections 为 ok。
