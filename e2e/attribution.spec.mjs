import { expect, test } from '@playwright/test';

test('unverified model memory is not announced as fact and can be reviewed by the producer', async ({ page }) => {
    await page.goto('/');
    const created = await page.evaluate(async () => (await fetch('/api/ghost/create_character', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile: { name: 'E2E人物归属', identity: '境界管理者', gm_mode: true } })
    })).json());
    await page.reload();
    await page.locator('.character-card').filter({ hasText: 'E2E人物归属' }).getByRole('button', { name: '继续异变' }).click();
    await page.evaluate(async () => {
        const dialogue = await import('/js/ghost/modules/dialogue.js');
        await dialogue.startNPCDialogue('npc_marisa', '雾雨魔理沙');
        await dialogue.callAIForDialogue('', '今天过得如何？');
    });
    // The mock proposes a Reimu memory even though Marisa is the dialogue target.
    await expect(page.locator('.th-message').filter({ hasText: '博丽灵梦记住了这件事' })).toHaveCount(0);
    const saved = await page.evaluate(async id => (await fetch(`/api/ghost/character/${id}`)).json(), created.character_id);
    const proposal = saved.npc_memories['博丽灵梦'].find(item => item.attribution_status === 'pending');
    expect(proposal).toBeTruthy();
    expect(saved.conversation_history.at(-1).npc_id).toBe('npc_marisa');
    await page.getByTitle('高级控制台').click();
    const consoleDialog = page.locator('.vue-producer-console');
    const memoryPanel = consoleDialog.locator('section').filter({ has: page.getByRole('heading', { name: 'NPC 长期记忆', exact: true }) });
    await expect(memoryPanel.locator('.producer-memory-preview')).toContainText('待核实');
    await memoryPanel.getByPlaceholder('NPC 名称', { exact: true }).fill('博丽灵梦');
    await memoryPanel.getByPlaceholder('记忆 ID，可留空').fill(proposal.id);
    await memoryPanel.getByPlaceholder('记忆内容', { exact: true }).fill('制作人核对：灵梦并未参与本次闲聊。');
    await memoryPanel.getByRole('button', { name: '确认/改写', exact: true }).click();
    await expect(memoryPanel.locator('.producer-memory-preview')).toContainText('来源明确');
    const updated = await page.evaluate(async id => (await fetch(`/api/ghost/character/${id}`)).json(), created.character_id);
    expect(updated.npc_memories['博丽灵梦'].some(item => item.id === proposal.id)).toBe(false);
    expect(updated.npc_memory_corrections['博丽灵梦'].some(item => item.memory_id === proposal.id)).toBe(true);
    expect(updated.npc_memories['博丽灵梦'].some(item => item.attribution_status === 'confirmed' && item.summary.includes('并未参与'))).toBe(true);
});
