# Debug Session: video-import-timeline

Status: [OPEN]

## Symptoms
- Import video dialog reports: `'NoneType' object has no attribute 'open_video'`.
- Timeline add dialog still reports: `name 'os' is not defined`.

## Hypotheses
1. `_preview_manager` is `None` during import, but `_import_video()` still calls `_preview_manager.open_video(...)`.
2. Timeline UI creation path uses `os.path.basename(...)` from a module that is still missing `import os`.
3. `EditorModule` has multiple `_add_clip_to_timeline` definitions, and runtime is using a different method body than expected.
4. The visible app window is running an older process that has not loaded current source changes.

## Evidence Plan
- Add temporary instrumentation around video import, preview manager calls, timeline manager add, and timeline widget clip creation.
- Reproduce once and inspect runtime evidence before applying further business fixes.


## Instrumentation
- Added temporary debug reporting around video import, timeline add, and ClipWidget creation.


## Evidence
- Pre-fix logs confirmed TimelineWidget had os available, but ClipWidget failed with QLabel.setEllipsize AttributeError.
- Pre-fix logs confirmed _preview_manager was None before open_video.
- Later logs confirmed PreviewManager is initialized before open_video and import result file contains: 1 PreviewManager.

## Fixes Applied
- Replaced QLabel.setEllipsize with QFontMetrics.elidedText in TimelineWidget ClipWidget.
- Initialized preview manager via _ensure_preview_manager() before open_video/get_frame_at.
- Added QPixmap import for preview frame rendering.

