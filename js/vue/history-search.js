import { defineComponent, ref, watch } from '../vendor/vue.esm-browser.prod.js';
import { apiCall } from '../api.js';
import { state } from '../ghost/core/state.js';
import { softenPublicText } from '../ghost/ui/text.js';

export default defineComponent({
    name: 'HistorySearch',
    setup() {
        const query = ref('');
        const searched = ref('');
        const result = ref(null);
        const busy = ref(false);
        const error = ref('');
        let generation = 0;
        function reset() {
            generation += 1;
            query.value = '';
            searched.value = '';
            result.value = null;
            busy.value = false;
            error.value = '';
        }
        watch(() => state.currentSession.characterId, reset);
        async function search(more = false) {
            if (busy.value || !query.value.trim()) return;
            const current = ++generation;
            const owner = state.currentSession.characterId;
            const term = more ? searched.value : query.value.trim();
            busy.value = true;
            error.value = '';
            try {
                const params = new URLSearchParams({ character_id: owner, query: term, limit: '30' });
                if (more && result.value?.messages.length) params.set('before_id', result.value.messages[0].message_id);
                const page = await apiCall('/ghost/conversation_history?' + params);
                if (current !== generation || owner !== state.currentSession.characterId) return;
                result.value = more ? { ...page, messages: [...page.messages, ...result.value.messages] } : page;
                searched.value = term;
            } catch (failure) {
                if (current === generation) error.value = failure.message;
            } finally {
                if (current === generation) busy.value = false;
            }
        }
        return { query, searched, result, busy, error, search, reset, softenPublicText };
    },
    template: `
        <details class="th-history-search">
            <summary>查找往事</summary>
            <form @submit.prevent="search()"><input v-model="query" aria-label="查找全部剧情" type="search" placeholder="人物或关键词"><button type="submit" :disabled="busy || !query.trim()">查找</button><button type="button" @click="reset">清空</button></form>
            <p v-if="error" role="alert">{{ error }}</p>
            <div v-if="result" class="th-history-results" aria-live="polite">
                <p v-if="!result.messages.length">没有找到相关记录</p>
                <button v-if="result.has_more" type="button" :disabled="busy" @click="search(true)">更早的匹配记录</button>
                <article v-for="message in result.messages" :key="message.message_id"><strong>{{ message.speaker }}</strong><p>{{ softenPublicText(message.content) }}</p></article>
            </div>
        </details>
    `
});
