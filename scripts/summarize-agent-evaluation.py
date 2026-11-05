"""Generate reproducible aggregate evidence without inventing human scores."""

from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean


def summarize(report):
    groups = defaultdict(list)
    for row in report['results']:
        groups[(row['id'].split(':')[0], row['mode'])].append(row)
    rows = []
    for (stage, mode), items in groups.items():
        seconds = sorted(item['seconds'] for item in items)
        calls = [call for item in items for call in item['calls']]
        rows.append({'stage': stage, 'mode': mode, 'attempts': len(items),
                     'successful': sum(not item['error'] for item in items),
                     'requests': len(calls), 'known_tokens': sum(call['usage'].get('total_tokens', 0) for call in calls),
                     'mean_seconds': round(mean(seconds), 2), 'p95_seconds': seconds[math.ceil(len(seconds) * .95) - 1],
                     'failed_checks': {key: sum(not item['checks'][key] for item in items)
                                       for key in items[0]['checks']},
                     'source_hashes': sorted({item['source_hash'] for item in items})})
    budget = {key: value for key, value in report['budget'].items() if key != 'calls'}
    return {'generated_at': datetime.now(timezone.utc).isoformat(), 'budget': budget, 'groups': rows,
            'failures': [{'id': row['id'], 'error': row['error'], 'causes': row.get('error_chain', [])}
                         for row in report['results'] if row['error']],
            'manual_scores_complete': all(all(value is not None for value in row['manual_review']['scores'].values())
                                          for row in report['results'])}


def main():
    directory = Path(__file__).resolve().parents[1] / 'reports' / 'agent-evaluation-2026-10-29'
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    result = summarize(report)
    (directory / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    budget = result['budget']
    lines = ['# NPC 协作真实对照评测汇总', '',
             '自动生成；原始逐回合记录及合成请求保留在同目录，不删除失败、不填写虚构人工分数。', '',
             f"- 合计上限：{budget['token_limit']:,} Token。",
             f"- 已计费用量（含未知消耗的保守值）：{budget['charged_tokens']:,} Token。",
             f"- 供应商已报告实际用量：{budget['actual_tokens']:,} Token。",
             f"- 请求数：{budget['requests']}；用量未知请求：{budget['unknown_requests']}。", '',
             '| 阶段 | 模式 | 成功/尝试 | 请求 | 已报告 Token | 平均等待秒 | P95 秒 |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for row in result['groups']:
        lines.append(f"| {row['stage']} | {row['mode']} | {row['successful']}/{row['attempts']} | {row['requests']} | {row['known_tokens']:,} | {row['mean_seconds']} | {row['p95_seconds']} |")
    lines += ['', '## 口径与边界', '',
              '- legacy 是当前兼容流程，不是历史 v0.17 EXE；三模式同合成初始状态、动作、输出上限和供应商格式策略。',
              '- 阶段名称区分协议修正前后复测，每条记录包含源码指纹。不能把不同指纹的结果当成同一次未变更实验。',
              '- 等待时间是本机并发测试的端到端时间，包含共享请求槽排队，不是服务商纯推理耗时。',
              '- 24/60 表示连续尝试；失败不提交状态但仍计费，随后继续脚本，不应称为全部回合成功。',
              '- 单条私密口令未进入未授权 NPC 输入、0/6 人调用约束等是有限夹具检查，不证明所有语义均正确。',
              '- 未给定计费单价，不推算人民币成本；启发式质量检测不等于人物口吻、事实承接、自由度、节奏或关系的人工评分。',
              '- 默认保留 legacy；协作模式的自由叙事与全领域规则效果仍须进一步验收。', '', '## 失败记录', '']
    for row in result['failures']:
        lines.append(f"- `{row['id']}`：{row['error'].replace(chr(10), ' ')}")
    lines += ['', '详细结构检查失败计数与源码指纹见 `summary.json`；逐次证据见 `report.json` 和 `call-*.json`。']
    (directory / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'failures'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
