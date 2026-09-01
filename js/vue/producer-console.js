import { computed, defineComponent, onMounted, ref } from '../vendor/vue.esm-browser.prod.js';
import { state } from '../ghost/core/state.js';
import { openAppModal } from './app-store.js';
import {
    loadProducerConsoleState,
    loadProducerContent,
    loadProducerContentBackups,
    maintainProducerMemory,
    restoreProducerContentBackup,
    runProducerEvaluation,
    saveProducerContent,
    validateProducerContent,
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
        const contentFiles = ref([]);
        const contentPath = ref('');
        const contentText = ref('');
        const contentDocument = ref({});
        const contentBaseline = ref({});
        const contentEditor = ref({ collections: [], references: { locations: [], npcs: [] } });
        const contentMode = ref('structured');
        const contentCollection = ref('');
        const contentRecordIndex = ref(0);
        const contentBackups = ref([]);
        const contentReport = ref(null);
        const contentMessage = ref('');
        const evaluationReport = ref(null);
        const evaluationMessage = ref('');
        const memoryReport = ref(null);
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
        const turnDiagnostics = computed(() => data.value.turn_diagnostics || {});
        const structuredCollections = computed(() => (
            (contentEditor.value.collections || []).filter(
                item => item.type === 'array' && item.item_type === 'object'
            )
        ));
        const structuredRecord = computed(() => {
            const document = contentDocument.value || {};
            if (!contentCollection.value) return document;
            const records = document[contentCollection.value];
            return Array.isArray(records) ? (records[contentRecordIndex.value] || null) : null;
        });
        const structuredFields = computed(() => Object.entries(structuredRecord.value || {}).map(
            ([key, value]) => ({ key, value, kind: Array.isArray(value) ? 'array' : value === null ? 'null' : typeof value })
        ));
        const contentDiff = computed(() => {
            const before = contentBaseline.value || {};
            const after = contentDocument.value || {};
            const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
            const changed = keys.filter(key => JSON.stringify(before[key]) !== JSON.stringify(after[key]));
            return { changed, dirty: changed.length > 0 };
        });

        async function reload() {
            data.value = await loadProducerConsoleState(state.currentSession.characterId);
            remaining.value = data.value.time?.chapter_time_remaining ?? 72;
            nodeName.value = data.value.time?.chapter_node_name || '';
        }

        async function loadContentFiles() {
            const result = await loadProducerContent(state.currentSession.characterId);
            contentFiles.value = result.files || [];
            if (!contentPath.value && contentFiles.value.length) contentPath.value = contentFiles.value[0].path;
            if (contentPath.value) await loadContent();
        }

        function cloneDocument(value) {
            return JSON.parse(JSON.stringify(value || {}));
        }

        function syncContentText() {
            contentText.value = JSON.stringify(contentDocument.value || {}, null, 2);
        }

        function selectDefaultCollection() {
            const first = structuredCollections.value[0];
            contentCollection.value = first?.key || '';
            contentRecordIndex.value = 0;
        }

        async function loadBackups() {
            if (!contentPath.value) {
                contentBackups.value = [];
                return;
            }
            const result = await loadProducerContentBackups(
                state.currentSession.characterId, contentPath.value
            );
            contentBackups.value = result.backups || [];
        }

        async function loadContent() {
            if (!contentPath.value) return;
            busy.value = true;
            contentMessage.value = '';
            try {
                const result = await loadProducerContent(state.currentSession.characterId, contentPath.value);
                contentDocument.value = cloneDocument(result.content);
                contentBaseline.value = cloneDocument(result.content);
                contentEditor.value = result.editor || { collections: [], references: { locations: [], npcs: [] } };
                syncContentText();
                selectDefaultCollection();
                contentReport.value = null;
                await loadBackups();
            } catch (error) {
                contentMessage.value = error.message || '内容读取失败';
            } finally {
                busy.value = false;
            }
        }

        function parsedContent() {
            try { return JSON.parse(contentText.value); }
            catch (error) { throw new Error(`JSON 格式错误：${error.message}`); }
        }

        function switchContentMode(mode) {
            if (mode === 'structured') {
                try {
                    contentDocument.value = cloneDocument(parsedContent());
                    selectDefaultCollection();
                } catch (error) {
                    contentMessage.value = error.message;
                    return;
                }
            } else {
                syncContentText();
            }
            contentMode.value = mode;
            contentMessage.value = '';
        }

        function editorValue(value) {
            if (value === null || value === undefined) return '';
            if (typeof value === 'object') return JSON.stringify(value, null, 2);
            return String(value);
        }

        function updateStructuredField(key, rawValue) {
            const record = structuredRecord.value;
            if (!record) return;
            const original = record[key];
            try {
                if (typeof original === 'number') record[key] = Number(rawValue);
                else if (typeof original === 'boolean') record[key] = rawValue === 'true';
                else if (original === null) record[key] = rawValue || null;
                else if (typeof original === 'object') record[key] = JSON.parse(rawValue || (Array.isArray(original) ? '[]' : '{}'));
                else record[key] = rawValue;
                syncContentText();
                contentMessage.value = '';
            } catch (error) {
                contentMessage.value = `${key} 格式错误：${error.message}`;
            }
        }

        function referenceValues(key) {
            const normalized = String(key || '').toLowerCase();
            if (normalized.includes('npc') || normalized.includes('character')) {
                return contentEditor.value.references?.npcs || [];
            }
            if (normalized.includes('location') || normalized.includes('scene')) {
                return contentEditor.value.references?.locations || [];
            }
            return [];
        }

        function addStructuredRecord() {
            const records = contentDocument.value?.[contentCollection.value];
            if (!Array.isArray(records)) return;
            records.push({});
            contentRecordIndex.value = records.length - 1;
            syncContentText();
        }

        function removeStructuredRecord() {
            const records = contentDocument.value?.[contentCollection.value];
            if (!Array.isArray(records) || !records.length) return;
            if (!window.confirm('确定删除当前内容条目吗？保存前仍可重新载入撤销。')) return;
            records.splice(contentRecordIndex.value, 1);
            contentRecordIndex.value = Math.max(0, Math.min(contentRecordIndex.value, records.length - 1));
            syncContentText();
        }

        async function validateContent() {
            if (!contentPath.value) return;
            busy.value = true;
            contentMessage.value = '';
            try {
                const document = parsedContent();
                contentDocument.value = cloneDocument(document);
                contentReport.value = await validateProducerContent(
                    state.currentSession.characterId, contentPath.value, document
                );
                contentMessage.value = contentReport.value.valid ? '结构与引用校验通过' : '内容存在错误';
            } catch (error) {
                contentReport.value = { valid: false, errors: [error.message || '校验失败'] };
                contentMessage.value = '内容存在错误';
            } finally {
                busy.value = false;
            }
        }

        async function saveContent() {
            if (!contentPath.value) return;
            busy.value = true;
            contentMessage.value = '';
            try {
                const document = parsedContent();
                const result = await saveProducerContent(
                    state.currentSession.characterId, contentPath.value, document
                );
                contentReport.value = result.validation || null;
                contentDocument.value = cloneDocument(document);
                contentBaseline.value = cloneDocument(document);
                syncContentText();
                await loadBackups();
                contentMessage.value = '内容已保存，旧版本已自动备份';
            } catch (error) {
                contentMessage.value = error.message || '内容保存失败';
            } finally {
                busy.value = false;
            }
        }

        async function restoreBackup(backupId) {
            if (!window.confirm('确定恢复这个内容备份吗？当前版本会先自动备份。')) return;
            busy.value = true;
            try {
                await restoreProducerContentBackup(
                    state.currentSession.characterId, contentPath.value, backupId
                );
                await loadContent();
                contentMessage.value = '备份已恢复，恢复前版本也已保留';
            } catch (error) {
                contentMessage.value = error.message || '备份恢复失败';
            } finally {
                busy.value = false;
            }
        }

        async function runEvaluation() {
            if (!window.confirm('将调用当前 AI 服务运行 4 组隔离评测，是否继续？')) return;
            busy.value = true;
            evaluationMessage.value = '正在运行真实模型评测…';
            try {
                evaluationReport.value = await runProducerEvaluation(state.currentSession.characterId);
                evaluationMessage.value = `评测完成：${evaluationReport.value.passed}/${evaluationReport.value.total} 通过`;
            } catch (error) {
                evaluationMessage.value = error.message || '模型评测失败';
            } finally {
                busy.value = false;
            }
        }

        async function runMemoryMaintenance() {
            busy.value = true;
            try {
                const response = await maintainProducerMemory(state.currentSession.characterId);
                memoryReport.value = response.report || {};
                await reload();
            } catch (error) {
                memoryReport.value = { error: error.message || '记忆维护失败' };
            } finally {
                busy.value = false;
            }
        }

        function downloadDiagnostics() {
            const id = encodeURIComponent(state.currentSession.characterId);
            window.location.href = `/api/ghost/producer_console/diagnostic_bundle?character_id=${id}`;
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

        onMounted(async () => { await reload(); await loadContentFiles(); });
        return {
            addStructuredRecord, attitude, busy, checkpoint, compressMemory, contentBackups,
            contentCollection, contentDiff, contentDocument, contentEditor, contentFiles, contentMessage, contentMode, contentPath,
            contentRecordIndex, contentReport, contentText, context, contextBudget, createEvent,
            data, debug, deleteMemory, downloadDiagnostics, editorValue, evaluationMessage,
            evaluationReport, eventDescription, eventTitle, eventType, loadContent, memoryGroups,
            memoryId, memoryImportance, memoryNpc, memoryReport, memoryRetrieval, memorySummary,
            memoryTags, nodeName, npcName, playerPairs, reason, referenceValues, remaining,
            removeStructuredRecord, resourceKey, resourcePairs, resourceValue, restore, restoreBackup,
            runEvaluation, runMemoryMaintenance, runtime, saveContent, scene, setAnomaly,
            setPlayerState, setRelationship, setResource, stateKey, stateValue, structuredCollections,
            structuredFields, structuredRecord, switchContentMode, teleport, turnDiagnostics,
            turnRuntime, updateStructuredField, upsertMemory, validateContent, workflow
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
                    <section class="producer-block producer-wide"><h3>NPC 长期记忆</h3><input v-model="memoryNpc" placeholder="NPC 名称"><input v-model="memoryId" placeholder="记忆 ID，可留空"><textarea v-model="memorySummary" rows="3" placeholder="记忆内容"></textarea><input v-model="memoryTags" placeholder="标签"><input v-model="memoryImportance" type="number" min="1" max="10" placeholder="重要度"><div class="producer-memory-actions"><button :disabled="busy" @click="upsertMemory">新增/改写</button><button :disabled="busy" @click="deleteMemory">删除 ID</button><button :disabled="busy" @click="compressMemory">压缩指定人物</button><button :disabled="busy" @click="runMemoryMaintenance">维护全部记忆</button></div><div v-if="memoryReport" class="producer-state-preview">去重 {{ memoryReport.duplicates_removed || 0 }} 条 · 压缩 {{ memoryReport.compressed_npcs?.length || 0 }} 人 · 索引失效 {{ memoryReport.invalidated_indexes || 0 }} 组<span v-if="memoryReport.error"> · {{ memoryReport.error }}</span></div><div class="producer-state-preview producer-memory-preview"><div v-for="[name,items] in memoryGroups" :key="name" class="producer-memory-npc"><strong>{{ name }}</strong><div v-for="item in items.slice(-3).reverse()" :key="item.id" class="producer-memory-item"><code>{{ item.id }}</code><span>{{ item.summary }}</span></div></div></div></section>
                    <section class="producer-block producer-wide producer-content-editor">
                        <h3>世界内容编辑器</h3>
                        <div class="producer-content-toolbar"><select v-model="contentPath" :disabled="busy" @change="loadContent"><option v-for="item in contentFiles" :key="item.path" :value="item.path">{{ item.label }} · {{ item.path }}</option></select><button :disabled="busy || !contentPath" @click="loadContent">重新载入</button><button :disabled="busy || !contentPath" @click="validateContent">模拟校验</button><button class="producer-primary-btn" :disabled="busy || !contentPath" @click="saveContent">校验并保存</button></div>
                        <div class="producer-editor-modes" role="tablist"><button type="button" :class="{ active: contentMode === 'structured' }" @click="switchContentMode('structured')">结构化</button><button type="button" :class="{ active: contentMode === 'json' }" @click="switchContentMode('json')">JSON</button><span :class="{ dirty: contentDiff.dirty }">{{ contentDiff.dirty ? '未保存：' + contentDiff.changed.join('、') : '内容已同步' }}</span></div>
                        <div v-if="contentMode === 'structured'" class="producer-structured-editor">
                            <div v-if="structuredCollections.length" class="producer-record-selector"><select v-model="contentCollection" @change="contentRecordIndex = 0"><option v-for="item in structuredCollections" :key="item.key" :value="item.key">{{ item.key }} · {{ item.count }} 项</option></select><select v-if="contentDocument?.[contentCollection]?.length" v-model.number="contentRecordIndex"><option v-for="(item,index) in contentDocument[contentCollection]" :key="index" :value="index">{{ index + 1 }} · {{ item.name || item.title || item.id || '未命名条目' }}</option></select><button type="button" @click="addStructuredRecord">新增</button><button type="button" :disabled="!structuredRecord" @click="removeStructuredRecord">删除</button></div>
                            <div v-if="structuredRecord" class="producer-field-grid"><label v-for="field in structuredFields" :key="field.key"><span>{{ field.key }}</span><select v-if="field.kind === 'boolean'" :value="String(field.value)" @change="updateStructuredField(field.key, $event.target.value)"><option value="true">true</option><option value="false">false</option></select><textarea v-else-if="field.kind === 'array' || field.kind === 'object'" rows="4" :value="editorValue(field.value)" @change="updateStructuredField(field.key, $event.target.value)"></textarea><input v-else :list="referenceValues(field.key).length ? 'producerReferenceValues' : null" :value="editorValue(field.value)" @change="updateStructuredField(field.key, $event.target.value)"></label></div>
                            <div v-else class="dialog-empty">当前集合没有条目。</div>
                            <datalist id="producerReferenceValues"><option v-for="value in [...(contentEditor.references?.locations || []), ...(contentEditor.references?.npcs || [])]" :key="value" :value="value"></option></datalist>
                        </div>
                        <textarea v-else v-model="contentText" rows="18" spellcheck="false" aria-label="世界内容 JSON"></textarea>
                        <div v-if="contentReport" class="producer-content-report" :class="{ 'is-valid': contentReport.valid, 'is-error': !contentReport.valid }"><strong>{{ contentReport.valid ? '校验通过' : '校验未通过' }}</strong><span v-for="(error,index) in (contentReport.errors || [])" :key="index">{{ error }}</span></div>
                        <div v-if="contentBackups.length" class="producer-backup-list"><strong>最近备份</strong><button v-for="item in contentBackups.slice(0, 6)" :key="item.backup_id" :disabled="busy" @click="restoreBackup(item.backup_id)">{{ new Date(item.created_at).toLocaleString() }} · {{ Math.ceil(item.size_bytes / 1024) }} KB</button></div>
                        <p v-if="contentMessage" class="dialog-status">{{ contentMessage }}</p>
                    </section>
                    <section class="producer-block producer-wide"><h3>真实模型回归</h3><div class="producer-tool-row"><button class="producer-primary-btn" :disabled="busy" @click="runEvaluation">运行隔离评测</button><span>{{ evaluationMessage || '尚未运行' }}</span></div><div v-if="evaluationReport" class="producer-evaluation-list"><article v-for="item in evaluationReport.results" :key="item.id" :class="{ passed: item.passed }"><strong>{{ item.passed ? '通过' : '未通过' }} · {{ item.title }}</strong><span>{{ item.evaluation.score }} 分 · {{ item.runtime?.elapsed_ms || 0 }} ms · {{ item.usage?.total_tokens || 0 }} Token</span><small v-for="issue in item.evaluation.issues" :key="issue.code">{{ issue.message }}</small></article></div></section>
                    <section class="producer-block producer-wide"><h3>最近 AI 调试</h3><div class="producer-state-preview">类型：{{ debug.kind || '暂无' }}<br>模型：{{ runtime.used_model || runtime.requested_model || '暂无' }} · 尝试 {{ runtime.attempts || 0 }} 次 · {{ runtime.fallback_used ? '已降级' : '未降级' }}<br>上下文：{{ runtime.prompt_chars || debug.prompt_chars || 0 }} 字符<span v-if="runtime.compressed">（由 {{ runtime.original_chars }} 压缩）</span><br>预算：{{ contextBudget.used_chars || 0 }} / {{ contextBudget.total_budget_chars || 0 }} 字符，约 {{ contextBudget.estimated_tokens || 0 }} Token<br>Token：{{ debug.actual_total_tokens || 0 }}（输入 {{ debug.usage?.prompt_tokens || 0 }} / 输出 {{ debug.usage?.completion_tokens || 0 }}）<br>世界书：{{ context.used_chars || 0 }} / {{ context.budget_chars || 0 }} 字符<br>注入：{{ (context.entries || []).map(item => item.title).join('、') || '无' }}</div><div class="producer-state-preview producer-memory-preview"><div v-for="item in memoryRetrieval" :key="item.npc_name + ':' + item.memory_id" class="producer-memory-item"><code>{{ item.memory_id }}</code><span>{{ item.npc_name }} · {{ item.reasons?.join('、') }} · {{ item.chars }} 字符 · {{ item.score }}</span></div></div><textarea rows="6" readonly :value="debug.prompt_preview || '普通模式未保存提示词内容'"></textarea><textarea rows="4" readonly :value="debug.response_preview || '普通模式未保存响应内容'"></textarea></section>
                    <section class="producer-block producer-wide"><h3>回合工作流与诊断</h3><div class="producer-tool-row"><button type="button" @click="downloadDiagnostics">导出脱敏诊断</button><span>{{ turnDiagnostics.turns || 0 }} 回合 · P50 {{ turnDiagnostics.p50_ms ?? '暂无' }} ms · P95 {{ turnDiagnostics.p95_ms ?? '暂无' }} ms · 回退 {{ turnDiagnostics.fallbacks || 0 }} · 失败 {{ turnDiagnostics.failures || 0 }}</span></div><div class="producer-state-preview">Functional API：{{ turnRuntime.langgraph_enabled ? '启用' : '回退路径' }} · 最近恢复：{{ workflow.recovered ? '是' : '否' }} · 本回合回退：{{ workflow.fallback ? '是' : '否' }}<br>工作流耗时：{{ workflow.workflow_ms || 0 }} ms · 检查点：{{ checkpoint.active_threads || 0 }} 个 · 数据库：{{ checkpoint.database_bytes || 0 }} bytes<br>最旧恢复数据：{{ checkpoint.oldest_age_seconds || 0 }} 秒 · 清理故障：{{ workflow.cleanup_error || '无' }}</div><div class="producer-state-preview producer-memory-preview"><div v-for="item in (turnRuntime.recent_turns || [])" :key="item.turn_id" class="producer-memory-item"><code>{{ item.turn_id }}</code><span>{{ item.kind }} · {{ item.state }} · {{ item.duration_ms || 0 }} ms<template v-if="item.recovered"> · 已恢复</template><small v-if="item.phase_durations_ms">{{ Object.entries(item.phase_durations_ms).map(([name,value]) => name + ' ' + value + 'ms').join(' · ') }}</small></span></div></div></section>
                </div>
            </section>
        </div>
    `
});


export async function openProducerConsoleVue() {
    if (!state.currentSession.gmMode) return;
    openAppModal('producer');
}
