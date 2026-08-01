import {
    computed,
    defineComponent,
    onBeforeUnmount,
    onMounted,
    ref
} from '../vendor/vue.esm-browser.prod.js';
import { CharacterSelection } from './character-selection.js';
import { CharacterCreationDialog, CharacterImportDialog } from './character-dialogs.js';
import { GameScreen, GameToolbar } from './game-screen.js';
import { DetailDialog, HelperDialog, NpcCreationDialog, RelationshipsDialog } from './game-dialogs.js';
import { gameUi } from './game-ui.js';
import { ProducerConsole } from './producer-console.js';
import { SettingsDialog } from './settings-dialog.js';
import { appUi, closeAppModal } from './app-store.js';

const THEME_KEY = 'touhou_theme';

export const TouhouApp = defineComponent({
    name: 'TouhouApp',
    components: {
        CharacterSelection,
        CharacterCreationDialog,
        CharacterImportDialog,
        GameScreen,
        GameToolbar,
        DetailDialog,
        HelperDialog,
        NpcCreationDialog,
        RelationshipsDialog,
        ProducerConsole,
        SettingsDialog
    },
    setup() {
        const ready = ref(false);
        const startupError = ref('');
        const loading = ref(false);
        const loadingMessage = ref('正在进入幻想乡...');
        const toast = ref(null);
        const developerMode = ref(false);
        const appVersion = window.TOUHOU_APP_VERSION || 'dev';
        const theme = ref(localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark');
        let toastTimer = null;

        const themeLabel = computed(() => theme.value === 'light' ? '切换为夜间主题' : '切换为日间主题');
        const gameSceneStyle = computed(() => (
            appUi.view === 'game'
                ? { '--scene-background': `url("${appUi.sceneArtwork}")` }
                : {}
        ));

        function applyTheme() {
            document.body.classList.toggle('light-theme', theme.value === 'light');
            document.documentElement.dataset.theme = theme.value;
        }

        function toggleTheme() {
            theme.value = theme.value === 'light' ? 'dark' : 'light';
            localStorage.setItem(THEME_KEY, theme.value);
            applyTheme();
        }

        function reloadApp() {
            window.location.reload();
        }

        async function playCharacter(characterId, scene) {
            const { loadAndEnterGhostMode } = await import('../ghost/core/session.js');
            await loadAndEnterGhostMode(characterId, scene);
        }

        async function testAi() {
            const { testAIConnection } = await import('../ghost/modules/chat.js');
            await testAIConnection();
        }

        async function shutdownApp() {
            if (!window.confirm('确定退出东方异变录吗？当前进度会保留。')) return;
            try {
                await fetch('/api/shutdown', { method: 'POST' });
            } finally {
                window.close();
            }
        }

        function showToast(detail = {}) {
            const normalized = typeof detail === 'string' ? { message: detail } : detail;
            toast.value = {
                message: normalized.message || '操作完成',
                type: normalized.type || 'info'
            };
            clearTimeout(toastTimer);
            toastTimer = setTimeout(() => { toast.value = null; }, normalized.duration || 3000);
        }

        function onLoadingStart(event) {
            loadingMessage.value = event.detail?.message || event.detail || '加载中...';
            loading.value = true;
        }

        function onLoadingEnd() {
            loading.value = false;
        }

        function onReady() {
            ready.value = true;
            startupError.value = '';
        }

        function onStartupError(event) {
            ready.value = true;
            startupError.value = event.detail?.message || '前端启动失败，请重新启动游戏。';
        }

        function onDeveloperMode(event) {
            developerMode.value = event.detail?.enabled === true;
        }

        onMounted(() => {
            applyTheme();
            window.addEventListener('touhou:loading-start', onLoadingStart);
            window.addEventListener('touhou:loading-end', onLoadingEnd);
            window.addEventListener('touhou:toast', event => showToast(event.detail));
            window.addEventListener('touhou:ready', onReady);
            window.addEventListener('touhou:startup-error', onStartupError);
            window.addEventListener('touhou:developer-mode', onDeveloperMode);
        });

        onBeforeUnmount(() => {
            clearTimeout(toastTimer);
            window.removeEventListener('touhou:loading-start', onLoadingStart);
            window.removeEventListener('touhou:loading-end', onLoadingEnd);
            window.removeEventListener('touhou:ready', onReady);
            window.removeEventListener('touhou:startup-error', onStartupError);
            window.removeEventListener('touhou:developer-mode', onDeveloperMode);
        });

        return {
            loading,
            loadingMessage,
            developerMode,
            appVersion,
            appUi,
            closeAppModal,
            gameSceneStyle,
            ready,
            reloadApp,
            playCharacter,
            startupError,
            testAi,
            theme,
            themeLabel,
            toast,
            toggleTheme,
            shutdownApp,
            gameUi
        };
    },
    template: `
        <div class="touhou-vue-shell">
            <header class="app-chrome">
                <div class="app-brand" aria-label="东方异变录">
                    <img src="/static/static/touhou-favicon.svg" alt="" class="app-brand-mark">
                    <span class="app-brand-copy">
                        <strong>东方异变录</strong>
                        <small>幻想乡异变记录</small>
                    </span>
                </div>
                <div id="appGameToolbar" class="app-game-toolbar" :class="{ 'has-content': gameUi.active }" aria-live="polite">
                    <GameToolbar />
                </div>
                <div class="app-chrome-actions">
                    <span v-if="developerMode" class="app-runtime-badge" title="仅制作人模式可见"><i aria-hidden="true"></i> DEV · Vue 3 · {{ appVersion }}</span>
                    <button class="icon-button" type="button" :title="themeLabel" :aria-label="themeLabel" @click="toggleTheme">
                        <span aria-hidden="true">{{ theme === 'light' ? '夜' : '昼' }}</span>
                    </button>
                    <button class="icon-button" type="button" title="退出游戏" aria-label="退出游戏" @click="shutdownApp">
                        <span aria-hidden="true">关</span>
                    </button>
                </div>
            </header>

            <main id="gameView" class="game-view" :class="'view-' + appUi.view" :style="gameSceneStyle">
                <section v-if="appUi.view === 'boot' && !startupError" class="vue-boot-state" aria-live="polite">
                    <img src="/static/static/touhou-favicon.svg" alt="" class="vue-boot-mark">
                    <div class="loading-spinner"></div>
                    <p>正在展开幻想乡的记录...</p>
                </section>
                <section v-if="startupError" class="vue-error-state" role="alert">
                    <strong>未能进入幻想乡</strong>
                    <p>{{ startupError }}</p>
                    <button type="button" class="ghost-btn" @click="reloadApp">重新加载</button>
                </section>
                <section v-else-if="appUi.view === 'characters'" class="character-screen">
                    <header class="screen-bar">
                        <div class="screen-context">
                            <span class="screen-context-mark" aria-hidden="true">界</span>
                            <span><strong>幻想乡</strong><small>异变记录 / 角色选择</small></span>
                        </div>
                        <div class="menu-tools">
                            <button id="apiKeyBtnMenu" class="ghost-btn" title="API Key 设置" @click="appUi.modal = 'settings'">钥匙 · API</button>
                            <button id="testAIBtnMenu" class="ghost-btn" title="测试 AI 连接" @click="testAi">试 · 连接</button>
                        </div>
                    </header>
                    <div class="touhou-hero">
                        <div class="touhou-hero-content">
                            <div class="touhou-hero-kicker">幻想乡异变记录</div>
                            <h1>开放异变档案</h1>
                            <p>循着大结界的微光自由调查。你的对话、探索与符卡，会写下新的幻想乡缘起。</p>
                        </div>
                        <div class="touhou-hero-seal" aria-hidden="true"><span>東</span><span>方</span></div>
                    </div>
                    <section class="character-records">
                        <div class="section-title"><span aria-hidden="true">記</span><strong>异变记录</strong></div>
                        <CharacterSelection :initial-characters="appUi.characters" :world="appUi.world" :on-play="playCharacter" />
                    </section>
                </section>
                <GameScreen v-else-if="appUi.view === 'game'" />
            </main>

            <SettingsDialog v-if="appUi.modal === 'settings'" :on-close="closeAppModal" />
            <ProducerConsole v-if="appUi.modal === 'producer'" :on-close="closeAppModal" />
            <CharacterCreationDialog v-if="appUi.modal === 'character-create'" />
            <CharacterImportDialog v-if="appUi.modal === 'character-import'" />
            <DetailDialog v-if="appUi.modal === 'detail'" />
            <RelationshipsDialog v-if="appUi.modal === 'relationships'" />
            <NpcCreationDialog v-if="appUi.modal === 'npc-create'" />
            <HelperDialog v-if="appUi.modal === 'helper'" />

            <Transition name="toast">
                <div v-if="toast" class="vue-toast" :class="'is-' + toast.type" role="status">
                    {{ toast.message }}
                </div>
            </Transition>

            <Transition name="fade">
                <div v-if="loading" class="vue-loading-overlay" role="status" aria-live="polite">
                    <div class="vue-loading-card">
                        <div class="loading-spinner"></div>
                        <span>{{ loadingMessage }}</span>
                    </div>
                </div>
            </Transition>
        </div>
    `
});
