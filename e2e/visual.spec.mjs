import { mkdirSync } from 'node:fs';
import { expect, test } from '@playwright/test';

const visualDir = 'test-results/visual';

test('captures the single-root Vue interface on desktop and mobile', async ({ page }) => {
    mkdirSync(visualDir, { recursive: true });
    await page.goto('/');
    await expect(page.locator('.vue-character-selection')).toBeVisible();

    const desktopLayout = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        roots: document.querySelectorAll('#app > .touhou-vue-shell').length,
        vueHosts: document.querySelectorAll('[id^="vue"][id$="Host"]').length
    }));
    expect(desktopLayout.overflow).toBeLessThanOrEqual(1);
    expect(desktopLayout.roots).toBe(1);
    expect(desktopLayout.vueHosts).toBe(0);
    await page.screenshot({ path: `${visualDir}/character-desktop.png`, fullPage: true });

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator('.touhou-hero')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${visualDir}/character-mobile.png`, fullPage: true });

    const created = await page.evaluate(async () => {
        const response = await fetch('/api/ghost/create_character', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profile: {
                    name: 'Vue视觉验收者',
                    gender: '女',
                    identity: '幻想乡原住民',
                    appearance: '佩戴红白发带',
                    personality: '沉着而好奇',
                    background: '长期居住在人间之里，熟悉符卡规则'
                }
            })
        });
        return response.json();
    });
    await page.reload();
    await page.locator('.character-card').filter({ hasText: 'Vue视觉验收者' }).getByRole('button', { name: '继续异变' }).click();
    await expect(page.locator('.th-game')).toBeVisible();

    await page.setViewportSize({ width: 1440, height: 900 });
    await expect(page.locator('.th-npc').first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${visualDir}/game-desktop.png` });

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator('.th-mobile-side-toggle')).toBeVisible();
    await page.waitForTimeout(260);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    const closedSidebar = await page.locator('.th-side').evaluate(element => ({
        className: element.className,
        display: getComputedStyle(element).display,
        transform: getComputedStyle(element).transform,
        left: element.getBoundingClientRect().left,
        right: element.getBoundingClientRect().right,
        width: element.getBoundingClientRect().width
    }));
    expect(closedSidebar.className).not.toContain('open');
    expect(closedSidebar.left).toBeGreaterThanOrEqual(388);
    await page.screenshot({ path: `${visualDir}/game-mobile.png` });
});
