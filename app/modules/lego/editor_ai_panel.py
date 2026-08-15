# -*- coding: utf-8 -*-
"""AI 工具面板 UI（从 editor_module 抽出）。

引擎状态 / Ollama 诊断 / 智能剪辑入口 / 历史列表。
业务方法仍在 EditorModule 与 AiAgentPanelMixin。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol

logger = logging.getLogger(__name__)

try:
    from PyQt6.QtWidgets import (
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover
    QWidget = object  # type: ignore


class _AiPanelHost(Protocol):
    _ai_model_label: Any
    _ai_gpu_label: Any
    _ai_task_label: Any
    _ai_progress: Any
    _ollama_status_label: Any
    _prompt_edit: Any
    _ai_history_list: Any

    def _sect(self, title: str) -> Any: ...
    def _refresh_ollama_diagnose_ui(self) -> None: ...
    def _show_ollama_diagnose_detail(self) -> None: ...
    def _on_ai_clip(self) -> None: ...
    def _funclip_process(self) -> None: ...
    def _autoclip_process(self) -> None: ...
    def _videofusion_process(self) -> None: ...
    def _lora_edit_process(self) -> None: ...
    def _generate_ai_subtitles(self) -> None: ...
    def _enhance_audio(self) -> None: ...
    def _on_send_clip_to_canvas(self) -> None: ...


def build_ai_panel_tab(editor: _AiPanelHost) -> Any:
    """构建 AI 页（逻辑仍在宿主 / AiAgentPanelMixin）。"""
    self = editor
    t = QWidget()
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
    c = QWidget()
    l = QVBoxLayout(c)
    l.setContentsMargins(8, 8, 8, 8)
    l.setSpacing(6)

    st = self._sect("🤖 AI引擎状态")
    st_lo = st.layout()
    info_row = QHBoxLayout()
    self._ai_model_label = QLabel("模型: 未加载")
    self._ai_model_label.setStyleSheet("color:#1e6bde;font-size:10px;font-weight:600;")
    info_row.addWidget(self._ai_model_label)
    try:
        # 修复：此前多绕了一层 dirname，解析到仓库根 data/active_provider.json
        # （不存在），实际文件位置是 app/data/active_provider.json（与
        # copywriting_module.py / account_ops_module.py / model_config.py
        # 里的算法一致：从本文件 app/modules/lego/xxx.py 往上 3 层到 app/）。
        # 这里模型状态因此常年显示"未加载"，即使真的已经激活了 provider。
        active_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data",
            "active_provider.json",
        )
        if os.path.exists(active_path):
            with open(active_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                provider = data.get("active_provider", "")
                if provider:
                    self._ai_model_label.setText(f"模型: {provider}")
                    self._ai_model_label.setStyleSheet("color:#22c55e;font-size:10px;font-weight:600;")
    except Exception as _e:
        logger.warning("操作异常（已忽略）: %s", _e)
    self._ai_gpu_label = QLabel("GPU: --")
    self._ai_gpu_label.setStyleSheet("color:#888;font-size:10px;")
    info_row.addWidget(self._ai_gpu_label)
    try:
        from app.core.gpu_acceleration import get_gpu_detector

        gpu = get_gpu_detector().detect_gpu()
        if gpu.gpu_type.value != "none":
            self._ai_gpu_label.setText(f"GPU: {gpu.name}")
            self._ai_gpu_label.setStyleSheet("color:#22c55e;font-size:10px;font-weight:600;")
    except Exception as _e:
        logger.warning("操作异常（已忽略）: %s", _e)
    info_row.addStretch()
    st_lo.addLayout(info_row)
    self._ai_task_label = QLabel("任务: 待机中")
    self._ai_task_label.setStyleSheet("color:#888;font-size:10px;")
    st_lo.addWidget(self._ai_task_label)
    self._ai_progress = QProgressBar()
    self._ai_progress.setRange(0, 100)
    self._ai_progress.setValue(0)
    self._ai_progress.setFixedHeight(4)
    self._ai_progress.setStyleSheet(
        "QProgressBar{background:#222;border:none;border-radius:2px;}"
        "QProgressBar::chunk{background:#1e6bde;border-radius:2px;}"
    )
    self._ai_progress.hide()
    st_lo.addWidget(self._ai_progress)
    l.addWidget(st)

    ol = self._sect("🖥️ Ollama 本地模型")
    ol_lo = ol.layout()
    self._ollama_status_label = QLabel("检测中…")
    self._ollama_status_label.setWordWrap(True)
    self._ollama_status_label.setStyleSheet("color:#888;font-size:10px;")
    ol_lo.addWidget(self._ollama_status_label)
    ollama_btn_row = QHBoxLayout()
    diag_btn = QPushButton("重新诊断")
    diag_btn.setStyleSheet(
        "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;"
        "border-radius:4px;padding:4px 10px;font-size:10px;}"
    )
    diag_btn.clicked.connect(self._refresh_ollama_diagnose_ui)
    ollama_btn_row.addWidget(diag_btn)
    detail_btn = QPushButton("诊断详情")
    detail_btn.setStyleSheet(
        "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;"
        "border-radius:4px;padding:4px 10px;font-size:10px;}"
    )
    detail_btn.clicked.connect(self._show_ollama_diagnose_detail)
    ollama_btn_row.addWidget(detail_btn)
    ollama_btn_row.addStretch()
    ol_lo.addLayout(ollama_btn_row)
    l.addWidget(ol)
    try:
        self._refresh_ollama_diagnose_ui()
    except Exception as _e:
        logger.warning("Ollama 诊断 UI 初始化失败: %s", _e)

    fl = self._sect("🎯 智能剪辑工具")
    fl_lo = fl.layout()
    prompt_row = QHBoxLayout()
    prompt_row.addWidget(QLabel("提示词:"))
    self._prompt_edit = QLineEdit()
    self._prompt_edit.setPlaceholderText("例如：提取反转高潮，控制在30秒内")
    self._prompt_edit.setStyleSheet(
        "QLineEdit{background:#0a0a0a;color:#ccc;border:1px solid #252525;"
        "border-radius:4px;padding:6px 8px;font-size:11px;}"
    )
    prompt_row.addWidget(self._prompt_edit, 1)
    fl_lo.addLayout(prompt_row)
    llm_btn = QPushButton("🧠 LLM 智能裁剪（需 Ollama + Whisper）")
    llm_btn.setStyleSheet(
        "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;"
        "padding:8px;font-size:11px;font-weight:600;}QPushButton:hover{background:#1557b0;}"
    )
    llm_btn.clicked.connect(self._on_ai_clip)
    fl_lo.addWidget(llm_btn)
    g = QGridLayout()
    g.setSpacing(4)
    # 修复：能力标签诚实化——原「LoRA/风格迁移」「音频AI/降噪增强+人声分离」
    # 会让人以为接了神经网络风格迁移/人声分离模型，实际实现分别是 FFmpeg
    # 调色滤镜组合、loudnorm+压缩，并无 LoRA 或声源分离。改成不虚标能力的
    # 文案（具体实现说明见各自弹窗）。
    tools = [
        ("🎬 FunClip", "场景检测\n自动分段", "#1e6bde", self._funclip_process),
        ("⚡ AutoClip", "高光识别\n多镜头组接", "#4caf50", self._autoclip_process),
        ("✨ Fusion", "视频修复\n画质增强", "#ff9800", self._videofusion_process),
        ("🎨 风格化", "调色滤镜\n（非LoRA/AI迁移）", "#9c27b0", self._lora_edit_process),
        ("📝 字幕AI", "语音识别\n自动字幕", "#22c55e", self._generate_ai_subtitles),
        ("🔊 音频增强", "响度/压缩\n（非人声分离）", "#6366f1", self._enhance_audio),
    ]
    for i, (nm, desc, hc, cb) in enumerate(tools):
        btn = QPushButton(f"{nm}\n{desc}")
        btn.setStyleSheet(
            f"""
                QPushButton {{
                    background:#0a0a0a;color:#ccc;border:1px solid #222;
                    border-left:3px solid {hc};border-radius:4px;
                    padding:8px 6px;font-size:10px;text-align:left;white-space:pre;
                }}
                QPushButton:hover {{background:#1a1a1a;color:#fff;}}
            """
        )
        btn.clicked.connect(cb)
        g.addWidget(btn, i // 2, i % 2)
    fl_lo.addLayout(g)
    l.addWidget(fl)

    canvas_sec = self._sect("🎨 AI 画布联动")
    canvas_lo = canvas_sec.layout()
    canvas_hint = QLabel("把当前选中片段推到 AI 画布（右下角「来自剪辑」可下载导入）")
    canvas_hint.setStyleSheet("color:#888;font-size:10px;")
    canvas_hint.setWordWrap(True)
    canvas_lo.addWidget(canvas_hint)
    to_canvas_btn = QPushButton("发送选中片段到画布")
    to_canvas_btn.setStyleSheet(
        "QPushButton{background:#7c3aed;color:#fff;border:none;border-radius:4px;"
        "padding:8px;font-size:11px;font-weight:600;}QPushButton:hover{background:#6d28d9;}"
    )
    to_canvas_btn.clicked.connect(self._on_send_clip_to_canvas)
    canvas_lo.addWidget(to_canvas_btn)
    l.addWidget(canvas_sec)

    hs = self._sect("📋 处理历史")
    self._ai_history_list = QListWidget()
    self._ai_history_list.setStyleSheet(
        "QListWidget{background:#0a0a0a;color:#888;border:1px solid #222;"
        "border-radius:4px;font-size:10px;}QListWidget::item{padding:4px 6px;}"
    )
    self._ai_history_list.setMaximumHeight(100)
    hs.layout().addWidget(self._ai_history_list)
    l.addWidget(hs)

    l.addStretch()
    s.setWidget(c)
    o = QVBoxLayout(t)
    o.setContentsMargins(0, 0, 0, 0)
    o.addWidget(s)
    return t
