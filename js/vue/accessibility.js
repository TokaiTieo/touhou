import { reactive } from '../vendor/vue.esm-browser.prod.js';

const DEFAULTS = Object.freeze({
    fontScale: 1,
    ttsEnabled: false,
    ttsRate: 1
});

function clamp(value, minimum, maximum, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.min(maximum, Math.max(minimum, number)) : fallback;
}

function readBoolean(key, fallback) {
    try {
        const value = localStorage.getItem(key);
        return value === null ? fallback : value === 'true';
    } catch {
        return fallback;
    }
}

function readNumber(key, fallback, minimum, maximum) {
    try {
        return clamp(localStorage.getItem(key), minimum, maximum, fallback);
    } catch {
        return fallback;
    }
}

export const accessibilityState = reactive({
    fontScale: readNumber('touhou_font_scale', DEFAULTS.fontScale, 0.85, 1.25),
    ttsEnabled: readBoolean('touhou_tts_enabled', DEFAULTS.ttsEnabled),
    ttsRate: readNumber('touhou_tts_rate', DEFAULTS.ttsRate, 0.7, 1.4)
});

export function applyAccessibilitySettings() {
    document.documentElement.style.setProperty('--touhou-font-scale', String(accessibilityState.fontScale));
}

export function updateAccessibilitySettings(settings = {}) {
    if (settings.fontScale !== undefined) {
        accessibilityState.fontScale = clamp(settings.fontScale, 0.85, 1.25, DEFAULTS.fontScale);
    }
    if (settings.ttsEnabled !== undefined) accessibilityState.ttsEnabled = Boolean(settings.ttsEnabled);
    if (settings.ttsRate !== undefined) {
        accessibilityState.ttsRate = clamp(settings.ttsRate, 0.7, 1.4, DEFAULTS.ttsRate);
    }
    try {
        localStorage.setItem('touhou_font_scale', String(accessibilityState.fontScale));
        localStorage.setItem('touhou_tts_enabled', String(accessibilityState.ttsEnabled));
        localStorage.setItem('touhou_tts_rate', String(accessibilityState.ttsRate));
    } catch {
        // The active settings still apply when browser storage is unavailable.
    }
    if (!accessibilityState.ttsEnabled) window.speechSynthesis?.cancel();
    applyAccessibilitySettings();
}

function plainSpeechText(value) {
    const source = String(value || '')
        .replace(/```[\s\S]*?```/g, ' ')
        .replace(/`([^`]+)`/g, '$1')
        .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
        .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
        .replace(/<[^>]*>/g, ' ');
    const decoder = document.createElement('textarea');
    decoder.innerHTML = source;
    return decoder.value.replace(/\s+/g, ' ').trim();
}

export function speakText(value) {
    if (!accessibilityState.ttsEnabled || !window.speechSynthesis || !window.SpeechSynthesisUtterance) {
        return false;
    }
    const text = plainSpeechText(value);
    if (!text) return false;
    window.speechSynthesis.cancel();
    const utterance = new window.SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-CN';
    utterance.rate = accessibilityState.ttsRate;
    window.speechSynthesis.speak(utterance);
    return true;
}

export function resetAccessibilitySettings() {
    updateAccessibilitySettings(DEFAULTS);
}
