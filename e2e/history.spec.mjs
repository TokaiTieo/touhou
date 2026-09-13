import { expect, test } from '@playwright/test';

test('virtual history preserves reading position, streams and prepends without rendering all rows', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.vue-character-selection')).toBeVisible();
    await page.evaluate(async () => {
        const { state } = await import('/js/ghost/core/state.js');
        const { loadAndEnterGhostMode } = await import('/js/ghost/core/session.js');
        const response = await fetch('/api/ghost/create_character', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ profile: { name: '阅读测试', identity: '旅人', background: '神社来访者' } })
        });
        const created = await response.json();
        await loadAndEnterGhostMode(created.character_id, '博丽神社');
        state.chatHistory = Array.from({ length: 1000 }, (_, i) => ({
            localId: `row-${i}`, messageId: `row-${i}`, role: 'assistant', speaker: '旁白',
            content: `第${i}段 ` + '神社的风吹过石阶。'.repeat(3 + i % 17)
        }));
    });
    const scroll = page.locator('.th-chat-scroll');
    await expect(scroll).toBeVisible();
    await expect.poll(() => page.locator('.th-message').count()).toBeLessThan(50);
    await scroll.evaluate(element => { element.scrollTop = 0; });
    await expect(page.locator('.th-message').first()).toContainText('第0段');
    await page.waitForTimeout(200);
    const anchor = await page.locator('[data-row-key="row-0"]').boundingBox();
    await page.evaluate(async () => {
        const { state } = await import('/js/ghost/core/state.js');
        state.chatHistory[999].content += '流式追加的后续叙事。';
    });
    await page.waitForTimeout(150);
    expect(await scroll.evaluate(element => element.scrollTop)).toBeLessThan(10);
    await page.evaluate(async () => {
        const { state } = await import('/js/ghost/core/state.js');
        state.chatHistory.unshift(...Array.from({ length: 80 }, (_, i) => ({
            localId: `older-${i}`, role: 'assistant', speaker: '旁白', content: `更早记录${i}`
        })));
    });
    await page.waitForTimeout(500);
    const restored = await page.locator('[data-row-key="row-0"]').boundingBox();
    expect(restored).not.toBeNull();
    expect(Math.abs(restored.y - anchor.y)).toBeLessThan(8);
    await scroll.evaluate(element => { element.scrollTop = element.scrollHeight; });
    await expect(page.locator('.th-message').last()).toContainText('流式追加');
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => page.locator('.th-message').count()).toBeLessThan(50);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
});
