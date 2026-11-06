import { expect, test } from '@playwright/test';

test('optional NPC mode publishes separate canonical decisions and survives reload', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/');
    const id = await page.evaluate(async () => {
        const response = await fetch('/api/ghost/create_character', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ profile: { name: 'E2E人物独立回应', age: 25, gender: '女', identity: '幻想乡原住民', starting_location: '博丽神社' } }) });
        return (await response.json()).character_id;
    });
    expect(id).toBeTruthy();
    await page.reload();
    await page.locator('.character-card').filter({ hasText: 'E2E人物独立回应' }).getByRole('button', { name: '继续异变' }).click();
    await expect(page.locator('.th-game')).toBeVisible();
    await page.getByRole('button', { name: '游戏设置', exact: true }).click();
    await expect(page.locator('#vueAgentMode')).toHaveValue('legacy');
    await page.locator('#vueAgentMode').selectOption('collaborative');
    await expect(page.locator('.vue-settings-dialog')).toContainText('本存档叙事方式已更新');
    await page.locator('.vue-settings-dialog').getByRole('button', { name: '关闭', exact: true }).click();
    await page.getByPlaceholder('观察、移动、调查或宣言符卡').fill('向博丽灵梦问好');
    await page.getByRole('button', { name: /宣言行动/ }).click();
    await expect(page.getByText('本人回应', { exact: true })).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole('button', { name: /宣言行动/ })).toBeEnabled();
    for (const width of [390, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        if (width < 800) await expect.poll(() => page.locator('.th-side').evaluate(element => element.getBoundingClientRect().left)).toBeGreaterThanOrEqual(width);
        else await expect.poll(() => page.locator('.th-side').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(width + 1);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
        await page.screenshot({ path: `test-results/visual/agents-${width}.png`, animations: 'disabled' });
    }
    await page.reload();
    await expect(page.getByText('本人回应', { exact: true })).toBeVisible();
    const status = await page.evaluate(async characterId => (await fetch(`/api/ghost/agent_mode?character_id=${characterId}`)).json(), id);
    expect(status.mode).toBe('collaborative');
    expect(status.last_turn.participants).toEqual(['npc_reimu']);
    await page.getByRole('button', { name: '人物', exact: true }).click();
    await page.locator('.th-npc').filter({ hasText: '博丽灵梦' }).getByTitle('开始对话').click();
    await expect(page.locator('.th-end-dialogue')).toBeVisible();
    for (const [index, [action, speech]] of [['想了想', '不知道'], ['独自坐下', '你好']].entries()) {
        await page.locator('.th-composer textarea').nth(0).fill(action);
        await page.locator('.th-composer textarea').nth(1).fill(speech);
        const response = page.waitForResponse(result => result.url().endsWith('/npc_dialogue_stream') && result.request().method() === 'POST');
        await page.locator('.th-send').click();
        const received = await response;
        await received.finished();
        expect(received.ok()).toBeTruthy();
        const sent = received.request().postDataJSON();
        expect(sent.npc_id).toBe('npc_reimu');
        expect(sent.user_input).toBe(`【动作】${action}\n【语言】"${speech}"`);
        await expect(page.locator('.th-send')).toBeEnabled();
        const saved = await page.evaluate(async characterId => (await fetch(`/api/ghost/character/${characterId}`)).json(), id);
        expect(saved.agent_state.last_turn.participants).toEqual(['npc_reimu']);
        const latestInput = saved.conversation_history.find(item => item.turn_id === sent.turn_id && item.agent_inputs?.length);
        expect(latestInput.agent_inputs).toEqual([{ npc_id: 'npc_reimu', content: `"${speech}"` }]);
        const decisions = saved.conversation_history.filter(item => item.canonical_decision);
        expect(decisions).toHaveLength(index + 2);
        expect(decisions.at(-1).turn_id).toBe(sent.turn_id);
        expect(decisions.at(-1).npc_id).toBe('npc_reimu');
        await expect(page.getByText('本人回应', { exact: true }).last()).toBeVisible();
    }
    const continuation = page.waitForResponse(result => result.url().endsWith('/npc_dialogue_stream') && result.request().method() === 'POST');
    await page.getByRole('button', { name: '静候对方继续', exact: true }).click();
    const continued = await continuation;
    await continued.finished();
    expect(continued.ok()).toBeTruthy();
    const sent = continued.request().postDataJSON();
    expect(sent.is_continue).toBe(true);
    expect(sent.npc_id).toBe('npc_reimu');
    await expect(page.locator('.th-send')).toBeEnabled();
    const saved = await page.evaluate(async characterId => (await fetch(`/api/ghost/character/${characterId}`)).json(), id);
    expect(saved.agent_state.last_turn.participants).toEqual(['npc_reimu']);
    const latestInput = saved.conversation_history.find(item => item.turn_id === sent.turn_id && item.role === 'user');
    expect(latestInput.agent_inputs).toEqual([]);
    const decisions = saved.conversation_history.filter(item => item.canonical_decision);
    expect(decisions).toHaveLength(4);
    expect(decisions.at(-1).turn_id).toBe(sent.turn_id);
    expect(decisions.at(-1).npc_id).toBe('npc_reimu');
    for (const width of [390, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        const button = page.getByRole('button', { name: '静候对方继续', exact: true });
        await button.scrollIntoViewIfNeeded();
        await expect(button).toBeVisible();
        const bounds = await button.boundingBox();
        expect(bounds.x).toBeGreaterThanOrEqual(0);
        expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
        await page.screenshot({ path: `test-results/visual/agents-continue-${width}.png`, animations: 'disabled' });
    }
    await page.locator('.th-end-dialogue').click();
    await expect(page.getByRole('button', { name: '静候对方继续', exact: true })).toHaveCount(0);
    expect(errors).toEqual([]);
});
