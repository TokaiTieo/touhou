import { nextTick, reactive } from '../vendor/vue.esm-browser.prod.js';

export const gameUi = reactive({
    active: false,
    inputDisabled: false,
    allowCancel: false,
    actionDraft: '',
    speechDraft: '',
    sidebarTab: 'encounter',
    completedOpen: false,
    mobileSidebarOpen: false,
    focusNonce: 0,
    scrollNonce: 0
});

export function activateGameUi() {
    gameUi.active = true;
}

export function deactivateGameUi() {
    gameUi.active = false;
    gameUi.inputDisabled = false;
    gameUi.allowCancel = false;
    gameUi.actionDraft = '';
    gameUi.speechDraft = '';
    gameUi.mobileSidebarOpen = false;
}

export function refreshGameUi() {
    // Reactive state updates render automatically. This remains a narrow
    // compatibility hook for older game logic while that logic is extracted.
}

export function setComposerDisabled(disabled, allowCancel = false) {
    gameUi.inputDisabled = disabled;
    gameUi.allowCancel = allowCancel;
}

export function fillComposer(action = '', speech = '') {
    gameUi.actionDraft = action;
    gameUi.speechDraft = speech;
    gameUi.focusNonce += 1;
}

export function clearComposer() {
    gameUi.actionDraft = '';
    gameUi.speechDraft = '';
}

export function scrollGameChatToBottom() {
    nextTick(() => {
        gameUi.scrollNonce += 1;
    });
}
