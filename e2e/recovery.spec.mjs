import { expect, test } from '@playwright/test';

test('an unconfirmed turn waits for explicit recovery and an uncertain stop keeps its id', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.vue-character-selection')).toBeVisible();
    await page.evaluate(async () => {
        const { apiCall } = await import('/js/api.js');
        const { rememberTurn } = await import('/js/ghost/core/pending-turn.js');
        const created = await apiCall('/ghost/create_character', { method: 'POST', body: { profile: { name: '待确认行动测试', identity: '旅人' } } });
        rememberTurn('environment_interact', { record_history: true, character_id: created.character_id, scene: '博丽神社', player_name: '待确认行动测试',
            user_input: { action: '观察待确认的花瓣' }, turn_id: 'manual-recovery', history: [], scene_npcs: [] });
    });
    let generations = 0;
    page.on('request', request => { if (/environment_interact/.test(request.url())) generations += 1; });
    await page.reload();
    await page.locator('.character-card').filter({ hasText: '待确认行动测试' }).getByRole('button', { name: '继续异变' }).click();
    await expect(page.locator('.th-turn-recovery')).toBeVisible();
    expect(generations).toBe(0);
    await page.getByRole('button', { name: '确认停止', exact: true }).click();
    await expect(page.locator('.th-turn-recovery')).toContainText('尚未确认停止');
    await page.getByRole('button', { name: '恢复本回合', exact: true }).click();
    await expect(page.locator('.th-turn-recovery')).toHaveCount(0);
    await expect(page.locator('.th-message.is-player')).toHaveCount(1);
    await expect(page.locator('.th-message.is-player')).toContainText('观察待确认的花瓣');
    expect(generations).toBe(1);
});

test('reload recovers a committed reply without another model turn and retains command ids', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.vue-character-selection')).toBeVisible();
    const owner = await page.evaluate(async () => {
        const { apiCall } = await import('/js/api.js');
        const { rememberTurn } = await import('/js/ghost/core/pending-turn.js');
        const created = await apiCall('/ghost/create_character', { method: 'POST', body: { profile: { name: '回合恢复测试', identity: '旅人' } } });
        const body = { record_history: true, character_id: created.character_id, scene: '博丽神社', player_name: '回合恢复测试',
            user_input: { action: '观察恢复标识' }, turn_id: 'reload-recovery', history: [], scene_npcs: [] };
        rememberTurn('environment_interact', body);
        await apiCall('/ghost/environment_interact', { method: 'POST', body });
        return created.character_id;
    });
    let replayCount = 0;
    page.on('request', request => { if (/environment_interact/.test(request.url())) replayCount += 1; });
    await page.reload();
    await page.locator('.character-card').filter({ hasText: '回合恢复测试' }).getByRole('button', { name: '继续异变' }).click();
    await expect(page.locator('.th-message.is-player')).toContainText('观察恢复标识');
    await expect(page.locator('.th-message.is-player')).toHaveCount(1);
    await expect(page.locator('.th-turn-recovery')).toHaveCount(0);
    expect(replayCount).toBe(0);
    expect(await page.evaluate(id => localStorage.getItem(`touhou:pending-turn:v1:${id}`), owner)).toBeNull();

    const operations = [];
    await page.route('**/api/ghost/set_task_status', async route => {
        operations.push(route.request().postDataJSON().operation_id);
        await route.abort();
    });
    const retryCommand = async () => page.evaluate(async characterId => {
        const { apiCall } = await import('/js/api.js');
        await apiCall('/ghost/set_task_status', { method: 'POST', body: { character_id: characterId, task_id: 'test', status: 'active' } }).catch(() => {});
    }, owner);
    await retryCommand();
    await page.reload();
    await retryCommand();
    expect(operations).toHaveLength(2);
    expect(operations[0]).toBeTruthy();
    expect(operations[1]).toBe(operations[0]);
});
