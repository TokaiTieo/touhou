import { expect, test } from '@playwright/test';

test('illustrated title retains its commands and fits empty, long and multiple saves', async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto('/');
    await expect(page.locator('.vue-character-selection')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole('heading', { name: '东方异变录', exact: true })).toBeVisible();
    await expect(page.locator('.screen-bar')).toHaveCount(0);
    const assets = await page.evaluate(async () => {
        const sources = [
            '/static/ui/title-shrine-approach-v1.png', '/static/ui/title-calligraphy-v1.png',
            '/static/ui/lucide/download.svg', '/static/ui/lucide/trash-2.svg',
            '/static/ui/lucide/history.svg', '/static/ui/lucide/user-round-plus.svg',
            '/static/ui/lucide/plus.svg', '/static/ui/lucide/upload.svg',
            '/static/ui/lucide/key-round.svg', '/static/ui/lucide/plug-zap.svg',
            '/static/ui/lucide/arrow-right.svg'
        ];
        const result = [];
        for (const src of sources) {
            const image = new Image();
            image.src = src;
            await image.decode();
            result.push(image.naturalWidth > 0);
        }
        const { appUi } = await import('/js/vue/app-store.js');
        appUi.characters = [];
        return result;
    });
    expect(assets.every(Boolean)).toBe(true);
    await expect(page.locator('.empty-character-state')).toBeVisible();
    for (const name of ['创建新外来者', '导入角色', '导入NPC']) {
        await expect(page.getByRole('button', { name, exact: true })).toBeVisible();
    }
    await page.getByRole('button', { name: '创建新外来者', exact: true }).click();
    await expect(page.locator('.character-creation-dialog')).toBeVisible();
    await page.evaluate(async () => (await import('/js/vue/app-store.js')).closeAppModal());
    await page.getByRole('button', { name: '导入角色', exact: true }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.evaluate(async () => (await import('/js/vue/app-store.js')).closeAppModal());
    await page.getByRole('button', { name: '导入NPC', exact: true }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.evaluate(async () => {
        const { appUi, closeAppModal } = await import('/js/vue/app-store.js');
        const { updateAccessibilitySettings } = await import('/js/vue/accessibility.js');
        closeAppModal();
        updateAccessibilitySettings({ reduceMotion: true });
        appUi.characters = Array.from({ length: 7 }, (_, index) => ({
            character_id: `title-fixture-${index}`, is_dead: index === 6,
            current_scene: '博丽神社',
            profile: { name: index === 0 ? '很长的自定义角色名字用于检查存档手札是否换行' : `标题页角色${index + 1}`, identity: '长期居住在幻想乡的旅人，正在调查大结界附近的异常' }
        }));
    });
    await expect(page.locator('.character-card')).toHaveCount(7);
    for (const theme of ['light', 'dark']) {
        if (theme === 'dark') await page.getByRole('button', { name: '切换为夜间主题' }).click();
        for (const size of [{ width: 2560, height: 1080 }, { width: 1440, height: 900 }, { width: 768, height: 900 }, { width: 390, height: 844 }, { width: 320, height: 568 }, { width: 390, height: 460 }]) {
            await page.setViewportSize(size);
            for (const fontScale of [1, 1.25]) {
                await page.evaluate(async value => {
                    (await import('/js/vue/accessibility.js')).updateAccessibilitySettings({ fontScale: value });
                    document.querySelector('.character-screen').scrollTop = 0;
                }, fontScale);
                const metrics = await page.evaluate(() => {
                    const screen = document.querySelector('.character-screen');
                    const hero = document.querySelector('.touhou-hero').getBoundingClientRect();
                    const title = document.querySelector('.title-calligraphy').getBoundingClientRect();
                    const targets = [...document.querySelectorAll('.character-card, .character-card-info, .character-actions, .menu-tools')];
                    return {
                        overflow: screen.scrollWidth - screen.clientWidth,
                        bounded: targets.every(el => el.scrollWidth <= el.clientWidth + 1),
                        titleInside: title.top >= hero.top && title.bottom <= hero.bottom,
                        nextSectionVisible: hero.bottom < innerHeight - 35,
                        toolsInside: [...document.querySelectorAll('.menu-tools button')].every(el => el.getBoundingClientRect().right <= innerWidth)
                    };
                });
                expect(metrics, `${theme} ${size.width}x${size.height} / ${fontScale}`).toMatchObject({ bounded: true, titleInside: true, nextSectionVisible: true, toolsInside: true });
                expect(metrics.overflow, `${theme} ${size.width}x${size.height} / ${fontScale}`).toBeLessThanOrEqual(1);
            }
        }
    }
    await page.evaluate(async () => (await import('/js/vue/accessibility.js')).updateAccessibilitySettings({ highContrast: true }));
    await expect(page.locator('.title-calligraphy')).toBeHidden();
    await expect(page.locator('.title-heading-text')).toBeVisible();
    await expect(page.getByRole('button', { name: '继续异变', exact: true })).toHaveCount(7);
    for (const name of ['时序', '导出', '转为NPC', '删除']) {
        await expect(page.locator('.character-card').first().getByRole('button', { name, exact: true })).toBeVisible();
    }
});
