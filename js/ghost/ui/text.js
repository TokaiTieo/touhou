import { state } from '../core/state.js';

export function softenPublicText(value) {
    if (value === undefined || value === null) return '';
    return String(value)
        .replace(/成人向关系/g, '亲密关系')
        .replace(/成人关系/g, '亲密关系')
        .replace(/成人向内容/g, '亲密内容')
        .replace(/成人内容/g, '亲密内容')
        .replace(/成人倾向/g, '恋爱倾向')
        .replace(/成人向/g, '亲密向')
        .replace(/成人暧昧/g, '暧昧邀约')
        .replace(/成人\/恋爱/g, '恋爱')
        .replace(/恋爱\/成人/g, '恋爱')
        .replace(/成人/g, '亲密');
}

export function getTaskDisplayName(taskId, update = {}) {
    if (update.task_name || update.name || update.title) {
        return update.task_name || update.name || update.title;
    }
    if (!taskId) return '线索';
    const pools = [
        ...(state.tasks?.active || []),
        ...(state.tasks?.completed || []),
        ...(state.currentSession?.activeTasks || []),
    ];
    const task = pools.find(item => item?.id === taskId);
    return task?.name || taskId;
}

export function renderMarkdownLite(value) {
    const escaped = escapeHtml(softenPublicText(value || ''));
    return escaped
        .replace(/^### (.*)$/gm, '<h3>$1</h3>')
        .replace(/^## (.*)$/gm, '<h2>$1</h2>')
        .replace(/^# (.*)$/gm, '<h1>$1</h1>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/^- (.*)$/gm, '<div class="md-list-item">• $1</div>')
        .replace(/\n/g, '<br>');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text ?? '');
    return div.innerHTML;
}
