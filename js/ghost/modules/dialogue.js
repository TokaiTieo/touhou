// js/ghost/modules/dialogue.js
import { state } from '../core/state.js';
import { CURRENT_CHAPTER_INDEX } from '../core/constants.js';
import { events, Events } from '../core/events.js';
import { renderChatHistory, refreshNPCList, refreshTasksPanel, renderActionSuggestions } from '../../vue/game-controller.js';
import { showToast } from '../ui/components.js';
import { appendToConversationHistory, loadRelationships, npcDialogue, npcDialogueStream, waitForTurnResult } from '../../api.js';
import { callAIAndRespond } from './chat.js';
import { getTaskDisplayName } from '../ui/text.js';
import { refreshCharacterTime } from '../core/session.js';
import { beginGeneration, endGeneration } from '../core/generation.js';
import {
    scrollGameChatToBottom as scrollChatToBottom,
    setComposerDisabled as updateInputsDisabled
} from '../../vue/game-ui.js';

// 开始NPC对话
export async function startNPCDialogue(npcId, npcName) {
    if (state.isWaitingForAI) {
        showToast('请等待上一条消息处理完成', 1500);
        return;
    }
    
    if (state.currentSession.isDead) {
        showToast('角色已死亡，无法对话', 2000);
        return;
    }
    
    state.currentDialogueNPC = { id: npcId, name: npcName };
    state.isInDialogue = true;
    
    // 添加系统消息
    const systemMsg = {
        role: 'system',
        speaker: '系统',
        content: `你开始与 ${npcName} 对话。`,
        timestamp: Date.now(),
        isDead: false
    };
    state.addChatMessage(systemMsg);
    
    await appendToConversationHistory(
        state.currentSession.characterId,
        '系统',
        `你开始与 ${npcName} 对话。`,
        state.currentSession.currentScene,
        false
    );
    
    renderChatHistory();
    scrollChatToBottom();
    
    // 不再自动触发NPC问候
    // 等待玩家输入第一句话
    showToast(`现在可以对 ${npcName} 说话了`, 2000);
}

// 继续对话（不说话，让NPC继续说）
export async function continueDialogue(npcId, npcName) {
    if (state.isWaitingForAI) {
        showToast('请等待上一条消息处理完成', 1500);
        return;
    }
    
    if (state.currentSession.isDead) {
        showToast('角色已死亡，无法继续对话', 2000);
        return;
    }
    
    await callAIForDialogue('', '', false, true);
}

// 结束对话
export async function endDialogue() {
    if (!state.isInDialogue) return;
    
    const npcName = state.currentDialogueNPC?.name || 'NPC';
    
    const systemMsg = {
        role: 'system',
        speaker: '系统',
        content: `你结束了与 ${npcName} 的对话。`,
        timestamp: Date.now(),
        isDead: false
    };
    state.addChatMessage(systemMsg);
    
    await appendToConversationHistory(
        state.currentSession.characterId,
        '系统',
        `你结束了与 ${npcName} 的对话。`,
        state.currentSession.currentScene,
        false
    );
    
    state.currentDialogueNPC = null;
    state.isInDialogue = false;
    
    renderChatHistory();
    scrollChatToBottom();
    showToast(`已结束与 ${npcName} 的对话`, 2000);
}

