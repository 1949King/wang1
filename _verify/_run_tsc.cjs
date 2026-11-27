const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
// 画布真源为 @shiguang/canvas-core；从脚本位置解析，避免绑定单台机器绝对路径。
const canvasCoreDir = path.resolve(__dirname, '../vendor/packages/canvas-core');
process.chdir(canvasCoreDir);
const tscCmd = process.platform === 'win32'
  ? 'node_modules/typescript/bin/tsc'
  : 'node_modules/typescript/bin/tsc';
const r = spawnSync(process.execPath, [tscCmd, '--noEmit'], {
  encoding: 'utf8',
  maxBuffer: 32 * 1024 * 1024,
});
const out = (r.stdout || '') + (r.stderr || '');
fs.writeFileSync(path.resolve(__dirname, '_tsc_out.txt'), out, 'utf8');
process.stdout.write('tsc exit=' + r.status + ' lines=' + out.split('\n').length + '\n');
process.exit(r.status === null ? 1 : r.status);
