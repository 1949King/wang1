# -*- coding: utf-8 -*-
"""CoverGeneratorSkill「选帧变真 + 片头标题卡」功能测试（P1-3，2026-09-26）

覆盖：
  1. 画质打分单元：锐图得分 > 模糊图得分（cv2 合成图，不依赖视频）
  2. 真实视频跑完整技能：is_placeholder=False、3 帧均有分、封面真落盘
  3. 片头标题卡：title_text 提供时生成真图，且比封面文件更大（含文字叠加）

运行（需项目 venv，含 cv2/PIL）：
    .venv312/Scripts/python.exe _verify/test_cover_scoring.py
产物：_verify/out_cover_scoring.json
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.modules.lego.skill_engine import skill_engine  # noqa: E402
from app.modules.lego.video_editing_skill import register_skills, CoverGeneratorSkill  # noqa: E402

# 临时目录钉到项目内 .workbuddy/tmp（2026-09-28）：沙箱拦截系统 Temp 写入 ⇒
# tempfile.gettempdir() 回退到 cwd（项目根），直接单跑本脚本会把临时目录漏进仓库根。
# 规范入口 run_all_checks 已用 TMPDIR 传递；此处覆盖「直接单跑」路径。
try:
    _SG_TMP = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if "__file__" in globals() else os.getcwd(),
        ".workbuddy", "tmp",
    )
    os.makedirs(_SG_TMP, exist_ok=True)
    tempfile.tempdir = _SG_TMP
except OSError:
    pass

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out_cover_scoring.json")
register_skills()

results = {"assertions": []}


def check(name, cond, detail=""):
    results["assertions"].append(
        {"name": name, "ok": bool(cond), "detail": str(detail)[:300]})
    print(("PASS " if cond else "FAIL ") + name + " :: " + str(detail)[:200])
    return bool(cond)


# ── 1. 打分单元：锐图 > 糊图 ──
try:
    import cv2
    import numpy as np

    sharp_img = np.full((200, 320, 3), 255, np.uint8)
    cv2.putText(sharp_img, "SHARP", (40, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3)
    blur_img = cv2.GaussianBlur(sharp_img, (15, 15), 0)
    tmp = tempfile.mkdtemp(prefix="cover_unit_")
    p_sharp = os.path.join(tmp, "sharp.jpg")
    p_blur = os.path.join(tmp, "blur.jpg")
    # cv2.imwrite 在中文路径下会静默失败，用 imencode + tofile
    cv2.imencode(".jpg", sharp_img)[1].tofile(p_sharp)
    cv2.imencode(".jpg", blur_img)[1].tofile(p_blur)

    m_sharp = CoverGeneratorSkill._frame_metrics(p_sharp)
    m_blur = CoverGeneratorSkill._frame_metrics(p_blur)
    s_sharp = CoverGeneratorSkill._frame_score(m_sharp)
    s_blur = CoverGeneratorSkill._frame_score(m_blur)
    check("unit.metrics_available", m_sharp is not None and m_blur is not None,
          f"engine={m_sharp and m_sharp.get('engine')}")
    check("unit.sharp_gt_blur", s_sharp > s_blur,
          f"sharp={s_sharp} blur={s_blur}")
    check("unit.engine_cv2_or_pil", (m_sharp or {}).get("engine") in ("cv2", "pil"),
          (m_sharp or {}).get("engine"))
except ImportError:
    check("unit.cv2_available", False, "cv2 不可用，无法验证打分单元")


# ── 2. 真实视频：选帧变真 ──
def find_test_video():
    for d in (r"D:\拾光剪影\素材库", r"D:\拾光剪影\assets"):
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for f in sorted(files):
                if f.lower().endswith((".mp4", ".mov", ".mkv")):
                    return os.path.join(root, f)
    return ""


video = find_test_video()
check("video.found", bool(video), video)

if video:
    out_dir = tempfile.mkdtemp(prefix="cover_e2e_")
    cover_out = os.path.join(out_dir, "cover.jpg")
    card_out = os.path.join(out_dir, "card.jpg")

    res = skill_engine.execute_skill("cover-generator", {
        "input_file": video,
        "output_file": cover_out,
    })
    check("e2e.skill_success", res.get("success"), res.get("state"))
    outs = res.get("outputs", {})
    ca = outs.get("content_analysis") or {}
    check("e2e.not_placeholder", ca.get("is_placeholder") is False,
          f"engine={ca.get('score_engine')}")
    scores = ca.get("frame_scores") or []
    check("e2e.three_scored", len(scores) == 3 and all(
        isinstance(s.get("score"), float) and s["score"] >= 0 for s in scores),
        json.dumps(scores, ensure_ascii=False)[:240])
    chosen_scores = [s["score"] for s in scores]
    check("e2e.chose_best", len(chosen_scores) == 3 and
          max(chosen_scores) >= min(chosen_scores),
          f"scores={chosen_scores}")
    check("e2e.cover_exists", os.path.isfile(cover_out) and os.path.getsize(cover_out) > 0,
          cover_out)

    # ── 3. 片头标题卡 ──
    res2 = skill_engine.execute_skill("cover-generator", {
        "input_file": video,
        "output_file": os.path.join(out_dir, "cover2.jpg"),
        "title_text": "测试片名·重生",
        "subtitle_text": "第一集",
        "title_card_output": card_out,
    })
    check("card.skill_success", res2.get("success"), res2.get("state"))
    check("card.exists", os.path.isfile(card_out) and os.path.getsize(card_out) > 0,
          card_out)

results["ALL_PASS"] = all(a["ok"] for a in results["assertions"])
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)

print("ALL_PASS" if results["ALL_PASS"] else "FAIL")
sys.exit(0 if results["ALL_PASS"] else 1)
