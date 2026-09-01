import { computed, defineComponent, ref } from '../vendor/vue.esm-browser.prod.js';
import {
    addNPC,
    getAllLocations,
    getAllNPCs,
    getLocationByName,
    systemHelper,
    validateCharacter,
    setSpellcardLoadout,
    performInventoryAction
} from '../api.js';
import { state } from '../ghost/core/state.js';
import { CURRENT_CHAPTER_INDEX } from '../ghost/core/constants.js';
import { renderMarkdownLite, softenPublicText } from '../ghost/ui/text.js';
import { refreshNPCList, refreshTasksPanel } from './game-controller.js';
import { appUi, closeAppModal } from './app-store.js';
import { readPngCharacterData } from './character-dialogs.js';

function displayValue(value) {
    if (Array.isArray(value)) return value.map(displayValue);
    if (value && typeof value === 'object') {
        return Object.entries(value).map(([key, item]) => `${softenPublicText(key)}：${displayValue(item)}`);
    }
    return softenPublicText(String(value ?? ''));
}

export const DetailDialog = defineComponent({
    name: 'DetailDialog',
    setup() {
        const detail = computed(() => appUi.modalPayload || {});
        const rows = computed(() => (detail.value.rows || [])
            .filter(row => row.value !== undefined && row.value !== null && row.value !== '')
            .map(row => ({ ...row, display: displayValue(row.value) })));
        const selectedSpellcards = ref([...(appUi.modalPayload?.spellcardLoadout || [])]);
        const loadoutBusy = ref(false);
        const loadoutMessage = ref('');
        const inventoryItems = ref([...(appUi.modalPayload?.inventoryItems || [])]);
        const equippedItems = ref([...(appUi.modalPayload?.equippedItems || [])]);
        const inventoryBusy = ref('');
        const inventoryMessage = ref('');
        const giftTarget = ref(appUi.modalPayload?.giftTargets?.[0] || '');
        function toggleSpellcard(name) {
            const index = selectedSpellcards.value.indexOf(name);
            if (index >= 0) selectedSpellcards.value.splice(index, 1);
            else if (selectedSpellcards.value.length < 6) selectedSpellcards.value.push(name);
        }
        async function saveLoadout() {
            loadoutBusy.value = true;
            loadoutMessage.value = '';
            try {
                await setSpellcardLoadout(state.currentSession.characterId, selectedSpellcards.value);
                loadoutMessage.value = '常用符卡栏已更新';
            } catch (error) {
                loadoutMessage.value = error.message || '符卡栏保存失败';
            } finally {
                loadoutBusy.value = false;
            }
        }
        async function itemAction(action, item) {
            if (action === 'discard' && !window.confirm(`确定丢弃「${item.name}」吗？`)) return;
            inventoryBusy.value = `${action}:${item.name}`;
            inventoryMessage.value = '';
            try {
                const result = await performInventoryAction(
                    state.currentSession.characterId, action, item.name,
                    action === 'gift' ? giftTarget.value : ''
                );
                inventoryItems.value = result.inventory?.items || [];
                equippedItems.value = result.inventory?.equipped || [];
                state.currentSession.playerState = result.player_state || state.currentSession.playerState;
                state.currentSession.relationshipsMap = result.relationships || state.currentSession.relationshipsMap;
                inventoryMessage.value = result.result?.message || '行囊已更新';
            } catch (error) {
                inventoryMessage.value = error.message || '行囊操作失败';
            } finally {
                inventoryBusy.value = '';
            }
        }
        return {
            closeAppModal, detail, equippedItems, giftTarget, inventoryBusy, inventoryItems, inventoryMessage,
            itemAction, loadoutBusy, loadoutMessage, rows, saveLoadout, selectedSpellcards, toggleSpellcard
        };
    },
    template: `
        <div class="vue-modal-backdrop" @click.self="closeAppModal">
            <section class="record-dialog detail-record-dialog" role="dialog" aria-modal="true">
                <header class="record-dialog__header">
                    <div><small>{{ detail.kicker || '幻想乡记录' }}</small><strong>{{ detail.title || '详情' }}</strong></div>
                    <button class="icon-button" type="button" title="关闭" aria-label="关闭" @click="closeAppModal">×</button>
                </header>
                <div class="record-dialog__body">
                    <div v-if="detail.name" class="record-subject">
                        <strong>{{ detail.name }}</strong><span>{{ detail.subtitle }}</span>
                    </div>
                    <dl class="record-rows">
                        <template v-for="row in rows" :key="row.label">
                            <dt>{{ row.label }}</dt>
                            <dd>
                                <template v-if="Array.isArray(row.display)">
                                    <div v-for="(item, index) in row.display" :key="index" class="record-list-item">{{ item }}</div>
                                </template>
                                <template v-else>{{ row.display }}</template>
                            </dd>
                        </template>
                    </dl>
                    <section v-if="detail.inventoryEditor" class="inventory-action-editor">
                        <div class="spellcard-loadout-heading"><strong>行囊操作</strong><span>{{ inventoryItems.length }} 件</span></div>
                        <div v-if="detail.giftTargets?.length" class="inventory-gift-target">
                            <label for="inventoryGiftTarget">赠送对象</label>
                            <select id="inventoryGiftTarget" v-model="giftTarget"><option v-for="name in detail.giftTargets" :key="name">{{ name }}</option></select>
                        </div>
                        <div v-if="inventoryItems.length" class="inventory-action-list">
                            <article v-for="item in inventoryItems" :key="item.name" :class="{ 'is-equipped': equippedItems.includes(item.name) }">
                                <div><strong>{{ item.name }} × {{ item.quantity || 1 }}<span v-if="equippedItems.includes(item.name)"> · 随身</span></strong><small>{{ item.description || item.category || '幻想乡物品' }}</small></div>
                                <div>
                                    <button type="button" :disabled="!!inventoryBusy" title="使用" @click="itemAction('use', item)">用</button>
                                    <button v-if="!equippedItems.includes(item.name)" type="button" :disabled="!!inventoryBusy" title="设为随身装备" @click="itemAction('equip', item)">装</button>
                                    <button v-else type="button" :disabled="!!inventoryBusy" title="卸下随身装备" @click="itemAction('unequip', item)">卸</button>
                                    <button v-if="detail.giftTargets?.length" type="button" :disabled="!!inventoryBusy || !giftTarget" title="赠送" @click="itemAction('gift', item)">赠</button>
                                    <button type="button" :disabled="!!inventoryBusy" title="丢弃" @click="itemAction('discard', item)">弃</button>
                                </div>
                            </article>
                        </div>
                        <div v-else class="dialog-empty">行囊里暂时没有可操作的物品。</div>
                        <p v-if="inventoryMessage" class="dialog-status">{{ inventoryMessage }}</p>
                    </section>
                    <section v-if="detail.spellcardEditor" class="spellcard-loadout-editor">
                        <div class="spellcard-loadout-heading"><strong>配置常用符卡</strong><span>{{ selectedSpellcards.length }}/6</span></div>
                        <p>仅影响叙事优先参考，不限制临场使用其他符卡。</p>
                        <div v-if="detail.availableSpellcards?.length" class="spellcard-loadout-options">
                            <button v-for="name in detail.availableSpellcards" :key="name" type="button" :class="{ 'is-selected': selectedSpellcards.includes(name) }" :aria-pressed="selectedSpellcards.includes(name)" @click="toggleSpellcard(name)">{{ name }}</button>
                        </div>
                        <div v-else class="dialog-empty">完成一次符卡战后，可在这里配置常用符卡。</div>
                        <div class="dialog-command-row"><button class="primary-command" type="button" :disabled="loadoutBusy" @click="saveLoadout">{{ loadoutBusy ? '正在保存...' : '保存符卡栏' }}</button></div>
                        <p v-if="loadoutMessage" class="dialog-status">{{ loadoutMessage }}</p>
                    </section>
                    <p v-if="detail.note" class="record-note">{{ detail.note }}</p>
                </div>
            </section>
        </div>
    `
});