// 观察NPC
export async function observeNPC(npcId, npcName) {
    if (state.isWaitingForAI) {
        showToast('请等待上一条消息处理完成', 1500);
        return;
    }
    
    if (state.currentSession.isDead) {
        showToast('角色已死亡，无法观察', 2000);
        return;
    }
    
    // 显示加载状态
    const loadingMsg = {
        role: 'assistant',
        speaker: '旁白',
        content: '🔍 观察中...',
        timestamp: Date.now(),
        isDead: false,
        isTemporary: true
    };
    state.addChatMessage(loadingMsg);
    renderChatHistory();
    scrollChatToBottom();
    
    try {
        const response = await fetch('/api/ghost/observe_npc', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                character_id: state.currentSession.characterId,
                npc_name: npcName,
                scene: state.currentSession.currentScene
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        
        // 移除临时的加载消息
        state.chatHistory = state.chatHistory.filter(msg => !msg.isTemporary);
        
        const observeMsg = {
            role: 'assistant',
            speaker: '旁白',
            content: data.description,
            timestamp: Date.now(),
            isDead: false
        };
        state.addChatMessage(observeMsg);
        
        await appendToConversationHistory(
            state.currentSession.characterId,
            '旁白',
            data.description,
            state.currentSession.currentScene,
            false
        );
        
        renderChatHistory();
        scrollChatToBottom();
        
    } catch (err) {
        console.error('观察失败:', err);
        // 移除临时的加载消息
        state.chatHistory = state.chatHistory.filter(msg => !msg.isTemporary);
        
        const errorMsg = {
            role: 'assistant',
            speaker: '旁白',
            content: '你试图观察，但什么也没发现。',
            timestamp: Date.now(),
            isDead: false
        };
        state.addChatMessage(errorMsg);
        renderChatHistory();
        scrollChatToBottom();
        showToast('观察失败，请重试', 2000, 'error');
    }
}

// 调用NPC对话AI
export async function callAIForDialogue(action, speech, isGreeting = false, isContinue = false) {
    state.isWaitingForAI = true;
    renderChatHistory();
    updateInputsDisabled(true, true);
    const turnId = crypto.randomUUID?.() || `turn-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const controller = beginGeneration({
        characterId: state.currentSession.characterId,
        turnId
    });
    
    const loadingIndicator = showLoadingIndicator();
    
    try {
        const historyForAI = state.chatHistory.slice(-15).map(msg => ({
            speaker: msg.speaker,
            content: msg.content,
            role: msg.role
        }));
        
        // 构建用户输入文本（包含动作和语言）
        let userInputText = '';
        if (isGreeting) {
            userInputText = '';
        } else if (isContinue) {
            userInputText = '[玩家没有说话，等待NPC继续]';
        } else {
            if (action && speech) {
                userInputText = `【动作】${action}\n【语言】"${speech}"`;
            } else if (action) {
                userInputText = `【动作】${action}`;
            } else if (speech) {
                userInputText = `【语言】"${speech}"`;
            }
        }
        
        const requestBody = {
            character_id: state.currentSession.characterId,
            chapter_index: CURRENT_CHAPTER_INDEX,
            scene: state.currentSession.currentScene,
            player_name: state.currentSession.profile?.name || '玩家',
            npc_id: state.currentDialogueNPC.id,
            npc_name: state.currentDialogueNPC.name,
            user_input: userInputText,
            is_greeting: isGreeting,
            is_continue: isContinue,
            history: historyForAI,
            scene_npcs: state.currentSceneNPCs
        };
        
        const assistantMsg = state.addChatMessage({
            role: 'assistant',
            speaker: state.currentDialogueNPC.name,
            content: '',
            timestamp: Date.now(),
            isDead: false,
            isDialogue: true,
            isStreaming: true
        });

        const requestArgs = [
            requestBody.character_id,
            requestBody.chapter_index,
            requestBody.scene,
            requestBody.player_name,
            requestBody.npc_id,
            requestBody.npc_name,
            requestBody.user_input,
            requestBody.is_greeting,
            requestBody.is_continue,
            requestBody.history,
            requestBody.scene_npcs,
            turnId
        ];

        let data;
        let hasStreamedText = false;
        try {
            data = await npcDialogueStream(...requestArgs, {
                signal: controller.signal,
                onToken: text => {
                    if (!hasStreamedText) {
                        hasStreamedText = true;
                        removeLoadingIndicator(loadingIndicator);
                    }
                    assistantMsg.content += text;
                    renderChatHistory();
                    scrollChatToBottom();
                }
            });
        } catch (streamError) {
            if (streamError.name === 'AbortError') throw streamError;
            console.warn('NPC流式接口中断，尝试恢复原回合:', streamError);
            assistantMsg.content = '（连接已中断，正在恢复本回合……）';
            renderChatHistory();
            showToast('连接中断，正在恢复本回合', 2500);
            data = await waitForTurnResult(
                state.currentSession.characterId,
                turnId,
                {
                    signal: controller.signal,
                    onStatus: status => {
                        if (status.state === 'settling' || status.state === 'checkpoint_cleanup') {
                            assistantMsg.content = '（回复已生成，正在完成本回合结算……）';
                            renderChatHistory();
                        }
                    }
                }
            );
            if (!data) {
                assistantMsg.content = '';
                data = await npcDialogue(...requestArgs);
            } else {
                showToast('本回合已恢复', 1800);
            }
        }
        removeLoadingIndicator(loadingIndicator);
        
        let npcResponse = '';
        let exitDialogue = false;
        
        if (typeof data === 'object') {
            npcResponse = data.description || data.message || `${state.currentDialogueNPC.name} 没有回应。`;
            exitDialogue = data.exit_dialogue === true;
        } else if (typeof data === 'string') {
            npcResponse = data;
        } else {
            npcResponse = `${state.currentDialogueNPC.name} 没有回应。`;
        }
        
        assistantMsg.content = npcResponse;
        assistantMsg.isStreaming = false;
        renderChatHistory();
        scrollChatToBottom();

        const turnSummary = buildDialogueSummary(data);
        if (turnSummary) {
            state.addChatMessage({
                role: 'system',
                speaker: '本回合变化',
                content: turnSummary,
                timestamp: Date.now(),
                isDead: false
            });
        }
        
        const savedMessage = await appendToConversationHistory(
            state.currentSession.characterId,
            state.currentDialogueNPC.name,
            npcResponse,
            state.currentSession.currentScene,
            false
        );
        assistantMsg.messageId = savedMessage.message_id;
        assistantMsg.conversationIndex = savedMessage.message_index;
        assistantMsg.rewriteCandidates = savedMessage.rewrite_candidates || [];
        assistantMsg.activeRewrite = -1;
        
        if (exitDialogue) {
            const exitMsg = {
                role: 'system',
                speaker: '系统',
                content: `⚠️ 由于事态升级，你被迫结束了与 ${state.currentDialogueNPC.name} 的对话。`,
                timestamp: Date.now(),
                isDead: false
            };
            state.addChatMessage(exitMsg);
            
            await appendToConversationHistory(
                state.currentSession.characterId,
                '系统',
                `⚠️ 由于事态升级，你被迫结束了与 ${state.currentDialogueNPC.name} 的对话。`,
                state.currentSession.currentScene,
                false
            );
            
            state.currentDialogueNPC = null;
            state.isInDialogue = false;
            
            renderChatHistory();
            scrollChatToBottom();
            await callAIAndRespond({ action: '', speech: '' });
        } else {
            renderChatHistory();
            scrollChatToBottom();
        }
        
        if (data.relationship_update) {
            try {
                const relationshipData = await loadRelationships(state.currentSession.characterId);
                state.updateRelationships(relationshipData.relationships || {});
            } catch (err) {
                console.warn('刷新关系失败:', err);
            }
        }

        if (data.incident_state) {
            state.currentSession.incidentState = data.incident_state;
        }

        if (data.player_state_delta) {
            await refreshCharacterTime();
        }

        // 刷新线索板
        await refreshTasksPanel();
        renderActionSuggestions();
        
    } catch (err) {
        console.error('NPC对话失败:', err);
        removeLoadingIndicator(loadingIndicator);
        if (err.name === 'AbortError') {
            const partial = state.chatHistory.findLast?.(msg => msg.isStreaming);
            if (partial) {
                partial.isStreaming = false;
                partial.content = partial.content || '（生成已停止）';
            }
            renderChatHistory();
            showToast('已停止生成', 1500);
            return;
        }
        
        const errorMsg = {
            role: 'assistant',
            speaker: '系统',
            content: `对话失败：${err.message}`,
            timestamp: Date.now(),
            isDead: false
        };
        state.addChatMessage(errorMsg);
        renderChatHistory();
        scrollChatToBottom();
        showToast('对话失败，请重试', 3000, 'error');
    } finally {
        endGeneration(controller);
        state.isWaitingForAI = false;
        updateInputsDisabled(state.currentSession.isDead);
        // 移除加载指示器
        // 关键：重新渲染聊天区域，更新按钮状态
        renderChatHistory();  // 确保这行存在
        
        // 刷新任务面板
        await refreshTasksPanel();
    }
}

function showLoadingIndicator() {
    return null;
}

function removeLoadingIndicator() {}

async function streamDialogueMessageContent(message, text) {
    const content = String(text || '');
    const step = content.length > 600 ? 12 : 6;
    for (let i = 0; i < content.length; i += step) {
        message.content = content.slice(0, i + step);
        renderChatHistory();
        scrollChatToBottom();
        await new Promise(resolve => setTimeout(resolve, 12));
    }
    message.content = content;
}

function buildDialogueSummary(data) {
    if (!data || typeof data !== 'object') return '';
    const parts = [];
    if (data.relationship_update) {
        parts.push(`缘分变化：${data.relationship_update}`);
    }
    if (data.incident_resolution?.summary) {
        parts.push(`异变结算：${data.incident_resolution.summary}`);
    }
    if (data.new_incident?.title) {
        parts.push(`新异变：${data.new_incident.title} · ${data.new_incident.rumor || '新的传闻正在扩散'}`);
    }
    if (Array.isArray(data.task_updates) && data.task_updates.length > 0) {
        parts.push(`线索板：${data.task_updates.map(item => {
            const label = item.action === 'complete' ? '归档' : '推进';
            return `${label}「${getTaskDisplayName(item.task_id, item)}」`;
        }).join('，')}`);
    }
    if (Array.isArray(data.memory_updates) && data.memory_updates.length > 0) {
        parts.push(`NPC记忆：${data.memory_updates.map(item => `${item.npc_name || item.name || 'NPC'}记住了这件事`).join('，')}`);
    }
    if (data.open_event) {
        parts.push(`自由事件：${data.open_event.title || data.open_event.type || '自由探索事件'}`);
    }
    if (data.dynamic_event) {
        parts.push(`新见闻：${data.dynamic_event.title || '人物事件'}`);
    }
    const progressionNotices = data.progression_notifications || data.progression_delta?.notifications || [];
    if (progressionNotices.length) {
        parts.push(`成长：${progressionNotices.map(item => item.detail ? `${item.title}（${item.detail}）` : item.title).join('，')}`);
    }
    const inventoryDelta = data.progression_delta?.inventory || [];
    const inventoryText = inventoryDelta
        .filter(item => item.action !== 'rejected')
        .map(item => `${item.action === 'add' ? '获得' : item.action === 'use' ? '使用' : '失去'}${item.name}×${item.quantity || 1}`);
    if (inventoryText.length) parts.push(`行囊：${inventoryText.join('，')}`);
    const reputationDelta = data.progression_delta?.reputation || [];
    if (reputationDelta.length) {
        parts.push(`声望：${reputationDelta.map(item => `${item.faction}${item.delta > 0 ? '+' : ''}${item.delta}`).join('，')}`);
    }
    if (data.spellcard_result) {
        const battle = data.spellcard_result;
        const metrics = battle.metrics || {};
        const mastery = battle.mastery || {};
        const detail = [
            metrics.accuracy !== undefined ? `命中${metrics.accuracy}%` : '',
            metrics.graze_count !== undefined ? `擦弹${metrics.graze_count}` : '',
            mastery.level ? `${mastery.tier || '熟练'} Lv.${mastery.level}` : ''
        ].filter(Boolean).join(' · ');
        parts.push(`符卡裁定：${battle.spellcard_name || '无名符卡'} · ${battle.opponent || '对手'} · ${battle.outcome || '已裁定'}${detail ? ` · ${detail}` : ''}`);
    }
    const stateDelta = formatPlayerStateDelta(data.player_state_delta);
    if (stateDelta) {
        parts.push(`状态变化：${stateDelta}`);
    }
    const echoes = (data.consequence_summary || []).filter(
        item => item.includes('后续回响') || item.includes('气氛') || item.includes('局势')
    );
    if (echoes.length) parts.push(`世界回响：${echoes.join('，')}`);
    return parts.join('；');
}

function formatPlayerStateDelta(delta) {
    if (!delta || typeof delta !== 'object') return '';
    return Object.entries(delta)
        .filter(([, change]) => typeof change === 'number' ? change !== 0 : change && typeof change === 'object' && change.old !== change.new)
        .map(([key, change]) => typeof change === 'number'
            ? `${key} ${change > 0 ? '+' : ''}${change}`
            : `${key} ${change.old}→${change.new}`)
        .join('，');
}
