import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const runtimeRoot = join(tmpdir(), 'touhou-e2e-runtime');
const dataDir = join(runtimeRoot, 'data');
const playwrightCacheDir = join(runtimeRoot, 'playwright-cache');
rmSync(runtimeRoot, { recursive: true, force: true });
rmSync(dataDir, { recursive: true, force: true });
rmSync(playwrightCacheDir, { recursive: true, force: true });
mkdirSync(dataDir, { recursive: true });
mkdirSync(playwrightCacheDir, { recursive: true });

const server = spawn(
    'python',
    ['-m', 'uvicorn', 'backend.api:app', '--host', '127.0.0.1', '--port', '8765', '--log-level', 'warning'],
    {
        cwd: process.cwd(),
        env: {
            ...process.env,
            PYTHONUNBUFFERED: '1',
            DEBUG: 'False',
            PRIVATE_DEBUG: 'False',
            TOUHOU_DATA_DIR: dataDir,
            TOUHOU_E2E_MOCK_AI: '1'
        },
        stdio: ['ignore', 'pipe', 'pipe']
    }
);

server.stdout.on('data', chunk => process.stdout.write(`[e2e-server] ${chunk}`));
server.stderr.on('data', chunk => process.stderr.write(`[e2e-server] ${chunk}`));

async function waitForServer() {
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
        try {
            const response = await fetch('http://127.0.0.1:8765/api/health');
            if (response.ok) return;
        } catch {}
        await new Promise(resolve => setTimeout(resolve, 200));
    }
    throw new Error('E2E server did not become healthy');
}

function runPlaywright() {
    return new Promise((resolve, reject) => {
        const extraArgs = process.argv.slice(2);
        const child = spawn(
            process.execPath,
            ['node_modules/@playwright/test/cli.js', 'test', ...extraArgs],
            {
                cwd: process.cwd(),
                stdio: 'inherit',
                env: { ...process.env, PWTEST_CACHE_DIR: playwrightCacheDir }
            }
        );
        const timer = setTimeout(() => {
            child.kill();
            reject(new Error('Playwright exceeded the 100 second E2E budget'));
        }, 100_000);
        child.on('error', reject);
        child.on('exit', code => {
            clearTimeout(timer);
            code === 0 ? resolve() : reject(new Error(`Playwright exited with ${code}`));
        });
    });
}

try {
    await waitForServer();
    await runPlaywright();
} catch (error) {
    const logPath = join(dataDir, 'logs', 'touhou.log');
    if (existsSync(logPath)) {
        process.stderr.write(`\n[e2e-app-log]\n${readFileSync(logPath, 'utf8')}\n`);
    }
    throw error;
} finally {
    if (process.platform === 'win32') {
        spawnSync('taskkill', ['/pid', String(server.pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
        server.kill('SIGTERM');
    }
    await Promise.race([
        new Promise(resolve => server.once('exit', resolve)),
        new Promise(resolve => setTimeout(resolve, 5000))
    ]);
    rmSync(runtimeRoot, { recursive: true, force: true });
}
