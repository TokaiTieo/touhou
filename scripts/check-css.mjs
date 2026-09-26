import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import assert from 'node:assert/strict';
import postcss from 'postcss';

function files(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? files(join(dir, entry.name)) : entry.name.endsWith('.css') ? [join(dir, entry.name)] : []);
}
for (const file of files('css')) {
    const root = postcss.parse(readFileSync(file, 'utf8'), { from: file });
    root.walkAtRules('import', rule => {
        const target = rule.params.match(/url\(['"](.+?)['"]\)/)?.[1];
        assert(target && existsSync(resolve(dirname(file), target)), `Missing CSS import in ${file}: ${rule.params}`);
    });
}
const shell = postcss.parse(readFileSync('css/vue-game.css', 'utf8'));
shell.walkRules(rule => assert(!/\.th-(message|composer|toolbar)(?=[\s.:>#[-]|$)/.test(rule.selector), `Component rule escaped its owner: ${rule.selector}`));
const messages = postcss.parse(readFileSync('css/components/messages.css', 'utf8'));
messages.walkRules('.th-message.is-system .th-message-body', rule => rule.walkDecls('border-radius', decl => assert.equal(decl.value, '8px')));
console.log(`CSS parsed and component ownership checked: ${files('css').length} files`);
