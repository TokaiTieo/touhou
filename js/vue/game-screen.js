import {
    computed,
    defineComponent,
    nextTick,
    onBeforeUnmount,
    onMounted,
    ref,
    watch
} from '../vendor/vue.esm-browser.prod.js';
import { state } from '../ghost/core/state.js';
import { renderMarkdownLite, softenPublicText } from '../ghost/ui/text.js';
import { showToast } from '../ghost/ui/components.js';
import {
    fillComposer,
    gameUi,
    refreshGameUi,
    scrollGameChatToBottom
} from './game-ui.js';
import { refreshTasksPanel } from './game-controller.js';
import {
    openLocationDetail,
    openNPCCreationDialog,
    openNPCDetail,
    openPlayerJournal,
    openRelationshipsPanel,
    openSystemHelperDialog
} from './dialog-actions.js';

function npcAccent(name) {
    const palette = ['#c73a4d', '#3e759f', '#4f8b6c', '#a96a3e', '#75569b', '#bd7936', '#39878b'];
    const hash = Array.from(String(name || '')).reduce((total, char) => total + char.codePointAt(0), 0);
    return palette[hash % palette.length];
}

function dangerTone(danger = '') {
    if (danger.includes('极危')) return 'extreme';
    if (danger.includes('高危') || danger.includes('危险')) return 'danger';
    if (danger.includes('注意')) return 'watch';
    if (danger.includes('安全')) return 'safe';
    return 'unknown';
}

function currentLocation() {
    const scene = state.currentSession.currentScene;
    for (const region of state.locationTree || []) {
        const location = (region.locations || []).find(item => item.name === scene);
        if (location) return location;
    }
    return null;
}

function buildSuggestions() {
    const scene = state.currentSession.currentScene || '当前位置';
    const npc = state.currentDialogueNPC || state.currentSceneNPCs?.[0] || null;
    const task = state.tasks?.active?.[0];
    const location = currentLocation();
    const danger = location?.dangerLevel || location?.danger_level || '';
    const relationship = npc?.name ? state.currentSession.relationshipsMap?.[npc.name] : '';
    const items = [{
        label: '调查异变',
        mark: '探',
        action: `观察${scene}附近的结界波纹、妖气流向和异常气息`,
        speech: ''
    }];

    if (npc?.name) {
        items.push({
            label: `询问${npc.name}`,
            mark: '问',
            action: `走向${npc.name}，留意对方的表情、距离和态度变化`,
            speech: `${npc.name}，你知道这次结界裂隙异变的线索吗？`
        });
        if (relationship) {
            items.push({
                label: '推进关系',
                mark: '缘',
                action: `根据${npc.name}当前对你的态度「${relationship}」，尝试拉近距离或制造暧昧氛围`,
                speech: `${npc.name}，我想更了解你真正的想法。`
            });
        }
    } else {
        items.push({ label: '观察周围', mark: '察', action: `仔细观察${scene}中有没有可疑人物或异变痕迹`, speech: '' });
    }

    items.push({
        label: '宣言符卡',
        mark: '符',
        action: `按照符卡规则后退一步，宣言一张试探性的符卡，观察${npc?.name || '对手'}的弹幕规律`,
        speech: '如果要用弹幕解决，那就按幻想乡的规矩来吧。'
    });
    if (danger.includes('危')) {
        items.push({ label: '谨慎探索', mark: '慎', action: `先确认${scene}的危险来源和退路，再继续深入`, speech: '' });
    }
    if (task) {
        items.push({ label: '推进目标', mark: '录', action: `围绕任务「${task.name}」寻找下一条线索`, speech: '' });
    }
    return items.slice(0, 4);
}

