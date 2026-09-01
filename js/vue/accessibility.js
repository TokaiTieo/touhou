import { reactive } from '../vendor/vue.esm-browser.prod.js';

const DEFAULTS = Object.freeze({
    fontScale: 1,
    ttsEnabled: false,
    ttsRate: 1,
    ttsVoice: '',
    highContrast: false,
    reduceMotion: false,
    sendKey: 'enter'
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
        const value = localStorage.getItem(key);
        return value === null ? fallback : clamp(value, minimum, maximum, fallback);
    } catch {
        return fallback;
    }
}

function readString(key, fallback) {
    try {
        return localStorage.getItem(key) || fallback;
    } catch {
        return fallback;
    }
}

export const accessibilityState = reactive({
    fontScale: readNumber('touhou_font_scale', DEFAULTS.fontScale, 0.85, 1.25),
    ttsEnabled: readBoolean('touhou_tts_enabled', DEFAULTS.ttsEnabled),
    ttsRate: readNumber('touhou_tts_rate', DEFAULTS.ttsRate, 0.7, 1.4),
    ttsVoice: readString('touhou_tts_voice', DEFAULTS.ttsVoice),
    highContrast: readBoolean('touhou_high_contrast', DEFAULTS.highContrast),
    reduceMotion: readBoolean('touhou_reduce_motion', DEFAULTS.reduceMotion),
    sendKey: readString('touhou_send_key', DEFAULTS.sendKey) === 'ctrl-enter' ? 'ctrl-enter' : 'enter'
});

export const ttsVoices = reactive({ list: [] });

export function refreshTtsVoices() {
    ttsVoices.list = (window.speechSynthesis?.getVoices?.() || [])
        .filter(voice => /^zh|Chinese|Mandarin/i.test(`${voice.lang} ${voice.name}`));
    return ttsVoices.list;
}

export function applyAccessibilitySettings() {
    document.documentElement.style.setProperty('--touhou-font-scale', String(accessibilityState.fontScale));
    document.documentElement.classList.toggle('touhou-high-contrast', accessibilityState.highContrast);
    document.documentElement.classList.toggle('touhou-reduce-motion', accessibilityState.reduceMotion);
}

export function updateAccessibilitySettings(settings = {}) {
    if (settings.fontScale !== undefined) {
        accessibilityState.fontScale = clamp(settings.fontScale, 0.85, 1.25, DEFAULTS.fontScale);
    }
    if (settings.ttsEnabled !== undefined) accessibilityState.ttsEnabled = Boolean(settings.ttsEnabled);
    if (settings.ttsRate !== undefined) {
        accessibilityState.ttsRate = clamp(settings.ttsRate, 0.7, 1.4, DEFAULTS.ttsRate);
    }
    if (settings.ttsVoice !== undefined) accessibilityState.ttsVoice = String(settings.ttsVoice || '');
    if (settings.highContrast !== undefined) accessibilityState.highContrast = Boolean(settings.highContrast);
    if (settings.reduceMotion !== undefined) accessibilityState.reduceMotion = Boolean(settings.reduceMotion);
    if (settings.sendKey !== undefined) {
        accessibilityState.sendKey = settings.sendKey === 'ctrl-enter' ? 'ctrl-enter' : 'enter';
    }
    try {
        localStorage.setItem('touhou_font_scale', String(accessibilityState.fontScale));
        localStorage.setItem('touhou_tts_enabled', String(accessibilityState.ttsEnabled));
        localStorage.setItem('touhou_tts_rate', String(accessibilityState.ttsRate));
        localStorage.setItem('touhou_tts_voice', accessibilityState.ttsVoice);
        localStorage.setItem('touhou_high_contrast', String(accessibilityState.highContrast));
        localStorage.setItem('touhou_reduce_motion', String(accessibilityState.reduceMotion));
        localStorage.setItem('touhou_send_key', accessibilityState.sendKey);
    } catch {
        // Active settings remain effective when browser storage is unavailable.
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
    const voice = refreshTtsVoices().find(item => item.voiceURI === accessibilityState.ttsVoice);
    if (voice) utterance.voice = voice;
    window.speechSynthesis.speak(utterance);
    return true;
}

export function resetAccessibilitySettings() {
    updateAccessibilitySettings(DEFAULTS);
}

if (window.speechSynthesis) {
    refreshTtsVoices();
    window.speechSynthesis.addEventListener?.('voiceschanged', refreshTtsVoices);
}