export const RelationshipsDialog = defineComponent({
    name: 'RelationshipsDialog',
    setup() {
        const payload = computed(() => appUi.modalPayload || {});
        const relationships = computed(() => Object.entries(payload.value.relationships || {}));
        return { closeAppModal, payload, relationships };
    },
    template: `
        <div class="vue-modal-backdrop" @click.self="closeAppModal">
            <section class="record-dialog compact-dialog relationship-record-dialog" role="dialog" aria-modal="true">
                <header class="record-dialog__header"><div><small>人物关系</small><strong>缘分录</strong></div><button class="icon-button" title="关闭" @click="closeAppModal">×</button></header>
                <div class="record-dialog__body">
                    <p class="record-note">记录幻想乡住民对你的当前态度，只作叙事参考，不限制行动与探索。</p>
                    <div v-if="!relationships.length" class="dialog-empty">还没有明确记录的缘分变化。</div>
                    <div v-else class="relationship-ledger">
                        <div v-for="[name, attitude] in relationships" :key="name"><strong>{{ name }}</strong><span>{{ attitude }}</span></div>
                    </div>
                    <p v-if="payload.latest" class="relationship-latest">最近记录：{{ payload.latest }}</p>
                </div>
            </section>
        </div>
    `
});

function profileFromImported(data) {
    return data?.profile || data || null;
}

