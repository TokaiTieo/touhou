import { copyFile, mkdir } from 'node:fs/promises';

await mkdir('js/vendor', { recursive: true });
await copyFile(
  'node_modules/vue/dist/vue.esm-browser.prod.js',
  'js/vendor/vue.esm-browser.prod.js'
);

console.log('Vue browser runtime copied to js/vendor.');
