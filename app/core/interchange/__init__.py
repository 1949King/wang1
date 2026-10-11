"""时间线互操作（OTIO / EDL / FCPXML 导入导出）。

对外统一入口，细节见 :mod:`app.core.interchange.otio_adapter`；
编辑器 ``_clips`` 桥接见 :mod:`app.core.interchange.editor_timeline_bridge`。
"""
from app.core.interchange.editor_timeline_bridge import (
    adapter_for_path,
    clips_to_timeline,
    export_editor_timeline,
    import_timeline_to_clips,
    is_timeline_extension,
    timeline_export_filters,
    timeline_to_clips,
)
from app.core.interchange.otio_adapter import (
    available_export_formats,
    export_otio,
    import_otio,
    is_available,
    otio_to_json_string,
    otio_to_timeline,
    roundtrip_ok,
    timeline_to_otio,
)

__all__ = [
    "adapter_for_path",
    "available_export_formats",
    "clips_to_timeline",
    "export_editor_timeline",
    "export_otio",
    "import_otio",
    "import_timeline_to_clips",
    "is_available",
    "is_timeline_extension",
    "otio_to_json_string",
    "otio_to_timeline",
    "roundtrip_ok",
    "timeline_export_filters",
    "timeline_to_clips",
    "timeline_to_otio",
]
