import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const root = new URL('../', import.meta.url);
const source = await readFile(new URL('static/touhou-favicon.svg', root));
const sizes = [16, 24, 32, 48, 64, 128, 256];
const browser = await chromium.launch({ channel: process.env.TOUHOU_BROWSER || 'msedge', headless: true });
try {
    const page = await browser.newPage({ deviceScaleFactor: 1 });
    async function raster(size) {
        await page.setViewportSize({ width: size, height: size });
        await page.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:${size}px;height:${size}px}</style>${source}`);
        return page.screenshot({ omitBackground: true });
    }
    const png = await raster(1024);
    const images = [];
    for (const size of sizes) images.push(await raster(size));
    const directory = Buffer.alloc(6 + 16 * sizes.length);
    directory.writeUInt16LE(1, 2);
    directory.writeUInt16LE(sizes.length, 4);
    let offset = directory.length;
    images.forEach((image, index) => {
        const entry = 6 + index * 16;
        directory[entry] = directory[entry + 1] = sizes[index] % 256;
        directory.writeUInt16LE(1, entry + 4);
        directory.writeUInt16LE(32, entry + 6);
        directory.writeUInt32LE(image.length, entry + 8);
        directory.writeUInt32LE(offset, entry + 12);
        offset += image.length;
    });
    const ico = Buffer.concat([directory, ...images]);
    const sha256 = data => createHash('sha256').update(data).digest('hex');
    await writeFile(new URL('touhou.png', root), png);
    await writeFile(new URL('static/touhou.ico', root), ico);
    await writeFile(new URL('static/branding.json', root), JSON.stringify({
        source: 'static/touhou-favicon.svg', sizes,
        sha256: { 'static/touhou-favicon.svg': sha256(source), 'touhou.png': sha256(png), 'static/touhou.ico': sha256(ico) }
    }, null, 2) + '\n');
    console.log(`Brand assets updated: ${fileURLToPath(root)}`);
} finally {
    await browser.close();
}
