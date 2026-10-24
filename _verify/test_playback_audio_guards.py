# -*- coding: utf-8 -*-
"""冒烟：播放音频路径不抢播放头、不挂视频输出。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def main():
    errors = []
    # 不实例化完整 EditorModule（需 QApp）；静态检查源码约定
    path = os.path.join(ROOT, "app", "modules", "lego", "editor_module.py")
    src = open(path, encoding="utf-8").read()
    if "setVideoOutput(self._video_widget)" in src:
        errors.append("QMediaPlayer still bound to QVideoWidget (double decode)")
    if "self._audio_output = None" in src and "on_deactivated" in src:
        # 允许局部临时变量，但不允许停用时清空
        chunk = src.split("def on_deactivated", 1)[-1].split("\n    def ", 1)[0]
        if "_audio_output = None" in chunk:
            errors.append("on_deactivated still clears _audio_output")
    if "if getattr(self, \"_timeline_playing\", False):\n            return" not in src.replace("'", '"'):
        # looser check
        if "_timeline_playing" not in src or "def _on_position_changed" not in src:
            errors.append("missing timeline_playing guard near position handler")
        else:
            # find _on_position_changed body
            i = src.find("def _on_position_changed")
            body = src[i:i + 400]
            if "_timeline_playing" not in body:
                errors.append("_on_position_changed missing timeline_playing early-return")
    if "def _arm_media_audio" not in src:
        errors.append("missing _arm_media_audio")
    if 'pm.set_preview_quality("low")' not in src and "pm.set_preview_quality('low')" not in src:
        errors.append("playback preview quality not set to low")
    if "FROZEN:playback-av:main-audio" not in src:
        errors.append("missing FROZEN marker on main-audio block")

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("PASS playback audio/stutter guards")
    sys.exit(0)


if __name__ == "__main__":
    main()
