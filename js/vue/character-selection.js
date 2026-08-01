import { computed, defineComponent, ref } from '../vendor/vue.esm-browser.prod.js';
import { convertToNPC as apiConvertToNPC, deleteCharacter, listCharacters, listSnapshots, restoreSnapshot } from '../api.js';
import { appUi, openAppModal } from './app-store.js';

export const CharacterSelection = defineComponent({
    name: 'CharacterSelection',
    props: {
        initialCharacters: { type: Array, default: () => [] },
        world: { type: Object, default: () => ({}) },
        onPlay: { type: Function, required: true }
    },
    setup(props) {
        const characters = computed(() => appUi.characters);
        const busyId = ref('');
        const snapshotCharacter = ref(null);
        const snapshots = ref([]);
        const snapshotLoading = ref(false);
        const branchName = ref('');

        async function refresh() {
            const result = await listCharacters(props.world.id || 'world_touhou');
            appUi.characters = result.characters || [];
        }

        async function play(character) {
            busyId.value = character.character_id;
            try {
                await props.onPlay(character.character_id, character.current_scene || null);
            } finally {
                busyId.value = '';
            }
        }

        function createCharacter() {
            openAppModal('character-create');
        }

        function importCharacter(type) {
            openAppModal(type === 'npc' ? 'npc-create' : 'character-import', {
                importOnly: type === 'npc'
            });
        }

        async function removeCharacter(character) {
            if (!window.confirm(`确定删除「${character.profile?.name || '未命名角色'}」吗？`)) return;
            busyId.value = character.character_id;
            try {
                await deleteCharacter(character.character_id);
                await refresh();
                window.dispatchEvent(new CustomEvent('touhou:toast', { detail: { message: '角色已删除', type: 'success' } }));
            } finally {
                busyId.value = '';
            }
        }

        async function exportCharacter(character) {
            const { exportCharacterToPNG } = await import('./export-character.js');
            await exportCharacterToPNG(character.character_id);
        }

        async function convertToNPC(character) {
            if (!window.confirm(`将「${character.profile?.name || '该角色'}」转为 NPC 吗？原角色存档会被归档。`)) return;
            busyId.value = character.character_id;
            try {
                await apiConvertToNPC(character.character_id);
                await refresh();
                window.dispatchEvent(new CustomEvent('touhou:toast', {
                    detail: { message: '角色已转入幻想乡人物名册', type: 'success' }
                }));
            } finally {
                busyId.value = '';
            }
        }

        async function openSnapshots(character) {
            snapshotCharacter.value = character;
            branchName.value = `${character.profile?.name || '角色'} · 分支`;
            snapshotLoading.value = true;
            try {
                const result = await listSnapshots(character.character_id);
                snapshots.value = result.snapshots || [];
            } finally {
                snapshotLoading.value = false;
            }
        }

        function closeSnapshots() {
            snapshotCharacter.value = null;
            snapshots.value = [];
        }

        async function restore(item, asBranch) {
            if (!snapshotCharacter.value) return;
            const action = asBranch ? '创建分支存档' : '覆盖当前进度';
            if (!window.confirm(`确定从此节点${action}吗？`)) return;
            snapshotLoading.value = true;
            try {
                const result = await restoreSnapshot(
                    snapshotCharacter.value.character_id,
                    item.snapshot_id,
                    asBranch,
                    asBranch ? branchName.value.trim() : null
                );
                await refresh();
                closeSnapshots();
                window.dispatchEvent(new CustomEvent('touhou:toast', {
                    detail: { message: asBranch ? '分支存档已创建' : '进度已恢复', type: 'success' }
                }));
                if (!asBranch) {
                    const restored = appUi.characters.find(char => char.character_id === result.character_id);
                    if (restored) await play(restored);
                }
            } finally {
                snapshotLoading.value = false;
            }
        }

        function formatSnapshotTime(value) {
            if (!value) return '未知时间';
            return new Date(value).toLocaleString('zh-CN', { hour12: false });
        }

        return {
            branchName,
            busyId,
            characters,
            closeSnapshots,
            convertToNPC,
            createCharacter,
            exportCharacter,
            formatSnapshotTime,
            importCharacter,
            openSnapshots,
            play,
            removeCharacter,
            restore,
            snapshotCharacter,
            snapshotLoading,
            snapshots
        };
    },
    template: `
        <div class="vue-character-selection">
            <div class="world-info touhou-world-info">
                <span class="world-info-label">当前舞台</span>
                <span class="world-info-name">{{ world.name || '幻想乡 - 东方Project' }}</span>
                <span class="world-info-note">第一章：结界裂隙异变</span>
            </div>

            <div v-if="!characters.length" class="empty-character-state">尚无异变记录。创建角色后，你会在博丽神社醒来。</div>

            <div class="vue-character-list">
                <article v-for="(character, index) in characters" :key="character.character_id" class="character-card" :class="character.is_dead ? 'dead' : 'alive'">
                    <div class="character-record-seal" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</div>
                    <div class="character-card-info">
                        <strong>{{ character.profile?.name || '未命名' }}</strong>
                        <span>{{ character.profile?.identity || '旅行者' }}</span>
                        <small>地点 · {{ character.current_scene || '未知' }}</small>
                    </div>
                    <div class="character-card-actions">
                        <button class="character-play-btn" :disabled="busyId === character.character_id" @click="play(character)">继续异变</button>
                        <button class="character-snapshot-btn" @click="openSnapshots(character)">时序</button>
                        <button class="character-export-btn" @click="exportCharacter(character)">导出</button>
                        <button class="character-to-npc-btn" @click="convertToNPC(character)">转为NPC</button>
                        <button class="character-delete-btn" @click="removeCharacter(character)">删除</button>
                    </div>
                </article>
            </div>

            <div class="character-actions with-border">
                <button class="action-btn primary" @click="createCharacter">创建新外来者</button>
                <button class="action-btn" @click="importCharacter('player')">导入角色</button>
                <button class="action-btn secondary" @click="importCharacter('npc')">导入NPC</button>
            </div>

            <Teleport to="body">
                <div v-if="snapshotCharacter" class="vue-modal-backdrop" @click.self="closeSnapshots">
                    <section class="vue-snapshot-dialog" role="dialog" aria-modal="true" aria-labelledby="snapshotTitle">
                        <header>
                            <div><small>角色时序</small><strong id="snapshotTitle">{{ snapshotCharacter.profile?.name }}</strong></div>
                            <button class="icon-button" title="关闭" aria-label="关闭" @click="closeSnapshots">×</button>
                        </header>
                        <div class="snapshot-branch-name">
                            <label for="branchName">分支名称</label>
                            <input id="branchName" v-model="branchName" maxlength="40">
                        </div>
                        <div v-if="snapshotLoading" class="snapshot-empty">正在读取时序...</div>
                        <div v-else-if="!snapshots.length" class="snapshot-empty">尚无可恢复节点</div>
                        <div v-else class="snapshot-list">
                            <div v-for="item in snapshots" :key="item.snapshot_id" class="snapshot-item">
                                <div><strong>{{ item.label }}</strong><span>{{ item.scene }} · {{ formatSnapshotTime(item.created_at) }}</span></div>
                                <div class="snapshot-actions">
                                    <button @click="restore(item, false)">恢复</button>
                                    <button @click="restore(item, true)">创建分支</button>
                                </div>
                            </div>
                        </div>
                    </section>
                </div>
            </Teleport>
        </div>
    `
});
