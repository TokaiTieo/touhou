// ========================= API 调用模块 =========================
// 文件: js/api.js
// 版本: v4.0 - 完整 ES6 模块导出

// ========== 基础 API 调用函数 ==========
async function apiCall(endpoint, options = {}) {
    const url = endpoint.startsWith('http') ? endpoint : `/api${endpoint}`;
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };
    
    const mergedOptions = {
        ...defaultOptions,
        ...options,
        headers: {
            ...defaultOptions.headers,
            ...options.headers,
        },
    };
    
    if (mergedOptions.body && typeof mergedOptions.body !== 'string') {
        mergedOptions.body = JSON.stringify(mergedOptions.body);
    }
    
    try {
        const response = await fetch(url, mergedOptions);
        
        if (!response.ok) {
            let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
            try {
                const errorData = await response.json();
                errorMessage = formatApiError(errorData, errorMessage);
            } catch (e) {
                // 忽略 JSON 解析错误
            }
            throw new Error(errorMessage);
        }
        
        if (response.status === 204) {
            return null;
        }
        
        return await response.json();
    } catch (err) {
        console.error(`API 调用失败 [${endpoint}]:`, err);
        throw err;
    }
}

function formatApiError(errorData, fallback) {
    if (!errorData) return fallback;
    const detail = errorData.detail ?? errorData.message ?? errorData.error ?? errorData.description;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail)) {
        const messages = detail.map(item => item?.msg || item?.message || String(item)).filter(Boolean);
        if (messages.length) return messages.join('；');
    }
    if (detail && typeof detail === 'object') {
        return detail.message || detail.msg || JSON.stringify(detail);
    }
    return fallback;
}

