import { state } from './state.js';

let activeController = null;
let activeTurn = null;
const phaseNames = { preparing: '整理见闻', npc_deciding: '等待人物回应', candidate_settlement: '核对行动结果',
    host_narrating: '整理场景叙事', settling: '保存本回合', checkpoint_cleanup: '完成收尾' };
window.addEventListener('touhou:turn-phase', ({ detail }) => {
    if (detail.character_id === activeTurn?.characterId && detail.turn_id === activeTurn?.turnId) {
        state.turnPhase = phaseNames[detail.state] || '书写中';
    }
});

export function beginGeneration(turn = null) {
    activeController?.abort();
    activeController = new AbortController();
    activeTurn = turn;
    state.turnPhase = '整理见闻';
    return activeController;
}

export async function cancelActiveGeneration() {
    if (!activeController || activeController.signal.aborted) return false;
    if (activeTurn?.characterId && activeTurn?.turnId) {
        const controller = activeController;
        const turn = activeTurn;
        const { cancelTurn } = await import('../../api.js');
        const result = await cancelTurn(turn.characterId, turn.turnId);
        if (!result.cancelled || result.state !== 'cancelled') return false;
        const { finishTurn } = await import('./pending-turn.js');
        finishTurn(turn.characterId, turn.turnId);
        controller.abort();
        return true;
    }
    return false;
}

export function endGeneration(controller) {
    if (activeController === controller) {
        activeController = null;
        activeTurn = null;
        state.turnPhase = '';
    }
}

export function hasActiveGeneration() {
    return Boolean(activeController && !activeController.signal.aborted);
}
