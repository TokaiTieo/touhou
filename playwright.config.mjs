import { defineConfig } from '@playwright/test';

export default defineConfig({
    testDir: './e2e',
    outputDir: './test-results/playwright-artifacts',
    globalTimeout: 100_000,
    timeout: 30_000,
    workers: 1,
    reporter: [['list']],
    use: {
        baseURL: 'http://127.0.0.1:8765',
        channel: 'msedge',
        headless: true,
        viewport: { width: 1440, height: 900 },
        screenshot: 'only-on-failure',
        trace: 'retain-on-failure'
    }
});
