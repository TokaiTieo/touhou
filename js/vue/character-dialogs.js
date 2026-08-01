import { computed, defineComponent, reactive, ref } from '../vendor/vue.esm-browser.prod.js';
import {
    createCharacter,
    importCharacter,
    listCharacters,
    validateCharacter
} from '../api.js';
import { state } from '../ghost/core/state.js';
import { CURRENT_CHAPTER_INDEX } from '../ghost/core/constants.js';
import { appUi, closeAppModal } from './app-store.js';

const BASE_TEMPLATES = [
    {
        id: 'outsider',
        name: '外界误入者',
        description: '我是从外界误入幻想乡的年轻人，身上残留结界裂隙的红白光尘。性格谨慎但好奇，渴望在异变中保护自己，也可能与幻想乡少女发展暧昧或恋爱关系。'
    },
    {
        id: 'onmyoji',
        name: '见习阴阳师',
        description: '我是见习阴阳师，能看见结界裂隙和灵力流动，擅长符纸、净化和基础弹幕。性格认真，对亲密关系略显青涩。'
    },
    {
        id: 'researcher',
        name: '魔法研究者',
        description: '我是追寻幻想魔法的研究者，带着魔导笔记来到幻想乡。擅长分析弹幕、采集魔力样本和改造符卡，对魔法使与图书馆抱有强烈好奇。'
    },
    {
        id: 'half_youkais',
        name: '妖怪混血',
        description: '我是人类与妖怪血脉混杂的异类，体内有尚未觉醒的妖力。外貌带有若隐若现的非人特征，性格敏感而执着。'
    },
    {
        id: 'moon_fugitive',
        name: '月都逃亡者',
        description: '我是从月之都逃亡到幻想乡的实验体，掌握少量月科技和精神干涉能力，与永远亭存在很深的剧情牵引。'
    },
    {
        id: 'anomaly_core',
        name: '失忆异变核心',
        description: '我在博丽神社醒来，失去了进入幻想乡前的记忆，身体似乎就是结界裂隙的一部分，适合主线、恋爱与长期关系展开。'
    },
    {
        id: 'custom',
        name: '完全自定义',
        description: ''
    }
];

const PRODUCER_TRIGGER = String.fromCodePoint(
    0x3010, 0x6211, 0x662f, 0x6e38, 0x620f, 0x5236, 0x4f5c, 0x4eba, 0x3011
);

function emptyProfile() {
    return {
        name: '',
        age: '20',
        gender: '',
        identity: '',
        appearance: '',
        personality: '',
        background: ''
    };
}

function producerTemplate() {
    return {
        id: 'producer',
        name: '游戏制作人专用',
        description: `${PRODUCER_TRIGGER}。我是二十五岁的本游戏制作人，以最高权限进入幻想乡；所有能力、灵力、符卡熟练度、恢复力和命运干预力均为最高，可以轻松处理所有对手与异变。`
    };
}

export const CharacterCreationDialog = defineComponent({
    name: 'CharacterCreationDialog',
    setup() {
        const phase = ref('describe');
        const description = ref('');
        const profile = reactive(emptyProfile());
        const busy = ref(false);
        const message = ref('');
        const templates = computed(() => (
            description.value.includes(PRODUCER_TRIGGER)
                ? [...BASE_TEMPLATES, producerTemplate()]
                : BASE_TEMPLATES
        ));

        function chooseTemplate(template) {
            description.value = template.description;
        }

        function editProfile(source = {}) {
            for (const key of Object.keys(profile)) delete profile[key];
            Object.assign(profile, emptyProfile(), source || {});
        }

        async function organize() {
            if (!description.value.trim()) {
                message.value = '请先写下角色设定。';
                return;
            }
            busy.value = true;
            message.value = '';
            try {
                const result = await validateCharacter(description.value.trim(), CURRENT_CHAPTER_INDEX);
                if (!result.valid || !result.suggested_profile) {
                    throw new Error(result.message || '未能整理角色设定');
                }
                editProfile(result.suggested_profile);
                phase.value = 'review';
            } catch (error) {
                message.value = error.message || '设定整理失败';
            } finally {
                busy.value = false;
            }
        }

        function manual() {
            editProfile();
            phase.value = 'manual';
        }

        async function create() {
            if (!profile.name.trim() || !profile.identity.trim()) {
                message.value = '姓名与身份不能为空。';
                return;
            }
            busy.value = true;
            message.value = '';
            try {
                const result = await createCharacter({ ...profile }, CURRENT_CHAPTER_INDEX);
                state.isCreatingCharacter = false;
                closeAppModal();
                window.dispatchEvent(new CustomEvent('touhou:toast', {
                    detail: { message: `角色「${profile.name}」创建成功`, type: 'success' }
                }));
                const { loadAndEnterGhostMode } = await import('../ghost/core/session.js');
                await loadAndEnterGhostMode(result.character_id, result.starting_location || '博丽神社');
            } catch (error) {
                message.value = error.message || '角色创建失败';
            } finally {
                busy.value = false;
            }
        }

        return {
            busy,
            chooseTemplate,
            closeAppModal,
            create,
            description,
            manual,
            message,
            organize,
            phase,
            profile,
            templates
        };
    },
    template: `
        <div class="vue-modal-backdrop" @click.self="closeAppModal">
            <section class="record-dialog character-creation-dialog" role="dialog" aria-modal="true" aria-labelledby="createCharacterTitle">
                <header class="record-dialog__header">
                    <div><small>新异变记录</small><strong id="createCharacterTitle">创建角色</strong></div>
                    <button class="icon-button" type="button" title="关闭" aria-label="关闭" @click="closeAppModal">×</button>
                </header>
                <div class="record-dialog__body">
                    <template v-if="phase === 'describe'">
                        <div class="template-grid">
                            <button v-for="template in templates" :key="template.id" type="button" :class="{ active: description === template.description }" @click="chooseTemplate(template)">
                                {{ template.name }}
                            </button>
                        </div>
                        <label class="field-stack">
                            <span>角色设定</span>
                            <textarea v-model="description" rows="8" placeholder="写下身份、外貌、性格、能力与来到幻想乡的缘由"></textarea>
                        </label>
                        <div class="dialog-command-row">
                            <button class="primary-command" type="button" :disabled="busy" @click="organize">{{ busy ? '正在整理...' : 'AI 整理设定' }}</button>
                            <button type="button" :disabled="busy" @click="manual">手动填写</button>
                        </div>
                    </template>
                    <template v-else>
                        <div class="profile-form">
                            <label><span>姓名</span><input v-model="profile.name" maxlength="40"></label>
                            <label><span>年龄</span><input v-model="profile.age" inputmode="numeric" maxlength="3"></label>
                            <label><span>性别</span><input v-model="profile.gender" maxlength="30"></label>
                            <label><span>身份</span><input v-model="profile.identity" maxlength="80"></label>
                            <label class="wide"><span>外貌</span><textarea v-model="profile.appearance" rows="3"></textarea></label>
                            <label class="wide"><span>性格</span><textarea v-model="profile.personality" rows="3"></textarea></label>
                            <label class="wide"><span>背景</span><textarea v-model="profile.background" rows="5"></textarea></label>
                        </div>
                        <div class="dialog-command-row">
                            <button class="primary-command" type="button" :disabled="busy" @click="create">{{ busy ? '正在写入...' : '确认并开始' }}</button>
                            <button type="button" :disabled="busy" @click="phase = 'describe'">返回修改</button>
                        </div>
                    </template>
                    <p v-if="message" class="dialog-status is-error">{{ message }}</p>
                </div>
            </section>
        </div>
    `
});