async function streamApiCall(endpoint, body, { signal, onToken } = {}) {
    const response = await fetch(`/api${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
        body: JSON.stringify(body),
        signal
    });
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    }
    if (!response.body) throw new Error('当前环境不支持流式响应');

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let finalResult = null;

    const consumeEvent = block => {
        let eventName = 'message';
        const dataLines = [];
        for (const line of block.split(/\r?\n/)) {
            if (line.startsWith('event:')) eventName = line.slice(6).trim();
            if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
        }
        if (!dataLines.length) return;
        const payload = JSON.parse(dataLines.join('\n'));
        if (eventName === 'token') onToken?.(payload.text || '');
        if (eventName === 'result') finalResult = payload;
        if (eventName === 'error') throw new Error(payload.message || '流式生成失败');
    };

    while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() || '';
        for (const block of blocks) consumeEvent(block);
        if (done) break;
    }
    if (buffer.trim()) consumeEvent(buffer);
    if (!finalResult) throw new Error('流式响应未返回最终结算');
    return finalResult;
}

// ========== 主线相关 API ==========
async function fetchChapters() {
    return await apiCall('/chapters');
}

async function fetchChapter(index) {
    return await apiCall(`/chapter/${index}`);
}

async function fetchChapterBridge(chapterIndex) {
    return await apiCall(`/chapter/${chapterIndex}/bridge`);
}

async function saveProgress(progressData) {
    return await apiCall('/save', {
        method: 'POST',
        body: progressData
    });
}

async function loadProgress(sessionId) {
    return await apiCall(`/load/${sessionId}`);
}

// ========== 幽灵模式相关 API ==========

// 初始化 NPC 池（基于章节内容）
async function initNPCPool(chapterIndex, locations) {
    return await apiCall('/ghost/init_npc_pool', {
        method: 'POST',
        body: {
            chapter_index: chapterIndex,
            locations: locations
        }
    });
}

// 验证角色设定是否符合世界观
async function validateCharacter(userInput, chapterIndex) {
    return await apiCall('/ghost/validate_character', {
        method: 'POST',
        body: {
            user_input: userInput,
            chapter_index: chapterIndex
        }
    });
}

// 创建自定义角色
async function createCharacter(profile, chapterIndex) {
    return await apiCall('/ghost/create_character', {
        method: 'POST',
        body: {
            profile: profile,
            chapter_index: chapterIndex
        }
    });
}

// 加载角色进入幽灵模式
async function loadCharacter(characterId, chapterIndex, scene = null) {
    //console.log('loadCharacter API call:', { characterId, chapterIndex, scene });
    const result = await apiCall('/ghost/load_character', {
        method: 'POST',
        body: {
            character_id: characterId,
            chapter_index: chapterIndex,
            scene: scene
        }
    });
    //console.log('loadCharacter API response:', result);
    return result;
}

// 获取角色列表（可选按世界过滤）
async function listCharacters(worldId = null) {
    let url = '/ghost/list_characters';
    if (worldId) {
        url += `?world_id=${encodeURIComponent(worldId)}`;
    }
    return await apiCall(url);
}

// 环境交互
async function environmentInteract(characterId, chapterIndex, scene, playerName, userInput, history, sceneNPCs, turnId = null) {
    return await apiCall('/ghost/environment_interact', {
        method: 'POST',
        body: {
            character_id: characterId,
            chapter_index: chapterIndex,
            scene: scene,
            player_name: playerName,
            user_input: userInput,
            history: history || [],
            scene_npcs: sceneNPCs || [],
            turn_id: turnId
        }
    });
}

async function environmentInteractStream(characterId, chapterIndex, scene, playerName, userInput, history, sceneNPCs, turnId = null, streamOptions = {}) {
    return await streamApiCall('/ghost/environment_interact_stream', {
        character_id: characterId,
        chapter_index: chapterIndex,
        scene,
        player_name: playerName,
        user_input: userInput,
        history: history || [],
        scene_npcs: sceneNPCs || [],
        turn_id: turnId
    }, streamOptions);
}

async function getTurnStatus(characterId, turnId) {
    return await apiCall(
        `/ghost/turn_status/${encodeURIComponent(characterId)}/${encodeURIComponent(turnId)}`
    );
}

async function waitForTurnResult(
    characterId,
    turnId,
    { signal, timeoutMs = 90000, pollMs = 450, onStatus } = {}
) {
    const deadline = Date.now() + timeoutMs;
    let unknownCount = 0;
    while (Date.now() < deadline) {
        if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
        const status = await getTurnStatus(characterId, turnId);
        onStatus?.(status);
        if (status.state === 'committed' && status.result) return status.result;
        if (status.persisted) return null;
        if (status.state === 'cancelled') {
            throw new DOMException('Aborted', 'AbortError');
        }
        if (status.state === 'failed' || status.state === 'interrupted') return null;
        if (status.state === 'unknown') {
            unknownCount += 1;
            if (unknownCount >= 2) return null;
        } else {
            unknownCount = 0;
        }
        await new Promise((resolve, reject) => {
            const timer = setTimeout(resolve, pollMs);
            signal?.addEventListener('abort', () => {
                clearTimeout(timer);
                reject(new DOMException('Aborted', 'AbortError'));
            }, { once: true });
        });
    }
    return null;
}

async function cancelTurn(characterId, turnId) {
    return await apiCall('/ghost/turn_cancel', {
        method: 'POST',
        body: { character_id: characterId, turn_id: turnId }
    });
}

// 获取指定场景的 NPC 列表
async function getNPCsByScene(sceneName, characterId = null) {
    const query = characterId ? `?character_id=${encodeURIComponent(characterId)}` : '';
    return await apiCall(`/ghost/npcs/by_scene/${encodeURIComponent(sceneName)}${query}`);
}

// 兼容旧名称
async function getNPCsByLocation(locationName) {
    return getNPCsByScene(locationName);
}

// 更新角色当前场景
async function updateCharacterScene(characterId, scene, chapterIndex) {
    return await apiCall('/ghost/update_scene', {
        method: 'POST',
        body: {
            character_id: characterId,
            scene: scene,
            chapter_index: chapterIndex
        }
    });
}

// 添加对话记录到历史
async function appendToConversationHistory(characterId, speaker, content, scene, isDead = false) {
    return await apiCall('/ghost/append_conversation', {
        method: 'POST',
        body: {
            character_id: characterId,
            speaker: speaker,
            content: content,
            scene: scene,
            is_dead: isDead
        }
    });
}

async function rewriteMessage(characterId, messageId, messageIndex, instruction = '') {
    return await apiCall('/ghost/rewrite_message', {
        method: 'POST',
        body: {
            character_id: characterId,
            message_id: messageId || null,
            message_index: Number.isInteger(messageIndex) ? messageIndex : null,
            instruction
        }
    });
}

// 删除历史记录
async function deleteHistory(characterId, fromIndex) {
    return await apiCall('/ghost/delete_history', {
        method: 'POST',
        body: {
            character_id: characterId,
            from_index: fromIndex
        }
    });
}

// 获取地点树（已解锁地点）
async function getLocationsTree(characterId) {
    if (!characterId || characterId === 'null' || characterId === 'undefined') {
        return { tree: [] };
    }
    return await apiCall(`/ghost/locations/tree?character_id=${encodeURIComponent(characterId)}`);
}

// 解锁新地点
async function unlockLocation(locationName, status = 'entered') {
    return await apiCall('/locations/discover', {
        method: 'POST',
        body: {
            location_name: locationName,
            status: status
        }
    });
}

// 根据名称获取地点信息
async function getLocationByName(locationName) {
    return await apiCall(`/ghost/locations/by_name/${encodeURIComponent(locationName)}`);
}

// 更新地点状态
async function updateLocationStatus(locationId, status) {
    return await apiCall('/ghost/locations/update', {
        method: 'POST',
        body: {
            location_id: locationId,
            status: status
        }
    });
}

// 结束幽灵会话
async function endGhostSession(characterId = null) {
    const id = characterId;
    if (!id) {
        return { status: 'ok', message: '无活跃会话' };
    }
    return await apiCall('/ghost/end_session', {
        method: 'POST',
        body: {
            character_id: id
        }
    });
}

// 删除角色
async function deleteCharacter(characterId) {
    return await apiCall(`/ghost/delete_character/${encodeURIComponent(characterId)}`, {
        method: 'DELETE'
    });
}

async function listSnapshots(characterId) {
    return await apiCall(`/ghost/snapshots?character_id=${encodeURIComponent(characterId)}`);
}

async function restoreSnapshot(characterId, snapshotId, branch = false, branchName = null) {
    return await apiCall('/ghost/snapshots/restore', {
        method: 'POST',
        body: {
            character_id: characterId,
            snapshot_id: snapshotId,
            branch,
            branch_name: branchName
        }
    });
}

// 复活角色
async function resurrectCharacter(characterId, newScene = null) {
    return await apiCall('/ghost/resurrect_character', {
        method: 'POST',
        body: {
            character_id: characterId,
            new_scene: newScene
        }
    });
}

// 获取角色存档大小
async function getCharacterStorageInfo() {
    return await apiCall('/ghost/storage_info');
}

// 归档旧角色
async function archiveCharacter(characterId) {
    return await apiCall('/ghost/archive_character', {
        method: 'POST',
        body: {
            character_id: characterId
        }
    });
}

// 导出角色数据
async function exportCharacter(characterId) {
    return await apiCall(`/ghost/export_character/${encodeURIComponent(characterId)}`);
}

// 导入角色数据
async function importCharacter(characterData) {
    return await apiCall('/ghost/import_character', {
        method: 'POST',
        body: {
            character_data: characterData
        }
    });
}

// ========== 新增缺失的 API 函数 ==========

// NPC 对话
async function npcDialogue(characterId, chapterIndex, scene, playerName, npcId, npcName, userInput, isGreeting, isContinue, history, sceneNPCs, turnId = null) {
    return await apiCall('/ghost/npc_dialogue', {
        method: 'POST',
        body: {
            character_id: characterId,
            chapter_index: chapterIndex || 1,
            scene: scene,
            player_name: playerName,
            npc_id: npcId,
            npc_name: npcName,
            user_input: userInput,
            is_greeting: isGreeting || false,
            is_continue: isContinue || false,
            history: history || [],
            scene_npcs: sceneNPCs || [],
            turn_id: turnId
        }
    });
}

async function npcDialogueStream(characterId, chapterIndex, scene, playerName, npcId, npcName, userInput, isGreeting, isContinue, history, sceneNPCs, turnId = null, streamOptions = {}) {
    return await streamApiCall('/ghost/npc_dialogue_stream', {
        character_id: characterId,
        chapter_index: chapterIndex || 1,
        scene,
        player_name: playerName,
        npc_id: npcId,
        npc_name: npcName,
        user_input: userInput,
        is_greeting: isGreeting || false,
        is_continue: isContinue || false,
        history: history || [],
        scene_npcs: sceneNPCs || [],
        turn_id: turnId
    }, streamOptions);
}

// 系统助手
async function systemHelper(characterId, query, playerName, playerIdentity, currentScene, resources, reputation, unlockedLocations, currentGoals, activeTasks, history, extraContext) {
    return await apiCall('/ghost/system_helper', {
        method: 'POST',
        body: {
            character_id: characterId,
            query: query,
            player_name: playerName,
            player_identity: playerIdentity,
            current_scene: currentScene,
            resources: resources || {},
            reputation: reputation || {},
            unlocked_locations: unlockedLocations || [],
            current_goals: currentGoals || [],
            active_tasks: activeTasks || [],
            history: history || [],
            extra_context: extraContext || {}
        }
    });
}

// 角色转NPC
async function convertToNPC(characterId) {
    return await apiCall('/ghost/convert_to_npc', {
        method: 'POST',
        body: {
            character_id: characterId
        }
    });
}

// 获取所有地点
async function getAllLocations() {
    return await apiCall('/ghost/locations/all');
}

// 获取所有NPC
async function getAllNPCs() {
    return await apiCall('/ghost/npcs/all');
}

// 添加NPC
async function addNPC(npcData) {
    return await apiCall('/ghost/add_npc', {
        method: 'POST',
        body: { npc: npcData }
    });
}

// 测试AI连接
async function testAI() {
    return await apiCall('/ghost/test_ai');
}

// 获取当前AI模型
async function getModel() {
    return await apiCall('/ghost/get_model');
}

// 获取本地 .env 中的 API Key
async function getApiKey() {
    return await apiCall('/ghost/get_api_key');
}

// 设置当前AI模型
async function setModel(modelName) {
    return await apiCall('/ghost/set_model', {
        method: 'POST',
        body: { model: modelName }
    });
}

// ========== 辅助函数 ==========
function showLoading(message = '加载中...') {
    window.dispatchEvent(new CustomEvent('touhou:loading-start', { detail: { message } }));
}

function hideLoading() {
    window.dispatchEvent(new CustomEvent('touhou:loading-end'));
}

function showTempMessage(message, duration = 3000) {
    window.dispatchEvent(new CustomEvent('touhou:toast', {
        detail: { message, duration, type: 'info' }
    }));
}

function escapeHtml(text) {
    return String(text || '').replace(/[&<>"']/g, character => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    })[character]);
}

// ========== 任务相关 API ==========

async function loadTasks(characterId) {
    if (!characterId) {
        return { active_tasks: [], completed_tasks: [] };
    }
    return await apiCall(`/ghost/tasks?character_id=${encodeURIComponent(characterId)}`);
}

async function loadRelationships(characterId) {
    if (!characterId) {
        return { relationships: {}, history: [] };
    }
    return await apiCall(`/ghost/relationships?character_id=${encodeURIComponent(characterId)}`);
}

async function loadCharacterJournal(characterId) {
    if (!characterId) {
        return { npc_memories: {}, open_events: [], spellcard_history: [] };
    }
    return await apiCall(`/ghost/character_journal?character_id=${encodeURIComponent(characterId)}`);
}

async function loadNPCMemories(characterId, npcName = '') {
    if (!characterId) {
        return npcName ? { npc_name: npcName, memories: [] } : { memories: {} };
    }
    const suffix = npcName ? `&npc_name=${encodeURIComponent(npcName)}` : '';
    return await apiCall(`/ghost/npc_memories?character_id=${encodeURIComponent(characterId)}${suffix}`);
}

async function loadProducerConsoleState(characterId) {
    return await apiCall(`/ghost/producer_console/state?character_id=${encodeURIComponent(characterId)}`);
}

async function producerRestore(characterId) {
    return await apiCall('/ghost/producer_console/restore', {
        method: 'POST',
        body: { character_id: characterId }
    });
}

async function producerTeleport(characterId, scene) {
    return await apiCall('/ghost/producer_console/teleport', {
        method: 'POST',
        body: { character_id: characterId, scene }
    });
}

async function producerSetRelationship(characterId, npcName, attitude, reason) {
    return await apiCall('/ghost/producer_console/set_relationship', {
        method: 'POST',
        body: { character_id: characterId, npc_name: npcName, attitude, reason }
    });
}

async function producerSetPlayerState(characterId, updates) {
    return await apiCall('/ghost/producer_console/set_player_state', {
        method: 'POST',
        body: { character_id: characterId, updates }
    });
}

async function producerSetResource(characterId, resource, value) {
    return await apiCall('/ghost/producer_console/set_resource', {
        method: 'POST',
        body: { character_id: characterId, resource, value }
    });
}

async function producerSetAnomaly(characterId, chapterTimeRemaining, chapterNodeName) {
    return await apiCall('/ghost/producer_console/set_anomaly', {
        method: 'POST',
        body: {
            character_id: characterId,
            chapter_time_remaining: chapterTimeRemaining,
            chapter_node_name: chapterNodeName
        }
    });
}

async function producerCreateEvent(characterId, event) {
    return await apiCall('/ghost/producer_console/create_event', {
        method: 'POST',
        body: { character_id: characterId, event }
    });
}

async function producerUpsertNPCMemory(characterId, npcName, memoryId, summary, tags, importance) {
    return await apiCall('/ghost/producer_console/upsert_npc_memory', {
        method: 'POST',
        body: {
            character_id: characterId,
            npc_name: npcName,
            memory_id: memoryId,
            summary,
            tags,
            importance
        }
    });
}

async function producerDeleteNPCMemory(characterId, npcName, memoryId) {
    return await apiCall('/ghost/producer_console/delete_npc_memory', {
        method: 'POST',
        body: {
            character_id: characterId,
            npc_name: npcName,
            memory_id: memoryId
        }
    });
}

async function producerCompressNPCMemory(characterId, npcName) {
    return await apiCall('/ghost/producer_console/compress_npc_memory', {
        method: 'POST',
        body: {
            character_id: characterId,
            npc_name: npcName
        }
    });
}

async function refreshTasks(characterId) {
    // 刷新任务面板的便捷函数
    return await loadTasks(characterId);
}

// ========== ES6 模块导出 ==========
export {
    apiCall,
    fetchChapters,
    fetchChapter,
    fetchChapterBridge,
    saveProgress,
    loadProgress,
    initNPCPool,
    validateCharacter,
    createCharacter,
    loadCharacter,
    listCharacters,
    environmentInteract,
    environmentInteractStream,
    getTurnStatus,
    waitForTurnResult,
    cancelTurn,
    getNPCsByScene,
    getNPCsByLocation,
    updateCharacterScene,
    appendToConversationHistory,
    rewriteMessage,
    getLocationsTree,
    unlockLocation,
    getLocationByName,
    updateLocationStatus,
    endGhostSession,
    deleteCharacter,
    listSnapshots,
    restoreSnapshot,
    resurrectCharacter,
    deleteHistory,
    getCharacterStorageInfo,
    archiveCharacter,
    exportCharacter,
    importCharacter,
    npcDialogue,
    npcDialogueStream,
    systemHelper,
    convertToNPC,
    getAllLocations,
    getAllNPCs,
    addNPC,
    testAI,
    getModel,
    setModel,
    getApiKey,
    showLoading,
    hideLoading,
    showTempMessage,
    escapeHtml,
    loadTasks,
    loadRelationships,
    loadCharacterJournal,
    loadNPCMemories,
    loadProducerConsoleState,
    producerRestore,
    producerTeleport,
    producerSetRelationship,
    producerSetPlayerState,
    producerSetResource,
    producerSetAnomaly,
    producerCreateEvent,
    producerUpsertNPCMemory,
    producerDeleteNPCMemory,
    producerCompressNPCMemory,
    refreshTasks
};
