import { expect, test } from '@playwright/test';


test.beforeEach(async ({ context }) => {
    await context.addInitScript(() => {
        localStorage.setItem('touhou_api_key', 'legacy-plaintext-key');
    });
});


test('boots the Vue app and removes legacy plaintext credentials', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/东方异变录/);
    await expect(page.locator('.vue-character-selection')).toBeVisible();
    await expect(page.locator('.app-brand strong')).toHaveText('东方异变录');
    expect(await page.evaluate(() => localStorage.getItem('touhou_api_key'))).toBeNull();
    const token = await page.locator('meta[name="touhou-session-token"]').getAttribute('content');
    expect(token?.length).toBeGreaterThan(20);
});


test('uses the Vue settings dialog without restoring the saved key', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#apiKeyBtnMenu')).toBeVisible();
    await page.locator('#apiKeyBtnMenu').click();
    await expect(page.locator('.vue-settings-dialog')).toBeVisible();
    await expect(page.locator('#vueApiKeyInput')).toHaveValue('');
    await expect(page.locator('.vue-settings-dialog')).toContainText('Key 不会保存在浏览器');
    await expect(page.locator('.accessibility-settings')).toContainText('本地朗读');
    await page.locator('#vueFontScale').evaluate(element => {
        element.value = '1.2';
        element.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await expect.poll(() => page.evaluate(() => document.documentElement.style.getPropertyValue('--touhou-font-scale'))).toBe('1.2');
    expect(await page.evaluate(() => localStorage.getItem('touhou_font_scale'))).toBe('1.2');
    await page.getByText('高对比度', { exact: true }).click();
    await expect(page.locator('html')).toHaveClass(/touhou-high-contrast/);
    await page.getByText('减少动态效果', { exact: true }).click();
    await expect(page.locator('html')).toHaveClass(/touhou-reduce-motion/);
    await page.locator('#vueSendKey').selectOption('ctrl-enter');
    expect(await page.evaluate(() => localStorage.getItem('touhou_send_key'))).toBe('ctrl-enter');
});

test('keeps the producer template secret and public relationship wording restrained', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '创建新外来者' }).click();
    const dialog = page.locator('.character-creation-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).not.toContainText('我是游戏制作人');
    await expect(dialog).not.toContainText('游戏制作人专用');
    await expect(dialog).not.toContainText('成人');
    await expect(dialog.getByPlaceholder('写下身份、外貌、性格、能力与来到幻想乡的缘由')).toBeVisible();
});


test('theme and protected API work from the injected game session', async ({ page }) => {
    await page.goto('/');
    const themeButton = page.getByRole('button', { name: /切换为/ });
    await themeButton.click();
    await expect(page.locator('body')).toHaveClass(/light-theme/);
    const status = await page.evaluate(async () => {
        const response = await fetch('/api/ghost/locations/all');
        return response.status;
    });
    expect(status).toBe(200);
});

test('loads a distinct widescreen scene for every base location', async ({ page }) => {
    await page.goto('/');
    const result = await page.evaluate(async () => {
        const { applySceneArtwork, getSceneArtwork } = await import('/js/ghost/ui/scene-art.js');
        const locations = [
            '博丽神社', '人间之里', '红魔馆', '雾雨魔法店', '魔法之森',
            '永远亭', '白玉楼', '守矢神社', '地灵殿', '雾之湖',
            '命莲寺', '妖怪之山', '月之都', '地狱', '太阳花田',
            '神灵庙', '后户之国', '畜生界', '虹龙洞集市', '梦境世界'
        ];
        const urls = locations.map(getSceneArtwork);
        const responses = await Promise.all(urls.map(url => fetch(url)));
        applySceneArtwork('畜生界');
        const { appUi } = await import('/js/vue/app-store.js');
        return {
            urls,
            statuses: responses.map(response => response.status),
            contentTypes: responses.map(response => response.headers.get('content-type')),
            appliedBackground: appUi.sceneArtwork
        };
    });

    expect(new Set(result.urls).size).toBe(20);
    expect(result.statuses.every(status => status === 200)).toBeTruthy();
    expect(result.contentTypes.every(type => type === 'image/png')).toBeTruthy();
    expect(result.appliedBackground).toContain('scene-animal-realm-v1.png');
});

test('opens the V8 producer tools without exposing them to ordinary players', async ({ page }) => {
    page.on('dialog', dialog => dialog.accept());
    await page.goto('/');
    const created = await page.evaluate(async () => {
        const response = await fetch('/api/ghost/create_character', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profile: {
                    name: 'E2E制作人工具验收', gender: '女', identity: '境界管理者',
                    appearance: '红白礼装', personality: '冷静', background: '内容工具隔离验收',
                    gm_mode: true
                }
            })
        });
        return response.json();
    });
    expect(created.character_id).toBeTruthy();
    await page.reload();
    await page.locator('.character-card').filter({ hasText: 'E2E制作人工具验收' }).getByRole('button', { name: '继续异变' }).click();
    await page.getByTitle('高级控制台').click();
    const consoleDialog = page.locator('.vue-producer-console');
    await expect(consoleDialog).toBeVisible();
    await expect(consoleDialog.locator('.producer-structured-editor')).toBeVisible();
    await consoleDialog.getByRole('button', { name: 'JSON', exact: true }).click();
    await expect(consoleDialog.locator('.producer-content-editor > textarea')).toBeVisible();
    await consoleDialog.getByRole('button', { name: '结构化', exact: true }).click();
    await consoleDialog.getByRole('button', { name: '校验并保存' }).click();
    await expect(consoleDialog.locator('.producer-backup-list button').first()).toBeVisible();
    await consoleDialog.getByRole('button', { name: '维护全部记忆' }).click();
    await expect(consoleDialog).toContainText('去重');
    await consoleDialog.getByRole('button', { name: '运行隔离评测' }).click();
    await expect(consoleDialog.locator('.producer-evaluation-list article')).toHaveCount(4, { timeout: 30_000 });
});