const GameToolbar = defineComponent({
    name: 'GameToolbar',
    setup() {
        const snapshot = computed(() => {
            const session = state.currentSession;
            const time = session.time || {};
            const hourRaw = Number(time.current_hour ?? 8);
            const hour = Math.floor(hourRaw);
            const minute = Math.round((hourRaw - hour) * 60).toString().padStart(2, '0');
            const resolved = time.anomaly_state === 'waiting' || time.chapter_status === 'resolved';
            return {
                name: session.profile?.name || '未知',
                identity: session.profile?.identity || '旅行者',
                scene: session.currentScene || '未知地点',
                dead: session.isDead === true,
                gm: session.gmMode === true,
                time: `第${time.current_day || 1}天 ${hour}:${minute}`,
                energy: time.energy_state || '精力充沛',
                node: resolved ? (time.chapter_node_name || '静候新的异变') : `距${time.chapter_node_name || '关键节点'} ${Math.round(time.chapter_time_remaining ?? 72)}小时`
            };
        });

        async function exitGame() {
            const { exitGhostMode } = await import('../ghost/core/session.js');
            await exitGhostMode();
        }
        async function openConsole() {
            const { openProducerConsole } = await import('../ghost/modules/producer-console.js');
            await openProducerConsole();
        }
        function exportFeedback() {
            const id = state.currentSession.characterId;
            if (id) window.location.href = `/api/ghost/export_feedback?character_id=${encodeURIComponent(id)}`;
        }
        async function testAi() {
            const { testAIConnection } = await import('../ghost/modules/chat.js');
            await testAIConnection();
        }

        return { exportFeedback, gameUi, openConsole, snapshot, testAi, exitGame };
    },
    template: `
        <div v-if="gameUi.active" class="th-toolbar">
            <div class="th-player-summary">
                <span class="th-player-seal" aria-hidden="true">人</span>
                <span class="th-player-copy"><strong>{{ snapshot.name }}</strong><small>{{ snapshot.identity }}</small></span>
                <span class="th-toolbar-divider"></span>
                <span class="th-scene-name">{{ snapshot.scene }}</span>
                <span class="th-life-state" :class="snapshot.dead ? 'is-dead' : 'is-alive'">{{ snapshot.dead ? '退场' : '在场' }}</span>
                <span v-if="snapshot.gm" class="th-gm-badge">制作人</span>
            </div>
            <div class="th-time-summary">
                <strong>{{ snapshot.time }}</strong><span>{{ snapshot.energy }}</span><small>{{ snapshot.node }}</small>
            </div>
            <div class="th-toolbar-actions">
                <button v-if="snapshot.gm" type="button" title="高级控制台" @click="openConsole">控</button>
                <button type="button" title="导出测试反馈" @click="exportFeedback">出</button>
                <button type="button" title="测试 AI 连接" @click="testAi">试</button>
                <button type="button" title="返回异变记录" @click="exitGame">返</button>
            </div>
        </div>
    `
});

const ChatMessage = defineComponent({
    name: 'ChatMessage',
    props: { message: { type: Object, required: true }, index: { type: Number, required: true }, last: Boolean },
    emits: ['delete', 'reroll', 'continue'],
    setup(props, { emit }) {
        const kind = computed(() => props.message.isDead ? '終' : (props.message.role === 'user' ? '行' : (props.message.isDialogue ? '話' : (props.message.role === 'system' ? '告' : '述'))));
        const messageClass = computed(() => ({
            'is-player': props.message.role === 'user',
            'is-system': props.message.role === 'system',
            'is-dialogue': props.message.isDialogue,
            'is-dead': props.message.isDead
        }));
        const displayContent = computed(() => {
            const candidateIndex = Number(props.message.activeRewrite ?? -1);
            if (candidateIndex >= 0) {
                return props.message.rewriteCandidates?.[candidateIndex]?.content || props.message.content || '';
            }
            return props.message.content || '';
        });
        const html = computed(() => renderMarkdownLite(String(displayContent.value).trim().replace(/\n{3,}/g, '\n\n')));
        async function copy() {
            await navigator.clipboard?.writeText(displayContent.value);
        }
        function speak() {
            if (!window.speechSynthesis) return;
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(displayContent.value);
            utterance.lang = 'zh-CN';
            window.speechSynthesis.speak(utterance);
        }
        function selectRewrite(index) {
            props.message.activeRewrite = index;
            refreshGameUi();
        }
        async function rate(value) {
            props.message.rating = value;
            if (state.currentSession.characterId && props.message.conversationIndex !== undefined) {
                await fetch('/api/ghost/rate_message', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ character_id: state.currentSession.characterId, message_index: props.message.conversationIndex, rating: value })
                }).catch(() => {});
            }
            refreshGameUi();
        }
        return { copy, emit, html, kind, messageClass, rate, selectRewrite, speak };
    },
    template: `
        <article class="th-message" :class="messageClass">
            <div class="th-message-rail"><span>{{ kind }}</span></div>
            <div class="th-message-body">
                <header><strong>{{ message.speaker }}</strong><span v-if="message.isStreaming" class="th-streaming">书写中</span></header>
                <div class="th-message-content" v-html="html"></div>
                <div v-if="message.rewriteCandidates?.length" class="th-rewrite-variants" aria-label="叙事版本">
                    <button type="button" :class="{ active: (message.activeRewrite ?? -1) === -1 }" @click="selectRewrite(-1)">原文</button>
                    <button v-for="(candidate, candidateIndex) in message.rewriteCandidates" :key="candidate.candidate_id || candidateIndex"
                        type="button" :class="{ active: message.activeRewrite === candidateIndex }" @click="selectRewrite(candidateIndex)">
                        改写 {{ candidateIndex + 1 }}
                    </button>
                </div>
                <footer class="th-message-tools">
                    <button type="button" title="复制" @click="copy">复制</button>
                    <button v-if="message.role === 'assistant'" type="button" title="朗读" @click="speak">朗读</button>
                    <button v-if="message.role === 'assistant'" type="button" :class="{ active: message.rating === 'up' }" title="满意" @click="rate('up')">好</button>
                    <button v-if="message.role === 'assistant'" type="button" :class="{ active: message.rating === 'down' }" title="需改进" @click="rate('down')">改</button>
                    <button v-if="message.role === 'assistant' && !message.isStreaming && message.conversationIndex !== undefined"
                        type="button" :disabled="message.isRewriting" title="生成措辞候选，不重放回合" @click="emit('reroll', index)">
                        {{ message.isRewriting ? '润色中' : '重写' }}
                    </button>
                    <button type="button" class="is-danger" title="从此处删除" @click="emit('delete', index)">删除</button>
                </footer>
                <button v-if="last && message.isDialogue && !message.isStreaming" class="th-dialogue-continue" type="button" @click="emit('continue')">静候对方继续</button>
            </div>
        </article>
    `
});

