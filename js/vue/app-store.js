import { reactive } from '../vendor/vue.esm-browser.prod.js';

export const appUi = reactive({
    view: 'boot',
    characters: [],
    world: {
        id: 'world_touhou',
        name: '幻想乡 - 东方Project'
    },
    modal: null,
    modalPayload: null,
    sceneArtwork: '/static/static/hakurei-shrine-hero-v1.png'
});

export function showCharacterScreen(characters = [], world = null) {
    appUi.characters = Array.isArray(characters) ? characters : [];
    if (world) appUi.world = { ...appUi.world, ...world };
    appUi.view = 'characters';
}

export function showGameScreen() {
    appUi.view = 'game';
}

export function openAppModal(type, payload = null) {
    appUi.modal = type;
    appUi.modalPayload = payload;
}

export function closeAppModal() {
    appUi.modal = null;
    appUi.modalPayload = null;
}