export const NpcCreationDialog = defineComponent({
    name: 'NpcCreationDialog',
    setup() {
        const description = ref('');
        const profile = ref(null);
        const location = ref(state.currentSession.currentScene || '博丽神社');
        const sourceName = ref('');
        const busy = ref(false);
        const message = ref('');
        const importOnly = computed(() => appUi.modalPayload?.importOnly === true);

        async function generate() {
            if (!description.value.trim()) {
                message.value = '请先描述这位人物。';
                return;
            }
            busy.value = true;
            message.value = '';
            try {
                const result = await validateCharacter(description.value.trim(), CURRENT_CHAPTER_INDEX);
                profile.value = result.suggested_profile || null;
                if (!profile.value) throw new Error('未能整理人物设定');
            } catch (error) {
                message.value = error.message || '人物生成失败';
            } finally {
                busy.value = false;
            }
        }

        async function importFile(event) {
            const file = event.target.files?.[0];
            if (!file) return;
            busy.value = true;
            message.value = '';
            try {
                sourceName.value = file.name;
                const raw = file.type === 'image/png'
                    ? await readPngCharacterData(file)
                    : await file.text();
                try {
                    profile.value = profileFromImported(JSON.parse(raw));
                } catch {
                    const result = await validateCharacter(raw, CURRENT_CHAPTER_INDEX);
                    profile.value = result.suggested_profile || null;
                }
                if (!profile.value?.name) throw new Error('文件中没有可用的人物资料');
            } catch (error) {
                profile.value = null;
                message.value = error.message || '人物导入失败';
            } finally {
                busy.value = false;
            }
        }

        async function save() {
            if (!profile.value?.name || !location.value.trim()) return;
            busy.value = true;
            message.value = '';
            try {
                let locationId = location.value.trim();
                try {
                    const locationData = await getLocationByName(locationId);
                    locationId = locationData.id || locationId;
                } catch {
                    // Custom locations remain valid in this open-world game.
                }
                await addNPC({
                    id: `npc_custom_${Date.now()}_${profile.value.name}`,
                    name: profile.value.name,
                    gender: profile.value.gender || '未知',
                    profile: {
                        identity: profile.value.identity || '幻想乡住民',
                        description: profile.value.appearance || profile.value.description || '',
                        personality: profile.value.personality || '',
                        personality_traits: String(profile.value.personality || '').split(/[，,、]/).filter(Boolean),
                        background: profile.value.background || '',
                        imported_from: sourceName.value || 'player_creation',
                        imported_at: new Date().toISOString()
                    },
                    location_id: locationId,
                    active: true,
                    dead: false
                });
                await refreshNPCList();
                closeAppModal();
                window.dispatchEvent(new CustomEvent('touhou:toast', {
                    detail: { message: `人物「${profile.value.name}」已加入当前世界`, type: 'success' }
                }));
            } catch (error) {
                message.value = error.message || '人物保存失败';
            } finally {
                busy.value = false;
            }
        }

        return {
            busy, closeAppModal, description, generate, importFile, importOnly,
            location, message, profile, save, sourceName
        };
    },
    template: `
        <div class="vue-modal-backdrop" @click.self="closeAppModal">
            <section class="record-dialog npc-record-dialog" role="dialog" aria-modal="true">
                <header class="record-dialog__header"><div><small>自由人物</small><strong>添加自定义角色</strong></div><button class="icon-button" title="关闭" @click="closeAppModal">×</button></header>
                <div class="record-dialog__body">
                    <template v-if="!profile">
                        <label v-if="!importOnly" class="field-stack"><span>人物设定</span><textarea v-model="description" rows="7" placeholder="描述身份、外貌、性格、能力和故事钩子"></textarea></label>
                        <div class="dialog-command-row" :class="{ 'is-single': importOnly }">
                            <button v-if="!importOnly" class="primary-command" type="button" :disabled="busy" @click="generate">{{ busy ? '正在整理...' : 'AI 整理人物' }}</button>
                            <label class="file-command"><input type="file" accept="image/png,application/json,.json,.txt" @change="importFile"><span>从文件导入</span></label>
                        </div>
                    </template>
                    <template v-else>
                        <div class="import-preview">
                            <strong>{{ profile.name }}</strong><span>{{ profile.identity || '幻想乡住民' }}</span>
                            <p>{{ profile.appearance || profile.description }}</p><p>{{ profile.personality }}</p>
                        </div>
                        <label class="field-stack"><span>出现地点</span><input v-model="location" placeholder="任意地点名称"></label>
                        <div class="dialog-command-row">
                            <button class="primary-command" type="button" :disabled="busy" @click="save">{{ busy ? '正在写入...' : '加入人物名册' }}</button>
                            <button type="button" :disabled="busy" @click="profile = null">重新选择</button>
                        </div>
                    </template>
                    <p v-if="message" class="dialog-status is-error">{{ message }}</p>
                </div>
            </section>
        </div>
    `
});

