import { defineComponent, onMounted, ref } from '../vendor/vue.esm-browser.prod.js';
import { state as gameState } from '../ghost/core/state.js';
import {
    accessibilityState,
    refreshTtsVoices,
    resetAccessibilitySettings,
    ttsVoices,
    updateAccessibilitySettings
} from './accessibility.js';
import { openAppModal } from './app-store.js';


export const SettingsDialog = defineComponent({
    name: 'SettingsDialog',
    props: { onClose: { type: Function, required: true } },
    setup(props) {
        const apiKey = ref('');
        const maskedKey = ref('');
        const keySource = ref('none');
        const hasKey = ref(false);
        const model = ref(localStorage.getItem('touhou_model') || 'deepseek-v4-flash');
        const models = ref(['deepseek-v4-flash', 'deepseek-v4-pro']);
        const providerBaseUrl = ref('https://api.deepseek.com');
        const providerName = ref('DeepSeek');
        const status = ref('');
        const statusType = ref('');
        const busy = ref(false);
        const usage = ref(null);
        const diagnosticsMessage = ref('');
        const recovery = ref(null);
        const saveHealth = ref(null);
        const fontScale = ref(accessibilityState.fontScale);
        const ttsEnabled = ref(accessibilityState.ttsEnabled);
        const ttsRate = ref(accessibilityState.ttsRate);
        const ttsVoice = ref(accessibilityState.ttsVoice);
        const highContrast = ref(accessibilityState.highContrast);
        const reduceMotion = ref(accessibilityState.reduceMotion);
        const sendKey = ref(accessibilityState.sendKey);
        const voices = ttsVoices;
        const ttsSupported = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;

        onMounted(async () => {
            refreshTtsVoices();
            try {
                const response = await fetch('/api/ghost/get_api_key');
                const data = await response.json();
                hasKey.value = Boolean(data.has_key);
                maskedKey.value = data.masked_key || '';
                keySource.value = data.key_source || 'none';
                if (data.model) model.value = data.model;
                const providerResponse = await fetch('/api/ghost/provider');
                const providerData = await providerResponse.json();
                providerBaseUrl.value = providerData.base_url || providerBaseUrl.value;
                providerName.value = providerData.name || providerName.value;
                models.value = providerData.models || models.value;
                if (providerData.current_model) model.value = providerData.current_model;
                const characterId = gameState.currentSession.characterId || '';
                const diagnosticsResponse = await fetch(`/api/ghost/diagnostics?character_id=${encodeURIComponent(characterId)}`);
                if (diagnosticsResponse.ok) {
                    const diagnostics = await diagnosticsResponse.json();
                    usage.value = diagnostics.usage || null;
                    diagnosticsMessage.value = diagnostics.message || '';
                }
                const recoveryResponse = await fetch('/api/ghost/turn_recovery');
                if (recoveryResponse.ok) recovery.value = await recoveryResponse.json();
                if (characterId) await loadSaveHealth(characterId);
            } catch (error) {
                status.value = '读取配置失败，请重新打开设置。';
                statusType.value = 'error';
            }
        });

        async function saveAndTest() {
            if (!apiKey.value.trim() && !hasKey.value) {
                status.value = '请输入 API Key';
                statusType.value = 'error';
                return;
            }
            busy.value = true;
            statusType.value = '';
            try {
                if (apiKey.value.trim()) {
                    status.value = '正在加密保存...';
                    const saveResponse = await fetch('/api/ghost/update_api_key', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ api_key: apiKey.value.trim() })
                    });
                    if (!saveResponse.ok) throw new Error('保存 API Key 失败');
                    hasKey.value = true;
                    keySource.value = 'encrypted_store';
                }
                const configuredModels = [...new Set([...models.value, model.value.trim()].filter(Boolean))];
                const providerResponse = await fetch('/api/ghost/provider', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        base_url: providerBaseUrl.value.trim(),
                        models: configuredModels,
                        model: model.value.trim()
                    })
                });
                const providerData = await providerResponse.json();
                if (!providerResponse.ok) throw new Error(providerData.detail || 'AI 服务配置失败');
                models.value = providerData.models || configuredModels;
                providerName.value = providerData.name || '兼容服务';
                localStorage.setItem('touhou_model', model.value);
                if (apiKey.value.trim()) {
                    status.value = '正在测试连接...';
                    const testResponse = await fetch('/api/ghost/test_ai_with_key', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ api_key: apiKey.value.trim(), model: model.value, base_url: providerBaseUrl.value.trim(), models: models.value })
                    });
                    const testData = await testResponse.json();
                    if (!testData.success) throw new Error(testData.message || '连接测试失败');
                }
                apiKey.value = '';
                status.value = `配置有效，当前模型：${model.value}`;
                statusType.value = 'ok';
                window.dispatchEvent(new CustomEvent('touhou:toast', {
                    detail: { message: 'AI 配置已更新', type: 'success' }
                }));
                setTimeout(props.onClose, 900);
            } catch (error) {
                status.value = error.message || '配置失败';
                statusType.value = 'error';
            } finally {
                busy.value = false;
            }
        }

        async function loadSaveHealth(characterId = gameState.currentSession.characterId) {
            if (!characterId) return;
            const response = await fetch(`/api/ghost/save_health?character_id=${encodeURIComponent(characterId)}`);
            if (response.ok) saveHealth.value = await response.json();
        }

        async function repairSave() {
            const characterId = gameState.currentSession.characterId;
            if (!characterId || !window.confirm('修复前会建立快照；损坏存档只会从已有有效快照恢复。继续吗？')) return;
            busy.value = true;
            try {
                const response = await fetch('/api/ghost/save_health/repair', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ character_id: characterId })
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.detail || '存档修复失败');
                saveHealth.value = result.health || saveHealth.value;
                status.value = result.status === 'restored_snapshot' ? '已从最近有效快照恢复' : '存档检查与自动升级已完成';
                statusType.value = 'ok';
            } catch (error) {
                status.value = typeof error.message === 'string' ? error.message : '存档修复失败';
                statusType.value = 'error';
            } finally {
                busy.value = false;
            }
        }

        async function clearRecovery() {
            if (!window.confirm('清除后，意外中断且尚未提交的回合将无法恢复。角色存档不会被删除。')) return;
            busy.value = true;
            try {
                const response = await fetch('/api/ghost/clear_turn_recovery', { method: 'POST' });
                if (!response.ok) throw new Error('清除恢复数据失败');
                const result = await response.json();
                recovery.value = { active_threads: 0, database_bytes: recovery.value?.database_bytes || 0 };
                status.value = result.message || '本地恢复数据已清除';
                statusType.value = 'ok';
            } catch (error) {
                status.value = error.message || '清除恢复数据失败';
                statusType.value = 'error';
            } finally {
                busy.value = false;
            }
        }

        function formatNumber(value) {
            return Number(value || 0).toLocaleString('zh-CN');
        }

        function costText() {
            if (usage.value?.estimated_cost == null) return '未配置本地计费单价';
            return `${usage.value.estimated_cost} ${usage.value.cost_currency || ''}`.trim();
        }

        function keySourceText() {
            return {
                encrypted_store: '本机加密存储',
                env_file: '本地兼容配置',
                system_environment: '系统环境变量'
            }[keySource.value] || '本地配置';
        }

        function saveAccessibility() {
            updateAccessibilitySettings({
                fontScale: fontScale.value,
                ttsEnabled: ttsEnabled.value,
                ttsRate: ttsRate.value,
                ttsVoice: ttsVoice.value,
                highContrast: highContrast.value,
                reduceMotion: reduceMotion.value,
                sendKey: sendKey.value
            });
        }

        function resetAccessibility() {
            resetAccessibilitySettings();
            fontScale.value = accessibilityState.fontScale;
            ttsEnabled.value = accessibilityState.ttsEnabled;
            ttsRate.value = accessibilityState.ttsRate;
            ttsVoice.value = accessibilityState.ttsVoice;
            highContrast.value = accessibilityState.highContrast;
            reduceMotion.value = accessibilityState.reduceMotion;
            sendKey.value = accessibilityState.sendKey;
        }

        return {
            apiKey, busy, clearRecovery, costText, diagnosticsMessage, formatNumber, hasKey,
            fontScale, highContrast, keySourceText, maskedKey, model, models, providerBaseUrl, providerName,
            recovery, reduceMotion, repairSave, resetAccessibility, saveAccessibility, saveAndTest, saveHealth,
            sendKey, status, statusType, ttsEnabled, ttsRate, ttsSupported, ttsVoice, usage, voices
        };
    },
    template: `
        <div class="vue-modal-backdrop" @click.self="onClose">
            <section class="api-key-dialog vue-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settingsTitle">
                <header class="dialog-header">
                    <div><small>本地安全配置</small><strong id="settingsTitle">AI 服务设置</strong></div>
                    <button class="icon-button" type="button" title="关闭" aria-label="关闭" @click="onClose">×</button>
                </header>
                <div class="dialog-content">
                    <div v-if="hasKey" class="api-key-status ok">当前已配置：{{ maskedKey || '已安全载入' }} · {{ keySourceText() }}</div>
                    <div class="form-group">
                        <label for="vueApiKeyInput">{{ hasKey ? '更换 API Key' : 'API Key' }}</label>
                        <input id="vueApiKeyInput" v-model="apiKey" type="password" autocomplete="off" placeholder="输入后将使用 Windows DPAPI 加密保存">
                        <div class="form-hint">Key 不会保存在浏览器、本地存储或前端文件中。</div>
                    </div>
                    <div class="form-group">
                        <label for="vueProviderBaseUrl">兼容接口地址</label>
                        <input id="vueProviderBaseUrl" v-model="providerBaseUrl" type="url" autocomplete="off" placeholder="https://api.deepseek.com">
                        <div class="form-hint">当前：{{ providerName }} · 使用 OpenAI-compatible Chat Completions 协议。</div>
                    </div>
                    <div class="form-group">
                        <label for="vueApiModel">模型</label>
                        <input id="vueApiModel" v-model="model" list="vueApiModelOptions" autocomplete="off" placeholder="输入服务支持的模型 ID">
                        <datalist id="vueApiModelOptions"><option v-for="item in models" :key="item" :value="item"></option></datalist>
                    </div>
                    <section class="accessibility-settings" aria-labelledby="accessibilitySettingsTitle">
                        <div class="usage-diagnostics__heading">
                            <strong id="accessibilitySettingsTitle">阅读与语音</strong>
                            <button type="button" class="text-command" @click="resetAccessibility">恢复默认</button>
                        </div>
                        <label class="accessibility-range" for="vueFontScale">
                            <span>界面字号 <strong>{{ Math.round(fontScale * 100) }}%</strong></span>
                            <input id="vueFontScale" v-model.number="fontScale" type="range" min="0.85" max="1.25" step="0.05" @input="saveAccessibility">
                        </label>
                        <label class="accessibility-toggle" :class="{ disabled: !ttsSupported }">
                            <input v-model="ttsEnabled" type="checkbox" :disabled="!ttsSupported" @change="saveAccessibility">
                            <span><strong>本地朗读</strong><small>{{ ttsSupported ? '由系统浏览器语音引擎朗读剧情，默认关闭。' : '当前系统浏览器不支持语音朗读。' }}</small></span>
                        </label>
                        <label v-if="ttsEnabled && ttsSupported" class="accessibility-range" for="vueTtsRate">
                            <span>朗读速度 <strong>{{ Number(ttsRate).toFixed(1) }}x</strong></span>
                            <input id="vueTtsRate" v-model.number="ttsRate" type="range" min="0.7" max="1.4" step="0.1" @input="saveAccessibility">
                        </label>
                        <label v-if="ttsEnabled && ttsSupported" class="field-stack" for="vueTtsVoice"><span>朗读音色</span><select id="vueTtsVoice" v-model="ttsVoice" @change="saveAccessibility"><option value="">系统默认中文音色</option><option v-for="voice in voices.list" :key="voice.voiceURI" :value="voice.voiceURI">{{ voice.name }} · {{ voice.lang }}</option></select></label>
                        <label class="accessibility-toggle"><input v-model="highContrast" type="checkbox" @change="saveAccessibility"><span><strong>高对比度</strong><small>增强文字、边线和焦点可见度。</small></span></label>
                        <label class="accessibility-toggle"><input v-model="reduceMotion" type="checkbox" @change="saveAccessibility"><span><strong>减少动态效果</strong><small>关闭非必要过渡和动效。</small></span></label>
                        <label class="field-stack" for="vueSendKey"><span>发送快捷键</span><select id="vueSendKey" v-model="sendKey" @change="saveAccessibility"><option value="enter">Enter 发送，Shift+Enter 换行</option><option value="ctrl-enter">Ctrl+Enter 发送，Enter 换行</option></select></label>
                        <p>设置仅保存在本机浏览器中，朗读文本不会发送到额外服务。</p>
                    </section>
                    <section class="usage-diagnostics" aria-label="AI 运行概况">
                        <div class="usage-diagnostics__heading">
                            <strong>本存档运行概况</strong>
                            <span v-if="usage?.last_model">{{ usage.last_model }}</span>
                        </div>
                        <div v-if="usage" class="usage-diagnostics__grid">
                            <span>请求次数<strong>{{ formatNumber(usage.requests) }}</strong></span>
                            <span>实际 Token<strong>{{ formatNumber(usage.total_tokens) }}</strong></span>
                            <span>上下文估算<strong>{{ formatNumber(usage.estimated_tokens) }}</strong></span>
                            <span>费用估算<strong>{{ costText() }}</strong></span>
                            <span>响应 P50<strong>{{ usage.latency_p50_ms == null ? '暂无' : usage.latency_p50_ms + ' ms' }}</strong></span>
                            <span>响应 P95<strong>{{ usage.latency_p95_ms == null ? '暂无' : usage.latency_p95_ms + ' ms' }}</strong></span>
                        </div>
                        <p v-else>{{ diagnosticsMessage || '进入角色后显示用量统计。' }}</p>
                        <p v-if="usage?.last_error" class="usage-diagnostics__error">
                            最近故障：{{ usage.last_error.message }}
                        </p>
                        <small v-else-if="usage">最近一次 AI 请求未记录故障。</small>
                    </section>
                    <section v-if="saveHealth" class="usage-diagnostics" aria-label="存档健康">
                        <div class="usage-diagnostics__heading"><strong>存档健康</strong><span>{{ saveHealth.status === 'healthy' ? '健康' : saveHealth.status === 'warning' ? '可升级' : '需要修复' }}</span></div>
                        <p v-for="(item,index) in [...(saveHealth.errors || []), ...(saveHealth.warnings || [])]" :key="index">{{ item }}</p>
                        <small>快照 {{ saveHealth.snapshot_count || 0 }} 个 · {{ formatNumber(saveHealth.size_bytes) }} bytes</small>
                        <button class="cancel-btn" type="button" :disabled="busy || !saveHealth.repairable" @click="repairSave">检查并修复</button>
                    </section>
                    <section class="usage-diagnostics" aria-label="本地恢复数据">
                        <div class="usage-diagnostics__heading"><strong>本地回合恢复</strong><span>{{ recovery?.active_threads || 0 }} 个未完成回合</span></div>
                        <p>仅用于在意外退出后继续尚未提交的回合，不属于角色存档。</p>
                        <button class="cancel-btn" type="button" :disabled="busy || !recovery?.active_threads" @click="clearRecovery">清除恢复数据</button>
                    </section>
                    <div v-if="status" class="api-key-status" :class="statusType">{{ status }}</div>
                    <div class="dialog-buttons">
                        <button class="save-btn" type="button" :disabled="busy" @click="saveAndTest">{{ busy ? '处理中...' : '保存并测试' }}</button>
                        <button class="cancel-btn" type="button" :disabled="busy" @click="onClose">取消</button>
                    </div>
                </div>
            </section>
        </div>
    `
});


export function openSettingsDialog() {
    openAppModal('settings');
}
