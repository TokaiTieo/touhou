import { expect, test } from '@playwright/test';

async function openLife(page, name) {
    await page.goto('/');
    const created = await page.evaluate(async label => {
        const response = await fetch('/api/ghost/create_character', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ profile: { name: label, gender: '女', identity: '幻想乡原住民', age: 25,
                appearance: '红白装束', personality: '好奇', background: '在博丽神社帮忙', starting_location: '博丽神社' } })
        });
        return response.json();
    }, name);
    expect(created.character_id).toBeTruthy();
    await page.reload();
    await page.locator('.character-card').filter({ hasText: name }).getByRole('button', { name: '继续异变' }).click();
    await expect(page.locator('.th-game')).toBeVisible();
    await page.evaluate(async () => {
        const { gameUi } = await import('/js/vue/game-ui.js');
        gameUi.sidebarTab = 'life';
        gameUi.mobileSidebarOpen = true;
    });
    await expect(page.locator('.th-life-panel h3').first()).toHaveText('今日闲事');
    return created.character_id;
}

test('daily action commits once and survives reload with participant-bound diary', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const id = await openLife(page, 'E2E日常活动');
    const panel = page.locator('.th-life-panel');
    await panel.locator('.th-life-list li').filter({ hasText: '神社帮工' }).getByRole('button', { name: '开始', exact: true }).click();
    await expect(panel.locator('.th-life-notice')).toContainText('完成神社帮工');
    const data = await page.evaluate(async characterId => (await fetch(`/api/ghost/life?character_id=${characterId}`)).json(), id);
    expect(data.experiences.filter(item => item.title === '神社帮工')).toHaveLength(1);
    expect(data.diaries.npc_reimu?.length).toBeGreaterThan(0);
    expect(data.diaries.npc_marisa).toBeUndefined();
    await page.screenshot({ path: 'test-results/visual/life-desktop.png' });
    await page.reload();
    await expect(page.locator('.th-game')).toBeVisible();
    await page.evaluate(async () => { const { gameUi } = await import('/js/vue/game-ui.js'); gameUi.sidebarTab = 'life'; });
    await expect(panel).toContainText('共同经历');
    await expect(panel.locator('details summary').filter({ hasText: '博丽灵梦' })).toBeVisible();
    expect(errors).toEqual([]);
});

test('calendar invitation can be created and cancelled without locking exploration', async ({ page }) => {
    await openLife(page, 'E2E日历约定');
    const panel = page.locator('.th-life-panel');
    await panel.getByLabel('邀请人物').selectOption('博丽灵梦');
    await panel.getByLabel('日期', { exact: true }).fill('3');
    await panel.getByLabel('时刻', { exact: true }).fill('12');
    await panel.getByRole('button', { name: '送出邀约' }).click();
    await expect(panel.locator('.th-life-notice')).toContainText('等待对方回应');
    await expect(panel).toContainText('与博丽灵梦的邀约');
    await panel.getByRole('button', { name: '取消约定' }).click();
    await expect(panel).toContainText('已取消');
    await page.screenshot({ path: 'test-results/visual/life-calendar.png' });
    await page.locator('.th-side-tabs').getByRole('button', { name: '地图', exact: true }).click();
    await expect(page.locator('.th-side-panel:visible')).toContainText('幻想乡绘卷');
});

test('daily panel fits narrow viewports and scaled text', async ({ page }) => {
    await openLife(page, 'E2E日常窄屏');
    for (const width of [320, 390, 768, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        await page.evaluate(async () => { (await import('/js/vue/game-ui.js')).gameUi.mobileSidebarOpen = true; document.documentElement.style.setProperty('--touhou-font-scale', '1.25'); });
        const panel = page.locator('.th-life-panel');
        expect(await panel.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
        await page.screenshot({ path: `test-results/visual/life-${width}.png` });
    }
});
