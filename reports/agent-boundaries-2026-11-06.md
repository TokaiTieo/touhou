# NPC 协作边界修复记录

本文件保留三轮过程；以末尾“三次复查”作为最新结论。此前44／56项测试未覆盖后续反例，不能用其通过证明完整隔离或恢复成立。

## 范围

- 日期：2026-11-06；源码 v0.18.0，存档 V14。工作树基线提交 `bea67ebab03b49d99b2c16bf259e33ae09a5dbe3`，含用户正在进行的前端视觉修改，本轮不改动这些文件。
- 来源：用户报告的四个反例，不将原有30项专项通过视为这些反例已覆盖。
- 本轮实施、验证和用户验收分开记录：四项修复 implemented，规定用例 verified，用户验收 pending；没有付费模型调用。

## 修复与证据

| 问题 | 修复 | 验证位置 |
| --- | --- | --- |
| 句号分隔／共同问好后私语泄漏 | 引号外分段与收件人切换；NPC对话和UI显式选择不跳过分段；记录统一使用分段结果 | test_agent_boundaries.py：14种分隔／转向×2种问好×3种选择方式，实际请求及下一回合召回 |
| 方向移动误激活、否定台词漏激活 | 动作头与互动谓词校验，不在整段发言中搜索否定词 | 同文件的动作识别与真实调度调用数测试（模型为模拟） |
| 缺席者挤占六人名额 | 先在场过滤再截取，保留缺席与超额待处理 | 七人首位缺席时六人完整执行；九人中两人缺席；全员缺席；既有六人连锁上限 |
| 非法记录挤掉合法记忆 | 后端资格谓词在embedding、rank和top-k之前执行 | 活动／归档两类，每类45条高分非法候选；epoch、owner、pending、撤回、损坏权限；断言rank输入只有合法记录且原数据未变 |
| 升级后复用旧策略结果 | 代码上下文策略版本纳入任务和候选指纹 | test_agent_recovery.py：策略变化重跑，随后相同策略复用且不重结算 |
| 取消清理竞态 | 不向已在取消的兄弟任务再次发送cancel，等待账本清理完成 | 可控阻塞两个账本写入，断言父回合未提前结束；旧迟到响应不写状态用例保留 |

补充边界包括中英文引号、转述中的姓名、动作／语言封装、括号和标签出现在引语中、同名自定义人物、未知收件人、缺失引号及未分句的多收件人歧义。歧义在模型调用前报错，不扩大可见范围。

## 运行记录

全部 Python 使用 Conda APITEST，测试数据在临时目录，模型为模拟。未读取或写入真实API密钥。

1. 修复前新增11项测试，79个子案例断言失败，复现四类问题；这是子案例失败数，不是79个独立测试方法。连接词扩展时又检测到“然后”被重复拆分，已修正后重新运行。
2. 首次完整Agent回归出现取消测试的 `WinError 32 / cancel.db` 临时文件占用。排查为父gather取消后再次取消兄弟任务打断清理等待；修复并加入可控清理阻塞用例，没有忽略清理异常。
3. `python -m unittest discover -p 'test_agent_*.py' -q`：最终 **44/44通过**，10.118秒。含真实Functional checkpoint本地持久化测试，不含真实付费模型。
4. `npm run quality`：JS 42、CSS 8、Python编译、Ruff、内容有效性及5个叙事规则案例通过；Python/API共 **315项，313通过、2失败**，26.480秒，进程退出1。
5. `npm run test:e2e -- e2e/agents.spec.mjs`：**1/1通过**，22.2秒；验证可选模式、独立决定、桌面／手机及刷新持久化，测试服务已退出。

### 完整质量检查未通过的两项

- `test_vue_architecture.py:test_every_base_location_has_a_valid_widescreen_scene`：固定要求1672×941，而用户现有新版 `static/ui/hakurei-panorama-v2.png` 为2172×724。
- `test_vue_architecture.py:test_theme_overrides_have_one_canonical_owner`：仍检查旧“东方异变录 · 统一主题层”标记，用户现有新版CSS已经移除。

这两项是现有视觉改版与测试契约不一致，本轮未改其代码、图片或断言。整体质量检查仍记失败，不把313项成功说成全量通过。前端是否符合新设计应另外更新有意义的测试契约，不应仅为了绿灯恢复旧图或添加空标记。

## 兼容和剩余风险

