# -*- coding: utf-8 -*-
"""一键拉片（视频→分镜）验证：语法 + 路由 AST + 纯函数 + 早退分支。

规避沙箱 wmic 污染：纯 AST 不 import 业务模块；import 测试走 subprocess 隔离。
结果统一写 UTF-8 到 _video_sb_result.txt。
"""
import ast
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
RESULT = os.path.join(HERE, "_video_sb_result.txt")

PY = sys.executable
lines = []
ok_all = True


def log(msg):
    lines.append(msg)
    print(msg)


def syntax_ok(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            ast.parse(f.read(), filename=path)
        return True
    except SyntaxError as e:
        lines.append(f"SYNTAX FAIL {path}: {e}")
        return False


def run(cmd, cwd=ROOT):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=180)
    return r


# 1) 语法
for rel in ("app/core/canvas_aigc.py", "app/core/canvas_server.py"):
    p = os.path.join(ROOT, rel)
    if syntax_ok(p):
        log(f"SYNTAX OK {rel}")
    else:
        ok_all = False

# 2) 路由 AST（检测不可达路由 / 重复注册）
r = run([PY, "_verify/check_canvas_routes.py"])
log("ROUTES stdout: " + (r.stdout or "").strip()[-2000:])
if r.returncode != 0:
    log(f"ROUTES EXIT {r.returncode}: " + (r.stderr or "").strip()[-2000:])
    ok_all = False

# 3) import 隔离测试：纯函数 + 早退分支
inner = (
    "import sys\n"
    "sys.path.insert(0, r'" + ROOT + "')\n"
    "from app.core.canvas_aigc import (\n"
    "    video_storyboard_breakdown, _infer_shot_size, _infer_camera,\n"
    ")\n"
    "# 纯函数\n"
    "assert _infer_shot_size(1.0) == '特写', _infer_shot_size(1.0)\n"
    "assert _infer_shot_size(2.0) == '近景'\n"
    "assert _infer_shot_size(4.0) == '中景'\n"
    "assert _infer_shot_size(6.0) == '全景'\n"
    "assert _infer_shot_size(10.0) == '远景'\n"
    "assert _infer_camera('特写') == '推'\n"
    "assert _infer_camera('全景') == '固定'\n"
    "# 早退分支（文件不存在，不触 ffmpeg）\n"
    "res = video_storyboard_breakdown('Z:/不存在的视频.mp4')\n"
    "assert res.get('ok') is False, res\n"
    "assert '不存在' in res.get('message', ''), res\n"
    "print('IMPORT+PURE OK')\n"
)
r = run([PY, "-c", inner])
log("IMPORT stdout: " + (r.stdout or "").strip()[-2000:])
if r.returncode != 0:
    log("IMPORT EXIT %d: %s" % (r.returncode, (r.stderr or "").strip()[-3000:]))
    ok_all = False

log("RESULT: " + ("ALL OK" if ok_all else "FAILED"))

with open(RESULT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

sys.exit(0 if ok_all else 1)
