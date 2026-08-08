# 发现记录

## 2026-07-22

- 根目录的 `1.prd` 是本项目需求，功能代码位于独立的 `library` 包。
- 项目已锁定 `uv run browser-harness`，不能调用全局可执行文件。
- 现有目标站点默认域名为 `https://monster-nest.com`，本次目标版块 URL 为 `forum.php?mod=forumdisplay&fid=3&page=1`。
- 现有发现表明普通主题在 `tbody#normalthread_*`，置顶主题在 `tbody#stickthread_*`；扫描器应优先读取普通主题。
- 第一阶段需要保留 `thread_id` 唯一性和每次扫描的 `current_rank`、`sort_type`、`rank_updated_at`。
- `uv run browser-harness --doctor` 显示 Chrome 和 daemon 正常，但当前 active browser connections 为 0；真实扫描需你先在 Chrome 中开启远程调试并保持已登录页面。
- 已按 `browser-harness-troubleshooting.md` 的项目范围方案安装固定 commit `9c95cea713ae4890df7518f0cff27f41427fbf5b`；当前项目版本为 `0.1.5`。
- 当前版本的 `uv run browser-harness skill` 只输出 `../../SKILL.md` 路径文本，因此项目 skill 使用了根目录 `.codex/skills/browser-harness/SKILL.md` 的有效本地内容，并明确要求 `uv run browser-harness`。
- 真实版块 `fid=3` 的普通主题行使用 `tbody#normalthread_*`；每行 `td.num > a` 是回复数、`td.num > em` 是查看数，主题标题是 `a.s.xst`，分类标签是 `a[href*="filter=typeid"]`，作者和时间在两个 `td.by` 中。
- 按查看数扫描 2 页已成功写入 34 条作品；分页链接可推导每个帖子的 `page_count`（例如 802 为 9 页、8997 为 19 页）。
- 按查看数扫描 20 页已成功写入 394 条作品；按回复数扫描第 1 页也已验证排序结果（前五条回复数 199、193、186、178、166）。
- 本地页面新增 `/api/tags` 和包含/排除标签多选控件；当前 394 条作品中识别出 14 个标签。
- 第二阶段只读勘察：thread 802 帖子页有 `a.viewpay`“购买主题”链接；付费页使用 `form#payform`，价格在表格中 `售价(金钱)`，提交按钮为 `button[name=paysubmit]`，当前页面登录态正常。
- 用户补充排除规则：`第1届站娘大赛`、`版务`、`绘画or游戏` 不进入购买/下载队列；已作为固定候选排除标签。
- 6 篇已购买作品已实际抓取作者楼层并保存 TXT；第一次清洗发现 `.quote` 父容器导致正文被跳过、`jammer` 干扰文本未过滤，已修正并从本地 `raw.html` 重清洗。当前 TXT 均为有效 UTF-8，无明显 `jammer`/mojibake。
- 用户补充无图模式和命名规则；已移除已保存 raw HTML 中的 `<img>`，TXT 改名为 `标题_作者名.txt`。正式抓取器在 DOM clone 后移除图片，再按楼层作者 ID 过滤；QA 截图仅作本次验收，不进入正式流程。
- `fid=3` 页面顶部预设标签共 17 个：催眠纯爱、催眠NTR、改造变化、女主视角、性转相关、常识改变、母系乱伦、清水无肉、其他XP、翻译小说、AI辅助、绘画or游戏、2025【怪物】征文、2025【巢】征文、2026新春征文、第1届站娘大赛、版务。扫描结果只覆盖其中一部分，管理页筛选不能只从扫描结果反推选项。
- PRD 剩余主要缺口集中在管理页：现有 `download`/`export` CLI 和底层模块已经存在，但前端按钮仍调用 `notReady`，且缺少“下载当前筛选”“导出当前筛选”、标题关键词、下载设置与运行反馈。
- `content_browser.py` 当前能购买并抓取作者楼层，但尚未识别余额不足/空页面，也没有把免费或已购买状态随抓取结果回写；完成 PRD 时需要补充这些状态分支。
- 前端真实下载必须继续设置双重安全闸：默认 dry-run，只有勾选“确认后实际下载”并经过浏览器确认才向 `/api/download` 发送 `execute=true`。本轮只验证 dry-run，不批量访问帖子。
- HTTP dry-run 验证表明下载队列可以复用现有 `build_download_queue`，不会访问 Browser Harness；导出可直接复用已保存作品目录，服务器统一将产物放入项目 `exports/`，避免前端传入任意文件路径。
- Browser Harness doctor 曾短暂报告 0 连接，但 `DevToolsActivePort` 仍存在且直接 `page_info()` 可恢复会话；最终本地页面交互验证成功，无需启动新浏览器配置。
- 自动下载的排名不能依赖 `current_rank`，因为该字段可能来自回复数扫描；应在启动时直接按当前数据库 `views DESC` 排序。完整下载判定应优先使用已保存的 `local_path`/下载时间，避免旧的“有更新”状态让作品再次进入队列。
- Browser Harness DOM 验收显示作者下拉框共 159 项（含“全部作者”），自动下载按钮和三项限制均可见，独立购买面板保持隐藏。全页截图出现疑似长页面拼接重复，需用 DOM 数量与普通视口截图复核，不能据此判断页面实际重复。
- 自动下载 run 13（15:28–15:30 UTC）配置为篇数 5、单篇上限 4、最低余额 10、单帖最多 5 页，结果为成功 5 / 失败 4。失败的 4 个 thread_id 为 1027、44574、26366、43338，数据库统一写成 `下载失败` / `购买失败`，没有保存更细的 reason。
- 对这 4 篇做了只读付款状态探测：1027、44574、43338 当前均无 `a.viewpay` 购买链接，而扫描时数据库价格分别为 1、3、2 金币；这与“点击购买后，程序 1.5 秒内回到主题仍看到旧购买链接”导致的误判相符，不能安全地再次购买。26366 当前仍有购买链接，仍是未确认购买状态。
- 这暴露出购买成功校验的竞态：`content_browser.py` 点击后固定等待 1.5 秒，只要旧链接暂时存在就写“购买失败”；运行记录只记聚合数，无法回溯每项 reason。当前不自动修正数据库，避免把疑似已扣费作品误标或重复购买。
- 购买修复采用三层等待：主题页等待 `#thread_subject` 与帖子楼层（最多 3 次）、付款页等待 `#payform` 与可见 `button[name=paysubmit]`（最多 3 次）、提交后等待网络空闲并最多 4 次重新打开主题验证购买链接消失。提交按钮只点击一次，验证重试绝不重复提交。
- run 17 使用明确授权的两篇未购买作品验证：34186 售价 3、38686 售价 1，限制为 count=2/max_price=4/min_balance=10/max_pages=6。最终成功 2、失败 0，两篇均标记已购买/已下载并生成 TXT；运行记录 `result_json` 保存逐项 reason、attempts、价格、路径和 post_count，不保存正文 HTML。
