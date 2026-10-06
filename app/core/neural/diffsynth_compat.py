# -*- coding: utf-8 -*-
"""diffsynth_engine 兼容层（2026-10-02，装主选引擎时的实测排障）

解决什么
========
`diffsynth_engine`（0.7.0）的 `utils/video.py` 顶层写：
    ``from moviepy import ImageSequenceClip, AudioFileClip, VideoClip``
这是 **moviepy 2.x** 的 import 形态；而本项目固定在 **moviepy 1.0.3**
（`moviepy.editor` 形态，见 `app/requirements.txt: moviepy>=1.0.3`），
两处活代码依赖 1.x API：
  - `app/integrations/autoclip/__init__.py`（4 处 `import moviepy.editor as mp`）
  - `app/modules/lego/editor_module.py:92`（`_lazy_import('moviepy.editor')`）
⇒ 直接 `import diffsynth_engine` 在本环境必炸 `ImportError`（已实测）。
   **升级 moviepy 到 2.x 会反向炸掉剪辑主路径**（2.x 删除了 `moviepy.editor`），
   而剪辑是本项目北极星 —— 不能因为装一个引擎顺手把主路径迁移了。

做法：进程内兼容垫片（shim）
============================
在 **import diffsynth_engine 之前**调用 `ensure_moviepy2_compat()`：
  - moviepy 已是 2.x ⇒ **空操作**（幂等，无副作用）；
  - moviepy 是 1.x ⇒ 把 `ImageSequenceClip / AudioFileClip / VideoClip`
    以**子类**形式挂到 `moviepy` 顶层，并补 2.x 改名的两个方法：
      · `subclipped(a, b)`  → 1.x 的 `subclip(a, b)`
      · `with_audio(audio)` → 1.x 的 `set_audio(audio)`

为什么子类形式是安全的
----------------------
1. **纯增量**：只往 `moviepy` 顶层**加**名字，不改 `moviepy.editor` 下任何既有行为
   —— 项目自己的 1.x 调用路径零影响。
2. **方法随实例走**：moviepy 1.x 的 `subclip`/`set_audio` 返回同类实例
   （1.x 的 set_* 系方法 in-place 返回 self），子类补的 2.x 名在链式调用中不丢。
3. **影响面实测**：全包只有 `utils/video.py` 一处 import moviepy，
   且只有 `save_video_with_audio()`（s2v 配音视频落盘）真正用到这两个改名方法；
   主生成路径（`save_video`）走 imageio，不碰 moviepy。

纪律
====
- **不是** monkeypatch 第三方包文件 —— 只改**本进程内**的模块属性，重启即还原。
- 将来若项目**有计划地**迁移 moviepy 2.x（把 autoclip / editor_module 一起改），
  本 shim 自动变空操作，可直接删除 —— 删除前搜 `ensure_moviepy2_compat` 的调用点。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_applied = False


def ensure_moviepy2_compat() -> bool:
    """确保 `from moviepy import ImageSequenceClip, ...`（2.x 形态）可用。

    幂等。返回 True 表示「现在可以 import diffsynth_engine 了」；
    返回 False 表示 moviepy 本身都不可用（那 diffsynth_engine 也跑不了，
    调用方应如实走降级路径，不要硬 import）。
    """
    global _applied
    if _applied:
        return True
    try:
        import moviepy
    except ImportError:
        logger.warning("[diffsynth_compat] moviepy 未安装，无法建立兼容层")
        return False

    if hasattr(moviepy, "ImageSequenceClip"):
        _applied = True            # 已是 moviepy 2.x，无需 shim
        return True

    try:
        import moviepy.editor as mpe
    except ImportError:
        logger.warning("[diffsynth_compat] moviepy.editor 不可用（版本形态未知）")
        return False

    class _Moviepy2Names:
        """moviepy 2.x 改名方法的 1.x 映射（只补 diffsynth_engine 用到的两个）。"""

        def subclipped(self, start_time=0, end_time=None):   # 2.x 名 → 1.x subclip
            return self.subclip(start_time, end_time)

        def with_audio(self, audio):                          # 2.x 名 → 1.x set_audio
            return self.set_audio(audio)

    class ImageSequenceClip(_Moviepy2Names, mpe.ImageSequenceClip):
        pass

    class AudioFileClip(_Moviepy2Names, mpe.AudioFileClip):
        pass

    class VideoClip(_Moviepy2Names, mpe.VideoClip):
        pass

    moviepy.ImageSequenceClip = ImageSequenceClip
    moviepy.AudioFileClip = AudioFileClip
    moviepy.VideoClip = VideoClip
    _applied = True
    logger.info("[diffsynth_compat] 已建立 moviepy 1.x→2.x 兼容层（进程内，重启还原）")
    return True


def import_diffsynth_engine():
    """**唯一推荐**的 diffsynth_engine 导入入口：先垫 shim，再 import。

    为什么要有这个入口：`import diffsynth_engine` 在 moviepy 1.x 下必炸
    （见模块 docstring），散落在各处的裸 import 必然有人忘记先垫 shim。
    失败时返回 None（诚实失败，调用方走 builtin 降级，不要硬撑）。
    """
    if not ensure_moviepy2_compat():
        return None
    try:
        import diffsynth_engine
        return diffsynth_engine
    except Exception:
        logger.debug("[diffsynth_compat] diffsynth_engine 导入失败", exc_info=True)
        return None