const MapPanel = defineComponent({
    name: 'MapPanel',
    props: { regions: Array, scene: String },
    emits: ['travel', 'detail'],
    setup() { return { dangerTone }; },
    template: `
        <div class="th-map">
            <div v-if="!regions?.length" class="th-empty">尚未绘入可探索地点</div>
            <section v-for="region in regions" :key="region.name" class="th-map-region">
                <h4><span>{{ region.icon || '界' }}</span>{{ region.name }}</h4>
                <button v-for="location in region.locations" :key="location.name" type="button" class="th-location"
                    :class="{ current: location.name === scene }" @click="$emit('travel', location)">
                    <span class="th-location-mark">{{ location.icon || '・' }}</span>
                    <span class="th-location-copy"><strong>{{ location.name }}</strong><small>{{ location.dangerNote || location.danger_note || '可自由探索' }}</small></span>
                    <span class="th-danger" :class="dangerTone(location.dangerLevel || location.danger_level)">{{ location.dangerLevel || location.danger_level || '未知' }}</span>
                    <span v-if="location.name === scene" class="th-current">此处</span>
                    <span class="th-detail-link" title="查看地点详情" @click.stop="$emit('detail', location.name)">详</span>
                </button>
            </section>
        </div>
    `
});

const NpcPanel = defineComponent({
    name: 'NpcPanel',
    props: { npcs: Array },
    emits: ['helper', 'detail', 'observe', 'talk', 'add'],
    setup() { return { npcAccent }; },
    template: `
        <div class="th-encounters">
            <button type="button" class="th-helper-record" @click="$emit('helper')">
                <span>札</span><span><strong>异变手札</strong><small>线索、目标与游玩帮助</small></span><i>打开</i>
            </button>
            <article v-for="npc in npcs" :key="npc.id" class="th-npc" :style="{ '--npc-accent': npcAccent(npc.name || npc.id) }">
                <div class="th-npc-avatar">
                    <img :src="'/avatars/' + encodeURIComponent(npc.id) + '.png'" :alt="npc.name" @error="$event.target.style.display='none'">
                    <span>{{ (npc.name || '?').slice(0, 1) }}</span>
                </div>
                <div class="th-npc-copy"><strong>{{ npc.name }}</strong><small>{{ npc.profile?.identity || '幻想乡居民' }}</small><small v-if="npc.schedule_status">{{ npc.schedule_status }}</small></div>
                <div class="th-npc-actions">
                    <button type="button" title="人物详情" @click="$emit('detail', npc)">详</button>
                    <button type="button" title="观察" @click="$emit('observe', npc)">察</button>
                    <button type="button" class="primary" title="开始对话" @click="$emit('talk', npc)">话</button>
                </div>
            </article>
            <button type="button" class="th-add-npc" @click="$emit('add')">＋ 添加自定义角色</button>
        </div>
    `
});

