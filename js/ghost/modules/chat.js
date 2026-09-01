// js/ghost/modules/chat.js
import { state } from '../core/state.js';
import { CURRENT_CHAPTER_INDEX } from '../core/constants.js';
import { events, Events } from '../core/events.js';
import { renderChatHistory, refreshTasksPanel, updateTimeDisplay, refreshNPCList, renderActionSuggestions, renderCharacterInfo } from '../../vue/game-controller.js';
import { showToast } from '../ui/components.js';
import { appendToConversationHistory, environmentInteract, environmentInteractStream, loadRelationships, waitForTurnResult } from '../../api.js';
import { refreshCharacterTime } from '../core/session.js';
import { beginGeneration, cancelActiveGeneration, endGeneration, hasActiveGeneration } from '../core/generation.js';
import { switchScene } from './location.js';
import { getTaskDisplayName } from '../ui/text.js';
import {
    clearComposer,
    gameUi,
    scrollGameChatToBottom as scrollChatToBottom,
    setComposerDisabled as updateInputsDisabled
} from '../../vue/game-ui.js';

// 发送消息
export async function handleSendMessage() {
    if (state.isWaitingForAI) {
        if (hasActiveGeneration() && cancelActiveGeneration()) {
            showToast('正在停止生成...', 1200);
        } else {
            showToast('请等待上一条消息处理完成', 1500);
        }
        return;
    }
    
    if (state.currentSession.isDead) {
        showToast('角色已死亡，无法互动', 2000);
        return;
    }
    
    const action = gameUi.actionDraft.trim();
    const speech = gameUi.speechDraft.trim();
    
    if (!action && !speech) {
        showToast('请填写动作或语言', 2000);
        return;
    }
    
    // 对话模式
    if (state.isInDialogue && state.currentDialogueNPC && speech) {
        await sendDialogueMessage(action, speech);
        return;
    }
    
    // 对话模式但有动作无语言
    if (state.isInDialogue && state.currentDialogueNPC && action && !speech) {
        showToast('请填写想对 NPC 说的话', 2000);
        return;
    }
    
    // 环境交互
    await sendEnvironmentMessage(action, speech);
}

// 发送环境交互消息
async function sendEnvironmentMessage(action, speech) {
    let displayContent = '';
    let storageContent = '';
    
    if (action && speech) {
        displayContent = `（${action}）"${speech}"`;
        storageContent = `（${action}）"${speech}"`;
    } else if (action) {
        displayContent = `（${action}）`;
        storageContent = action;
    } else if (speech) {
        displayContent = `"${speech}"`;
        storageContent = speech;
    }
    
    // 添加用户消息
    const userMsg = {
        role: 'user',
        speaker: state.currentSession.profile?.name || '我',
        content: displayContent,
        timestamp: Date.now(),
        isDead: false
    };
    state.addChatMessage(userMsg);
    
    await appendToConversationHistory(
        state.currentSession.characterId,
        state.currentSession.profile?.name || '我',
        storageContent,
        state.currentSession.currentScene,
        false
    );
    
    renderChatHistory();
    scrollChatToBottom();
    
    // 清空输入框
    clearComposer();
    
    // 调用AI
    await callAIAndRespond({ action, speech });
}

// 发送对话消息
async function sendDialogueMessage(action, speech) {
    // 构建显示内容和存储内容
    let displayContent = '';
    let storageContent = '';
    
    if (action && speech) {
        displayContent = `（${action}）"${speech}"`;
        storageContent = `（${action}）"${speech}"`;
    } else if (action) {
        displayContent = `（${action}）`;
        storageContent = action;
    } else if (speech) {
        displayContent = `"${speech}"`;
        storageContent = speech;
    }
    
    const userMsg = {
        role: 'user',
        speaker: state.currentSession.profile?.name || '我',
        content: displayContent,
        timestamp: Date.now(),
        isDead: false
    };
    state.addChatMessage(userMsg);
    
    await appendToConversationHistory(
        state.currentSession.characterId,
        state.currentSession.profile?.name || '我',
        storageContent,
        state.currentSession.currentScene,
        false
    );
    
    renderChatHistory();
    scrollChatToBottom();
    
    clearComposer();
    
    // 传递 action 和 speech
    const { callAIForDialogue } = await import('./dialogue.js');
    await callAIForDialogue(action, speech, false);
}

