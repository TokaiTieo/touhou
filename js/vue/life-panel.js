import { computed, defineComponent, onBeforeUnmount, ref, watch } from '../vendor/vue.esm-browser.prod.js';
import { getLifeState, performLifeCommand } from '../api.js';
import { state } from '../ghost/core/state.js';
import { gameUi } from './game-ui.js';
import { refreshNPCList, refreshTasksPanel } from './game-controller.js';
import { softenPublicText } from '../ghost/ui/text.js';

export default defineComponent({
    name: 'LifePanel',
    setup() {
        const data = ref(null);
        const busy = ref(false);
        const error = ref('');
        const message = ref('');
        const target = ref('');
        const day = ref(1);
        const hour = ref(12);
        const scene = ref('');
        let sequence = 0;
        let disposed = false;
        const npcs = computed(() => state.currentSceneNPCs || []);
        const locations = computed(() => (state.locationTree || []).flatMap(region => region.locations || []));
        const disabled = computed(() => busy.value || state.isWaitingForAI || Boolean(gameUi.recovery));
        const labels = { discovered: '新发现', participating: '进行中', completed: '已完成', abandoned: '已搁置',
            proposed: '等待回应', scheduled: '已约定', missed: '已错过', cancelled: '已取消' };
        async function refresh() {
            const id = state.currentSession.characterId;
            if (!id) { data.value = null; return; }
            const request = ++sequence;
            try {
                const result = await getLifeState(id);
                if (disposed || request !== sequence || id !== state.currentSession.characterId) return;
                data.value = result;
                gameUi.lifeData = result;
                day.value = Math.max(Number(day.value), result.day + 1);
                scene.value ||= result.scene;
                target.value ||= npcs.value[0]?.name || '';
                error.value = '';
            } catch (reason) {
                if (!disposed && request === sequence) error.value = reason.message || '暂时无法读取手札';
            }
        }
        watch(() => [state.currentSession.characterId, state.currentSession.time?.current_day,
            state.currentSession.time?.current_hour, state.currentSession.currentScene, gameUi.sidebarTab], refresh, { immediate: true });
        onBeforeUnmount(() => { disposed = true; sequence++; });
        async function command(payload) {
            if (disabled.value) return;
            busy.value = true;
            sequence++;
            error.value = '';
            const id = state.currentSession.characterId;
            try {
                const result = await performLifeCommand(id, payload);
                if (id !== state.currentSession.characterId || disposed) return;
                data.value = result.life;
                gameUi.lifeData = result.life;
                message.value = result.message;
                const character = result.character || {};
                state.currentSession.time = character.time || state.currentSession.time;
                state.currentSession.playerState = character.player_state || state.currentSession.playerState;
                state.currentSession.relationshipsMap = character.relationships_map || state.currentSession.relationshipsMap;
                await refreshNPCList();
                await refreshTasksPanel();
            } catch (reason) {
                if (!disposed && id === state.currentSession.characterId) error.value = reason.message || '操作未确认，请重试';
            } finally { busy.value = false; }
        }
        function appoint() { return command({ command: 'appointment', target: target.value, day: Number(day.value), hour: Number(hour.value), scene: scene.value }); }
        function reschedule(item) { return command({ command: 'appointment_update', target: item.id, choice: 'reschedule', day: Number(day.value), hour: Number(hour.value) }); }
        function when(value) { return `第${Math.floor(value / 24) + 1}天 ${Math.floor(value % 24)}:${String(Math.round(value % 1 * 60)).padStart(2, '0')}`; }
        return { data, disabled, error, message, labels, command, appoint, reschedule, refresh, npcs, locations, target, day, hour, scene, when, softenPublicText };
    },
    template: `
        <div class="th-life-panel">
            <p v-if="error" role="alert">{{ error }} <button type="button" @click="refresh">重试</button></p>
            <p v-if="message" class="th-life-notice" role="status">{{ message }}</p>
            <template v-if="data">
                <h3>今日闲事</h3>
                <ul class="th-life-list"><li v-for="activity in data.activities" :key="activity.id">
                    <strong>{{ activity.title }}</strong><small>{{ activity.scene }} · {{ activity.hours }}小时 · {{ activity.input ? '消耗' + activity.input : '获得' + activity.output }}</small>
                    <button type="button" :disabled="disabled || !activity.available" :title="activity.reason || activity.title" @click="command({command:'activity',target:activity.id})">开始</button>
                </li></ul>
                <h3>来往心意</h3>
                <p v-if="!data.proposals.length" class="th-empty">尚无待回应的心意</p>
                <ul class="th-life-list"><li v-for="proposal in data.proposals" :key="proposal.id">
                    <strong>{{ proposal.npc_name }} · {{ softenPublicText(proposal.title) }}</strong><p>{{ softenPublicText(proposal.description) }}</p>
                    <div class="th-life-actions"><button type="button" :disabled="disabled" @click="command({command:'relationship',target:proposal.id,choice:'accept'})">接受</button><button type="button" :disabled="disabled" @click="command({command:'relationship',target:proposal.id,choice:'decline'})">暂不接受</button><button type="button" :disabled="disabled" @click="command({command:'relationship',target:proposal.id,choice:'friendship'})">保持朋友</button></div>
                </li></ul>
                <h3>日历与约定</h3>
                <ul class="th-life-list"><li v-for="festival in data.festivals" :key="festival.id"><strong>第{{ festival.day }}天 · {{ festival.title }}</strong><small>{{ festival.scene }}</small></li></ul>
                <form class="th-life-form" @submit.prevent="appoint">
                    <label>邀请人物<select v-model="target" required><option value="" disabled>选择人物</option><option v-for="npc in npcs" :key="npc.id" :value="npc.name">{{ npc.name }}</option></select></label>
                    <label>日期<input v-model.number="day" type="number" :min="data.day" max="1000000" required></label>
                    <label>时刻<input v-model.number="hour" type="number" min="0" max="23.75" step="0.25" required></label>
                    <label>地点<select v-model="scene" required><option v-for="location in locations" :key="location.id" :value="location.name">{{ location.name }}</option></select></label>
                    <button type="submit" :disabled="disabled || !target">送出邀约</button>
                </form>
                <ul class="th-life-list"><li v-for="item in data.appointments" :key="item.id"><strong>{{ item.title }}</strong><small>{{ when(item.hour) }} · {{ item.scene }} · {{ labels[item.status] || item.status }}</small><div v-if="['proposed','scheduled'].includes(item.status)" class="th-life-actions"><button type="button" :disabled="disabled" @click="reschedule(item)">按所选时间改期</button><button type="button" :disabled="disabled" @click="command({command:'appointment_update',target:item.id,choice:'cancel'})">取消约定</button></div></li></ul>
                <h3>身边事件</h3>
                <ul class="th-life-list"><li v-for="event in data.events.slice().reverse()" :key="event.id"><strong>{{ event.title }}</strong><small>{{ event.scene }} · {{ labels[event.status] || '新发现' }}</small><p>{{ event.description }}</p><div class="th-life-actions"><button v-if="['discovered','abandoned'].includes(event.status)" type="button" :disabled="disabled" @click="command({command:'event',target:event.id,choice:'participate'})">参与</button><button v-if="['discovered','participating'].includes(event.status)" type="button" :disabled="disabled" @click="command({command:'event',target:event.id,choice:'abandon'})">搁置</button></div></li></ul>
                <h3>共同经历</h3>
                <p v-if="!data.experiences.length" class="th-empty">尚无记录</p>
                <ul class="th-life-list"><li v-for="item in data.experiences.slice().reverse()" :key="item.id"><strong>{{ item.title }}</strong><small>{{ when(item.hour) }} · {{ item.scene }}</small><p>{{ item.detail }}</p></li></ul>
                <h3>人物札记</h3>
                <details v-for="(entries, key) in data.diaries" :key="key"><summary>{{ entries[0]?.owner?.npc_name }}</summary><ul class="th-life-list"><li v-for="entry in entries.slice().reverse()" :key="entry.id"><strong>{{ entry.title }}</strong><p>{{ entry.detail }}</p></li></ul></details>
            </template>
        </div>
    `
});
