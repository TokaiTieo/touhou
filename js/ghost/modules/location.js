// js/ghost/modules/location.js
import { state } from '../core/state.js';
import { CURRENT_CHAPTER_INDEX } from '../core/constants.js';
import { events, Events } from '../core/events.js';
import { showLoading, hideLoading, showToast } from '../ui/components.js';
import { renderCharacterInfo, renderSidebarLocations, refreshNPCList, updateTimeDisplay } from '../../vue/game-controller.js';
import { updateCharacterScene, getLocationByName } from '../../api.js';
import { refreshCharacterTime } from '../core/session.js';
import { callAIAndRespond } from './chat.js';

// 构建地点树
export async function buildLocationTree() {
    try {
        const response = await fetch('/api/ghost/locations/all');
        if (response.ok) {
            const data = await response.json();
            return buildTreeFromLocations(data);
        }
    } catch (err) {
        console.warn('获取地点失败:', err);
    }
    
    // 降级：从全局解锁地点获取
    const globalUnlocked = getGlobalUnlockedLocations();
    const globalLocationNames = Object.keys(globalUnlocked);
    
    if (globalLocationNames.length === 0) return [];
    
    const locationsWithParent = [];
    for (const locName of globalLocationNames) {
        try {
            const locInfo = await getLocationByName(locName);
            locationsWithParent.push({
                name: locName,
                id: locInfo.id || locName,
                description: locInfo.description || '',
                icon: locInfo.icon || '📍',
                parentId: locInfo.parent || null
            });
        } catch (err) {
            locationsWithParent.push({
                name: locName,
                id: locName,
                description: '',
                icon: '📍',
                parentId: null
            });
        }
    }
    
    const parentIds = [...new Set(locationsWithParent.map(loc => loc.parentId).filter(id => id))];
    const regionMap = new Map();
    
    for (const parentId of parentIds) {
        try {
            const regionInfo = await getLocationByName(parentId);
            regionMap.set(parentId, {
                id: regionInfo.id || parentId,
                name: regionInfo.name || parentId,
                icon: regionInfo.icon || '📁',
                locations: []
            });
        } catch (err) {
            regionMap.set(parentId, { id: parentId, name: parentId, icon: '📁', locations: [] });
        }
    }
    
    for (const loc of locationsWithParent) {
        if (loc.parentId && regionMap.has(loc.parentId)) {
            regionMap.get(loc.parentId).locations.push(loc);
        }
    }
    
    const orphanLocations = locationsWithParent.filter(loc => !loc.parentId);
    if (orphanLocations.length > 0) {
        regionMap.set('other', { id: 'other', name: '其他地点', icon: '📍', locations: orphanLocations });
    }
    
    return Array.from(regionMap.values());
}

// 从地点数据构建树
function buildTreeFromLocations(locationsData) {
    const regions = locationsData.regions || [];
    const locations = locationsData.locations || [];
    
    const regionMap = new Map();
    for (const region of regions) {
        regionMap.set(region.id, {
            id: region.id,
            name: region.name,
            icon: region.icon || '📁',
            locations: []
        });
    }
    
    for (const location of locations) {
        const parentId = location.parent;
        if (parentId && regionMap.has(parentId)) {
            regionMap.get(parentId).locations.push({
                id: location.id,
                name: location.name,
                description: location.description || '',
                icon: location.icon || '📍',
                parentId: parentId,
                dangerLevel: location.danger_level || '未知',
                dangerNote: location.danger_note || '',
                mainRewards: location.main_rewards || ''
            });
        } else {
            if (!regionMap.has('other')) {
                regionMap.set('other', { id: 'other', name: '其他地点', icon: '📍', locations: [] });
            }
            regionMap.get('other').locations.push({
                id: location.id,
                name: location.name,
                description: location.description || '',
                icon: location.icon || '📍',
                parentId: null,
                dangerLevel: location.danger_level || '未知',
                dangerNote: location.danger_note || '',
                mainRewards: location.main_rewards || ''
            });
        }
    }
    
    return Array.from(regionMap.values()).filter(region => region.locations.length > 0);
}

// 切换场景
export async function switchScene(newScene) {
    showLoading(`正在前往 ${newScene}...`);
    
    try {
        await updateCharacterScene(state.currentSession.characterId, newScene, CURRENT_CHAPTER_INDEX);
        state.currentSession.currentScene = newScene;
        
        const systemMsg = {
            role: 'system',
            speaker: '系统',
            content: `📍 场景已切换至：${newScene}`,
            timestamp: Date.now(),
            isDead: false
        };
        state.addChatMessage(systemMsg);
        
        const { appendToConversationHistory } = await import('../../api.js');
        await appendToConversationHistory(
            state.currentSession.characterId,
            '系统',
            `📍 场景已切换至：${newScene}`,
            newScene,
            false
        );
        
        renderCharacterInfo();
        await renderSidebarLocations();
        await refreshNPCList();
        
        hideLoading();
        showToast(`已前往 ${newScene}`, 1500);
        
        // 自动触发场景描述
        await callAIAndRespond({ action: '', speech: '' });
        
    } catch (err) {
        hideLoading();
        console.error('切换场景失败:', err);
        showToast('切换场景失败，请重试', 2000, 'error');
    }
}

// 获取全局解锁地点
function getGlobalUnlockedLocations() {
    return JSON.parse(localStorage.getItem('global_unlocked_locations') || '{}');
}
