# 怪物派趣小说下载器

这是一个用于扫描论坛帖子、筛选作品、自动购买并下载小说正文的本地工具。项目提供浏览器可视化界面，也提供命令行入口。

## 环境

- Windows PowerShell
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- 真实扫描和正文下载使用项目专用 Chrome profile；第一次登录需要用户在可见窗口完成，后续任务自动复用登录态

首次使用可先同步依赖：

```powershell
cd D:\Github_All\guaiwu_paiqu
uv sync
```

## 打开可视化界面

使用现有数据库启动：

```powershell
uv run python -m library.app --db runtime/library.sqlite3 serve --open
```

如果浏览器没有自动打开，手动访问：<http://127.0.0.1:8765/>

界面包含：

- 按查看数或回复数扫描并更新帖子库
- 标题、作者、状态、标签、查看数和回复数筛选
- 按批次自动购买并下载
- 对勾选作品强制重新抓取正文；成功后替换旧快照，失败时保留旧内容
- 单篇最高金币、最低保留余额、单帖最多页数限制
- 导出合并 TXT 或包含独立 TXT 文件的 ZIP
- 最近运行记录和失败原因

下载按钮会访问网页并可能扣除金币；确认前请检查下载篇数、金币限制和余额设置。

## 初始化专用浏览器

项目不会接管日常 Chrome，也不需要每次人工同意远程调试。第一次使用时启动可见窗口并完成登录：

```powershell
uv run python -m library.automation_browser --with-images --url https://monster-nest.com/
```

登录完成后关闭该窗口。之后扫描、购买和下载命令会自动启动同一个专用 profile，保持有头窗口但禁止加载图片。profile 和 Browser Harness 状态保存在用户本地目录，不写入 SQLite。

如需手动启动当前模式：

```powershell
uv run python -m library.automation_browser
```

默认配置也可用环境变量覆盖：`LIBRARY_AUTOMATION_ROOT`、`LIBRARY_CHROME_PROFILE`、`LIBRARY_CDP_PORT`、`LIBRARY_BROWSER_NAME`、`LIBRARY_BROWSER_HARNESS_HOME`、`LIBRARY_CHROME_PATH`。

## 离线验收

不连接浏览器也可以用 fixture 验证扫描和页面：

```powershell
uv run python -m library.app --db runtime/demo.sqlite3 scan --fixture fixtures/library_sample.json --pages 1
uv run python -m library.app --db runtime/demo.sqlite3 serve --open
```

## 命令行

初始化数据库：

```powershell
uv run python -m library.app --db runtime/library.sqlite3 init
```

真实扫描（需要已登录浏览器）：

```powershell
uv run python -m library.app --db runtime/library.sqlite3 scan --sort views --pages 20
```

价格探测和下载默认是 dry-run，不会购买或保存正文：

```powershell
uv run python -m library.app --db runtime/library.sqlite3 purchase --count 2 --max-price 3
uv run python -m library.app --db runtime/library.sqlite3 download --count 2
```

只有明确增加 `--execute` 才会执行实际购买或正文抓取：

```powershell
uv run python -m library.app --db runtime/library.sqlite3 purchase --count 2 --max-price 3 --execute
uv run python -m library.app --db runtime/library.sqlite3 download --count 2 --max-pages-per-work 6 --execute
```

导出已下载作品：

```powershell
uv run python -m library.app --db runtime/library.sqlite3 export --status 已下载 --format zip --output exports/作品.zip
```

## 文件位置

- `library/`：应用、扫描、购买、下载、清洗和导出代码
- `runtime/library.sqlite3`：作品、帖子和运行记录数据库
- `data/`：下载后的作品快照和 TXT
- `exports/`：导出的 TXT 或 ZIP
- `fixtures/`：离线测试数据
- `tests/`：自动化测试

下载正文时会保存 `raw.html`、`metadata.json` 和按“标题_作者名.txt”命名的 TXT；默认不下载正文图片。

## 测试

```powershell
uv run python -m unittest discover -s tests -v
```

停止可视化服务时，在运行它的终端按 `Ctrl+C`。
