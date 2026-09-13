import { computed, defineComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from '../vendor/vue.esm-browser.prod.js';

export default defineComponent({
    name: 'VirtualHistory',
    props: { items: { type: Array, required: true }, scrollParent: Object },
    setup(props) {
        const root = ref(null);
        const position = ref(0);
        const viewport = ref(700);
        const revision = ref(0);
        const heights = new Map();
        let observer, parentObserver, attached;
        const keyOf = (item, index) => item.localId || item.messageId || String(index);
        const offsets = computed(() => {
            revision.value;
            const result = [0];
            props.items.forEach((item, i) => result.push(result.at(-1) + (heights.get(keyOf(item, i)) || 180)));
            return result;
        });
        const windowed = computed(() => {
            const list = offsets.value;
            let low = 0, high = props.items.length;
            const top = Math.max(0, position.value - 600);
            while (low < high) {
                const middle = (low + high) >> 1;
                if (list[middle + 1] < top) low = middle + 1;
                else high = middle;
            }
            let end = low;
            while (end < props.items.length && list[end] < position.value + viewport.value + 600) end++;
            end = Math.min(props.items.length, Math.max(low + 1, end));
            return { top: list[low], bottom: list.at(-1) - list[end],
                rows: props.items.slice(low, end).map((message, i) => ({ message, index: low + i, key: keyOf(message, low + i) })) };
        });
        function sync() {
            if (!attached || !root.value) return;
            position.value = Math.max(0, attached.getBoundingClientRect().top - root.value.getBoundingClientRect().top);
            viewport.value = attached.clientHeight;
        }
        function measure() {
            if (!root.value || !observer) return;
            observer.disconnect();
            root.value.querySelectorAll(':scope > [data-row-key]').forEach(element => observer.observe(element));
        }
        function attach(parent) {
            attached?.removeEventListener('scroll', sync);
            parentObserver?.disconnect();
            attached = parent;
            attached?.addEventListener('scroll', sync, { passive: true });
            if (attached) parentObserver?.observe(attached);
            sync();
        }
        onMounted(() => {
            observer = new ResizeObserver(entries => {
                let changed = false;
                let shift = 0;
                for (const { target } of entries) {
                    const key = target.dataset.rowKey;
                    const size = target.getBoundingClientRect().height;
                    const old = heights.get(key) || 180;
                    if (Math.abs(old - size) > 1) {
                        if (target.getBoundingClientRect().bottom < attached?.getBoundingClientRect().top) shift += size - old;
                        heights.set(key, size);
                        changed = true;
                    }
                }
                if (changed) {
                    const bottom = attached && attached.scrollHeight - attached.scrollTop - attached.clientHeight < 80;
                    revision.value++;
                    nextTick(() => {
                        if (attached) attached.scrollTop = bottom ? attached.scrollHeight : attached.scrollTop + shift;
                        sync();
                    });
                }
            });
            parentObserver = new ResizeObserver(() => { heights.clear(); revision.value++; sync(); });
            attach(props.scrollParent);
            measure();
        });
        watch(() => props.scrollParent, attach);
        watch(() => windowed.value.rows.map(row => row.key).join('|'), () => nextTick(measure));
        watch(() => props.items.length, () => nextTick(sync));
        watch(() => props.items.map(keyOf), async (keys, previous) => {
            if (!attached || !previous.length || keys[0] === previous[0]) return;
            const parent = attached;
            const origin = root.value.getBoundingClientRect().top - parent.getBoundingClientRect().top + parent.scrollTop;
            let oldOffset = 0;
            let anchor = previous[0];
            for (const key of previous) {
                anchor = key;
                const height = heights.get(key) || 180;
                if (oldOffset + height > position.value) break;
                oldOffset += height;
            }
            const index = keys.indexOf(anchor);
            if (index < 0) return;
            const newOffset = keys.slice(0, index).reduce((sum, key) => sum + (heights.get(key) || 180), 0);
            const scrollTop = parent.scrollTop;
            await nextTick();
            if (attached !== parent) return;
            const newOrigin = root.value.getBoundingClientRect().top - parent.getBoundingClientRect().top + parent.scrollTop;
            parent.scrollTop = scrollTop + newOffset - oldOffset + newOrigin - origin;
            sync();
        });
        onBeforeUnmount(() => {
            attached?.removeEventListener('scroll', sync);
            observer?.disconnect();
            parentObserver?.disconnect();
        });
        return { root, windowed };
    },
    template: `
        <div ref="root" class="th-virtual-history">
            <div aria-hidden="true" :style="{ height: windowed.top + 'px' }"></div>
            <div v-for="row in windowed.rows" :key="row.key" :data-row-key="row.key" class="th-history-row">
                <slot :message="row.message" :index="row.index"></slot>
            </div>
            <div aria-hidden="true" :style="{ height: windowed.bottom + 'px' }"></div>
        </div>
    `
});