export const HelperDialog = defineComponent({
    name: 'HelperDialog',
    setup() {
        const query = ref('');
        const answer = ref('');
        const pendingTask = ref(null);
        const busy = ref(false);
        const message = ref('');
        const commands = [
            ['状态梳理', '结合我的玩家状态、资源、关系和当前位置，梳理当前局势与可做的事情。'],
            ['线索建议', '根据当前异变、已知线索和位置，给出三条不限制探索路线的行动建议。'],
            ['自由目标', '根据我目前的经历生成一个可自由接受或忽略的个人目标。']
        ];

        function chooseCommand(item) {
            query.value = item[1];
        }

        async function ask() {
            if (!query.value.trim()) return;
            busy.value = true;
            message.value = '';
            pendingTask.value = null;
            try {
                const [locations, npcs] = await Promise.all([getAllLocations(), getAllNPCs()]);
                const result = await systemHelper(
                    state.currentSession.characterId,
                    query.value.trim(),
                    state.currentSession.profile?.name || '玩家',
                    state.currentSession.profile?.identity || '旅行者',
                    state.currentSession.currentScene,
                    state.currentSession.resources || {},
                    state.currentSession.reputation || {},
                    (locations.locations || []).map(item => item.name),
                    state.currentSession.currentGoals || [],
                    state.tasks.active || [],
                    state.chatHistory.slice(-8),
                    { npcs: npcs.npcs || [], worldview: '东方Project幻想乡' }
                );
                answer.value = renderMarkdownLite(result.description || '手札暂时没有新的记录。');
                pendingTask.value = result.task_generated ? (result.task_data || result.task) : null;
            } catch (error) {
                message.value = error.message || '手札回应失败';
            } finally {
                busy.value = false;
            }
        }

        async function acceptTask() {
            if (!pendingTask.value) return;
            busy.value = true;
            try {
                await fetch('/api/ghost/add_task', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        character_id: state.currentSession.characterId,
                        task: {
                            ...pendingTask.value,
                            source: pendingTask.value.source || 'system_helper'
                        }
                    })
                }).then(response => {
                    if (!response.ok) throw new Error('线索写入失败');
                });
                pendingTask.value = null;
                await refreshTasksPanel();
                window.dispatchEvent(new CustomEvent('touhou:toast', {
                    detail: { message: '自由目标已写入线索板', type: 'success' }
                }));
            } catch (error) {
                message.value = error.message || '目标写入失败';
            } finally {
                busy.value = false;
            }
        }

        return {
            acceptTask, answer, ask, busy, chooseCommand, closeAppModal,
            commands, message, pendingTask, query
        };
    },
    template: `
        <div class="vue-modal-backdrop" @click.self="closeAppModal">
            <section class="record-dialog helper-record-dialog" role="dialog" aria-modal="true">
                <header class="record-dialog__header"><div><small>调查辅助</small><strong>异变手札</strong></div><button class="icon-button" title="关闭" @click="closeAppModal">×</button></header>
                <div class="record-dialog__body">
                    <div class="helper-command-strip"><button v-for="item in commands" :key="item[0]" type="button" @click="chooseCommand(item)">{{ item[0] }}</button></div>
                    <label class="field-stack"><span>询问手札</span><textarea v-model="query" rows="4" placeholder="询问状态、线索，或让手札记录一个自由目标"></textarea></label>
                    <button class="primary-command helper-submit" type="button" :disabled="busy || !query.trim()" @click="ask">{{ busy ? '正在检索记录...' : '翻阅手札' }}</button>
                    <div v-if="answer" class="helper-answer" v-html="answer"></div>
                    <section v-if="pendingTask" class="pending-task">
                        <small>可选目标</small><strong>{{ pendingTask.name || '新的个人目标' }}</strong><p>{{ pendingTask.description }}</p>
                        <div><button class="primary-command" :disabled="busy" @click="acceptTask">写入线索板</button><button :disabled="busy" @click="pendingTask = null">暂不记录</button></div>
                    </section>
                    <p v-if="message" class="dialog-status is-error">{{ message }}</p>
                </div>
            </section>
        </div>
    `
});
