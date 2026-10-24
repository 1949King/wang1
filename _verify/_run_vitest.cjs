const { spawnSync } = require('child_process');
// P0-1 抽包 Phase 1（2026-10-18）：测试随画布真源迁入 @shiguang/libtv 包。
process.chdir('D:/拾光剪影/vendor/packages/libtv');
const args = process.argv.slice(2);
const r = spawnSync(process.execPath, ['node_modules/vitest/vitest.mjs', 'run', ...args], {
  encoding: 'utf8',
});
process.stdout.write(r.stdout || '');
process.stderr.write(r.stderr || '');
process.exit(r.status === null ? 1 : r.status);
