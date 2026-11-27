const { spawnSync } = require('child_process');
const path = require('path');
// 测试随画布真源 @shiguang/canvas-core 执行，路径不绑定单台机器。
process.chdir(path.resolve(__dirname, '../vendor/packages/canvas-core'));
const args = process.argv.slice(2);
const r = spawnSync(process.execPath, ['node_modules/vitest/vitest.mjs', 'run', ...args], {
  encoding: 'utf8',
});
process.stdout.write(r.stdout || '');
process.stderr.write(r.stderr || '');
process.exit(r.status === null ? 1 : r.status);