test('completes the playable loop, compares a rewrite, branches, and reloads the V8 save', async ({ page }) => {
    page.on('dialog', dialog => dialog.accept());
    await page.goto('/');
    const created = await page.evaluate(async () => {
        const response = await fetch('/api/ghost/create_character', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profile: {
                    name: 'E2E异变测试者',
                    gender: '女',
                    identity: '幻想乡原住民',
                    appearance: '佩戴红色发带',
                    personality: '冷静而好奇',
                    background: '长期居住在人间之里，熟悉符卡规则'
                }
            })
        });
        return response.json();
    });
    expect(created.character_id).toBeTruthy();

    await page.reload();
    const card = page.locator('.character-card').filter({ hasText: 'E2E异变测试者' });
    await expect(card).toBeVisible();
    await card.getByRole('button', { name: '继续异变' }).click();
    await expect(page.locator('.th-game')).toBeVisible();
    await expect(page.locator('.th-onboarding')).toBeVisible();
    await expect(page.locator('.th-npc').filter({ hasText: '博丽灵梦' })).toBeVisible();

    const messageCountBeforeComposition = await page.locator('.th-message').count();
    await page.locator('.th-composer textarea').nth(0).fill('输入法组合中的行动');
    await page.locator('.th-composer textarea').nth(0).dispatchEvent('keydown', {
        key: 'Enter', code: 'Enter', keyCode: 229, isComposing: true
    });
    await expect(page.locator('.th-message')).toHaveCount(messageCountBeforeComposition);

    // Force the streaming endpoint to fail once and verify the normal-request fallback.
    await page.route('**/api/ghost/environment_interact_stream', route => {
        route.abort('failed');
    }, { times: 1 });
    await page.locator('.th-composer textarea').nth(0).fill('完成结界裂隙调查并用仪式稳定博丽大结界');
    await page.locator('.th-send').click();
    const resolvedMessage = page.locator('.th-message').filter({ hasText: '结界波纹逐渐恢复平静' });
    await expect(resolvedMessage.locator('.th-message-content')).toBeVisible({ timeout: 30_000 });

    const stateBeforeRewrite = await page.evaluate(async characterId => {
        return (await fetch(`/api/ghost/character/${characterId}`)).json();
    }, created.character_id);
    await resolvedMessage.getByRole('button', { name: '重写' }).click();
    await expect(resolvedMessage.locator('.th-rewrite-variants')).toContainText('改写 1');
    const stateAfterRewrite = await page.evaluate(async characterId => {
        return (await fetch(`/api/ghost/character/${characterId}`)).json();
    }, created.character_id);
    expect(stateAfterRewrite.time).toEqual(stateBeforeRewrite.time);
    expect(stateAfterRewrite.player_state).toEqual(stateBeforeRewrite.player_state);
    expect(stateAfterRewrite.consequence_log).toEqual(stateBeforeRewrite.consequence_log);
    expect(stateAfterRewrite.conversation_history.at(-1).rewrite_candidates).toHaveLength(1);

    await page.getByRole('button', { name: '线索', exact: true }).click();
    await expect(page.locator('.th-archive-toggle')).toContainText('已归档线索');

    await page.getByRole('button', { name: '人物', exact: true }).click();
    const reimu = page.locator('.th-npc').filter({ hasText: '博丽灵梦' });
    await reimu.getByTitle('开始对话').click();
    await expect(page.locator('.th-end-dialogue')).toBeVisible();
    await page.locator('.th-composer textarea').nth(1).fill('之后有新的异变线索，请告诉我。');
    await page.locator('.th-send').click();
    await expect(page.locator('.th-message.is-dialogue').last()).toContainText('这次做得不错');
    await page.locator('.th-end-dialogue').click();

    await page.getByTitle('返回异变记录').click();
    await expect(page.locator('.vue-character-selection')).toBeVisible();
    const returnedCard = page.locator('.character-card').filter({ hasText: 'E2E异变测试者' });
    await returnedCard.getByRole('button', { name: '时序' }).click();
    await expect(page.locator('.snapshot-item').first()).toBeVisible();
    await page.locator('#branchName').fill('E2E异变测试者 · 独立分支');
    await page.locator('.snapshot-item').first().getByRole('button', { name: '创建分支' }).click();
    const branchCard = page.locator('.character-card').filter({ hasText: 'E2E异变测试者 · 独立分支' });
    await expect(branchCard).toBeVisible();

    await page.reload();
    const reloadedBranch = page.locator('.character-card').filter({ hasText: 'E2E异变测试者 · 独立分支' });
    await reloadedBranch.getByRole('button', { name: '继续异变' }).click();
    await expect(page.locator('.th-game')).toBeVisible();
    const save = await page.evaluate(async () => {
        const list = await (await fetch('/api/ghost/list_characters')).json();
        const branch = list.characters.find(item => item.profile?.name === 'E2E异变测试者 · 独立分支');
        return (await fetch(`/api/ghost/character/${branch.character_id}`)).json();
    });
    expect(save.save_version).toBe(8);
    expect(save.story_summary).toBeTruthy();
    expect(save.migration_history.some(item => item.version === 8)).toBeTruthy();
});
