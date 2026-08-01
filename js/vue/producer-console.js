import { computed, defineComponent, onMounted, ref } from '../vendor/vue.esm-browser.prod.js';
import { state } from '../ghost/core/state.js';
import { openAppModal } from './app-store.js';
import {
    loadProducerConsoleState,
    producerCompressNPCMemory,
    producerCreateEvent,
    producerDeleteNPCMemory,
    producerRestore,
    producerSetAnomaly,
    producerSetPlayerState,
    producerSetRelationship,
    producerSetResource,
    producerTeleport,
    producerUpsertNPCMemory
} from '../api.js';
import {
    refreshNPCList,
    renderActionSuggestions,
    renderCharacterInfo,
    renderSidebarLocations,
    updateTimeDisplay
} from './game-controller.js';


function parseValue(value) {
    const text = String(value ?? '').trim();
    if (text.includes('、') || text.includes(',')) return text.split(/[、,]/).map(item => item.trim()).filter(Boolean);
    if (/^-?\d+(\.\d+)?$/.test(text)) return Number(text);
    return text;
}


export const ProducerConsole = defineComponent({
    name: 'ProducerConsole',
    props: { onClose: { type: Function, required: true } },
    setup(props) {
        const data = ref({});
        const busy = ref(false);
        const scene = ref(state.currentSession.currentScene || '');
        const npcName = ref('');
        const attitude = ref('');
        const reason = ref('');
        const stateKey = ref('');
        const stateValue = ref('');
        const resourceKey = ref('');
        const resourceValue = ref('');
        const remaining = ref(72);
        const nodeName = ref('');
        const eventTitle = ref('');
        const eventType = ref('异变线索');
        const eventDescription = ref('');
        const memoryNpc = ref('');
        const memoryId = ref('');
        const memorySummary = ref('');
        const memoryTags = ref('');
        const memoryImportance = ref('');
        const debug = computed(() => data.value.debug_last_ai || {});
        const runtime = computed(() => data.value.model_runtime || debug.value.model_runtime || {});
        const context = computed(() => debug.value.context_injection || {});
        const contextBudget = computed(() => debug.value.context_budget || {});
        const memoryRetrieval = computed(() => debug.value.memory_retrieval || []);
        const turnRuntime = computed(() => data.value.turn_runtime || {});
        const checkpoint = computed(() => turnRuntime.value.checkpoints || {});
        const workflow = computed(() => turnRuntime.value.workflow || {});
        const playerPairs = computed(() => Object.entries(data.value.player_state || {}).slice(0, 12));
        const resourcePairs = computed(() => Object.entries(data.value.resources || {}).slice(0, 12));
        const memoryGroups = computed(() => Object.entries(data.value.npc_memories || {}).slice(0, 8));

        async function reload() {
            data.value = await loadProducerConsoleState(state.currentSession.characterId);
            remaining.value = data.value.time?.chapter_time_remaining ?? 72;
            nodeName.value = data.value.time?.chapter_node_name || '';
        }

        async function run(action, message) {
            busy.value = true;
            try {
                await action();
                await reload();
                window.dispatchEvent(new CustomEvent('touhou:toast', { detail: { message, type: 'success' } }));
            } catch (error) {
                window.dispatchEvent(new CustomEvent('touhou:toast', {
                    detail: { message: error.message || '控制台操作失败', type: 'error' }
                }));
            } finally {
                busy.value = false;
            }
        }

        async function restore() {
            await run(async () => {
                await producerRestore(state.currentSession.characterId);
                state.currentSession.playerState = data.value.player_state || {};
                renderCharacterInfo();
                updateTimeDisplay();
            }, '已恢复最强状态');
        }

        async function teleport() {
            if (!scene.value.trim()) return;
            await run(async () => {
                await producerTeleport(state.currentSession.characterId, scene.value.trim());
                state.currentSession.currentScene = scene.value.trim();
                renderCharacterInfo();
                await renderSidebarLocations();
                await refreshNPCList();
                renderActionSuggestions();
            }, `已传送到 ${scene.value.trim()}`);
        }

        async function setRelationship() {
            if (!npcName.value.trim() || !attitude.value.trim()) return;
            await run(() => producerSetRelationship(
                state.currentSession.characterId,
                npcName.value.trim(),
                attitude.value.trim(),
                reason.value.trim() || '高权限指令'
            ), '关系已改写');
        }

        async function setPlayerState() {
            if (!stateKey.value.trim()) return;
            await run(async () => {
                const result = await producerSetPlayerState(state.currentSession.characterId, {
                    [stateKey.value.trim()]: parseValue(stateValue.value)
                });
                state.currentSession.playerState = result.player_state || {};
                updateTimeDisplay();
            }, '玩家数值已写入');
        }

        async function setResource() {
            if (!resourceKey.value.trim()) return;
            await run(() => producerSetResource(
                state.currentSession.characterId,
                resourceKey.value.trim(),
                parseValue(resourceValue.value)
            ), '资源已写入');
        }

        async function setAnomaly() {
            await run(async () => {
                const result = await producerSetAnomaly(
                    state.currentSession.characterId,
                    remaining.value,
                    nodeName.value.trim()
                );
                state.currentSession.time = result.time || state.currentSession.time;
                updateTimeDisplay();
            }, '异变状态已改写');
        }

        async function createEvent() {
            if (!eventTitle.value.trim() && !eventDescription.value.trim()) return;
            await run(() => producerCreateEvent(state.currentSession.characterId, {
                title: eventTitle.value.trim(),
                type: eventType.value,
                scene: state.currentSession.currentScene,
                description: eventDescription.value.trim(),
                hooks: ['制作人创建']
            }), '自由探索事件已写入');
        }

        async function upsertMemory() {
            if (!memoryNpc.value.trim() || !memorySummary.value.trim()) return;
            await run(() => producerUpsertNPCMemory(
                state.currentSession.characterId,
                memoryNpc.value.trim(),
                memoryId.value.trim(),
                memorySummary.value.trim(),
                memoryTags.value.trim(),
                memoryImportance.value === '' ? null : Number(memoryImportance.value)
            ), memoryId.value.trim() ? 'NPC 记忆已改写' : 'NPC 记忆已新增');
        }

        async function deleteMemory() {
            if (!memoryNpc.value.trim() || !memoryId.value.trim()) return;
            await run(() => producerDeleteNPCMemory(
                state.currentSession.characterId,
                memoryNpc.value.trim(),
                memoryId.value.trim()
            ), 'NPC 记忆已删除');
        }

        async function compressMemory() {
            if (!memoryNpc.value.trim()) return;
            await run(() => producerCompressNPCMemory(
                state.currentSession.characterId,
                memoryNpc.value.trim()
            ), 'NPC 记忆已压缩');
        }

        onMounted(reload);
        return {
            attitude, busy, compressMemory, context, contextBudget, createEvent, data, debug, deleteMemory,
            eventDescription, eventTitle, eventType, memoryGroups, memoryId, memoryImportance,
            memoryNpc, memoryRetrieval, memorySummary, memoryTags, nodeName, npcName, playerPairs, reason,
            checkpoint, remaining, resourceKey, resourcePairs, resourceValue, restore, runtime,
            scene, setAnomaly, setPlayerState, setRelationship, setResource, stateKey, stateValue,
            teleport, turnRuntime, upsertMemory, workflow
        };
    },
    template: `
        <div class="vue-modal-backdrop producer-console-backdrop" @click.self="onClose">
            <section class="producer-console-dialog vue-producer-console" role="dialog" aria-modal="true">
                <header class="dialog-header"><strong>高权限用户控制台</strong><button class="icon-button" @click="onClose">×</button></header>
                <div class="dialog-content producer-console-content">
                    <div class="producer-console-note">所有操作直接写入当前存档，但不会限制地点或探索方式。</div>
                    <div class="producer-grid">
                        <section class="producer-block"><h3>权限与状态</h3><button class="producer-primary-btn" :disabled="busy" @click="restore">恢复最强状态</button><div class="producer-state-preview"><div v-for="[key,value] in playerPairs" :key="key" class="producer-pair"><span>{{ key }}</span><strong>{{ value }}</strong></div></div></section>
                        <section class="producer-block"><h3>传送地点</h3><input v-model="scene" placeholder="任意地点名称"><button :disabled="busy" @click="teleport">立即传送</button></section>
                        <section class="producer-block"><h3>NPC 关系</h3><input v-model="npcName" placeholder="NPC 名称"><input v-model="attitude" placeholder="关系"><input v-model="reason" placeholder="原因"><button :disabled="busy" @click="setRelationship">改写关系</button></section>
                        <section class="producer-block"><h3>玩家数值</h3><input v-model="stateKey" placeholder="数值名"><input v-model="stateValue" placeholder="值"><button :disabled="busy" @click="setPlayerState">写入数值</button></section>
                        <section class="producer-block"><h3>资源</h3><input v-model="resourceKey" placeholder="资源名"><input v-model="resourceValue" placeholder="值"><button :disabled="busy" @click="setResource">写入资源</button><div class="producer-state-preview"><div v-for="[key,value] in resourcePairs" :key="key" class="producer-pair"><span>{{ key }}</span><strong>{{ Array.isArray(value) ? value.join('、') : value }}</strong></div></div></section>
                        <section class="producer-block"><h3>异变进度</h3><input v-model.number="remaining" type="number" min="0"><input v-model="nodeName" placeholder="节点名称"><button :disabled="busy" @click="setAnomaly">改写异变</button></section>
                    </div>
                    <section class="producer-block producer-wide"><h3>创建自由探索事件</h3><input v-model="eventTitle" placeholder="事件标题"><select v-model="eventType"><option>异变线索</option><option>日常</option><option>偶遇</option><option>战斗</option><option>暧昧邀约</option><option>资源发现</option></select><textarea v-model="eventDescription" rows="3" placeholder="事件描述"></textarea><button :disabled="busy" @click="createEvent">写入事件池</button></section>
                    <section class="producer-block producer-wide"><h3>NPC 长期记忆</h3><input v-model="memoryNpc" placeholder="NPC 名称"><input v-model="memoryId" placeholder="记忆 ID，可留空"><textarea v-model="memorySummary" rows="3" placeholder="记忆内容"></textarea><input v-model="memoryTags" placeholder="标签"><input v-model="memoryImportance" type="number" min="1" max="10" placeholder="重要度"><div class="producer-memory-actions"><button :disabled="busy" @click="upsertMemory">新增/改写</button><button :disabled="busy" @click="deleteMemory">删除 ID</button><button :disabled="busy" @click="compressMemory">压缩记忆</button></div><div class="producer-state-preview producer-memory-preview"><div v-for="[name,items] in memoryGroups" :key="name" class="producer-memory-npc"><strong>{{ name }}</strong><div v-for="item in items.slice(-3).reverse()" :key="item.id" class="producer-memory-item"><code>{{ item.id }}</code><span>{{ item.summary }}</span></div></div></div></section>
                    <section class="producer-block producer-wide"><h3>最近 AI 调试</h3><div class="producer-state-preview">类型：{{ debug.kind || '暂无' }}<br>模型：{{ runtime.used_model || runtime.requested_model || '暂无' }} · 尝试 {{ runtime.attempts || 0 }} 次 · {{ runtime.fallback_used ? '已降级' : '未降级' }}<br>上下文：{{ runtime.prompt_chars || debug.prompt_chars || 0 }} 字符<span v-if="runtime.compressed">（由 {{ runtime.original_chars }} 压缩）</span><br>预算：{{ contextBudget.used_chars || 0 }} / {{ contextBudget.total_budget_chars || 0 }} 字符，约 {{ contextBudget.estimated_tokens || 0 }} Token<br>Token：{{ debug.actual_total_tokens || 0 }}（输入 {{ debug.usage?.prompt_tokens || 0 }} / 输出 {{ debug.usage?.completion_tokens || 0 }}）<br>世界书：{{ context.used_chars || 0 }} / {{ context.budget_chars || 0 }} 字符<br>注入：{{ (context.entries || []).map(item => item.title).join('、') || '无' }}</div><div class="producer-state-preview producer-memory-preview"><div v-for="item in memoryRetrieval" :key="item.npc_name + ':' + item.memory_id" class="producer-memory-item"><code>{{ item.memory_id }}</code><span>{{ item.npc_name }} · {{ item.reasons?.join('、') }} · {{ item.chars }} 字符 · {{ item.score }}</span></div></div><textarea rows="6" readonly :value="debug.prompt_preview || '普通模式未保存提示词内容'"></textarea><textarea rows="4" readonly :value="debug.response_preview || '普通模式未保存响应内容'"></textarea></section>
                    <section class="producer-block producer-wide"><h3>回合工作流</h3><div class="producer-state-preview">Functional API：{{ turnRuntime.langgraph_enabled ? '启用' : '回退路径' }} · 最近恢复：{{ workflow.recovered ? '是' : '否' }} · 本回合回退：{{ workflow.fallback ? '是' : '否' }}<br>工作流耗时：{{ workflow.workflow_ms || 0 }} ms · 检查点：{{ checkpoint.active_threads || 0 }} 个 · 数据库：{{ checkpoint.database_bytes || 0 }} bytes<br>最旧恢复数据：{{ checkpoint.oldest_age_seconds || 0 }} 秒 · 清理故障：{{ workflow.cleanup_error || '无' }}</div><div class="producer-state-preview producer-memory-preview"><div v-for="item in (turnRuntime.recent_turns || [])" :key="item.turn_id" class="producer-memory-item"><code>{{ item.turn_id }}</code><span>{{ item.kind }} · {{ item.state }}<template v-if="item.recovered"> · 已恢复</template></span></div></div></section>
                </div>
            </section>
        </div>
    `
});


export async function openProducerConsoleVue() {
    if (!state.currentSession.gmMode) return;
    openAppModal('producer');
}
