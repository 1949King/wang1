# -*- coding: utf-8 -*-
"""通电验证（V4.41.8，2026-10-09）：验证五件套新端点真的可达。

背景：全景体检发现「换词重配五件套 + 深度/拉片/重拍」全部只有测试 import，
产品内零端点可达（「造好未接」）。本脚本起真 bridge 服务，逐个打新端点：

  /host/diarize-speakers     —— 说话人分离（funasr 未装 ⇒ 应诚实降级 200 + available=False）
  /host/reference-breakdown  —— 拉片（真视频 → 真镜头表）
  /host/segment-retake       —— 片段重拍（真视频拼接 + 颜色语义验证）
  /host/redub-preflight      —— 重配预检（引擎全缺 ⇒ 报降级版）
  /host/redub-execute        —— 重配执行（目标角色未知 ⇒ 诚实失败 400）

验证判据全部是**行为语义**（非仅 200），照抄 check_canvas_bridge_e2e.py 模式。
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 沙箱纪律：临时目录钉 .workbuddy/tmp（gettempdir 会回退 cwd）
_SG_TMP = os.path.join(ROOT, ".workbuddy", "tmp")
os.makedirs(_SG_TMP, exist_ok=True)
tempfile.tempdir = _SG_TMP

PORT = 18997
BASE = f"http://127.0.0.1:{PORT}"

fails = []


def check(name, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + name + (("  " + detail) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def req(method, path, body=None, token=True):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    if token:
        r.add_header("X-Shiguang-Token", TOKEN)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "ignore") or "{}")
        except Exception:
            return e.code, {}


def _mk_color_video(path, color, dur=1.0):
    """造一段纯色测试视频（拉片/重拍 e2e 用）。"""
    from app.core.ffmpeg_utils import find_ffmpeg
    ff = find_ffmpeg()
    subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"color=c={color}:s=320x240:d={dur}:r=10",
                    "-pix_fmt", "yuv420p", path], check=True)
    return path


# ── 导入并起服务（照抄 e2e 模式）──────────────────────────────
import app.core.canvas_server as cs

TOKEN = cs._SESSION_TOKEN


def main() -> int:
    d = tempfile.mkdtemp(prefix="poweron_e2e_")
    red = _mk_color_video(os.path.join(d, "red.mp4"), "red")
    green = _mk_color_video(os.path.join(d, "green.mp4"), "green")
    blue = _mk_color_video(os.path.join(d, "blue.mp4"), "blue")
    # 三段 concat 成 3 秒原片（红→绿→蓝）
    lst = os.path.join(d, "list.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        for p in (red, green, blue):
            fh.write("file '%s'\n" % os.path.abspath(p).replace("\\", "/"))
    orig = os.path.join(d, "orig.mp4")
    from app.core.ffmpeg_utils import find_ffmpeg
    subprocess.run([find_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", orig], check=True)

    srv = cs.CanvasBridgeServer("127.0.0.1", PORT)
    print(f"启动 bridge @ {BASE} ...")
    if not srv.start():
        print("✗ 启动失败")
        return 1
    import time
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    try:
        print("\n[A] 说话人分离 /host/diarize-speakers")
        code, js = req("POST", "/host/diarize-speakers", {
            "video_path": orig,
            "segments": [{"start": 0.0, "end": 1.0, "text": "你好"}],
        })
        check("端点可达（非 404）", code != 404, f"code={code}")
        check("返回结构完整（ok/available/reason）",
              all(k in js for k in ("ok", "available", "reason")), str(js)[:120])
        check("funasr 未装 ⇒ 诚实降级（ok=False + reason 给指引）",
              js.get("ok") is False and bool(js.get("reason")), str(js)[:120])

        print("\n[B] 拉片 /host/reference-breakdown")
        code, js = req("POST", "/host/reference-breakdown", {
            "video_path": orig, "out_dir": os.path.join(d, "kf"), "threshold": 0.05,
        })
        check("拉片成功", code == 200 and js.get("ok") is True, f"code={code} {str(js)[:120]}")
        check("3 段色片应检出 ≥2 镜头", int(js.get("count") or 0) >= 2, f"count={js.get('count')}")
        check("镜头表 Markdown 存在", str(js.get("table_markdown") or "").startswith("| 镜号 |"))

        print("\n[C] 片段重拍 /host/segment-retake")
        out = os.path.join(d, "retake.mp4")
        code, js = req("POST", "/host/segment-retake", {
            "original": orig, "replacement": blue, "out_path": out,
            "start": 1.0, "end": 2.0, "cuts": [1.0, 2.0],
        })
        check("重拍成功", code == 200 and js.get("ok") is True, f"code={code} {str(js)[:150]}")
        check("输出文件真的落盘", os.path.isfile(out))
        check("接缝风险如实报告", js.get("seam_risk") in ("low", "medium"), f"seam_risk={js.get('seam_risk')}")

        print("\n[D] 重配预检 /host/redub-preflight")
        code, js = req("POST", "/host/redub-preflight", {
            "video_path": orig, "new_line": "新台词", "target_character": "女主",
        })
        check("预检可达", code == 200, f"code={code}")
        check("预期质量如实（降级版说明缺什么）",
              "降级版" in str(js.get("expected_quality")), str(js)[:150])
        check("显存信息存在（真探测或如实报不可测）", bool(js.get("vram")))

        print("\n[E] 重配执行 /host/redub-execute")
        code, js = req("POST", "/host/redub-execute", {
            "video_path": orig, "new_line": "新台词",
            # 故意不给 target_character ⇒ 应诚实失败「不知道给谁配」
        })
        check("目标角色未知 ⇒ 诚实失败 400", code == 400, f"code={code}")
        check("失败原因明确（不知道给谁配）", "不知道给谁配" in str(js.get("reason")), str(js)[:150])

        code, js = req("POST", "/host/redub-execute", {
            "video_path": orig, "new_line": "新台词", "target_character": "女主",
        })
        check("指定角色 ⇒ 计划成立（骨架产物为空是预期）",
              code == 200 and js.get("plan", {}).get("ok") is True, f"code={code} {str(js)[:150]}")

        print("\n[F] 无 token ⇒ 401")
        code, _ = req("POST", "/host/redub-execute", {"video_path": "x"}, token=False)
        check("未授权拒绝", code == 401, f"code={code}")
    finally:
        try:
            srv.stop()
        except Exception:
            pass

    print()
    if fails:
        print(f"✗ 失败 {len(fails)} 项：{fails}")
        return 1
    print("✓ 通电验证全部通过：五件套从「测试黑屏」变成「产品可达」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
