import { getLocationByName, getNPCsByScene, loadTasks } from '../api.js';
import { state } from '../ghost/core/state.js';
import { events, Events } from '../ghost/core/events.js';
import { applySceneArtwork } from '../ghost/ui/scene-art.js';
import {
    activateGameUi,
    refreshGameUi,
    scrollGameChatToBottom
} from './game-ui.js';
import { showGameScreen } from './app-store.js';

function buildTreeFromLocations(data = {}) {
    const regionMap = new Map();
    for (const region of data.regions || []) {
        regionMap.set(region.id, {
            id: region.id,
            name: region.name,
            icon: region.icon || '界',
            locations: []
        });
    }
    for (const location of data.locations || []) {
        const parentId = location.parent;
        if (!regionMap.has(parentId || 'other')) {
            regionMap.set(parentId || 'other', {
                id: parentId || 'other',
                name: parentId || '其他地点',
                icon: '境',
                locations: []
            });
        }
        regionMap.get(parentId || 'other').locations.push({
            id: location.id,
            name: location.name,
            description: location.description || '',
            icon: location.icon || '・',
            parentId: parentId || null,
            dangerLevel: location.danger_level || '未知',
            dangerNote: location.danger_note || '',
            mainRewards: location.main_rewards || ''
        });
    }
    return Array.from(regionMap.values()).filter(region => region.locations.length > 0);
}

async function fallbackLocationTree() {
    const unlocked = JSON.parse(localStorage.getItem('global_unlocked_locations') || '{}');
    const locations = [];
    for (const name of Object.keys(unlocked)) {
        try {
            const item = await getLocationByName(name);
            locations.push({
                id: item.id || name,
                name,
                description: item.description || '',
                icon: item.icon || '・',
                parent: item.parent || null,
                danger_level: item.danger_level || '未知',
                danger_note: item.danger_note || '',
                main_rewards: item.main_rewards || ''
            });
        } catch {
            locations.push({ id: name, name, parent: null });
        }
    }
    return buildTreeFromLocations({ locations });
}

export function renderChatHistory() {
    refreshGameUi();
    scrollGameChatToBottom();
}

export function renderCharacterInfo() {
    applySceneArtwork(state.currentSession.currentScene);
    window.dispatchEvent(new CustomEvent('touhou:developer-mode', {
        detail: { enabled: state.currentSession.gmMode === true }
    }));
    refreshGameUi();
}

export function updateTimeDisplay() {
    refreshGameUi();
}

export function renderActionSuggestions() {
    refreshGameUi();
}

export async function renderSidebarLocations() {
    try {
        const response = await fetch('/api/ghost/locations/all');
        state.locationTree = response.ok
            ? buildTreeFromLocations(await response.json())
            : await fallbackLocationTree();
    } catch (error) {
        console.warn('加载地点失败，使用已解锁地点:', error);
        state.locationTree = await fallbackLocationTree();
    }
    refreshGameUi();
    return state.locationTree;
}

export async function refreshNPCList() {
    try {
        const result = await getNPCsByScene(state.currentSession.currentScene, state.currentSession.characterId);
        state.currentSceneNPCs = result.npcs || [];
    } catch (error) {
        console.error('加载当前场景 NPC 失败:', error);
        state.currentSceneNPCs = [];
    }
    events.emit(Events.NPC_LIST_UPDATED, { npcs: state.currentSceneNPCs });
    refreshGameUi();
    return state.currentSceneNPCs;
}

export async function refreshTasksPanel() {
    if (!state.currentSession.characterId) return state.tasks;
    try {
        state.updateTasks(await loadTasks(state.currentSession.characterId));
        events.emit(Events.TASKS_UPDATED, { tasks: state.tasks });
    } catch (error) {
        console.error('加载线索失败:', error);
    }
    refreshGameUi();
    return state.tasks;
}

export async function showGameInterface() {
    activateGameUi();
    showGameScreen();
    await Promise.all([renderSidebarLocations(), refreshNPCList(), refreshTasksPanel()]);
    renderCharacterInfo();
    if (state.chatHistory.length > 0) {
        renderChatHistory();
    } else {
        const { callAIAndRespond } = await import('../ghost/modules/chat.js');
        await callAIAndRespond({ action: '', speech: '' });
    }
    const { saveGhostSessionToStorage } = await import('../ghost/core/session.js');
    saveGhostSessionToStorage();
}