const TaskPanel = defineComponent({
    name: 'TaskPanel',
    props: { active: Array, completed: Array, incident: Object },
    emits: ['delete'],
    setup() { return { gameUi, softenPublicText }; },
    template: `
        <div class="th-tasks">
            <div class="th-chapter-note"><span>异</span><div><strong>{{ incident?.title || '幻想乡异变' }}</strong><small>开放线索，探索路线不受限制</small></div></div>
            <div v-if="!active?.length" class="th-empty">暂无线索。你仍然可以自由前往任何地点。</div>
            <article v-for="task in active" :key="task.id" class="th-task" :class="{ urgent: (task.priority ?? 100) <= 30 }">
                <span class="th-task-pin">{{ (task.priority ?? 100) <= 30 ? '急' : '记' }}</span>
                <div><strong>{{ task.name }}</strong><p>{{ softenPublicText(task.description) }}</p><small>{{ task.source || '异变记录' }} · 关注度 {{ task.priority ?? 100 }}</small></div>
                <button type="button" title="移除线索" @click="$emit('delete', task)">×</button>
            </article>
            <button v-if="completed?.length" type="button" class="th-archive-toggle" @click="gameUi.completedOpen = !gameUi.completedOpen">
                已归档线索 {{ completed.length }} 条 <span>{{ gameUi.completedOpen ? '收起' : '展开' }}</span>
            </button>
            <div v-if="gameUi.completedOpen" class="th-task-archive">
                <article v-for="task in completed.slice(-10).reverse()" :key="task.id"><strong>{{ task.name }}</strong><p>{{ softenPublicText(task.description) }}</p></article>
            </div>
        </div>
    `
});

