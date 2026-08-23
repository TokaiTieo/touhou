import { loadCharacterJournal, loadNPCMemories, loadRelationships } from '../api.js';
import { state } from '../ghost/core/state.js';
import { openAppModal } from './app-store.js';

function memoryLabel(item) {
    if (!item) return '';
    if (typeof item === 'string') return item;
    const meta = [];
    if (item.importance !== undefined) meta.push(`重要度 ${item.importance}`);
    if (item.emotion) meta.push(item.emotion);
    if (item.used_count) meta.push(`召回 ${item.used_count} 次`);
    return `${item.summary || ''}${meta.length ? `（${meta.join(' · ')}）` : ''}`;
}

export async function openNPCDetail(npcId) {
    const npc = (state.currentSceneNPCs || []).find(item => item.id === npcId);
    if (!npc) return;
    const profile = npc.profile || {};
    let memories = [];
    let summary = '';
    try {
        const result = await loadNPCMemories(state.currentSession.characterId, npc.name);
        memories = (result.memories || []).map(memoryLabel);
        summary = result.summary || '';
    } catch (error) {
        console.warn('读取人物记忆失败:', error);
    }
    openAppModal('detail', {
        kicker: '人物档案',
        title: 'NPC 详情',
        name: npc.name,
        subtitle: `${profile.identity || '幻想乡住民'} · ${profile.encounter_tier || '自由探索'}`,
        rows: [
            { label: '当前态度', value: state.currentSession.relationshipsMap?.[npc.name] || profile.initial_attitude || '尚未明确' },
            { label: '外貌', value: profile.description },
            { label: '性格', value: profile.personality },
            { label: '身材数据', value: profile.measurements },
            { label: '剧情钩子', value: profile.story_hook },
            { label: '符卡倾向', value: profile.spellcard_style },
            { label: '恋爱倾向', value: profile.romance_adult_hook },
            { label: '背景', value: profile.background },
            { label: '长期印象', value: summary },
            { label: '近期记忆', value: memories }
        ]
    });
}

export async function openPlayerJournal() {
    const journal = await loadCharacterJournal(state.currentSession.characterId);
    const profile = journal.profile || {};
    const progress = Object.fromEntries(Object.entries(journal.relationship_progress || {}).map(
        ([name, value]) => [name, `${value.stage || '相识'} · ${value.score ?? 0}`]
    ));
    const availableSpellcards = [...new Set([
        ...Object.keys(journal.spellcard_mastery || {}),
        ...(journal.spellcard_loadout || [])
    ])];
    openAppModal('detail', {
        kicker: '角色记录',
        title: '玩家档案',
        name: profile.name || '玩家',
        subtitle: `${profile.identity || '旅行者'}${journal.gm_mode ? ' · 高权限模式' : ''}`,
        spellcardEditor: true,
        availableSpellcards,
        spellcardLoadout: journal.spellcard_loadout || [],
        rows: [
            { label: '外貌', value: profile.appearance },
            { label: '性格', value: profile.personality },
            { label: '背景', value: profile.background },
            { label: '玩家状态', value: journal.player_state },
            { label: '资源', value: journal.resources },
            { label: '行囊', value: (journal.inventory?.items || []).map(item => `${item.name} × ${item.quantity || 1}${item.description ? ` · ${item.description}` : ''}`) },
            { label: '势力声望', value: journal.reputation },
            { label: '关系阶段', value: journal.relationships },
            { label: '关系进展', value: progress },
            { label: '关系边界', value: Object.fromEntries(Object.entries(journal.relationship_boundaries || {}).map(([name, value]) => [name, value.romance === 'closed' ? '保持普通交往' : value.romance === 'open' ? '愿意自然发展' : '尚未明确'])) },
            { label: '长期剧情摘要', value: [journal.story_summary?.recent_arc, ...(journal.story_summary?.key_events || []).slice(-6)].filter(Boolean) },
            { label: '叙事焦点', value: [journal.story_director?.current_arc?.title, journal.story_director?.current_arc?.focus, ...(journal.story_director?.suggested_focus || [])].filter(Boolean) },
            { label: '自由探索事件', value: (journal.open_events || []).slice(-8).map(item => `${item.scene || '未知地点'} · ${item.title}：${item.description}`) },
            { label: '符卡与战斗', value: (journal.spellcard_history || []).slice(-8).map(item => `${item.spellcard_name || '无名符卡'} · ${item.opponent || '未知对手'} · ${item.outcome || '未裁定'}${item.metrics?.accuracy !== undefined ? ` · 命中${item.metrics.accuracy}% · 擦弹${item.metrics.graze_count || 0}` : ''}`) },
            { label: '常用符卡栏', value: (journal.spellcard_loadout || []).length ? journal.spellcard_loadout : '尚未配置；不影响临场使用其他符卡' },
            { label: '成长里程碑', value: Object.values(journal.progression_milestones || {}).slice(-10).map(item => `${item.title} · ${item.detail}`) },
            { label: '符卡熟练', value: Object.entries(journal.spellcard_mastery || {}).map(([name, item]) => `${name} · ${item.tier || '初学'} Lv.${item.level || 1} · 使用${item.uses || 0}次 · 最佳连胜${item.best_streak || 0}${(item.traits || []).length ? ` · ${(item.traits || []).join('、')}` : ''}`) },
            { label: '世界回响', value: (journal.consequence_log || []).slice(-8).map(item => `${item.scene || '幻想乡'} · ${(item.summary || []).join('；') || item.cause}`) },
            { label: '后续动向', value: (journal.deferred_consequences || []).filter(item => item.status === 'pending').slice(-6).map(item => item.effect) },
            { label: '人物近况', value: (journal.npc_simulation?.events || []).slice(-8).map(item => `${item.npc_name} · ${item.location}：${item.activity}`) }
        ]
    });
}

export function openLocationDetail(locationName, locationTree) {
    const location = (locationTree || [])
        .flatMap(region => region.locations || [])
        .find(item => item.name === locationName);
    if (!location) return;
    const npcs = (state.currentSceneNPCs || []).filter(
        npc => npc.location_id === location.id || state.currentSession.currentScene === location.name
    );
    openAppModal('detail', {
        kicker: '幻想乡绘卷',
        title: '地点详情',
        name: `${location.icon || '地'} ${location.name}`,
        subtitle: `危险度：${location.dangerLevel || location.danger_level || '未知'}`,
        rows: [
            { label: '描述', value: location.description },
            { label: '风险提示', value: location.dangerNote || location.danger_note },
            { label: '主要收益', value: location.mainRewards || location.main_rewards },
            { label: '可能遭遇', value: npcs.length ? npcs.map(npc => npc.name) : '进入后由当前场景动态刷新' }
        ],
        note: '这些记录不构成通行条件，你可以随时前往任何地点。'
    });
}

export async function openRelationshipsPanel() {
    let relationships = state.currentSession.relationshipsMap || {};
    let history = [];
    try {
        const result = await loadRelationships(state.currentSession.characterId);
        relationships = result.relationships || {};
        history = result.history || [];
        state.updateRelationships(relationships);
    } catch (error) {
        console.warn('加载缘分录失败:', error);
    }
    const latest = history[0];
    openAppModal('relationships', {
        relationships,
        latest: latest ? `第 ${latest.hour ?? '?'} 时辰 · ${latest.content || ''}` : ''
    });
}

export function openNPCCreationDialog(payload = null) {
    openAppModal('npc-create', payload);
}

export function openSystemHelperDialog() {
    openAppModal('helper');
}
