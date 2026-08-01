// js/ghost/index.js
// 幽灵模式主入口

import { state } from './core/state.js';
import { events } from './core/events.js';
import { showWorldSelection } from './modules/world.js';
import { loadAndEnterGhostMode, exitGhostMode, saveGhostSessionToStorage } from './core/session.js';
import { registerGlobalUIEvents } from './ui/components.js';

// 注册全局UI事件
registerGlobalUIEvents();

// 导出模块
export { state, events, showWorldSelection, loadAndEnterGhostMode, exitGhostMode, saveGhostSessionToStorage };