export async function readPngCharacterData(file) {
    const buffer = await file.arrayBuffer();
    const view = new DataView(buffer);
    const signature = [137, 80, 78, 71, 13, 10, 26, 10];
    if (signature.some((value, index) => view.getUint8(index) !== value)) {
        throw new Error('不是有效的 PNG 文件');
    }
    let position = 8;
    while (position + 12 <= buffer.byteLength) {
        const length = view.getUint32(position);
        const type = new TextDecoder().decode(new Uint8Array(buffer, position + 4, 4));
        if (type === 'tEXt') {
            const bytes = new Uint8Array(buffer, position + 8, length);
            const divider = bytes.indexOf(0);
            const keyword = new TextDecoder().decode(bytes.slice(0, divider));
            if (keyword === 'CharacterData') {
                return new TextDecoder().decode(bytes.slice(divider + 1));
            }
        }
        position += length + 12;
    }
    throw new Error('PNG 中没有角色数据');
}

export const CharacterImportDialog = defineComponent({
    name: 'CharacterImportDialog',
    setup() {
        const busy = ref(false);
        const message = ref('');
        const fileName = ref('');
        const payload = ref(null);

        async function choose(event) {
            const file = event.target.files?.[0];
            if (!file) return;
            busy.value = true;
            message.value = '';
            try {
                fileName.value = file.name;
                const raw = file.type === 'image/png' ? await readPngCharacterData(file) : await file.text();
                payload.value = JSON.parse(raw);
            } catch (error) {
                payload.value = null;
                message.value = error.message || '无法读取角色文件';
            } finally {
                busy.value = false;
            }
        }

        async function confirmImport() {
            if (!payload.value) return;
            busy.value = true;
            try {
                await importCharacter(payload.value);
                const result = await listCharacters('world_touhou');
                appUi.characters = result.characters || [];
                closeAppModal();
                window.dispatchEvent(new CustomEvent('touhou:toast', {
                    detail: { message: '角色存档已导入', type: 'success' }
                }));
            } catch (error) {
                message.value = error.message || '导入失败';
            } finally {
                busy.value = false;
            }
        }

        const profile = computed(() => payload.value?.profile || payload.value || {});
        return { busy, choose, closeAppModal, confirmImport, fileName, message, payload, profile };
    },
    template: `
        <div class="vue-modal-backdrop" @click.self="closeAppModal">
            <section class="record-dialog compact-dialog" role="dialog" aria-modal="true">
                <header class="record-dialog__header"><div><small>外部记录</small><strong>导入角色</strong></div><button class="icon-button" title="关闭" @click="closeAppModal">×</button></header>
                <div class="record-dialog__body">
                    <label class="file-drop">
                        <input type="file" accept="image/png,application/json,.json" @change="choose">
                        <span>{{ fileName || '选择角色 PNG 或 JSON 文件' }}</span>
                    </label>
                    <div v-if="payload" class="import-preview">
                        <strong>{{ profile.name || '未命名角色' }}</strong>
                        <span>{{ profile.identity || '身份未记录' }}</span>
                        <p>{{ profile.background || '背景未记录' }}</p>
                    </div>
                    <p v-if="message" class="dialog-status is-error">{{ message }}</p>
                    <div class="dialog-command-row">
                        <button class="primary-command" type="button" :disabled="busy || !payload" @click="confirmImport">{{ busy ? '处理中...' : '确认导入' }}</button>
                        <button type="button" :disabled="busy" @click="closeAppModal">取消</button>
                    </div>
                </div>
            </section>
        </div>
    `
});
