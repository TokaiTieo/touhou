// js/ghost/core/session.js
import { state } from './state.js';
import { events, Events } from './events.js';
import { loadCharacter as apiLoadCharacter, loadTasks as apiLoadTasks, loadRelationships as apiLoadRelationships, endGhostSession as apiEndSession } from '../../api.js';
import { CURRENT_CHAPTER_INDEX } from './constants.js';

// 加载角色进入幽灵模式
export async function loadAndEnterGhostMode(characterId, sceneId) {
    console.log('loadAndEnterGhostMode called with:', characterId, sceneId);
    
    showLoading('加载角色中...');
    
    try {
        const result = await apiLoadCharacter(characterId, CURRENT_CHAPTER_INDEX, sceneId);
        //console.log('API response:', result);
        
        // 加载任务数据
        const tasksResult = await apiLoadTasks(characterId);
        state.updateTasks(tasksResult);
        const relationshipsResult = await apiLoadRelationships(characterId);
        state.updateRelationships(relationshipsResult.relationships || {});
        
        // 检查响应是否有效
        if (!result || !result.character_id) {
            throw new Error('API 返回数据无效');
        }
        
        // 确定当前场景
        let currentScene = result.current_scene || sceneId || "博丽神社";
        
        state.updateSession({
            characterId: result.character_id,
            profile: result.profile,
            currentScene: currentScene,
            conversationHistory: result.conversation_history || [],
            isDead: result.is_dead || false,
            gmMode: result.gm_mode || false,
            relationshipsMap: relationshipsResult.relationships || {},
            playerState: result.player_state || {},
            incidentState: result.incident_state || {},
            campaignState: result.campaign_state || {},
            onboarding: result.onboarding || {},
            resources: result.resources || {},
            reputation: result.reputation || {},
            currentGoals: result.current_goals || [],
            time: result.time || {
                current_day: 1,
                current_hour: 8,
                energy_state: "精力充沛",
                chapter_time_remaining: 72,
                chapter_node_name: "下个节点",
                last_rest_day: 1,
                last_rest_hour: 20
            }
        });
        window.dispatchEvent(new CustomEvent('touhou:developer-mode', {
            detail: { enabled: state.currentSession.gmMode === true }
        }));
        
        // 转换历史记录格式
        state.clearChatHistory();
        for (let i = 0; i < state.currentSession.conversationHistory.length; i++) {
            const msg = state.currentSession.conversationHistory[i];
            let role = 'assistant';
            let isDialogue = false;
            
            if (msg.speaker === state.currentSession.profile?.name) {
                role = 'user';
            } else if (msg.speaker === '旁白') {
                role = 'assistant';
            } else if (msg.speaker === '系统') {
                role = 'system';
            } else {
                role = 'assistant';
                isDialogue = true;
            }
            
            state.addChatMessage({
                role, speaker: msg.speaker, content: msg.content,
                timestamp: Date.now(), isDead: msg.is_dead || false, isDialogue,
                conversationIndex: i,
                messageId: msg.message_id || null,
                rating: msg.rating || null,
                rewriteCandidates: Array.isArray(msg.rewrite_candidates) ? msg.rewrite_candidates : [],
                activeRewrite: -1
            });
        }
        
        events.emit(Events.TIME_UPDATED);
        hideLoading();
        
        // 显示聊天界面
        console.log('Loading chat interface...');
        const { showGameInterface } = await import('../../vue/game-controller.js');
        await showGameInterface();
        
    } catch (err) {
        console.error('加载角色失败:', err);
        hideLoading();
        const message = err instanceof Error ? err.message : String(err || '未知错误');
        events.emit(Events.TOAST, { message: '加载角色失败：' + message, type: 'error' });
    }
}

// 退出幽灵模式
export async function exitGhostMode() {
    // 结束对话
    if (state.isInDialogue && state.currentDialogueNPC) {
        const { endDialogue } = await import('../modules/dialogue.js');
        await endDialogue();
    }
    
    if (state.currentSession.characterId) {
        await apiEndSession(state.currentSession.characterId);
    }
    
    state.reset();
    window.dispatchEvent(new CustomEvent('touhou:developer-mode', {
        detail: { enabled: false }
    }));
    
    // 清除sessionStorage
    sessionStorage.removeItem('ghost_mode_active');
    sessionStorage.removeItem('ghost_character_id');
    sessionStorage.removeItem('ghost_current_scene');
    sessionStorage.removeItem('ghost_profile');
    
    // 返回世界选择
    const { showWorldSelection } = await import('../modules/world.js');
    await showWorldSelection();
}

// 刷新角色时间
export async function refreshCharacterTime() {
    try {
        const result = await apiLoadCharacter(state.currentSession.characterId, CURRENT_CHAPTER_INDEX);
        if (result?.time) {
            state.currentSession.time = result.time;
            state.currentSession.playerState = result.player_state || state.currentSession.playerState || {};
            state.currentSession.incidentState = result.incident_state || state.currentSession.incidentState || {};
            events.emit(Events.TIME_UPDATED);
        }
    } catch (err) {
        console.error('刷新角色时间失败:', err);
    }
}

// 保存幽灵模式状态到sessionStorage
export function saveGhostSessionToStorage() {
    try {
        sessionStorage.setItem('ghost_mode_active', 'true');
        sessionStorage.setItem('ghost_character_id', state.currentSession.characterId);
        sessionStorage.setItem('ghost_current_scene', state.currentSession.currentScene);
        sessionStorage.setItem('ghost_profile', JSON.stringify(state.currentSession.profile));
    } catch (e) {
        console.warn('保存幽灵模式状态失败:', e);
    }
}

// 辅助函数
function showLoading(message) {
    events.emit(Events.LOADING_START, message);
}

function hideLoading() {
    events.emit(Events.LOADING_END);
}
