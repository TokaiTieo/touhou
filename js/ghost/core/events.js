// js/ghost/core/events.js
// 简单的事件总线，用于模块间通信

class EventBus {
    constructor() {
        this.events = {};
    }
    
    on(event, callback) {
        if (!this.events[event]) {
            this.events[event] = [];
        }
        this.events[event].push(callback);
    }
    
    off(event, callback) {
        if (!this.events[event]) return;
        this.events[event] = this.events[event].filter(cb => cb !== callback);
    }
    
    emit(event, data) {
        if (!this.events[event]) return;
        this.events[event].forEach(callback => callback(data));
    }
}

export const events = new EventBus();

// 预定义事件
export const Events = {
    CHAT_UPDATED: 'chat:updated',
    LOCATION_CHANGED: 'location:changed',
    NPC_LIST_UPDATED: 'npc:updated',
    CHARACTER_INFO_UPDATED: 'character:info_updated',
    TIME_UPDATED: 'time:updated',
    LOADING_START: 'loading:start',
    LOADING_END: 'loading:end',
    TOAST: 'toast',
    TASKS_UPDATED: 'tasks:updated'  // 任务更新事件
};