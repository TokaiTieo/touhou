import { events, Events } from '../core/events.js';
import { openSettingsDialog } from '../../vue/settings-dialog.js';
import { showCharacterScreen } from '../../vue/app-store.js';
import { deactivateGameUi } from '../../vue/game-ui.js';


const TOUHOU_WORLD = { id: 'world_touhou', name: '幻想乡 - 东方Project' };


export async function showWorldSelection() {
    deactivateGameUi();
    window.dispatchEvent(new CustomEvent('touhou:developer-mode', { detail: { enabled: false } }));
    syncModelSetting();
    checkAndPromptApiKey();
    await selectWorld('world_touhou');
}


export async function selectWorld(worldId = 'world_touhou') {
    if (worldId !== 'world_touhou') {
        events.emit(Events.TOAST, { message: '正式版仅包含幻想乡世界', type: 'error' });
        return;
    }
    try {
        await fetch('/api/world/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ world_id: 'world_touhou' })
        });
        await showGhostModeMenu();
    } catch (err) {
        events.emit(Events.TOAST, { message: `进入幻想乡失败：${err.message}`, type: 'error' });
    }
}


export async function checkAndInitWorld() {
    try {
        const status = await (await fetch('/api/world/status')).json();
        if (status.initialized) return true;
        const response = await fetch('/api/world/init', { method: 'POST' });
        return response.ok;
    } catch (err) {
        console.error('幻想乡数据初始化失败:', err);
        events.emit(Events.TOAST, { message: '幻想乡数据初始化失败，请重新启动游戏', type: 'error' });
        return false;
    }
}


export async function showGhostModeMenu() {
    deactivateGameUi();
    if (!await checkAndInitWorld()) return;

    let existingCharacters = [];
    try {
        const { listCharacters } = await import('../../api.js');
        existingCharacters = (await listCharacters('world_touhou')).characters || [];
    } catch (err) {
        console.error('获取角色列表失败:', err);
    }

    showCharacterScreen(existingCharacters, TOUHOU_WORLD);
}


async function syncModelSetting() {
    const model = localStorage.getItem('touhou_model');
    if (!model) return;
    try {
        await fetch('/api/ghost/set_model', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model })
        });
    } catch (err) {
        console.warn('同步模型设置失败:', err);
    }
}


async function checkAndPromptApiKey() {
    try {
        const { getApiKey } = await import('../../api.js');
        const data = await getApiKey();
        if (!data?.has_key) setTimeout(openSettingsDialog, 800);
    } catch (err) {
        console.warn('检测 API Key 失败:', err);
    }
}