- 本轮无新持久字段，保留V14及既有V1–V13增量升级；迁移、快照、导入导出和私人资料保留用例在本轮完整回归中通过。未修改正式玩家存档，默认模式仍legacy。
- 已保存的错误事实不能可靠地从任意自由文本自动推断并清除；当前记忆、摘要及回滚记录不做无依据批量删除。若有具体受污染存档，需要另行备份并按来源审计修复。
- 自由文本分段支持已定义的显式语法，不保证任意隐含指代或绕写都能得到确定性权限证明。主持人自由叙事与NPC决定的语义一致性仍为 `unverified`，规范决定单独展示。
- 本轮未运行真实24/60回合。10-30最后补丁的24/24不等于本版已真实复测，完整新版60仍未完成。此前失败及3,234,112 Token保守计费记录保留，不改变5,000,000总授权上限。
- 未重打包EXE/ZIP，当前修复只能按源码运行验证，旧产物不包含此次修复。没有创建临时 `.codex-*` 文件。

## 二次复查：未知动作、独立台词与旧预留

用户确认上轮缺席补位、召回前过滤有效，但补充三个未覆盖反例。本轮沿用MA-001/003/006/007，不改变原要求；实现和范围内验证完成，用户验收pending。

| 已报问题 | 本轮处理 | 可定位证据 |
| --- | --- | --- |
| “向甲问好。把蓝色密码悄悄告诉乙”泄漏 | 未识别后句不分发，不继承甲或UI所选受众，后续裸引语也不恢复旧受众 | test_unknown_actions_never_inherit_previous_or_selected_audience；test_unknown_action_is_absent_from_request_history_and_memory |
| “想了想＋不知道”“独自坐下＋你好”漏回应 | 保留UI动作与语言边界，独立台词重新绑定所选NPC；旧括号尾部只有明确引语作为语言 | test_independent_ui_speech_rebinds_selected_target_after_noninteraction；浏览器实际两次对话并核对提交历史 |
| “告诉甲不要担心”漏激活 | 直接说话谓词后的否定视为正文，不是未执行动作 | test_direct_speech_verb_does_not_negate_its_payload |
| 旧预留阻断新策略恢复 | 同一scope的过期planned预留和新预留原子替换；保留所有已发请求和未知收费 | test_policy_upgrade_releases_unsent_slots_but_preserves_failed_charge；BudgetTests三项替换／回滚／计费测试 |

未知句式不分发不等于乙成功接收。任意自然语言仍不构成确定性权限契约；普通UI语言、加引号的续接和明确目标的支持语法可正常使用。主持人自由叙事语义风险继续保留，未自动删除旧存档的污染记忆。

### 本轮验证过程

1. 修复前七项新增用例出现30个子案例失败和11个错误，分别覆盖泄漏、漏激活及真实Functional检查点的预算阻断。修复后专项先51项、扩展预算边界后54项通过。
2. 浏览器新断言曾分别因监听普通接口而非SSE、用可见数量计算虚拟历史、流式完成前读取存档而失败。测试改为等待实际SSE响应完整结束，按请求turn_id核对落盘的agent_inputs和canonical_decision，另检查最新本人回应可见；未延长30秒单测超时或修改产品前端。
3. 首次全量325项出现两项原有视觉断言失败及一项六人检查点错误。单独重复十次有一次在 `PRAGMA journal_mode=WAL` 报 `database is locked`，继而出现未注册连接的临时文件占用；不是仅凭偶发结果忽略清理错误。
4. 账本初始化提前启用WAL，`_open_runtime`增加取消时的连接关闭，并分别补测试。之后六人并发、重放和清理连续 **20/20通过**（35.171秒）。
5. 最终 `python -m unittest discover -p 'test_agent_*.py' -q`：**56/56通过**（11.212秒）。`npm run quality`：JS42、CSS8、编译、Ruff、内容及5个叙事规则案例通过；**327项Python/API中325通过、2失败**（23.821秒，退出1）。仍是上文两项视觉旧断言，未放宽或删除。
6. 最终源码执行 `npm run test:e2e -- e2e/agents.spec.mjs`：**1/1通过**（22.9秒），覆盖设置、独立回应、刷新以及新增加的两组对话与实际落盘检查。使用隔离数据和模拟AI；没有真实付费请求。测试服务已退出，早前失败遗留的两个临时数据库目录经绝对路径及文件白名单核验后清理。

本轮无新存档字段，V14兼容、自动升级、导入导出及私人资料保留的测试继续通过；上下文代码策略版本变更为3，使旧策略候选失效但不重置收费。真实24/60回合、自由叙事语义验收和EXE/ZIP重新发布未完成，不能由本次局部回归代替。

## 三次复查：转向停顿、继续意图与主持人引用

