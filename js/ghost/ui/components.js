// js/ghost/ui/components.js
import { events, Events } from '../core/events.js';

export function showLoading(message = '加载中...') {
    window.dispatchEvent(new CustomEvent('touhou:loading-start', {
        detail: { message }
    }));
}

export function hideLoading() {
    window.dispatchEvent(new CustomEvent('touhou:loading-end'));
}

export function showToast(message, duration = 3000, type = 'info') {
    window.dispatchEvent(new CustomEvent('touhou:toast', {
        detail: { message, duration, type }
    }));
}

export function showWorldInitDialog() {
    showLoading('正在初始化幻想乡记录...');
}

export function hideWorldInitDialog() {
    hideLoading();
}

// 注册全局事件监听
export function registerGlobalUIEvents() {
    events.on(Events.LOADING_START, showLoading);
    events.on(Events.LOADING_END, hideLoading);
    events.on(Events.TOAST, ({ message, type, duration }) => showToast(message, duration, type));
}
