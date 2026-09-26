import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';

test('long names, task text and dialogs fit narrow and short viewports', async ({ page }) => {
    mkdirSync('test-results/visual', { recursive: true });
    await page.goto('/');
    await expect(page.locator('.vue-character-selection')).toBeVisible();
    await page.evaluate(async () => {
        const { apiCall } = await import('/js/api.js');
        const { loadAndEnterGhostMode } = await import('/js/ghost/core/session.js');
        const { state } = await import('/js/ghost/core/state.js');
        const { updateAccessibilitySettings } = await import('/js/vue/accessibility.js');
        const created = await apiCall('/ghost/create_character', { method: 'POST', body: { profile: { name: '长期游历幻想乡各处并记录异变的无名旅人', identity: '旅行者' } } });
        await loadAndEnterGhostMode(created.character_id);
        state.tasks.active = [{ id: 'long-layout', name: '调查多个地点之间不断变化的结界波纹并向相关人物询问情况', description: '自由探索的线索记录。'.repeat(12) }];
        updateAccessibilitySettings({ reduceMotion: true, fontScale: 1.25 });
    });
    for (const [width, height] of [[320, 600], [390, 460], [768, 700], [1440, 900]]) {
        await page.setViewportSize({ width, height });
        await page.evaluate(async () => {
            const { gameUi } = await import('/js/vue/game-ui.js');
            gameUi.sidebarTab = 'tasks';
            gameUi.mobileSidebarOpen = true;
        });
        const task = page.locator('.th-task').first();
        await expect(task).toBeVisible();
        expect(await task.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
        await page.evaluate(async () => { (await import('/js/vue/game-ui.js')).gameUi.mobileSidebarOpen = false; });
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
        const player = await page.locator('.th-player-copy strong').boundingBox();
        const chrome = await page.locator('.app-chrome').boundingBox();
        expect(player.y + player.height).toBeLessThanOrEqual(chrome.y + chrome.height);
        for (const kind of ['detail', 'settings']) {
            await page.evaluate(async modal => {
                const { openAppModal } = await import('/js/vue/app-store.js');
                openAppModal(modal, { title: '人物档案', name: 'A'.repeat(90), subtitle: '长资料边界检查', rows: [{ label: '背景', value: '多行人物经历。'.repeat(40) }] });
            }, kind);
            const dialog = page.getByRole('dialog').last();
            await expect(dialog).toBeVisible();
            const box = await dialog.boundingBox();
            expect(box.x).toBeGreaterThanOrEqual(0);
            expect(box.x + box.width).toBeLessThanOrEqual(width + 1);
            expect(box.y + box.height).toBeLessThanOrEqual(height + 1);
            expect(await dialog.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
            if (width === 320) await dialog.screenshot({ path: `test-results/visual/${kind}-long-320.png` });
            await page.evaluate(async () => (await import('/js/vue/app-store.js')).closeAppModal());
        }
    }
});
