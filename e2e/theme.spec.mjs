import { mkdirSync } from 'node:fs';
import { expect, test } from '@playwright/test';

test('day and night surfaces keep text, portraits and sidebar controls readable', async ({ page }) => {
    test.setTimeout(90_000);
    mkdirSync('test-results/visual', { recursive: true });
    await page.goto('/');
    await expect(page.locator('.vue-character-selection')).toBeVisible({ timeout: 20_000 });
    await page.evaluate(async () => {
        const { apiCall } = await import('/js/api.js');
        const { loadAndEnterGhostMode } = await import('/js/ghost/core/session.js');
        const { updateAccessibilitySettings } = await import('/js/vue/accessibility.js');
        const created = await apiCall('/ghost/create_character', { method: 'POST', body: {
            profile: { name: '昼夜视觉验收', identity: '幻想乡原住民', starting_location: '博丽神社' }
        } });
        await loadAndEnterGhostMode(created.character_id);
        updateAccessibilitySettings({ reduceMotion: true });
        await document.fonts.ready;
    });

    const artwork = await page.evaluate(async () => {
        const sources = [
            '/static/ui/hakurei-panorama-v2.png',
            '/static/ui/shrine-rope-v1.png',
            '/static/ui/shrine-floral-corner-v1.png'
        ];
        const result = [];
        for (const src of sources) {
            const image = new Image();
            image.src = src;
            await image.decode();
            const canvas = document.createElement('canvas');
            canvas.width = 120;
            canvas.height = 120;
            const context = canvas.getContext('2d');
            context.drawImage(image, 0, 0, 120, 120);
            const pixels = context.getImageData(0, 0, 120, 120).data;
            let opaque = 0;
            let transparent = 0;
            for (let index = 3; index < pixels.length; index += 4) {
                if (pixels[index] > 200) opaque += 1;
                if (pixels[index] < 10) transparent += 1;
            }
            result.push({ src, width: image.naturalWidth, opaque, transparent });
        }
        return result;
    });
    for (const item of artwork) {
        expect(item.width, item.src).toBeGreaterThan(1000);
        expect(item.opaque, item.src).toBeGreaterThan(100);
    }
    expect(artwork[1].transparent).toBeGreaterThan(5000);
    expect(artwork[2].transparent).toBeGreaterThan(5000);
    await expect(page.locator('.th-scene-heading')).toHaveCSS('background-image', /hakurei-panorama-v2/);
    await expect(page.locator('.th-message:not(.is-system):not(.is-player) .th-message-body').first()).toHaveCSS('border-top-width', '0px');

    for (const theme of ['light', 'dark']) {
        if (theme === 'dark') await page.getByRole('button', { name: '切换为夜间主题' }).click();
        await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
        for (const width of [1440, 390, 320]) {
            await page.setViewportSize({ width, height: 900 });
            await page.evaluate(async () => {
                const { gameUi } = await import('/js/vue/game-ui.js');
                gameUi.mobileSidebarOpen = false;
            });
            expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
            await page.screenshot({ path: `test-results/visual/theme-${theme}-${width}.png`, animations: 'disabled' });
            if (width < 821) await page.locator('.th-mobile-side-toggle').click();
            for (const name of ['人物', '地图', '线索', '日常', '状态']) {
                const tab = page.locator('.th-side-tabs').getByRole('button', { name, exact: true });
                await tab.click();
                await expect(tab).toHaveClass(/active/);
                const panel = page.locator('.th-side-panel:visible');
                expect(await panel.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
                if (name === '人物') {
                    await expect.poll(() => page.locator('.th-npc-avatar img').first().evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
                }
                if (width === 390 || width === 1440) {
                    await page.locator('.th-side').screenshot({ path: `test-results/visual/sidebar-${theme}-${width}-${name}.png`, animations: 'disabled' });
                }
            }
            if (width < 821) await page.locator('.th-mobile-side-toggle').click();
            await page.getByRole('button', { name: '游戏设置', exact: true }).click();
            const dialog = page.getByRole('dialog');
            await expect(dialog).toBeVisible();
            expect(await dialog.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
            const contrast = await page.evaluate(() => {
                const rgb = value => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
                const luminance = color => rgb(color).reduce((sum, channel, index) => {
                    const v = channel / 255;
                    return sum + (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4) * [0.2126, 0.7152, 0.0722][index];
                }, 0);
                const ratio = (foreground, background) => {
                    const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
                    return (values[0] + 0.05) / (values[1] + 0.05);
                };
                const hint = getComputedStyle(document.querySelector('.form-hint'));
                const surface = getComputedStyle(document.querySelector('.vue-settings-dialog'));
                const send = getComputedStyle(document.querySelector('.th-send'));
                return { hint: ratio(hint.color, surface.backgroundColor), send: ratio(send.color, send.backgroundColor) };
            });
            expect(contrast.hint).toBeGreaterThanOrEqual(4.5);
            expect(contrast.send).toBeGreaterThanOrEqual(4.5);
            if (width === 390) await dialog.screenshot({ path: `test-results/visual/settings-${theme}.png`, animations: 'disabled' });
            await dialog.getByRole('button', { name: '关闭', exact: true }).click();
        }
    }
    await page.evaluate(async () => {
        const { updateAccessibilitySettings } = await import('/js/vue/accessibility.js');
        updateAccessibilitySettings({ highContrast: true, fontScale: 1.25 });
    });
    await expect(page.locator('.th-message-content').first()).toHaveCSS('color', 'rgb(255, 255, 255)');
    await expect(page.locator('.th-side')).toHaveCSS('background-color', 'rgb(16, 22, 18)');
    await page.screenshot({ path: 'test-results/visual/theme-high-contrast-320.png', animations: 'disabled' });
});
