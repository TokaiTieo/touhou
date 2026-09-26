let activeController = null;
let activeTurn = null;

export function beginGeneration(turn = null) {
    activeController?.abort();
    activeController = new AbortController();
    activeTurn = turn;
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
    }
}

export function hasActiveGeneration() {
    return Boolean(activeController && !activeController.signal.aborted);
}