来源：用户确认原三个复现已通过、56项Agent＋5项工作流通过，但仍复现三处遗漏。沿用MA-001/003/006/007；此前“用例范围通过”不扩大为“全部修复”。本轮不更改正式玩家档、付费授权额度或默认模式。

| 本轮要求 | 修复与范围 | 新增证据 |
| --- | --- | --- |
| 选中甲，向乙私下说后想了想，密码不能给甲 | 分离默认／明确／阻断受众；独立语言只继承已确认对象；未知动作不恢复默认绑定，独自行动不强制指定NPC | test_explicit_redirect_survives_self_pause_without_ui_fallback；test_uncertain_redirect_blocks_ui_speech_instead_of_falling_back；test_solo_action_and_speech_do_not_require_an_npc_audience |
| 不能只挡住当前请求而污染后续记忆 | 实际NPC请求、agent_inputs、逐人历史展开与候选记忆沿用同一确定受众 | test_redirect_pause_secret_stays_out_of_original_npc_request_and_memory |
| `is_continue=true`必须激活当前NPC | NPC路由传入回合契约，运行时接收continue_dialogue意图；忽略占位文本里的新目标，不凭占位文字自动激活；无有效ID拒绝 | test_continue_intent_is_bound_to_selected_npc_not_placeholder_text；test_continue_calls_selected_npc_without_inventing_player_speech |
| 无效引用不得作为成功缓存 | 允许ID由后端绑定，在_generate成功之前校验；失败计费保留；重启恢复一次NPC、两次主持人、一次候选结算，成功后重放无新请求 | test_invalid_host_citation_retries_host_only_after_restart；test_empty_public_events_reject_stale_citations_before_checkpoint |
| 老的无效成功缓存不能一直被复用 | 主持人策略单独版本化，绕过旧策略缓存和计费槽；相同上下文的有效NPC和候选仍可复用 | test_old_successful_invalid_host_cache_is_bypassed_by_host_policy：模拟旧无校验策略落盘后重开SQLite恢复，旧费用逐条保持 |

### 运行与修订过程

1. 首轮64项Agent测试63通过、1失败：新增“独自休息”用例误断言8:15，既有game_rules.py的休息最少耗时0.5小时，实际8:30。只修正测试预期，未改变玩法；随后64项Agent＋5项工作流69/69通过。补充无目标自言自语后最终为65＋5项。
2. 首次新增浏览器继续操作在30秒内未找到按钮，页面实况确认“本回合变化”成为最后消息，原来的last条件使按钮消失。将入口移到当前对话操作区，生成期间／死亡／结束后不显示，不改现有用户CSS或其他视觉设计。修复后浏览器1/1通过（34.0秒为含启动清理的总时长，单测13.5秒），没有延长单测30秒预算。
3. 最终专项命令：`python -m unittest test_agent_boundaries test_agent_recovery test_agent_context test_agent_runtime test_agent_scheduler test_agent_persistence test_turn_workflow -q`，**70/70通过，15.714秒**。
4. 最终 `npm run quality`：JS42、CSS8、编译、Ruff、内容检查和5项叙事规则通过；Python/API **336项中334通过、2失败，31.221秒**。仍是上文两项视觉旧断言，未删除或放宽，完整quality退出1。
5. 最终 `npm run test:e2e -- e2e/agents.spec.mjs`：**1/1通过，31.0秒总时长、单测13.4秒**。真实点击继续按钮，核对is_continue、npc_id、SSE结束、正式历史新增本人回应及空agent_inputs；390/1440px按钮在视口内、无横向溢出，退出对话后隐藏。已查看截图 `test-results/visual/agents-continue-390.png` 和 `agents-continue-1440.png`。测试服务退出并清理隔离目录。

### 兼容与尚未验收

- 存档仍V14，旧TurnInput缺少is_continue默认false；全量回归中的迁移、导入导出、快照、分支及私人资料保留用例通过。正式玩家档、旧记忆、摘要和回滚记录不做自动清洗。
- 本次受众变化升级上下文策略3→4，会整体使旧策略NPC／候选失效；主持人策略版本2用于单独的结果校验更新。不能把“相同上下文内仅重试主持人”误写成“跨权限／上下文升级仍保证NPC零新调用”。旧未发送预留替换、取消保护和失败／未知计费保留用例继续通过。
- 未发真实API请求，未运行当前补丁真实24/60回合，未重打包EXE/ZIP；原产物不包含本轮修复。自由文本受众判断仍是有限语法，主持人引用集合校验只证明ID合法，不证明叙事语义正确。implementation完成本轮范围，verification仅限以上本地模拟与浏览器证据，acceptance仍pending。
