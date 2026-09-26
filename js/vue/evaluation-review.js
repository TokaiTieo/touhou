import { defineComponent, ref } from '../vendor/vue.esm-browser.prod.js';
import { apiCall } from '../api.js';

export default defineComponent({
    name: 'EvaluationReview',
    props: { report: { type: Object, required: true } },
    setup(props) {
        const saving = ref(false);
        const message = ref('');
        async function save() {
            saving.value = true;
            try {
                const report = await apiCall('/ghost/producer_console/evaluation/review', { method: 'POST', body: {
                    character_id: props.report.character_id, report_id: props.report.report_id,
                    reviews: props.report.results.map(item => ({ id: item.id, ...item.manual_review }))
                } });
                Object.assign(props.report, report);
                message.value = '人工评分已保存';
            } catch (error) { message.value = error.message; }
            finally { saving.value = false; }
        }
        function download() {
            const url = URL.createObjectURL(new Blob([JSON.stringify(props.report, null, 2)], { type: 'application/json' }));
            const link = document.createElement('a');
            link.href = url;
            link.download = `${props.report.report_id || 'evaluation'}.json`;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        }
        return { saving, message, save, download };
    },
    template: `<div class="producer-evaluation-list">
        <div class="producer-tool-row"><button :disabled="saving || !report.report_id" @click="save">保存人工评分</button><button @click="download">导出评测记录</button><span role="status">{{ message }}</span></div>
        <article v-for="item in report.results" :key="item.id" :class="{ passed: item.passed }">
            <strong>{{ item.passed ? '自动检查通过' : '待复核' }} · {{ item.title }}</strong>
            <span>{{ item.evaluation.score }} 分 · {{ item.runtime?.elapsed_ms || 0 }} ms · {{ item.usage?.total_tokens || 0 }} Token</span>
            <small v-for="issue in item.evaluation.issues" :key="issue.code">{{ issue.message }}</small>
            <details><summary>行动与回复</summary><p>{{ item.action }}</p><p class="evaluation-prose">{{ item.response_text }}</p></details>
            <div v-if="item.manual_review" class="evaluation-rubric">
                <label v-for="(label, key) in report.review_rubric" :key="key">{{ label }}<select v-model="item.manual_review.scores[key]"><option :value="null">未评分</option><option v-for="score in 5" :key="score" :value="score">{{ score }}</option></select></label>
                <label class="evaluation-note">复核备注<textarea v-model="item.manual_review.note" rows="2" maxlength="4000"></textarea></label>
            </div>
        </article>
    </div>`
});
