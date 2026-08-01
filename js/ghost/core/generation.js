let activeController = null;
let activeTurn = null;

export function beginGeneration(turn = null) {
    activeController?.abort();
    activeController = new AbortController();
    activeTurn = turn;
    return activeController;
}

export function cancelActiveGeneration() {
    if (!activeController || activeController.signal.aborted) return false;
    if (activeTurn?.characterId && activeTurn?.turnId) {
        import('../../api.js').then(({ cancelTurn }) => (
            cancelTurn(activeTurn.characterId, activeTurn.turnId)
        )).catch(error => console.warn('取消回合失败:', error));
    }
    activeController.abort();
    return true;
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
