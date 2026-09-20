const { spawnSync } = require('child_process');
const fs = require('fs');
process.chdir('D:/拾光剪影/vendor/shiguang-canvas');
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
