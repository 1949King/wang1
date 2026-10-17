const { spawnSync } = require('child_process');
const fs = require('fs');
// P0-1 抽包 Phase 1（2026-10-18）：画布真源已迁 vendor/packages/libtv（@shiguang/libtv），
// tsc 棘轮（基线 37，见 check_canvas_overlays 注记）随真源指向包目录。
process.chdir('D:/拾光剪影/vendor/packages/libtv');
const tscCmd = process.platform === 'win32'
  ? 'node_modules/typescript/bin/tsc'
  : 'node_modules/typescript/bin/tsc';
const r = spawnSync(process.execPath, [tscCmd, '--noEmit'], {
  encoding: 'utf8',
  maxBuffer: 32 * 1024 * 1024,
});
const out = (r.stdout || '') + (r.stderr || '');
fs.writeFileSync('D:/拾光剪影/_verify/_tsc_out.txt', out, 'utf8');
process.stdout.write('tsc exit=' + r.status + ' lines=' + out.split('\n').length + '\n');
process.exit(r.status === null ? 1 : r.status);
