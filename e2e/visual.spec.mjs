import { mkdirSync } from 'node:fs';
import { expect, test } from '@playwright/test';

const visualDir = 'test-results/visual';

test('multiline system notices keep text and tools inside small rounded corners', async ({ page }) => {
    mkdirSync(visualDir, { recursive: true });
    await page.goto('/');
    await expect(page.locator('.vue-character-selection')).toBeVisible();
    await page.evaluate(async () => {
        const { state } = await import('/js/ghost/core/state.js');
        const { loadAndEnterGhostMode } = await import('/js/ghost/core/session.js');
        const { updateAccessibilitySettings } = await import('/js/vue/accessibility.js');
        const response = await fetch('/api/ghost/create_character', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ profile: { name: '系统提示布局测试', identity: '旅人' } })
        });
        const created = await response.json();
        await loadAndEnterGhostMode(created.character_id, '博丽神社');
        updateAccessibilitySettings({ reduceMotion: true });
        state.chatHistory = [{
            localId: 'system-layout', role: 'system', speaker: '本回合变化',
            content: '时间流逝 15 分钟；状态变为「精力充沛」；新见闻：无人投币的清晨。\n\n状态变化：疲劳 +1'
        }];
        await document.fonts.ready;
    });
    const notice = page.locator('.th-message.is-system .th-message-body');
    await expect(notice).toBeVisible();
    await expect(notice.getByRole('button', { name: '复制', exact: true })).toBeVisible();
    await expect(notice.getByRole('button', { name: '删除', exact: true })).toBeVisible();
    for (const width of [320, 390, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        for (const fontScale of [1, 1.25]) {
            await page.evaluate(async scale => {
                const { updateAccessibilitySettings } = await import('/js/vue/accessibility.js');
                updateAccessibilitySettings({ fontScale: scale });
            }, fontScale);
            await expect(notice).toHaveCSS('border-radius', '8px');
            await expect(notice).toHaveCSS('text-align', 'left');
            const metrics = await notice.evaluate(element => {
                const body = element.getBoundingClientRect();
                const style = getComputedStyle(element);
                const header = element.querySelector('header').getBoundingClientRect();
                const content = element.querySelector('.th-message-content');
                const tools = element.querySelector('footer').getBoundingClientRect();
                const safeLeft = body.left + parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft);
                const safeRight = body.right - parseFloat(style.borderRightWidth) - parseFloat(style.paddingRight);
                const boxes = [...element.querySelectorAll('header strong, .th-message-content p, footer button')]
                    .map(child => child.getBoundingClientRect());
                return {
                    aligned: Math.abs(header.left - content.getBoundingClientRect().left) <= 1,
                    inside: boxes.every(box => box.left >= safeLeft - 1 && box.right <= safeRight + 1 && box.top >= body.top && box.bottom <= body.bottom),
                    footerBelow: tools.top >= content.getBoundingClientRect().bottom,
                    contentOverflow: content.scrollWidth - content.clientWidth,
                    pageOverflow: document.documentElement.scrollWidth - innerWidth
                };
            });
            expect(metrics, `${width}px / font ${fontScale}`).toMatchObject({ aligned: true, inside: true, footerBelow: true });
            expect(metrics.contentOverflow).toBeLessThanOrEqual(1);
            expect(metrics.pageOverflow).toBeLessThanOrEqual(1);
        }
        await notice.screenshot({ path: `${visualDir}/system-notice-${width}.png`, animations: 'disabled' });
    }
});

test('captures the single-root Vue interface on desktop and mobile', async ({ page }) => {
    test.setTimeout(60_000);
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
    await page.waitForTimeout(450);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${visualDir}/game-desktop.png` });

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator('.th-mobile-side-toggle')).toBeVisible();
    await page.waitForTimeout(450);
    const sendBox = await page.locator('.th-send').boundingBox();
    expect(sendBox.x + sendBox.width).toBeLessThanOrEqual(390);
    expect(await page.locator('.th-send strong').evaluate(element => element.scrollWidth <= element.clientWidth)).toBeTruthy();
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

    await page.evaluate(async () => {
        const { updateAccessibilitySettings } = await import('/js/vue/accessibility.js');
        updateAccessibilitySettings({ reduceMotion: true });
        await document.fonts.ready;
    });
    for (const width of [320, 390, 768, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        for (const fontScale of [1, 1.25]) {
            await page.evaluate(async scale => {
                const { updateAccessibilitySettings } = await import('/js/vue/accessibility.js');
                updateAccessibilitySettings({ fontScale: scale });
            }, fontScale);
            const metrics = await page.locator('.th-send strong').evaluate(element => {
                const label = element.getBoundingClientRect();
                const button = element.closest('button').getBoundingClientRect();
                const range = document.createRange();
                range.selectNodeContents(element);
                const text = range.getBoundingClientRect();
                return {
                    width: element.scrollWidth - element.clientWidth,
                    height: element.scrollHeight - element.clientHeight,
                    textInside: text.top >= label.top - 1 && text.bottom <= label.bottom + 1,
                    insideButton: label.top >= button.top && label.bottom <= button.bottom,
                    visible: button.bottom <= innerHeight && button.right <= innerWidth,
                    pageOverflow: document.documentElement.scrollWidth - innerWidth
                };
            });
            expect(metrics, `${width}px / font ${fontScale}`).toMatchObject({ textInside: true, insideButton: true, visible: true });
            expect(metrics.width).toBeLessThanOrEqual(1);
            expect(metrics.height).toBeLessThanOrEqual(1);
            expect(metrics.pageOverflow).toBeLessThanOrEqual(1);
        }
        await expect(page.locator('.th-composer')).toHaveScreenshot(`composer-${width}-large.png`, { animations: 'disabled', maxDiffPixelRatio: 0.01 });
    }
    await page.setViewportSize({ width: 390, height: 460 });
    await page.getByPlaceholder('输入你想说的话').focus();
    await expect(page.getByPlaceholder('输入你想说的话')).toBeFocused();
    const inputBox = await page.getByPlaceholder('输入你想说的话').boundingBox();
    expect(inputBox.y + inputBox.height).toBeLessThanOrEqual(460);
    expect((await page.locator('.th-send').boundingBox()).y).toBeGreaterThan(0);
    await expect(page.locator('.th-composer')).toHaveScreenshot('composer-keyboard.png', { animations: 'disabled', maxDiffPixelRatio: 0.01 });
});
