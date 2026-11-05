"""Explicitly authorized, resumable three-mode evaluation with one durable cap."""

import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.pending')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


async def run(args):
    output = ROOT / 'reports' / 'agent-evaluation-2026-10-29'
    output.mkdir(parents=True, exist_ok=True)
    runtime = output / 'runtime'
    os.environ['TOUHOU_DATA_DIR'] = str(runtime)
    if args.mock:
        os.environ['TOUHOU_E2E_MOCK_AI'] = '1'
        output = output / 'mock'
        output.mkdir(exist_ok=True)
    elif os.environ.get('TOUHOU_E2E_MOCK_AI') == '1':
        raise RuntimeError('Real evaluation refuses mock environment')
    if not args.mock and not os.environ.get('DEEPSEEK_API_KEY'):
        raise RuntimeError('OS DEEPSEEK_API_KEY is required; credentials will not be copied')
    # Only content, never sessions, private settings or real player saves.
    shutil.copytree(ROOT / 'worlds', runtime / 'worlds', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('sessions', '*.bak', '*.tmp'))
    from backend.services.agent_context_service import digest, catalogue
    from backend.services.agent_contracts import default_agent_state
    from backend.services.ai_service import call_ai_async, get_last_ai_usage, get_last_ai_error, get_last_ai_runtime, reset_ai_diagnostics
    from backend.services.npc_agent_runtime import BudgetLedger, AgentBudgetError
    from backend.services.evaluation_context import EvaluationContext, evaluation_context
    from backend.services.turn_models import TurnInput, TurnContext
    from backend.services.turn_history_service import append_turn_history
    from backend.services.turn_workflow import CHECKPOINT_PATH
    from backend.services.play_quality_service import evaluate_play_quality, RUBRIC
    from backend.world_manager import ensure_character_fields, get_default_tasks
    from backend.routes import ghost

    sources = list((ROOT / 'backend').rglob('*.py')) + list((ROOT / 'js').rglob('*.js'))
    sources += [p for p in (ROOT / 'worlds').rglob('*') if p.is_file() and 'sessions' not in p.parts]
    source_hash = digest({str(p.relative_to(ROOT)): digest(p.read_bytes().hex()) for p in sorted(sources)})
    ledger = BudgetLedger(output / 'budget.sqlite3', 'authorized-5000k-all-modes', 5_000_000, 3000)
    # Production Functional API uses WAL. Dry-run evaluations must use it too.
    runtime_ledger = BudgetLedger(CHECKPOINT_PATH, 'evaluation-initialization', 1, 1)
    for database in (ledger, runtime_ledger):
        with database.connect() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
    harness_hash = digest(Path(__file__).read_bytes().hex())
    report_path = output / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {
        'protocol': 1, 'mock': args.mock, 'cap': 5_000_000, 'results': [],
        'manual_review_required': True, 'rubric': RUBRIC,
        'legacy_baseline': 'current compatibility workflow, not a historical v0.17 executable',
        'fixture': 'synthetic adult player; same actions, identities, content and initial facts in every mode; controlled scene staging',
        'limitations': ['Automated checks do not establish semantic truth or human-rated quality.',
                       'No monetary cost estimated without provider prices.']}
    base = ensure_character_fields({'character_id': 'evaluation-synthetic', 'timeline_epoch': 'eval-one',
        'profile': {'name': '评测旅人', 'age': 25, 'identity': '幻想乡原住民'},
        'status': {'current_scene': '博丽神社', 'is_dead': False},
        'time': {'current_day': 1, 'current_hour': 8, 'chapter_time_remaining': 720}})
    base['gm_mode'] = False
    base['custom_npcs'] = [{'id': 'npc_eval_custom', 'name': '雾川灯', 'location_name': '博丽神社',
                           'profile': {'identity': '成年人类药师', 'personality': '谨慎而友善', 'age': 28}}]
    base['agent_state'] = default_agent_state()
    records = catalogue(base)
    identities = ['npc_reimu', 'npc_marisa', 'npc_alice', 'npc_patchouli_n', 'npc_sakuya', 'npc_youmu', 'npc_eval_custom']
    # Resolve canonical IDs by stable names, not model or client-supplied identity.
    from backend.services.npc_identity_service import resolve_npc
    identities[:6] = [resolve_npc(name)['id'] for name in ['博丽灵梦', '雾雨魔理沙', '爱丽丝', '帕秋莉', '十六夜咲夜', '魂魄妖梦']]
    random_id = sorted(set(records) - set(identities))[17]
    for identity in [*identities, random_id]:
        name = records[identity]['name']
        base.setdefault('npc_runtime', {})[name] = {'temporary_location': '博丽神社', 'until_hour': 1000000, 'reason': '评测场景集合'}
    secret = '青瓷匣口令是松月七三'
    base.setdefault('npc_memories', {})['帕秋莉'] = [{'id': 'fixture-secret', 'summary': secret,
        'owner_npc_id': identities[3], 'importance': 10, 'knowledge_type': 'direct', 'truth_status': 'accepted',
        'attribution_status': 'confirmed', 'visibility': {'scope': 'recipients', 'audience': [identities[3]]}}]
    base.setdefault('npc_memories', {})['博丽灵梦'] = [{'id': 'fixture-promise', 'summary': '玩家与灵梦约好一起整理神社旧符札',
        'owner_npc_id': identities[0], 'importance': 10, 'knowledge_type': 'direct', 'truth_status': 'accepted',
        'attribution_status': 'confirmed', 'visibility': {'scope': 'recipients', 'audience': [identities[0], '@player']}}]
    cases = [
        ('alone', [], '独自坐在神社庭院休息十五分钟'),
        ('one', identities[:1], '询问之前一起整理旧符札的约定'),
        ('three', identities[:3], '逐个问好，各自说说今天的计划'),
        ('six', identities[:6], '逐个问好，请每个人简短介绍自己的近况'),
        ('seven', identities, '逐个问好，请每个人简短介绍自己的近况'),
        ('private_probe', identities[1:2], '请介绍最近的见闻，不猜测未被告知的事'),
        ('custom', identities[-1:], '询问药师工作的日常'),
        ('unadapted', [random_id], '询问你的日常与兴趣'),
        ('ordinary_friendship', identities[2:3], '说明希望保持普通朋友关系，不推进亲密关系'),
    ]
    if args.stage != 'fixed':
        cases = [cases[i] for i in (1, 5, 8, 0, 6, 2, 0, 7)]
    if args.cases:
        cases = [case for case in cases if case[0] in args.cases.split(',')]
        if not cases:
            raise ValueError('No matching cases')
    count = len(cases) if args.stage == 'fixed' else int(args.stage)
    stop = asyncio.Event()
    provider_slots = asyncio.Semaphore(3)

    def persist_report():
        report['budget'] = ledger.summary()
        report['updated_at'] = time.time()
        write_json(report_path, report)

    async def mode_run(mode):
        prefix = args.stage if args.run_id == 'initial' else args.stage + '-' + args.run_id
        checkpoint = output / f'{prefix}-{mode}-state.json'
        previous = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else None
        if previous and previous['source_hash'] != source_hash:
            raise RuntimeError('Source changed: preserve old run and explicitly start a new report, never mix revisions')
        owner = previous['character'] if previous else copy.deepcopy(base)
        tasks = previous['tasks'] if previous else get_default_tasks()
        owner['agent_state']['mode'] = mode
        pending_calls = []
        case_key = ''

        async def generate(prompt, temperature=0.8):
            bound = len(prompt.encode('utf-8')) + 256 + 1800
            job = uuid.uuid4().hex
            # Fixed cases reserve 2M for subsequent stages; 24 turns reserve 1M for 60.
            stage_limit = 3_000_000 if args.stage == 'fixed' else 4_000_000 if args.stage == '24' else 5_000_000
            if ledger.summary()['reserved_and_charged'] + bound > stage_limit:
                stop.set()
                raise AgentBudgetError('Stage reserve reached; no request sent')
            ledger.reserve({job: bound})
            call_id = ledger.start(job, bound)
            usage, ok, response = {}, False, None
            start = time.monotonic()
            reset_ai_diagnostics()
            try:
                async with provider_slots:
                    response = await call_ai_async(prompt, temperature=temperature, max_output_tokens=1800, single_attempt=True, structured=True)
                usage = get_last_ai_usage()
                error = get_last_ai_error()
                ok = not error
                if error:
                    if error.get('code') in ('authentication', 'quota', 'missing_key'):
                        stop.set()
                    raise RuntimeError('provider_' + str(error.get('code')))
                return response
            finally:
                ledger.finish(call_id, usage, success=ok)
                entry = {'id': call_id, 'case': case_key, 'mode': mode, 'usage': usage, 'success': ok,
                         'seconds': round(time.monotonic() - start, 3), 'prompt_hash': digest(prompt),
                         'npc_id': json.loads(prompt.splitlines()[-1])['binding']['npc_id'] if '独立的人物' in prompt else None,
                         'secret_in_input': secret in prompt, 'runtime': get_last_ai_runtime()}
                pending_calls.append(entry)
                # Only synthetic fixture prompts are retained, never keys or player saves.
                write_json(output / f'call-{call_id}.json', {**entry, 'prompt': prompt, 'response': response})
                persist_report()

        ctx = EvaluationContext(owner, tasks, generate)
        token = evaluation_context.set(ctx)
        try:
            for index in range(previous['next'] if previous else 0, count):
                if stop.is_set():
                    break
                case_id, selected, action = cases[index % len(cases)]
                case_key = f'{prefix}:{mode}:{index + 1}:{case_id}'
                if args.stage == 'fixed':
                    ctx.character, ctx.tasks = copy.deepcopy(base), get_default_tasks()
                    ctx.character['agent_state']['mode'] = mode
                ctx.character['status']['current_scene'] = '博丽神社'
                if selected:
                    action = '向' + '、'.join(records[key]['name'] for key in selected) + action
                pending_calls.clear()
                turn_id = uuid.uuid4().hex
                common = dict(character_id=ctx.character['character_id'], scene='博丽神社', player_name='评测旅人',
                              scene_npcs=[records[key] for key in selected], turn_id=turn_id)
                result, error, error_chain = {}, None, []
                before = digest(ctx.character)
                started = time.monotonic()
                try:
                    request = ghost.EnvironmentInteractRequest(**common, user_input={'action': action}, interaction_npc_ids=selected)
                    async with asyncio.timeout(300):
                        result = await ghost.environment_interact.__wrapped__(request)
                    if not result.get('contract_valid'):
                        raise RuntimeError('invalid_turn_contract')
                    append_turn_history(TurnContext(turn=TurnInput(**common, kind='environment', action_text=action, record_history=True),
                                        character=ctx.character, tasks=ctx.tasks), result)
                except Exception as exc:
                    error = type(exc).__name__ + ': ' + str(getattr(exc, 'detail', str(exc)))[:500]
                    cause = exc
                    while cause is not None and len(error_chain) < 8:
                        error_chain.append({'type': type(cause).__name__, 'detail': str(cause)[:2000],
                                            'frames': traceback.format_tb(cause.__traceback__)})
                        cause = cause.__cause__ or cause.__context__
                text = result.get('description', '')
                row = {'id': case_key, 'source_hash': source_hash, 'harness_hash': harness_hash, 'sqlite_policy': 'wal_like_production',
                       'provider_policy': 'structured_non_thinking_if_official_deepseek', 'output_limit_per_call': 1800,
                       'mode': mode, 'stage': args.stage, 'index': index + 1,
                       'action': action, 'expected_participants': selected[:6], 'result': result, 'error': error, 'error_chain': error_chain,
                       'calls': copy.deepcopy(pending_calls), 'seconds': round(time.monotonic() - started, 3),
                       'state_before_hash': before, 'state_after_hash': digest(ctx.character),
                       'state_after': copy.deepcopy(ctx.character.get('player_state', {})),
                       'heuristic': evaluate_play_quality(text, case_id) if text else None,
                       'manual_review': {'scores': {key: None for key in RUBRIC}, 'note': ''},
                       'checks': {'no_secret_to_unauthorized_npc': not any(c['secret_in_input'] and c['npc_id'] and c['npc_id'] != identities[3] for c in pending_calls),
                                  'zero_npc_when_alone': bool(selected) or not any(c['npc_id'] for c in pending_calls),
                                  'required_npcs_responded': mode != 'collaborative' or set((result.get('agent_turn') or {}).get('participants', [])) == set(selected[:6]),
                                  'max_six': len((result.get('agent_turn') or {}).get('participants', [])) <= 6}}
                report['results'].append(row)
                write_json(checkpoint, {'source_hash': source_hash, 'next': index + 1, 'character': ctx.character, 'tasks': ctx.tasks})
                persist_report()
                print(json.dumps({'case': case_key, 'error': error, 'seconds': row['seconds'], 'charged': report['budget']['charged_tokens']}, ensure_ascii=False), flush=True)
        finally:
            evaluation_context.reset(token)

    await asyncio.gather(*(mode_run(mode) for mode in args.modes))
    persist_report()
    print('REPORT ' + str(report_path), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['fixed', '24', '60'], required=True)
    parser.add_argument('--mock', action='store_true')
    parser.add_argument('--run-id', default='initial')
    parser.add_argument('--cases', default='')
    parser.add_argument('--modes', nargs='+', choices=['legacy', 'retrieval', 'collaborative'], default=['legacy', 'retrieval', 'collaborative'])
    asyncio.run(run(parser.parse_args()))
