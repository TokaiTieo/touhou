import { defineComponent, onMounted, ref } from '../vendor/vue.esm-browser.prod.js';
import { state as gameState } from '../ghost/core/state.js';
import { openAppModal } from './app-store.js';


export const SettingsDialog = defineComponent({
    name: 'SettingsDialog',
    props: { onClose: { type: Function, required: true } },
    setup(props) {
        const apiKey = ref('');
        const maskedKey = ref('');
        const hasKey = ref(false);
        const model = ref(localStorage.getItem('touhou_model') || 'deepseek-v4-flash');
        const models = ref(['deepseek-v4-flash', 'deepseek-v4-pro']);
        const status = ref('');
        const statusType = ref('');
        const busy = ref(false);
        const usage = ref(null);
        const diagnosticsMessage = ref('');
        const recovery = ref(null);

        onMounted(async () => {
            try {
                const response = await fetch('/api/ghost/get_api_key');
                const data = await response.json();
                hasKey.value = Boolean(data.has_key);
                maskedKey.value = data.masked_key || '';
                if (data.model) model.value = data.model;
                const modelResponse = await fetch('/api/ghost/get_model');
                const modelData = await modelResponse.json();
                models.value = modelData.available_models || models.value;
                const characterId = gameState.currentSession.characterId || '';
                const diagnosticsResponse = await fetch(`/api/ghost/diagnostics?character_id=${encodeURIComponent(characterId)}`);
                if (diagnosticsResponse.ok) {
                    const diagnostics = await diagnosticsResponse.json();
                    usage.value = diagnostics.usage || null;
                    diagnosticsMessage.value = diagnostics.message || '';
                }
                const recoveryResponse = await fetch('/api/ghost/turn_recovery');
                if (recoveryResponse.ok) recovery.value = await recoveryResponse.json();
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
                }
                const modelResponse = await fetch('/api/ghost/set_model', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ model: model.value })
                });
                if (!modelResponse.ok) throw new Error('模型切换失败');
                localStorage.setItem('touhou_model', model.value);
                if (apiKey.value.trim()) {
                    status.value = '正在测试连接...';
                    const testResponse = await fetch('/api/ghost/test_ai_with_key', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ api_key: apiKey.value.trim(), model: model.value })
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

        return {
            apiKey, busy, clearRecovery, costText, diagnosticsMessage, formatNumber, hasKey,
            maskedKey, model, models, recovery, saveAndTest, status, statusType, usage
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
                    <div v-if="hasKey" class="api-key-status ok">当前已配置：{{ maskedKey || '已加密保存' }}</div>
                    <div class="form-group">
                        <label for="vueApiKeyInput">{{ hasKey ? '更换 DeepSeek API Key' : 'DeepSeek API Key' }}</label>
                        <input id="vueApiKeyInput" v-model="apiKey" type="password" autocomplete="off" placeholder="输入后将使用 Windows DPAPI 加密保存">
                        <div class="form-hint">Key 不会保存在浏览器、本地存储或前端文件中。</div>
                    </div>
                    <div class="form-group">
                        <label for="vueApiModel">模型</label>
                        <select id="vueApiModel" v-model="model">
                            <option v-for="item in models" :key="item" :value="item">{{ item }}</option>
                        </select>
                    </div>
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
                        </div>
                        <p v-else>{{ diagnosticsMessage || '进入角色后显示用量统计。' }}</p>
                        <p v-if="usage?.last_error" class="usage-diagnostics__error">
                            最近故障：{{ usage.last_error.message }}
                        </p>
                        <small v-else-if="usage">最近一次 AI 请求未记录故障。</small>
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
