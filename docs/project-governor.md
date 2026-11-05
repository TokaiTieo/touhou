# NPC 协作系统实施与验收记录

## 当前快照

- 核对日期：2026-10-30；基线 v0.17.0 / 存档 V13，当前源码 v0.18.0 / V14。
- 治理：严格，仅覆盖本次权限、结算、恢复、评测和发布改动。
- 目标：全部稳定 ID 的 NPC 可独立决策，每回合按互动激活 0–6 人；可选上线，默认关闭。
- implementation: implemented-for-optional-release（M1–M5 已接入）；verification: automated-passed / real-quality-partial；acceptance: pending。最终产物已复验，真实评测已停止，默认模式未改变。
- 保留并行用户任务的人设修补、头像、updatelog.md 修改及用户 DOCX，不修改正式玩家存档。

## Project Map 与需求台账

人物串写风险 → 后端身份/权限和证据 → 上下文服务 → 隔离测试。
多人物决策 → 契约/运行时/调度/规则 → 候选状态 → 单次事务 → 恢复与冲突测试。
质量与费用 → 三模式同初始状态 → 固定案例、24/60 回合 → 独立测试报告与预算账本。

所有要求来源为本次用户最终方案；范围均 active，未列出的已完成证据不得推定为通过。

| ID | 要求与验收 | 验证 | 实现 / 验证 | 证据 |
| --- | --- | --- | --- | --- |
| MA-001 | 后端身份、五类只读查询、ACL/时间线/证据过滤 | 私密/纠错/传闻/统计延后 | implemented / scoped-pass | test_agent_context.py；test_agent_scheduler.py 后续私密隔离 |
| MA-002 | 通用人物实例、本人提案、主持人独立叙事 | 任意登记/自定义、拒绝跨 ID | implemented / scoped-pass | 94/94登记人物本人上下文检查；test_agent_runtime.py；真实自定义/随机人物通过 |
| MA-003 | 整回合 0–6 人、并发 3、依赖与延期 | 0/1/3/6/7/连锁唤醒 | implemented / scoped-pass | test_agent_scheduler.py；test_agent_recovery.py 六人真实检查点并发及重放 |
| MA-004 | 资源/日程冲突、去重、统一结算、轻量生活 | 转交须对方接受、日历一次推进 | implemented / scoped-pass | test_agent_scheduler.py；支持的领域命令外不声称全自由文本效果等价 |
| MA-005 | 候选结算一次、独立发言和统一事务 | 恢复不重复结算、分人历史 | implemented / scoped-pass | test_agent_recovery.py；e2e/agents.spec.mjs；EXE/解压ZIP 回执验证 |
| MA-006 | 子任务恢复、指纹失效、失败待恢复、取消保护 | 部分完成/主持人失败/ACL/revision/epoch/纠错 | implemented / scoped-pass | test_agent_recovery.py；test_agent_context.py；test_agent_persistence.py |
| MA-007 | 请求/Token/时间预算、预留和持久账本 | 未知计费、失败重试、重启 | implemented / scoped-pass | test_agent_runtime.py；reports/agent-evaluation-2026-10-29/budget.sqlite3 |
| MA-008 | 真实三模式固定案例 | 同初始夹具与调用政策、人工质量待审 | implemented / partial | structured-v2及release-wal均27/27；定性复核已记录，人工分数未填写 |
| MA-009 | 真实三模式 24/60 连续回合 | 失败留档、Token 统一封顶 | implemented / partial | 首轮24为24/24、24/24、22/24；60为60/60、60/60、58/60；最后协作复测24/24，人工质量未验收 |
| MA-010 | 可选设置、状态、V14 自动迁移/导入导出/回退 | 旧档/浏览器/布局 | implemented / scoped-pass | 完整Playwright20/20退出0；旧档导入分支测试通过 |
| MA-011 | EXE/ZIP 与源码一致、无 Key/玩家档 | 启动及协作回执验证 | implemented / scoped-pass | release/artifact-status.json：两产物current/verified；最终构建a4d1650f1872；ZIP白名单/空Key/解压运行通过 |

## 用户决策与不变量

