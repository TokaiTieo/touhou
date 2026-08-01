import { execFileSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { extname, join, relative } from 'node:path';

const roots = ['js', 'scripts'];
const files = [];

function collect(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
        if (entry.name === 'node_modules') continue;
        const path = join(directory, entry.name);
        if (entry.isDirectory()) collect(path);
        else if (['.js', '.mjs'].includes(extname(entry.name))) files.push(path);
    }
}

for (const root of roots) collect(root);
for (const file of files.sort()) {
    execFileSync(process.execPath, ['--check', file], { stdio: 'pipe' });
}
console.log(`JavaScript syntax OK: ${files.length} files`);
