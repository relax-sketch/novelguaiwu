# 第一阶段：扫描与筛选

## 目标

在项目根目录实现一个可运行的帖子扫描与筛选工具：

- 用 SQLite 保存 `works`、`posts`、`runs` 的第一阶段字段；
- 支持按查看数/回复数排序、扫描页数和本次排名写入；
- 提供可替换的 Browser Harness 扫描适配器，并支持离线样例数据验证；
- 提供本地筛选页面，支持状态、标签、标题/作者/数值条件和勾选操作。

## 阶段

- [completed] 1. 盘点现有工程并确定新增模块边界
- [completed] 2. 实现 SQLite 仓储与扫描数据模型
- [completed] 3. 实现 Browser Harness/fixture 扫描入口
- [completed] 4. 实现本地筛选页面与 HTTP API
- [completed] 5. 测试、文档和交接
- [completed] 6. 按排障记录将 Browser Harness 安装到当前项目
- [completed] 7. 用真实 `fid=3` 完成 20 页扫描与筛选页面验收
- [completed] 8. 第二阶段：实现价格/购买状态探测（默认 dry-run）
- [completed] 9. 第二阶段/第三阶段：单篇下载、清洗和 TXT/ZIP 导出实现
- [completed] 10. 第四阶段：更新检测、楼层去重和内容哈希
- [completed] 11. 全流程测试与批量下载安全闸
- [completed] 12. 按 thread_id 下载 6 篇并生成 TXT 预览
- [completed] 13. 对照 PRD 盘点剩余前端/API 缺口并确定安全边界
- [completed] 14. 接通前端下载：勾选帖子与当前筛选结果
- [completed] 15. 接通前端导出：勾选作品与当前筛选结果（TXT/ZIP）
- [completed] 16. 完善运行记录、状态显示、更新后重抓与错误反馈
- [completed] 17. 单元测试、HTTP 验证与浏览器完整验收（不执行批量下载）
- [completed] 18. 按用户简化实际操作流：隐藏独立购买面板，下载时自动购买，仅保留批次篇数与余额不足停止
- [completed] 19. 恢复单篇金币/最低余额限制，新增独立按查看数自动下载与作者预设筛选
- [completed] 20. 回归测试、HTTP 验证与 Browser Harness 可视化验收（不触发真实下载）
- [completed] 21. 增加全局单帖页数上限（默认 6），达到上限后按已下载保存
- [completed] 22. 修复购买状态竞态：元素等待、加载重试、购买后多次验证与逐项失败记录

## 决策记录

- 新功能放在仓库根目录下的独立 `library` 包。
- 第一阶段不购买、不下载正文、不清洗、不导出；按钮先提供明确的“未实现”反馈。
- 网站选择器采用 Discuz 常见结构并允许通过环境变量覆盖；真实页面校正留到人机交互阶段。
- 第一阶段验收已完成；第二阶段购买/正文下载暂不自动执行，等待明确进入下一阶段。
- 第二阶段购买已获用户明确授权，但本轮执行发生数量上限 bug；已停止外部操作并修复，后续下载范围需用户确认。
- 用户要求继续完成 PRD；本轮授权实现与本地 dry-run 验收，不把“完成前端入口”解释为再次执行真实批量下载。所有外部购买/下载接口默认预览，必须由前端明确勾选执行确认。
- 自动下载忽略页面筛选，始终按数据库最新查看数降序；已存在完整本地快照的作品永久跳过，不再因扫描检测到变化而覆盖。单篇超价只跳过，达到最低保留余额则停止整轮，成功完成数达到批次篇数后停止。

## 错误记录

| 错误 | 尝试 | 处理 |
| --- | --- | --- |
| 本地 HTTP 验证脚本用未编码的中文 query，`urllib` 抛 `UnicodeEncodeError` | 1 | 这是测试脚本问题，改用 `urllib.parse.urlencode` 重试 |
| Browser Harness DOM 检查把 `querySelector` 当成可迭代集合 | 1 | 改用 `querySelectorAll`，不影响扫描流程 |
| 在 PowerShell 中使用 Bash heredoc `python - <<'PY'` | 1 | 改用 PowerShell here-string 管道给 Python |
| 首次真实扫描标题为空，因为页面图标链接先于 `a.s.xst` 被匹配 | 1 | 优先选择 `a.s.xst`，再用任意帖子链接兜底 |
| dry-run 单测按 Python repr 查找 JSON 中的布尔值 | 1 | 改为断言生成脚本包含 `"execute": false` |
| 购买执行循环未传递 `--count`，一次误购 6 篇而非 2 篇 | 1 | 立即停止后续操作；将 count 写入 Browser Harness 配置并在成功数达到目标时硬 break；记录受影响 thread 和金额 |
| 最终前端验收时 Browser Harness doctor 显示 Chrome 存在但 active connections=0 | 1 | 不启动新的 automation profile；继续本地 HTTP/静态测试，等待用户重新开启当前 Chrome 的远程调试后补可视化复核 |
| 本轮首次回归仍断言旧的“有更新”和无限价格配置 | 1 | 需求已明确改为永久跳过完整下载并恢复价格上限，更新测试为新行为后 5/5 通过 |
| 合并停止旧服务与启动新服务的 PowerShell 命令被执行策略拦截 | 1 | 拆分为精确 PID 停止、单独隐藏启动和独立健康检查，成功恢复服务 |
| `py_compile library/*.py` 在 Windows 不展开通配符 | 1 | 改用 `python -m compileall -q library`，全部模块编译通过 |
| 首次只读候选探测被外层 10 秒命令超时终止 | 1 | 未执行购买；缩小候选范围并将只读超时提高到 180 秒，成功得到付款页状态 |
| 两篇真实验证的 HTTP 客户端被外层 10 秒超时终止 | 1 | 未重发请求以避免重复购买；监控原 run 17，服务器继续完成并最终成功 2 / 失败 0 |