- 2026-10-29 授权真实固定案例及长回合测试；所有模式、失败和重试合计上限 **5,000,000 Token**（用户回复“5000k token”）。不是消费目标，不自动追加。
- 2026-10-29 用户选择：保留主持人自由叙事，NPC 决定独立原文展示，增加审计并明确仍有语义风险。规则状态不得被主持人改写，但不承诺确定性语义一致。
- 先固定案例，再 24 回合，再 60 回合；预算不足停止；付费任务不得由刷新或自动恢复静默发起。
- 状态写入仍通过现有事务。读取者 ID 不可由模型参数覆盖；信息相关性不能替代权限。
- 模型发言是发言事实，不是内容真伪证明；pending/撤回/纠错内容不能作为确定事实。
- 同一回合最多六个不同 NPC；并发槽位不得改变参与人数；闲置不发请求。
- NPC 失败不得由主持人编造决定。取消后迟到结果不能写入正式状态。
- 旧存档与自由探索、恋爱和身体设定保留；新模式默认关闭，不削减原模式功能。

## 理解责任与风险

- A：权限、规则、统一提交和预算是硬边界；口吻自然度等需人工最终验收。
- B：使用现有 FastAPI、模型客户端、LangGraph Functional API、索引和事务；不另建脱离存档的 NPC 状态。
- C：UI 接线、文档、打包由自动化处理并验证。
- 风险：自由文本无法通过提示词保证不改变人物决定，发布应以验证后的结构化决定为依据；不把模型自评当成质量结论。
- 风险：已发出的取消/超时请求仍可能计费，账本需保留未知消耗的预留额。

## 进行中的工作与恢复

- 固定、24和60真实评测及最后复测均结束，不再发起真实请求；582次请求，供应商已报告3,176,604 Token，含5次未知消耗保守值共3,234,112 Token，未超过5,000,000。证据在summary.md/report.json/budget.sqlite3，真实API只读OS环境变量，不落盘密钥。
- 开发/测试/打包 Python：Conda APITEST，C:/Users/莱茵金属Rhm/.conda/envs/APITEST/python.exe。
- 基线249项；新增六人真实checkpoint并发和超长身份测试后，最终quality通过，Python测试总数298项；完整浏览器20项通过，套件总预算150秒（外层180秒）。SQLite异步阻塞和取消后遗留工作线程已修复。
- 已新增五职责模块：agent_contracts.py、agent_context_service.py、npc_agent_runtime.py、agent_scheduler.py、agent_rules_service.py。TurnOrchestrator 增加候选提交；新模式中暂停旧自动接受邀约/主动关系/人物主动事件，旧模式不变。
- 已接入正式路由、V14迁移、恢复清理、未使用预算释放、旧邀约与关系提案、转交接受、NPC日历、逐人消息和游戏设置。分支保留历史重绑定新 epoch，来源 epoch 留档。
- 交付：根目录touhou.exe与release/touhou-test-package.zip均已替换，完整流水线退出0，源码指纹一致。临时模拟目录与候选文件清理，保留真实评测证据；无新增.codex-*文件。桌面/移动端稳定帧已核对，补充浏览器测试退出0，所有本轮测试、构建和付费评测进程均结束。
- 限制：协作模式目前仅对已实现的规则活动/已知地点提供确定性结算，不承诺任意自由文本任务变更与旧模式等价；默认仍legacy。身份超出预算时明确拒绝，不静默删除人物资料。主观质量待人工，不保证主持人自由文本无语义矛盾。
- 24轮两次失败：一次relationship多余字段（已公开精确命令schema）；另一次原始speak JSON可重放校验，原因未确定，未声称修复，已补错误链记录。不得删除失败记录或将尝试数算作全部成功。
- 60轮出现一次评测SQLite锁及一次禁止顶层字段；前者评测库已对齐正式WAL配置，后者严格拒绝是预期失败边界。WAL后24复测23/24，一次空事件回合引用旧ID，补maxItems=0后最终24/24通过。末次补丁未重新跑整套60轮，不把之前58/60改写为新版本60/60；所有旧失败与计费保留。
- 最近完成矩阵如上；没有范围取消。所有 acceptance 仍 pending，自动化通过不替代用户验收。
