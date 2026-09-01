# LangGraph Functional API 迁移记录

## 最终边界

- FastAPI、Vue、DeepSeek/OpenAI 客户端、SSE 接口和现有 URL 保持不变。
- `TurnOrchestrator` 统一环境行动与 NPC 对话的状态结算。
- `TurnInput`、`TurnContext`、`TurnOutcome` 是工作流内部契约，不替代角色存档。
- LangGraph Functional API 只负责编排模型生成与结构化响应解析。
- 角色 JSON、任务 JSON、V8 自动迁移和快照系统仍是游戏状态的唯一事实源。
- SQLite checkpoint 位于 `DATA_DIR/runtime/turn_checkpoints.sqlite3`，只保存未完成运行；角色与任务成功提交后立即删除相应 thread。
- LangSmith 追踪默认关闭，不上传提示词、回复、角色状态或存档。

## 事务与幂等

每个回合先在内存中完成规则、成长、关系、记忆、事件、任务、异变和后果结算，最后只调用一次 `save_turn_bundle`。以下记录均识别 `turn_id`：

- 关系变化与关系历史
- NPC 显式记忆和自动记忆
- 开放事件与动态事件
- 符卡战斗记录及成长结算
- 任务更新
- 本地规则与成长结算
- 世界后果和最终回合收据

模型调用完成而解析阶段中断时，同一 thread 会从 SQLite 恢复，复用已经完成的模型任务，不会再次请求模型。若回合已经提交，原有回合收据直接返回相同结果。

## 第二阶段可靠性强化

### 并发与 revision

- `TurnCoordinator` 按角色串行执行不同回合，防止两个回合从同一旧快照结算后发生最后写入者覆盖。
- 相同 `(character_id, turn_id)` 的请求共享同一个在途任务，SSE 断线后的普通请求不会产生第二次模型调用。
- 角色和任务文件分别携带向后兼容的 `state_revision`；旧文件缺失时视为 0。
- `save_turn_bundle` 在写入前校验角色与任务 revision，冲突时拒绝覆盖并要求前端刷新。

### 完整事务

- AI 生成与规则结算期间只产生内存状态。
- 新发现的动态地点先写入 `TurnContext.pending_world_changes`，不再提前修改世界文件。
- 事务日志 V2 同时记录角色、任务和世界变更；恢复时按幂等方式补齐动态地点、角色与任务后再删除日志。

### checkpoint 身份与生命周期

- workflow thread 前缀升级为 `turn-v2`。
- SQLite 伴随表记录 `input_hash`、模型、工作流版本、Prompt 契约版本、状态和更新时间。
- 相同 `turn_id` 的 Prompt、模型或契约身份不一致时拒绝恢复。
- 默认保留未完成 checkpoint 72 小时，最多 200 个 thread；超期或超量数据自动回收。
- 清理采用尽力语义：角色存档已经提交后，checkpoint 删除失败不会改变成功响应。
- SQLite 损坏时隔离原文件并重建；LangGraph/SQLite 初始化失败时仅回退当前回合。

### 玩家恢复与取消

- `GET /api/ghost/turn_status/{character_id}/{turn_id}` 返回进行中、恢复中、结算中、已提交或失败状态。
- SSE 传输中断后，前端先查询原回合并等待收据；找不到运行时才以同一 `turn_id` 调用普通接口。
- 传输断开不会自动取消权威回合；玩家点击停止生成时通过独立取消接口终止。

### 隐私与开发诊断

- LangGraph 和 aiosqlite 均延迟导入，关闭功能开关后不依赖其成功初始化。
- 设置面板可以查看并清除本地恢复数据，操作不影响角色 JSON、任务 JSON或快照。
- 测试包白名单不包含 `runtime`、checkpoint、角色存档或现有 API Key。
- 普通玩家不显示工作流技术信息；制作人控制台可查看恢复标志、工作流耗时、checkpoint 指标、回合阶段、上下文预算和记忆召回原因。

## 上下文预算

世界设定、玩家状态、NPC 信息、近期历史、长期摘要、任务、NPC 记忆、世界回响和离屏人物动向拥有独立字符预算。硬规则、当前玩家信息和目标 NPC 设定优先保留，历史与记忆超限时保留最近部分。

记忆召回诊断记录每条入选记忆的原因、分数与字符成本，但只写入制作人可见的本地诊断，不上传到 LangSmith。

## 自动验证

- 138 项 Python/API 测试通过。
- 33 个 JavaScript 模块语法检查通过。
- 8 项 Playwright 端到端测试通过。
- 固定剧情评测 `6/6` 通过，覆盖状态恢复、调查成长、符卡裁定、制作人优势、异变完成和非法响应无副作用。
- V1-V7 测试存档仍可自动、增量、幂等升级到 V8。

## 对照结果

本地基准使用模拟模型，排除网络与模型生成时间，连续运行 30 个环境回合：

| 指标 | 结果 |
| --- | ---: |
| 新旧结果关键字段一致 | 是 |
| 旧路径平均本地耗时 | 0.023 ms |
| LangGraph 冷启动 | 19.83 ms |
| LangGraph 稳定后平均耗时 | 7.065 ms |
| 每回合平均本地增量 | 7.042 ms |

实际 DeepSeek 请求通常远高于这部分本地开销，因此对玩家体感影响有限。基准可通过 `python scripts/benchmark-turn-workflow.py` 重跑。

## 打包结果

| 构建 | 大小 |
| --- | ---: |
| v0.11.0 原 EXE | 224,068,108 bytes |
| v0.12.0 LangGraph EXE | 230,622,913 bytes |
| 增量 | 6,554,805 bytes / 6.251 MiB / 2.925% |

最终构建 SHA-256：`178C61184091DABA600EC192B4DEBA707F77BBE973427C8ED73D4FCE98D852AD`。

隔离冒烟测试已验证打包版能够创建角色、运行 Functional API 回合、创建 SQLite checkpoint、通过回合收据去重并正常关闭。

## 回退方式

设置 `TOUHOU_LANGGRAPH=0` 可临时切换到旧的直接模型调用与契约解析路径。两条路径共用同一个 `TurnOrchestrator`，因此回退不会改变存档格式或结算规则。

## Graph API 采用结论

当前离屏 NPC 模拟是确定性的六小时刻度计算，每次最多生成四条活动，不调用多个 AI，也不存在并行状态合流。现在改用 Graph API 只会增加状态模式、节点迁移和打包维护成本，因此暂不采用。

满足以下任一条件时再评估 Graph API：

1. 三个以上 AI NPC 需要并行推演后合并为同一世界状态。
2. NPC 计划之间出现多级条件分支、冲突仲裁和循环协商。
3. 需要在运行中暂停，让制作人审核或修改某个节点再恢复。
4. 团队需要可视化节点拓扑来定位复杂剧情工作流。
5. 单个 Functional entrypoint 再次增长为难以测试的大型共享状态流程。

未来若采用 Graph API，应把它限制在“多 NPC 世界模拟”子系统，并继续通过稳定结果契约写回 `TurnOrchestrator`，不能让 graph checkpoint 取代角色存档。
