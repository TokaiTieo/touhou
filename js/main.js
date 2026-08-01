// Vue application entry with a compatibility bridge for the existing game modules.

import { createApp } from './vendor/vue.esm-browser.prod.js';
import { TouhouApp } from './vue/app.js';

window.TOUHOU_APP_VERSION = 'dev';
window.__TOUHOU_VUE_SHELL__ = true;
window.TOUHOU_SESSION_TOKEN = document.querySelector('meta[name="touhou-session-token"]')?.content || '';

// Old versions stored the complete API Key in browser storage. Remove that
// plaintext copy before any legacy module can read it.
try {
    localStorage.removeItem('touhou_api_key');
} catch (error) {
    console.warn('无法清理旧版 API Key 缓存:', error);
}

const nativeFetch = window.fetch.bind(window);
window.fetch = (input, init = {}) => {
    const rawUrl = typeof input === 'string' ? input : input?.url;
    const url = new URL(rawUrl || '', window.location.href);
    if (url.origin !== window.location.origin || !url.pathname.startsWith('/api')) {
        return nativeFetch(input, init);
    }
    const headers = new Headers(init.headers || (typeof input !== 'string' ? input?.headers : undefined));
    if (window.TOUHOU_SESSION_TOKEN) {
        headers.set('X-Touhou-Token', window.TOUHOU_SESSION_TOKEN);
    }
    return nativeFetch(input, { ...init, headers });
};

try {
    const versionResponse = await fetch('/api/version');
    if (versionResponse.ok) {
        const versionData = await versionResponse.json();
        window.TOUHOU_APP_VERSION = versionData.display_version || `v${versionData.version}`;
        window.TOUHOU_VERSION_MANIFEST = versionData;
    }
} catch (error) {
    console.warn('版本信息读取失败，使用开发标识。', error);
}

document.title = 'TouHou · 东方异变录';
let favicon = document.querySelector('link[rel="icon"]');
if (!favicon) {
    favicon = document.createElement('link');
    favicon.rel = 'icon';
    favicon.type = 'image/svg+xml';
    document.head.appendChild(favicon);
}
favicon.href = '/static/static/touhou-favicon.svg';

createApp(TouhouApp).mount('#app');

async function startGame() {
    try {
        const module = await import('./ghost/index.js');
        console.log('Vue shell and game modules loaded');

        // 检查是否有保存的幽灵模式会话
        const ghostModeActive = sessionStorage.getItem('ghost_mode_active');
        const characterId = sessionStorage.getItem('ghost_character_id');
        const currentScene = sessionStorage.getItem('ghost_current_scene');
        
        if (ghostModeActive === 'true' && characterId) {
            console.log('检测到未完成的幽灵模式会话，正在恢复...', characterId);
            if (module.loadAndEnterGhostMode) {
                await module.loadAndEnterGhostMode(characterId, currentScene);
                window.dispatchEvent(new CustomEvent('touhou:ready'));
                return;
            }
        }
        
        // 没有会话或恢复失败，显示世界选择
        if (typeof module.showWorldSelection === 'function') {
            await module.showWorldSelection();
        } else {
            throw new Error('游戏入口未正确导出');
        }
        window.dispatchEvent(new CustomEvent('touhou:ready'));
    } catch (error) {
        console.error('加载游戏模块失败:', error);
        window.dispatchEvent(new CustomEvent('touhou:startup-error', {
            detail: { message: error?.message || String(error) }
        }));
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startGame, { once: true });
} else {
    startGame();
}
