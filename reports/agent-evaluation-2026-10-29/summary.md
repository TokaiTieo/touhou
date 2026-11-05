# NPC 协作真实对照评测汇总

自动生成；原始逐回合记录及合成请求保留在同目录，不删除失败、不填写虚构人工分数。

- 合计上限：5,000,000 Token。
- 已计费用量（含未知消耗的保守值）：3,234,112 Token。
- 供应商已报告实际用量：3,176,604 Token。
- 请求数：582；用量未知请求：5。

| 阶段 | 模式 | 成功/尝试 | 请求 | 已报告 Token | 平均等待秒 | P95 秒 |
| --- | --- | --- | --- | --- | --- | --- |
| fixed | legacy | 6/9 | 9 | 75,668 | 6.67 | 8.725 |
| fixed | retrieval | 4/9 | 9 | 58,613 | 18.39 | 24.34 |
| fixed | collaborative | 5/9 | 24 | 54,067 | 19.54 | 40.732 |
| fixed-contract-diagnosis | retrieval | 1/3 | 3 | 20,042 | 19.57 | 22.735 |
| fixed-contract-diagnosis | collaborative | 3/3 | 8 | 21,998 | 21.9 | 28.041 |
| fixed-structured-v2 | legacy | 9/9 | 9 | 74,309 | 5.44 | 7.04 |
| fixed-structured-v2 | collaborative | 9/9 | 29 | 64,258 | 17.37 | 27.0 |
| fixed-structured-v2 | retrieval | 9/9 | 9 | 51,628 | 15.43 | 30.032 |
| 24 | legacy | 24/24 | 24 | 258,832 | 5.65 | 7.096 |
| 24 | retrieval | 24/24 | 24 | 168,240 | 11.1 | 15.454 |
| 24 | collaborative | 22/24 | 46 | 155,143 | 13.01 | 24.486 |
| fixed-contract-v3 | collaborative | 4/4 | 10 | 26,390 | 14.17 | 21.391 |
| 60 | legacy | 60/60 | 60 | 668,831 | 5.33 | 6.646 |
| 60 | retrieval | 60/60 | 60 | 418,296 | 12.55 | 20.825 |
| 60 | collaborative | 58/60 | 115 | 472,937 | 13.88 | 24.221 |
| fixed-release-wal | legacy | 9/9 | 9 | 74,742 | 6.44 | 7.68 |
| fixed-release-wal | collaborative | 9/9 | 29 | 83,565 | 17.72 | 37.586 |
| fixed-release-wal | retrieval | 9/9 | 9 | 49,708 | 13.46 | 20.117 |
| 24-release-wal | collaborative | 23/24 | 48 | 189,484 | 11.02 | 19.355 |
| 24-final-citations | collaborative | 24/24 | 48 | 189,853 | 12.46 | 20.36 |

## 口径与边界

- legacy 是当前兼容流程，不是历史 v0.17 EXE；三模式同合成初始状态、动作、输出上限和供应商格式策略。
- 阶段名称区分协议修正前后复测，每条记录包含源码指纹。不能把不同指纹的结果当成同一次未变更实验。
- 等待时间是本机并发测试的端到端时间，包含共享请求槽排队，不是服务商纯推理耗时。
- 24/60 表示连续尝试；失败不提交状态但仍计费，随后继续脚本，不应称为全部回合成功。
- 单条私密口令未进入未授权 NPC 输入、0/6 人调用约束等是有限夹具检查，不证明所有语义均正确。
- 未给定计费单价，不推算人民币成本；启发式质量检测不等于人物口吻、事实承接、自由度、节奏或关系的人工评分。
- 默认保留 legacy；协作模式的自由叙事与全领域规则效果仍须进一步验收。

## 失败记录

- `fixed:legacy:3:three`：RuntimeError: invalid_turn_contract
- `fixed:legacy:4:six`：RuntimeError: invalid_turn_contract
- `fixed:collaborative:3:three`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `fixed:legacy:9:ordinary_friendship`：RuntimeError: invalid_turn_contract
- `fixed:retrieval:4:six`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `fixed:retrieval:5:seven`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `fixed:collaborative:5:seven`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `fixed:retrieval:6:private_probe`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `fixed:collaborative:7:custom`：HTTPException: 主持人引用了不存在或无权公开的事件，本回合保留待恢复
- `fixed:retrieval:8:unadapted`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `fixed:retrieval:9:ordinary_friendship`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `fixed:collaborative:9:ordinary_friendship`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `fixed-contract-diagnosis:retrieval:1:three`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `fixed-contract-diagnosis:retrieval:2:private_probe`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `24:collaborative:3:ordinary_friendship`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `24:collaborative:11:ordinary_friendship`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `60:collaborative:22:three`：HTTPException: database is locked
- `60:collaborative:24:unadapted`：HTTPException: 协作回合尚未提交，请手动恢复。结构化决策未通过校验，本回合未提交；可手动恢复
- `24-release-wal:collaborative:7:alone`：HTTPException: 主持人引用了不存在或无权公开的事件，本回合保留待恢复

详细结构检查失败计数与源码指纹见 `summary.json`；逐次证据见 `report.json` 和 `call-*.json`。