export const GameScreen = defineComponent({
    name: 'GameScreen',
    components: { ChatMessage, MapPanel, NpcPanel, TaskPanel },
    setup() {
        const chatRef = ref(null);
        const actionRef = ref(null);
        const speechRef = ref(null);
        const sendRef = ref(null);
        const session = computed(() => {
            return {
                ...state.currentSession,
                isInDialogue: state.isInDialogue,
                currentDialogueNPC: state.currentDialogueNPC,
                isWaitingForAI: state.isWaitingForAI
            };
        });
        const messages = computed(() => state.chatHistory);
        const locations = computed(() => state.locationTree || []);
        const npcs = computed(() => state.currentSceneNPCs || []);
        const activeTasks = computed(() => [...(state.tasks?.active || [])].sort((a, b) => (a.priority ?? 100) - (b.priority ?? 100)));
        const completedTasks = computed(() => state.tasks?.completed || []);
        const suggestions = computed(buildSuggestions);
        const playerState = computed(() => Object.entries(state.currentSession.playerState || {}));
        const anomaly = computed(() => {
            const time = state.currentSession.time || {};
            const incident = state.currentSession.incidentState || {};
            const resolved = incident.status === 'resolved' || time.anomaly_state === 'waiting' || time.chapter_status === 'resolved';
            const remaining = Math.max(0, Number(time.chapter_time_remaining ?? 72));
            const progress = resolved ? 100 : Math.max(0, Math.min(100, Math.round(Number(incident.investigation_progress ?? 0))));
            const threat = resolved ? 100 : Math.max(0, Math.min(100, Math.round(Number(incident.threat_progress ?? ((72 - remaining) / 72 * 100)))));
            const stageNames = { discovery: '初现', investigation: '调查中', confrontation: '对决', aftermath: '已平息' };
            const stage = resolved ? '已平息' : (stageNames[incident.stage] || '初现');
            return { progress, threat, stage, note: resolved ? '等待新的传闻或后续异变' : `调查不限制路线 · 距关键节点 ${Math.round(remaining)} 小时` };
        });

        function scrollChat() {
            nextTick(() => {
                if (chatRef.value) chatRef.value.scrollTop = chatRef.value.scrollHeight;
            });
        }
        const stopScrollWatch = watch(
            [
                () => gameUi.scrollNonce,
                () => state.chatHistory.length,
                () => state.chatHistory.at(-1)?.content
            ],
            scrollChat
        );
        const stopFocusWatch = watch(
            () => gameUi.focusNonce,
            () => nextTick(() => actionRef.value?.focus())
        );
        onMounted(scrollChat);
        onBeforeUnmount(() => {
            stopScrollWatch();
            stopFocusWatch();
        });

        async function send() {
            const { handleSendMessage } = await import('../ghost/modules/chat.js');
            await handleSendMessage();
        }
        function keydown(event) {
            if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); }
        }
        async function travel(location) {
            if (location.name === session.value.currentScene || !window.confirm(`确定要前往「${location.name}」吗？`)) return;
            const { switchScene } = await import('../ghost/modules/location.js');
            await switchScene(location.name);
        }
        async function locationDetail(name) {
            openLocationDetail(name, state.locationTree);
        }
        async function npcAction(type, npc) {
            if (type === 'detail') {
                return openNPCDetail(npc.id);
            }
            const dialogue = await import('../ghost/modules/dialogue.js');
            if (type === 'observe') return dialogue.observeNPC(npc.id, npc.name);
            return dialogue.startNPCDialogue(npc.id, npc.name);
        }
        function helper() { openSystemHelperDialog(); }
        function addNpc() { openNPCCreationDialog(); }
        async function journal() { await openPlayerJournal(); }
        async function relationships() { await openRelationshipsPanel(); }
        async function deleteTask(task) {
            if (!window.confirm(`确定从线索板移除「${task.name}」吗？\n\n这不会限制你的探索。`)) return;
            const response = await fetch('/api/ghost/delete_task', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ character_id: state.currentSession.characterId, task_id: task.id })
            });
            if (response.ok) await refreshTasksPanel();
        }
        async function deleteMessage(index) {
            if (window.confirm('删除此条及之后所有消息？')) (await import('../ghost/modules/chat.js')).handleDeleteHistory(index);
        }
        async function reroll(index) {
            const message = state.chatHistory[index];
            if (!message || message.isRewriting || message.conversationIndex === undefined) return;
            message.isRewriting = true;
            refreshGameUi();
            try {
                const { rewriteMessage } = await import('../api.js');
                const result = await rewriteMessage(
                    state.currentSession.characterId,
                    message.messageId,
                    message.conversationIndex
                );
                message.messageId = result.message_id || message.messageId;
                message.conversationIndex = result.message_index;
                message.rewriteCandidates = result.rewrite_candidates || [];
                message.activeRewrite = Number.isInteger(result.active_candidate) ? result.active_candidate : -1;
                showToast('已生成不影响剧情状态的改写版本', 1800);
            } catch (error) {
                showToast(`改写失败：${error?.message || error}`, 2600);
            } finally {
                message.isRewriting = false;
                refreshGameUi();
            }
        }
        async function continueDialogue() {
            const npc = state.currentDialogueNPC;
            if (npc) await (await import('../ghost/modules/dialogue.js')).continueDialogue(npc.id, npc.name);
        }
        async function endDialogue() { await (await import('../ghost/modules/dialogue.js')).endDialogue(); }
        function voice() {
            const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!Recognition) return;
            const recognition = new Recognition();
            recognition.lang = 'zh-CN';
            recognition.onresult = event => { gameUi.speechDraft += event.results?.[0]?.[0]?.transcript || ''; };
            recognition.start();
        }
        async function testAi() {
            const { testAIConnection } = await import('../ghost/modules/chat.js');
            await testAIConnection();
        }
        function selectSuggestion(item) { fillComposer(item.action, item.speech); }

        return {
            actionRef, activeTasks, addNpc, anomaly, chatRef, completedTasks, continueDialogue,
            deleteMessage, deleteTask, endDialogue, gameUi, helper, journal, keydown, locationDetail,
            locations, messages, npcAction, npcs, playerState, relationships, reroll, selectSuggestion,
            send, sendRef, session, speechRef, suggestions, testAi, travel, voice
        };
    },
    template: `
        <div class="th-game">
            <section class="th-story-stage">
                <div ref="chatRef" class="th-chat-scroll" aria-live="polite">
                    <div v-if="!messages.length" class="th-opening"><span>東</span><strong>异变记录尚未落笔</strong><small>第一段叙事正在生成</small></div>
                    <ChatMessage v-for="(message, index) in messages" :key="message.timestamp + '-' + index" :message="message" :index="index"
                        :last="index === messages.length - 1" @delete="deleteMessage" @reroll="reroll" @continue="continueDialogue" />
                    <button v-if="session.isInDialogue && session.currentDialogueNPC && !session.isWaitingForAI" type="button" class="th-end-dialogue" @click="endDialogue">结束与 {{ session.currentDialogueNPC?.name }} 的对话</button>
                </div>

                <div class="th-composer">
                    <div class="th-suggestions">
                        <button v-for="item in suggestions" :key="item.label" type="button" @click="selectSuggestion(item)"><span>{{ item.mark }}</span>{{ item.label }}</button>
                    </div>
                    <div class="th-composer-fields">
                        <label><span>行动</span><textarea ref="actionRef" v-model="gameUi.actionDraft" rows="2" :disabled="gameUi.inputDisabled" placeholder="观察、移动、调查或宣言符卡" @keydown="keydown"></textarea></label>
                        <label><span>台词</span><textarea ref="speechRef" v-model="gameUi.speechDraft" rows="2" :disabled="gameUi.inputDisabled" placeholder="输入你想说的话" @keydown="keydown"></textarea><button type="button" class="th-voice" title="语音输入" @click="voice">音</button></label>
                    </div>
                    <button ref="sendRef" type="button" class="th-send" :class="{ cancel: gameUi.allowCancel }" :disabled="gameUi.inputDisabled && !gameUi.allowCancel" @click="send">
                        <span>{{ gameUi.allowCancel ? '止' : '宣' }}</span><strong>{{ gameUi.allowCancel ? '停止生成' : '宣言行动' }}</strong>
                    </button>
                </div>
            </section>

            <aside class="th-side" :class="{ open: gameUi.mobileSidebarOpen }">
                <nav class="th-side-tabs" aria-label="侧栏视图">
                    <button v-for="tab in [{id:'encounter',label:'人物'},{id:'map',label:'地图'},{id:'tasks',label:'线索'},{id:'status',label:'状态'}]" :key="tab.id" type="button" :class="{ active: gameUi.sidebarTab === tab.id }" @click="gameUi.sidebarTab = tab.id">{{ tab.label }}</button>
                </nav>
                <div class="th-side-scroll">
                    <section v-show="gameUi.sidebarTab === 'encounter'" class="th-side-panel"><header><span>遇</span><div><strong>当前遭遇</strong><small>{{ session.currentScene }}</small></div></header><NpcPanel :npcs="npcs" @helper="helper" @detail="npcAction('detail', $event)" @observe="npcAction('observe', $event)" @talk="npcAction('talk', $event)" @add="addNpc" /></section>
                    <section v-show="gameUi.sidebarTab === 'map'" class="th-side-panel"><header><span>図</span><div><strong>幻想乡绘卷</strong><small>所见之地皆可前往</small></div></header><MapPanel :regions="locations" :scene="session.currentScene" @travel="travel" @detail="locationDetail" /></section>
                    <section v-show="gameUi.sidebarTab === 'tasks'" class="th-side-panel"><header><span>録</span><div><strong>开放线索板</strong><small>记录，而非通行条件</small></div></header><TaskPanel :active="activeTasks" :completed="completedTasks" :incident="session.incidentState" @delete="deleteTask" /></section>
                    <section v-show="gameUi.sidebarTab === 'status'" class="th-side-panel">
                        <header><span>勢</span><div><strong>异变与状态</strong><small>{{ anomaly.stage }}</small></div></header>
                        <div class="th-anomaly">
                            <div><strong>调查进展</strong><span>{{ anomaly.progress }}%</span></div><i><b :style="{ width: anomaly.progress + '%' }"></b></i>
                            <div><strong>异变威胁</strong><span>{{ anomaly.threat }}%</span></div><i class="is-threat"><b :style="{ width: anomaly.threat + '%' }"></b></i>
                            <small>{{ anomaly.note }}</small>
                        </div>
                        <div class="th-state-list"><div v-if="!playerState.length" class="th-empty">状态尚未记录</div><div v-for="entry in playerState" :key="entry[0]"><span>{{ entry[0] }}</span><strong>{{ entry[1] }}</strong></div></div>
                        <div class="th-record-actions"><button type="button" @click="journal">完整档案</button><button type="button" @click="relationships">缘分录</button></div>
                    </section>
                </div>
            </aside>
            <button type="button" class="th-mobile-side-toggle" @click="gameUi.mobileSidebarOpen = !gameUi.mobileSidebarOpen">{{ gameUi.mobileSidebarOpen ? '收起' : '人物与地图' }}</button>
        </div>
    `
});

export { GameToolbar };