// 调用AI并响应
export async function callAIAndRespond(userInput) {
    state.isWaitingForAI = true;
    renderChatHistory();
    updateInputsDisabled(true, true);
    const turnId = crypto.randomUUID?.() || `turn-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const controller = beginGeneration({
        characterId: state.currentSession.characterId,
        turnId
    });
    
    // 显示加载指示器
    const loadingIndicator = showLoadingIndicator();
    
    try {
        const historyForAI = state.chatHistory.slice(-10).map(msg => ({
            speaker: msg.speaker,
            content: msg.content,
            role: msg.role
        }));
        
        let hasStreamedText = false;
        const assistantMsg = state.addChatMessage({
            role: 'assistant',
            speaker: '旁白',
            content: '',
            timestamp: Date.now(),
            isDead: false,
            continueDisabled: false,
            isStreaming: true
        });

        const requestArgs = [
            state.currentSession.characterId,
            CURRENT_CHAPTER_INDEX,
            state.currentSession.currentScene,
            state.currentSession.profile?.name || '我',
            { action: userInput.action, speech: userInput.speech },
            historyForAI,
            state.currentSceneNPCs,
            turnId
        ];

        let response;
        try {
            response = await environmentInteractStream(...requestArgs, {
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
            console.warn('流式接口中断，尝试恢复原回合:', streamError);
            assistantMsg.content = '（连接已中断，正在恢复本回合……）';
            renderChatHistory();
            showToast('连接中断，正在恢复本回合', 2500);
            response = await waitForTurnResult(
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
            if (!response) {
                assistantMsg.content = '';
                response = await environmentInteract(...requestArgs);
            } else {
                showToast('本回合已恢复', 1800);
            }
        }

        removeLoadingIndicator(loadingIndicator);
        
        const description = response.description || '世界没有给出回应。';
        const isDead = response.is_dead === true;
        const newLocation = response.new_location;
        const turnSummary = buildTurnSummary(response, userInput);

        if (response.incident_state) {
            state.currentSession.incidentState = response.incident_state;
            updateTimeDisplay();
        }
        if (response.onboarding) {
            state.currentSession.onboarding = response.onboarding;
        }
        
        // 处理时间变化
        if (response.time_cost !== undefined && response.time_cost > 0) {
            await refreshCharacterTime();
            updateTimeDisplay();
        }
        
        if (response.new_energy_state && state.currentSession.time) {
            state.currentSession.time.energy_state = response.new_energy_state;
            updateTimeDisplay();
        }
        if (response.player_state_delta) {
            await refreshCharacterTime();
            updateTimeDisplay();
        }
        
        assistantMsg.content = description;
        assistantMsg.isDead = isDead;
        assistantMsg.isStreaming = false;
        renderChatHistory();
        scrollChatToBottom();

        if (turnSummary) {
            state.setLastTurnSummary(turnSummary);
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
            '旁白',
            description,
            state.currentSession.currentScene,
            isDead
        );
        assistantMsg.messageId = savedMessage.message_id;
        assistantMsg.conversationIndex = savedMessage.message_index;
        assistantMsg.rewriteCandidates = savedMessage.rewrite_candidates || [];
        assistantMsg.activeRewrite = -1;
        
        // 处理死亡
        if (isDead) {
            state.currentSession.isDead = true;
            showToast('💀 角色死亡，无法继续互动', 5000);
            updateInputsDisabled(true);
        }
        
        // 处理场景切换
        if (newLocation && newLocation !== state.currentSession.currentScene) {
            await switchScene(newLocation);
        } else {
            renderChatHistory();
            scrollChatToBottom();
        }
        
        await refreshNPCList();

        if (response.relationship_update) {
            try {
                const relationshipData = await loadRelationships(state.currentSession.characterId);
                state.updateRelationships(relationshipData.relationships || {});
                pulseRelationshipsButton();
            } catch (relationshipErr) {
                console.warn('刷新缘分录失败:', relationshipErr);
            }
        }
        
        // 刷新任务面板（因为 AI 可能更新了任务）
        await refreshTasksPanel();
        renderActionSuggestions();
        
    } catch (err) {
        console.error('AI调用失败:', err);
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
            content: `错误：${err.message}`,
            timestamp: Date.now(),
            isDead: false
        };
        state.addChatMessage(errorMsg);
        renderChatHistory();
        scrollChatToBottom();
        showToast('AI调用失败，请重试', 3000, 'error');
    } finally {
        endGeneration(controller);
        state.isWaitingForAI = false;
        updateInputsDisabled(state.currentSession.isDead);
    }
}

async function streamMessageContent(message, text) {
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

function pulseRelationshipsButton() {
    const btn = document.getElementById('relationshipsBtn');
    if (!btn) return;
    btn.classList.add('relationship-updated');
    setTimeout(() => btn.classList.remove('relationship-updated'), 5000);
}

function buildTurnSummary(response, userInput) {
    const parts = [];
    const actionText = `${userInput?.action || ''} ${userInput?.speech || ''}`;

    if (response.time_cost !== undefined && response.time_cost > 0) {
        parts.push(`时间流逝 ${formatTimeCost(response.time_cost)}`);
    }

    if (response.new_energy_state) {
        parts.push(`状态变为「${response.new_energy_state}」`);
    }

    if (response.relationship_update && typeof response.relationship_update === 'string') {
        parts.push(`缘分变化：${response.relationship_update}`);
    }

    if (response.incident_resolution?.summary) {
        parts.push(`异变结算：${response.incident_resolution.summary}`);
    }
    if (response.new_incident?.title) {
        parts.push(`新异变：${response.new_incident.title} · ${response.new_incident.rumor || '新的传闻正在扩散'}`);
    }

    if (Array.isArray(response.task_updates) && response.task_updates.length > 0) {
        const taskText = response.task_updates.map(t => {
            const label = t.action === 'complete' ? '完成' : '推进';
            return `${label}「${getTaskDisplayName(t.task_id, t)}」`;
        }).join('，');
        parts.push(`线索板：${taskText}`);
    }

    if (Array.isArray(response.memory_updates) && response.memory_updates.length > 0) {
        const memoryText = response.memory_updates
            .map(item => `${item.npc_name || item.name || 'NPC'}记住了这件事`)
            .join('，');
        parts.push(`NPC记忆：${memoryText}`);
    }

    if (response.open_event) {
        const eventTitle = response.open_event.title || response.open_event.type || '自由探索事件';
        parts.push(`自由事件：${eventTitle}`);
    }
    if (response.dynamic_event) {
        parts.push(`新见闻：${response.dynamic_event.title || '地点偶遇'}`);
    }
    const progressionNotices = response.progression_notifications || response.progression_delta?.notifications || [];
    if (progressionNotices.length) {
        parts.push(`成长：${progressionNotices.map(item => item.detail ? `${item.title}（${item.detail}）` : item.title).join('，')}`);
    }
    const inventoryDelta = response.progression_delta?.inventory || [];
    const inventoryText = inventoryDelta
        .filter(item => item.action !== 'rejected')
        .map(item => `${item.action === 'add' ? '获得' : item.action === 'use' ? '使用' : '失去'}${item.name}×${item.quantity || 1}`);
    if (inventoryText.length) parts.push(`行囊：${inventoryText.join('，')}`);
    const reputationDelta = response.progression_delta?.reputation || [];
    if (reputationDelta.length) {
        parts.push(`声望：${reputationDelta.map(item => `${item.faction}${item.delta > 0 ? '+' : ''}${item.delta}`).join('，')}`);
    }

    if (response.spellcard_result) {
        const battle = response.spellcard_result;
        const opponent = battle.opponent || '对手';
        const outcome = battle.outcome || '已裁定';
        const metrics = battle.metrics || {};
        const mastery = battle.mastery || {};
        const detail = [
            metrics.accuracy !== undefined ? `命中${metrics.accuracy}%` : '',
            metrics.graze_count !== undefined ? `擦弹${metrics.graze_count}` : '',
            mastery.level ? `${mastery.tier || '熟练'} Lv.${mastery.level}` : ''
        ].filter(Boolean).join(' · ');
        parts.push(`符卡裁定：${battle.spellcard_name || '无名符卡'} · ${opponent} · ${outcome}${detail ? ` · ${detail}` : ''}`);
    }

    const stateDelta = formatPlayerStateDelta(response.player_state_delta);
    if (stateDelta) {
        parts.push(`状态变化：${stateDelta}`);
    }

    if (response.new_location) {
        const locName = typeof response.new_location === 'string' ? response.new_location : response.new_location.name;
        if (locName) parts.push(`位置变化：${locName}`);
    }
    const echoes = (response.consequence_summary || []).filter(
        item => item.includes('后续回响') || item.includes('气氛') || item.includes('局势')
    );
    if (echoes.length) parts.push(`世界回响：${echoes.join('，')}`);

    if (!response.spellcard_result && /符卡|弹幕|决斗|挑战|spell/i.test(actionText)) {
        parts.push('符卡规则已介入：本次冲突按弹幕胜负、回避空间与认输机制裁定');
    }

    if (response.is_dead === true) {
        parts.push('角色死亡：可以删除历史回溯');
    }

    return parts.length > 0 ? parts.join('；') : '';
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

function formatTimeCost(cost) {
    if (cost === 0.25) return '15 分钟';
    if (cost === 0.5) return '30 分钟';
    if (cost === 0.75) return '45 分钟';
    if (cost === 1) return '1 小时';
    if (cost < 1) return `${Math.round(cost * 60)} 分钟`;
    if (Number.isInteger(cost)) return `${cost} 小时`;
    const hours = Math.floor(cost);
    const minutes = Math.round((cost - hours) * 60);
    return hours > 0 ? `${hours} 小时 ${minutes} 分钟` : `${minutes} 分钟`;
}

// 继续按钮处理
export async function handleContinue() {
    if (state.isWaitingForAI) {
        showToast('请等待上一条消息处理完成', 1500);
        return;
    }
    
    if (state.currentSession.isDead) {
        showToast('角色已死亡，无法继续', 2000);
        return;
    }
    
    await callAIAndRespond({ action: '继续', speech: '' });
}

// 删除历史
export async function handleDeleteHistory(fromIndex) {
    const deletedCount = state.chatHistory.length - fromIndex;
    state.chatHistory = state.chatHistory.slice(0, fromIndex);
    
    try {
        const { deleteHistory } = await import('../../api.js');
        await deleteHistory(state.currentSession.characterId, fromIndex);
        showToast(`已删除 ${deletedCount} 条消息`, 2000);
    } catch (err) {
        console.error('删除后端记录失败:', err);
        showToast('后端删除失败，但前端已移除', 3000);
    }
    
    if (state.currentSession.isDead) {
        state.currentSession.isDead = false;
        updateInputsDisabled(false);
        showToast('已复活，可以继续游戏', 2000);
    }
    
    renderChatHistory();
    scrollChatToBottom();
    renderCharacterInfo();
}

// 测试AI连接
export async function testAIConnection() {
    try {
        const response = await fetch('/api/ghost/test_ai');
        const data = await response.json();
        if (data.success) {
            showToast('AI 连接正常', 2000, 'success');
        } else {
            showToast(data.message || 'AI 连接不可用', 3000, 'error');
        }
    } catch (err) {
        console.error('测试AI失败:', err);
        showToast(`连接失败：${err.message}`, 3000, 'error');
    }
}

function showLoadingIndicator() {
    return null;
}

function removeLoadingIndicator() {}
