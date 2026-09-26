import { apiCall, getTurnStatus, cancelTurn } from '../../api.js';
import { gameUi } from '../../vue/game-ui.js';

const key = owner => `touhou:pending-turn:v1:${owner}`;

export function readPendingTurn(owner) {
    try {
        const entry = JSON.parse(localStorage.getItem(key(owner)) || 'null');
        return entry?.body?.character_id === owner && typeof entry.body.turn_id === 'string'
            && ['environment_interact', 'npc_dialogue'].includes(entry.kind) ? entry : null;
    } catch { return null; }
}

export function rememberTurn(kind, body) {
    const previous = readPendingTurn(body.character_id);
    if (previous && previous.body.turn_id !== body.turn_id) throw new Error('上一回合尚未确认，请先恢复或确认停止');
    localStorage.setItem(key(body.character_id), JSON.stringify({ kind, body, createdAt: Date.now() }));
}

export function finishTurn(owner, turnId) {
    if (readPendingTurn(owner)?.body.turn_id === turnId) localStorage.removeItem(key(owner));
    if (gameUi.recovery?.body?.turn_id === turnId && gameUi.recovery.body.character_id === owner) gameUi.recovery = null;
}

export async function checkPendingTurn(owner) {
    const entry = readPendingTurn(owner);
    gameUi.recovery = entry ? { ...entry, phase: 'checking' } : null;
    if (!entry) return;
    try {
        const status = await getTurnStatus(owner, entry.body.turn_id);
        if (['committed', 'cancelled'].includes(status.state)) {
            finishTurn(owner, entry.body.turn_id);
        } else if (gameUi.recovery?.body?.turn_id === entry.body.turn_id) {
            gameUi.recovery.phase = status.state;
        }
    } catch (error) {
        if (gameUi.recovery?.body?.turn_id === entry.body.turn_id) gameUi.recovery.error = error.message;
    }
}

export async function resolvePendingTurn(cancel = false) {
    const entry = gameUi.recovery;
    if (!entry || entry.busy) return;
    entry.busy = true;
    entry.error = '';
    try {
        const status = cancel ? await cancelTurn(entry.body.character_id, entry.body.turn_id)
            : await apiCall(`/ghost/${entry.kind}`, { method: 'POST', body: entry.body, timeoutMs: 180000 });
        if (cancel && !['committed', 'cancelled'].includes(status.state)) {
            entry.error = '尚未确认停止；回合可能正在结算，请稍后查询。';
            return;
        }
        finishTurn(entry.body.character_id, entry.body.turn_id);
        const { loadAndEnterGhostMode } = await import('./session.js');
        await loadAndEnterGhostMode(entry.body.character_id);
    } catch (error) { entry.error = error.message; }
    finally { entry.busy = false; }
}

export async function queryPendingTurn() {
    const owner = gameUi.recovery?.body?.character_id;
    if (!owner) return;
    await checkPendingTurn(owner);
    if (!readPendingTurn(owner)) {
        const { loadAndEnterGhostMode } = await import('./session.js');
        await loadAndEnterGhostMode(owner);
    }
}
