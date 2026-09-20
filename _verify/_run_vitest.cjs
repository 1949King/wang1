const { spawnSync } = require('child_process');
process.chdir('D:/拾光剪影/vendor/shiguang-canvas');
const args = process.argv.slice(2);
const r = spawnSync(process.execPath, ['node_modules/vitest/vitest.mjs', 'run', ...args], {
  encoding: 'utf8',
});
process.stdout.write(r.stdout || '');
process.stderr.write(r.stderr || '');
process.exit(r.status === null ? 1 : r.status);
