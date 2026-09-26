import { defineComponent } from '../vendor/vue.esm-browser.prod.js';
import { gameUi } from './game-ui.js';
import { queryPendingTurn, resolvePendingTurn } from '../ghost/core/pending-turn.js';

export default defineComponent({
    name: 'TurnRecovery',
    setup() { return { gameUi, queryPendingTurn, resolvePendingTurn }; },
    template: `<aside v-if="gameUi.recovery" class="th-turn-recovery" role="status">
        <strong>上一回合尚未确认</strong>
        <p v-if="gameUi.recovery.error" role="alert">{{ gameUi.recovery.error }}</p>
        <div><button :disabled="gameUi.recovery.busy" @click="resolvePendingTurn()">恢复本回合</button>
        <button :disabled="gameUi.recovery.busy" @click="queryPendingTurn">查询结果</button>
        <button :disabled="gameUi.recovery.busy" @click="resolvePendingTurn(true)">确认停止</button></div>
    </aside>`
});
