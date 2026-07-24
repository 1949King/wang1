"""
文案生成模块 (CopywritingModule)
==================================
从 modules.py 拆分出来的独立模块文件。

功能:
- AI 文案生成 (标题/描述/标签/脚本)
- 视频导入分析 (帧提取 + OCR 内容识别)
- 多平台适配 (抖音/快手/视频号/小红书/B站)
- 多模型调用 (DeepSeek/豆包/本地模板)
- 历史记录管理 (50条上限，点击回放)
- C-1: 批量文案生成 (batch_generate)
- C-3: A/B 文案对比 (ab_generate + 5维评分引擎)
"""

import os
import json
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QComboBox, QGroupBox, QTabWidget,
    QListWidget, QListWidgetItem, QApplication,
    QMessageBox, QFileDialog,
)
from PyQt6.QtCore import Qt, QTimer

from .base_module import BaseModule
from .core import EventBus, EventType

logger = logging.getLogger("AI短剧编辑器.copywriting")


class CopywritingModule(BaseModule):
    """
    文案生成模块
    - 输入:剧情,关键词,标题
    - 输出:标题,话题,简介,脚本
    """
    
    module_id = "copywriting"
    module_name = "文案生成"
    module_icon = "✍️"
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        header = QLabel("✍️ AI文案生成")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(header)
        
        input_group = self._create_card("输入内容")
        input_layout = QVBoxLayout(input_group)
        
        # 视频导入按钮
        video_import_layout = QHBoxLayout()
        video_import_btn = QPushButton("🎬 导入视频分析")
        video_import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        video_import_btn.clicked.connect(self._import_video)
        video_import_layout.addWidget(video_import_btn)
        video_import_layout.addStretch()
        input_layout.addLayout(video_import_layout)
        
        self._content_input = QTextEdit()
        self._content_input.setPlaceholderText("输入视频内容描述,剧情概要或关键词...")
        self._content_input.setMinimumHeight(120)
        self._content_input.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
            }
        """)
        input_layout.addWidget(self._content_input)
        
        # 视频信息显示
        self._video_info_label = QLabel("未导入视频")
        self._video_info_label.setStyleSheet("color: #808080; font-size: 12px;")
        input_layout.addWidget(self._video_info_label)
        
        options_layout = QHBoxLayout()
        
        options_layout.addWidget(QLabel("平台:"))
        self._platform_combo = QComboBox()
        self._platform_combo.addItems(["抖音", "快手", "视频号", "小红书", "B站"])
        self._platform_combo.setStyleSheet(self._combo_style())
        options_layout.addWidget(self._platform_combo)
        
        options_layout.addWidget(QLabel("风格:"))
        self._style_combo = QComboBox()
        self._style_combo.addItems(["爆款", "剧情", "解说", "情感", "搞笑"])
        self._style_combo.setStyleSheet(self._combo_style())
        options_layout.addWidget(self._style_combo)
        
        options_layout.addWidget(QLabel("模型:"))
        self._model_combo = QComboBox()
        self._model_combo.addItems(["DeepSeek", "豆包", "本地模板"])
        self._model_combo.setStyleSheet(self._combo_style())
        options_layout.addWidget(self._model_combo)
        
        options_layout.addStretch()
        input_layout.addLayout(options_layout)
        
        layout.addWidget(input_group)
        
        # ── 按钮行：生成 + 推送到剪辑 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        
        generate_btn = QPushButton("🚀 生成文案")
        generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 14px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #43a047;
            }
        """)
        generate_btn.clicked.connect(self._generate)
        btn_row.addWidget(generate_btn, 2)
        
        push_btn = QPushButton("📋 推送到剪辑模块")
        push_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 14px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #666666;
            }
        """)
        push_btn.clicked.connect(self._push_to_editor)
        push_btn.setEnabled(False)
        self._push_btn = push_btn
        btn_row.addWidget(push_btn, 1)
        
        layout.addLayout(btn_row)
        
        output_group = self._create_card("生成结果")
        output_layout = QVBoxLayout(output_group)
        
        self._output_tabs = QTabWidget()
        self._output_tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #1a1a1a; }
            QTabBar::tab {
                background-color: #2a2a2a;
                color: #808080;
                padding: 8px 20px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected { background-color: #3a3a3a; color: #ffffff; }
        """)
        
        for name in ["标题", "描述", "标签", "脚本"]:
            output = QTextEdit()
            output.setReadOnly(True)
            output.setStyleSheet("""
                QTextEdit {
                    background-color: #1a1a1a;
                    color: #ffffff;
                    border: none;
                    padding: 10px;
                    font-size: 14px;
                }
            """)
            self._output_tabs.addTab(output, name)
        
        output_layout.addWidget(self._output_tabs)
        
        # ── 单条操作按钮 ──
        copy_row = QHBoxLayout()
        copy_row.setSpacing(6)
        self._copy_title_btn = self._make_small_btn("📝 复制标题")
        self._copy_desc_btn = self._make_small_btn("📄 复制描述")
        self._copy_tags_btn = self._make_small_btn("🏷 复制标签")
        self._copy_script_btn = self._make_small_btn("🎬 复制脚本")
        self._copy_title_btn.clicked.connect(lambda: self._copy_tab(0))
        self._copy_desc_btn.clicked.connect(lambda: self._copy_tab(1))
        self._copy_tags_btn.clicked.connect(lambda: self._copy_tab(2))
        self._copy_script_btn.clicked.connect(lambda: self._copy_tab(3))
        copy_row.addWidget(self._copy_title_btn)
        copy_row.addWidget(self._copy_desc_btn)
        copy_row.addWidget(self._copy_tags_btn)
        copy_row.addWidget(self._copy_script_btn)
        copy_row.addStretch()
        output_layout.addLayout(copy_row)
        
        # ── 历史记录 ──
        history_header = QHBoxLayout()
        history_label = QLabel("📜 生成历史")
        history_label.setStyleSheet("color: #cccccc; font-size: 12px; font-weight: bold;")
        history_header.addWidget(history_label)
        history_header.addStretch()
        clear_history_btn = self._make_small_btn("清空")
        clear_history_btn.clicked.connect(self._clear_history)
        history_header.addWidget(clear_history_btn)
        output_layout.addLayout(history_header)
        
        self._history_list = QListWidget()
        self._history_list.setMaximumHeight(150)
        self._history_list.setStyleSheet("""
            QListWidget {
                background-color: #161616;
                color: #cccccc;
                border: 1px solid #2a2a2a;
                border-radius: 6px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #222222;
            }
            QListWidget::item:hover {
                background-color: #1e2a3a;
                color: #ffffff;
            }
            QListWidget::item:selected {
                background-color: #1a3050;
                color: #ffffff;
            }
        """)
        self._history_list.itemClicked.connect(self._on_history_selected)
        output_layout.addWidget(self._history_list)
        
        # 历史数据存储
        self._history: list = []
        
        layout.addWidget(output_group, 1)
    
    def _make_small_btn(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: #999999;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                color: #ffffff;
            }
        """)
        return btn
    
    def _create_card(self, title: str) -> QGroupBox:
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        return group
    
    def _combo_style(self) -> str:
        return """
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 100px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """
    
    def _import_video(self):
        """导入视频并进行真实帧提取和元数据分析"""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from PyQt6.QtCore import QThread, pyqtSignal
        import os

        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", "",
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.webm)"
        )

        if not file_path:
            return

        try:
            video_name = os.path.basename(file_path)
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

            # 尝试用 OpenCV 读取视频元数据
            fps, total_frames, duration_sec, width, height = 0, 0, 0, 0, 0
            has_cv2 = False
            try:
                import cv2
                has_cv2 = True
                cap = cv2.VideoCapture(file_path)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    duration_sec = total_frames / fps if fps > 0 else 0
                    cap.release()
            except ImportError:
                pass

            # 构建视频信息字符串
            info_parts = [f"已导入视频: {video_name}", f"大小: {file_size_mb:.1f}MB"]
            if duration_sec > 0:
                mins, secs = divmod(int(duration_sec), 60)
                info_parts.append(f"时长: {mins}分{secs}秒")
            if width > 0:
                info_parts.append(f"分辨率: {width}x{height}")
            if fps > 0:
                info_parts.append(f"帧率: {fps:.1f}fps")

            self._video_info_label.setText(" | ".join(info_parts))
            if not has_cv2:
                self._video_info_label.setText(
                    self._video_info_label.text() +
                    "\n💡 提示: 安装 opencv-python 可获取更详细的视频元数据"
                )

            # 尝试提取关键帧并做内容分析
            video_content = self._analyze_video_content(file_path, fps, total_frames, duration_sec)

            self._content_input.setText(video_content)
            self._generate_from_video(video_content)

        except Exception as e:
            QMessageBox.warning(self, "错误", f"视频分析失败: {str(e)}")

    def _analyze_video_content(self, file_path: str, fps: float, total_frames: int, duration_sec: float) -> str:
        """从视频提取关键帧并分析内容，提取元数据描述"""
        import os

        parts = []
        video_name = os.path.basename(file_path)

        # 基础元数据描述
        if duration_sec > 0:
            if duration_sec < 60:
                parts.append(f"短视频（{int(duration_sec)}秒）")
            elif duration_sec < 300:
                parts.append(f"中等长度视频（{int(duration_sec / 60)}分钟）")
            else:
                parts.append(f"长视频（{int(duration_sec / 60)}分钟）")

        if fps > 0:
            parts.append(f"帧率{fps:.0f}fps")

        # 尝试提取关键帧并用 OCR 识别画面文字
        try:
            import cv2
            cap = cv2.VideoCapture(file_path)
            if cap.isOpened() and fps > 0:
                # 提取 3-5 个关键帧（开始、中间、结尾）
                key_positions = []
                if total_frames > 0:
                    key_positions = [
                        int(total_frames * 0.1),
                        int(total_frames * 0.5),
                        int(total_frames * 0.9),
                    ]

                ocr_texts = []
                for pos in key_positions:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        # 尝试 OCR 识别
                        try:
                            import easyocr
                            reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
                            results = reader.readtext(frame)
                            texts = [r[1] for r in results if r[2] > 0.5][:5]
                            ocr_texts.extend(texts)
                        except (ImportError, Exception):
                            # 无 OCR 时用帧统计信息
                            pass

                cap.release()

                if ocr_texts:
                    # 取前3个关键词作为内容提示
                    parts.append("画面包含关键词: " + "、".join(ocr_texts[:3]))
        except Exception:
            pass

        # 回退: 基于视频文件名和基础特征生成描述
        description = f"这是一段视频文件「{video_name}」，" + "，".join(parts) + "。"
        description += "请根据视频特征生成适合短视频平台发布的文案。"

        return description
    
    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """调用当前激活的 AI 模型生成文案，失败时回退到本地模板

        调用链路:
          1. 首选: ai_engine.chat_with_fallback()（统一 AI 入口）
          2. 备选: cloud_api_service.chat()（直连云端模型）
          3. 回退: _template_generate()（本地智能模板）
        """
        import os, json
        import traceback as _tb

        # ── 检查是否有激活的 AI 模型 ──
        active_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                   "data", "active_provider.json")

        provider_id = ""
        try:
            if os.path.exists(active_file):
                with open(active_file, 'r', encoding='utf-8') as f:
                    provider_id = json.load(f).get("active_provider", "")
        except (OSError, json.JSONDecodeError, KeyError):
            pass

        if not provider_id:
            # 无激活模型，直接走模板回退
            return ""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # ── 策略 1: 通过 ai_engine 统一调用 ──
        try:
            from app.core.ai_engine import ai_engine
            result_parts = []
            for chunk in ai_engine.chat_with_fallback(
                messages=messages,
                template=lambda: "",
                temperature=0.8, max_tokens=2048,
            ):
                if chunk and not chunk.startswith("错误") and not chunk.startswith("API 错误"):
                    result_parts.append(chunk)
            result = "".join(result_parts).strip()
            if result and len(result) > 10:
                return result
        except Exception as e:
            print(f"[Copywriting] ai_engine 调用失败: {e}，回退到 cloud_api_service")

        # ── 策略 2: 直连 cloud_api_service ──
        try:
            from .cloud_api import cloud_api_service
            result_parts = []
            for chunk in cloud_api_service.chat(provider_id, messages, stream=False,
                                                 temperature=0.8, max_tokens=2048):
                if chunk and not chunk.startswith("错误") and not chunk.startswith("API 错误"):
                    result_parts.append(chunk)
            result = "".join(result_parts).strip()
            if result and len(result) > 10:
                return result
        except Exception as e:
            print(f"[Copywriting] cloud_api_service 调用失败: {e}")

        # ── 所有 AI 路径失败，返回空字符串交由调用方走模板 ──
        return ""
    
    def _parse_llm_response(self, raw: str, content: str) -> dict:
        """从 LLM 原始回复中解析出标题/描述/标签/脚本"""
        result = {"title": "", "description": "", "tags": "", "script": ""}
        if not raw:
            return result
        lines = raw.split("\n")
        section = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if "标题" in line and ("：" in line or ":" in line):
                section = "title"
                val = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                result["title"] = val
            elif "描述" in line and ("：" in line or ":" in line):
                section = "desc"
                val = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                result["description"] = val
            elif "标签" in line and ("：" in line or ":" in line):
                section = "tags"
                val = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                result["tags"] = val
            elif "脚本" in line and ("：" in line or ":" in line):
                section = "script"
                val = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                result["script"] = val
            elif section == "title" and not result["title"].endswith(line):
                result["title"] += line
            elif section == "desc":
                result["description"] += "\n" + line if result["description"] else line
            elif section == "tags":
                result["tags"] += " " + line if result["tags"] else line
            elif section == "script":
                result["script"] += "\n" + line if result["script"] else line
        return result
    
    def _template_generate(self, content: str):
        """模板回退：当 LLM 不可用时使用智能模板

        根据内容长度和平台/风格自适应生成文案，
        相比纯硬编码截断，提供更合理的回退体验。
        """
        platform = self._platform_combo.currentText()
        style = self._style_combo.currentText()

        # 按平台定制标签和描述风格
        platform_tags = {
            "抖音": ("追剧", "上头短片", "热门推荐"),
            "快手": ("短剧推荐", "剧情", "爽文改编"),
            "小红书": ("好看推荐", "好剧安利", "剧情种草"),
            "视频号": ("短剧精选", "剧情推荐", "热播推荐"),
        }
        plat_tag1, plat_tag2, plat_tag3 = platform_tags.get(platform, ("短剧", "热门", "推荐"))

        # 按风格定制标题模板
        style_templates = {
            "爆款": ("🔥", "看完直呼过瘾", "全程高能"),
            "剧情": ("📖", "剧情反转太绝了", "代入感拉满"),
            "解说": ("🎙️", "深度解析来了", "干货满满"),
            "情感": ("💕", "泪目了家人们", "共鸣感爆棚"),
            "搞笑": ("😂", "笑不活了", "快乐源泉"),
        }
        emoji, tag1, tag2 = style_templates.get(style, ("🔥", "精彩", "推荐"))

        # 智能截取内容摘要（优先断在标点符号处）
        def smart_truncate(text: str, max_len: int) -> str:
            text = text.strip()
            if len(text) <= max_len:
                return text
            # 尽量在标点处断开
            cut = max_len
            for punct in "，。！？；：\n,.;:!?":
                pos = text.rfind(punct, 0, max_len)
                if pos > max_len // 2:
                    cut = pos + 1
                    break
            return text[:cut]

        content_summary = smart_truncate(content, 40)
        post_summary = smart_truncate(content, 80)

        title = f"{emoji} {smart_truncate(content, 25)}，{tag1}！"
        desc = (
            f"#{plat_tag1} #{plat_tag2}\n\n"
            f"{post_summary}...\n\n"
            f"{platform}热推 | {style}风格 | {tag2}"
        )
        tags = f"#{plat_tag3} #短剧 #热门 #推荐 #追剧 #{platform}"
        script = (
            f"[开场 hook]\n{smart_truncate(content, 50)}...\n\n"
            "[高潮转折]\n意想不到的反转让观众欲罢不能\n\n"
            "[结尾引导]\n点赞收藏转发，下期更精彩"
        )

        self._output_tabs.widget(0).setText(title)
        self._output_tabs.widget(1).setText(desc)
        self._output_tabs.widget(2).setText(tags)
        self._output_tabs.widget(3).setText(script)
    
    def _generate_from_video(self, video_content):
        """根据视频内容分析结果，调用 AI 生成文案"""
        platform = self._platform_combo.currentText()
        style = self._style_combo.currentText()
        
        system_prompt = (
            f"你是{platform}平台的顶级短剧文案专家。"
            f"请根据视频内容生成{style}风格的文案。"
            "严格按以下格式输出（不要省略任何部分）：\n"
            "标题：[一条吸睛标题，15字以内]\n"
            "描述：[一段吸引人的描述，50-80字]\n"
            "标签：[5-8个相关标签，用#开头]\n"
            "脚本：[开场→高潮→结尾的口播脚本]"
        )
        user_prompt = f"视频内容概要：{video_content[:500]}\n平台：{platform}\n风格：{style}"
        
        raw = self._call_llm(system_prompt, user_prompt)
        if raw:
            parsed = self._parse_llm_response(raw, video_content)
            self._output_tabs.widget(0).setText(parsed["title"] or f"🔥 {video_content[:20]}，必看！")
            self._output_tabs.widget(1).setText(parsed["description"] or f"关于{video_content[:30]}的精彩内容\n\n#短剧 #热门")
            self._output_tabs.widget(2).setText(parsed["tags"] or "#短剧 #热门 #推荐")
            self._output_tabs.widget(3).setText(parsed["script"] or f"[开场]\n{video_content[:50]}...\n[结尾]\n关注不迷路")
        else:
            self._template_generate(video_content)
        
        self._event_bus.emit(EventType.COPY_GENERATED, {
            "title": self._output_tabs.widget(0).toPlainText(),
            "description": self._output_tabs.widget(1).toPlainText()
        })

        self._save_to_history()
    
    def _generate(self):
        content = self._content_input.toPlainText().strip()
        if not content:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请先输入内容或导入视频")
            return
        
        platform = self._platform_combo.currentText()
        style = self._style_combo.currentText()
        
        # 如果选择了"本地模板"，直接走模板
        if self._model_combo.currentText() == "本地模板":
            self._template_generate(content)
            self._event_bus.emit(EventType.COPY_GENERATED, {
                "title": self._output_tabs.widget(0).toPlainText(),
                "description": self._output_tabs.widget(1).toPlainText()
            })
            self._save_to_history()  # 本地模板也保存历史
            return
        
        system_prompt = (
            f"你是{platform}平台的顶级短剧文案专家。"
            f"请根据用户输入生成{style}风格的爆款文案。"
            "严格按以下格式输出（不要省略任何部分）：\n"
            "标题：[一条吸睛标题，15字以内]\n"
            "描述：[一段吸引人的描述，50-80字]\n"
            "标签：[5-8个相关标签，用#开头]\n"
            "脚本：[包含开场hook→高潮转折→结尾引导的口播脚本]"
        )
        user_prompt = f"用户输入：{content[:500]}\n目标平台：{platform}\n文案风格：{style}"
        
        raw = self._call_llm(system_prompt, user_prompt)
        if raw:
            parsed = self._parse_llm_response(raw, content)
            self._output_tabs.widget(0).setText(parsed["title"] or f"🔥 {content[:20]}，必看！")
            self._output_tabs.widget(1).setText(parsed["description"] or f"关于{content[:30]}的精彩内容\n\n#短剧 #热门")
            self._output_tabs.widget(2).setText(parsed["tags"] or "#短剧 #热门 #推荐")
            self._output_tabs.widget(3).setText(parsed["script"] or f"[开场]\n{content[:50]}...\n[结尾]\n关注不迷路")
        else:
            self._template_generate(content)
        
        self._event_bus.emit(EventType.COPY_GENERATED, {
            "title": self._output_tabs.widget(0).toPlainText(),
            "description": self._output_tabs.widget(1).toPlainText()
        })

        self._save_to_history()
    
    # ════════════════════════════════════════════════════════════════
    # 新增: 历史记录 + 推送到剪辑模块 (5.4 + 5.5)
    # ════════════════════════════════════════════════════════════════

    def _save_to_history(self):
        """将当前输出保存到历史记录"""
        from datetime import datetime
        entry = {
            "time": datetime.now().strftime("%m/%d %H:%M"),
            "platform": self._platform_combo.currentText(),
            "style": self._style_combo.currentText(),
            "title": self._output_tabs.widget(0).toPlainText().strip(),
            "description": self._output_tabs.widget(1).toPlainText().strip(),
            "tags": self._output_tabs.widget(2).toPlainText().strip(),
            "script": self._output_tabs.widget(3).toPlainText().strip(),
        }
        # 去重: 相同标题不重复添加
        for h in self._history:
            if h.get("title") == entry["title"]:
                return
        self._history.insert(0, entry)
        if len(self._history) > 50:
            self._history = self._history[:50]
        self._update_history_ui()

    def _update_history_ui(self):
        """刷新历史列表 UI"""
        self._history_list.clear()
        for entry in self._history:
            preview = entry.get("title", "无标题")[:40]
            time_str = entry.get("time", "")
            platform = entry.get("platform", "")
            style = entry.get("style", "")
            item_text = f"[{time_str}] {platform}/{style} — {preview}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._history_list.addItem(item)
        # 启用推送到剪辑按钮
        if self._history:
            self._push_btn.setEnabled(True)

    def _on_history_selected(self, item: QListWidgetItem):
        """点击历史记录项 → 恢复到输出 tabs"""
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return
        self._output_tabs.widget(0).setText(entry.get("title", ""))
        self._output_tabs.widget(1).setText(entry.get("description", ""))
        self._output_tabs.widget(2).setText(entry.get("tags", ""))
        self._output_tabs.widget(3).setText(entry.get("script", ""))

    def _clear_history(self):
        """清空历史记录"""
        self._history.clear()
        self._history_list.clear()
        self._push_btn.setEnabled(False)

    def _copy_tab(self, tab_index: int):
        """复制单个 tab 内容到剪贴板"""
        text = self._output_tabs.widget(tab_index).toPlainText().strip()
        if not text:
            return
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        # 短暂高亮提示
        btns = [self._copy_title_btn, self._copy_desc_btn,
                self._copy_tags_btn, self._copy_script_btn]
        if tab_index < len(btns):
            btn = btns[tab_index]
            original = btn.text()
            btn.setText("✓ 已复制")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1500, lambda b=btn, o=original: b.setText(o))

    def _push_to_editor(self):
        """将当前生成的文案推送到剪辑模块"""
        title = self._output_tabs.widget(0).toPlainText().strip()
        description = self._output_tabs.widget(1).toPlainText().strip()
        tags = self._output_tabs.widget(2).toPlainText().strip()
        script = self._output_tabs.widget(3).toPlainText().strip()

        if not any([title, description, tags, script]):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", "请先生成文案内容")
            return

        # 构建推送数据
        subtitle_text = ""
        if script:
            subtitle_text = script
        elif description:
            subtitle_text = description

        push_data = {
            "title": title,
            "description": description,
            "tags": tags,
            "script": script,
            "subtitle": subtitle_text,
            "source": "copywriting",
            "platform": self._platform_combo.currentText(),
            "style": self._style_combo.currentText(),
        }

        # 通过事件总线推送到剪辑模块
        self._event_bus.emit(EventType.COPY_GENERATED, push_data)
        # 同时发送模块切换事件
        self._event_bus.emit(EventType.MODULE_ACTIVATED, {
            "target": "editor",
            "data": push_data,
        })

        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "推送成功",
            f"文案已推送到剪辑模块\n标题: {title[:30]}..."
        )

    # ════════════════════════════════════════════════════════════════
    # C-1: 批量文案生成 (ShortGPT 参考架构)
    # ════════════════════════════════════════════════════════════════

    def batch_generate(self, inputs: list, platform: str = None, style: str = None,
                       on_progress: callable = None) -> list:
        """批量生成多条文案 (C-1)

        Args:
            inputs: 输入列表，每项为 str(内容) 或 dict({"content":...,"platform":...,"style":...})
            platform: 默认平台
            style: 默认风格
            on_progress: 进度回调 (current, total, result)

        Returns:
            [{input, title, description, tags, script, source}, ...]
        """
        if not platform:
            platform = self._platform_combo.currentText()
        if not style:
            style = self._style_combo.currentText()

        results = []
        total = len(inputs)

        for i, inp in enumerate(inputs):
            if isinstance(inp, str):
                content = inp
                plat = platform
                stl = style
            else:
                content = inp.get("content", inp.get("input", ""))
                plat = inp.get("platform", platform)
                stl = inp.get("style", style)

            if not content:
                results.append({"input": inp, "error": "空内容"})
                if on_progress:
                    on_progress(i + 1, total, None)
                continue

            # 调用单次生成逻辑 (复用已有 _call_llm + _template_generate)
            system_prompt = (
                f"你是{plat}平台的顶级短剧文案专家。"
                f"请根据用户输入生成{stl}风格的爆款文案。"
                "严格按以下格式输出（不要省略任何部分）：\n"
                "标题：[一条吸睛标题，15字以内]\n"
                "描述：[一段吸引人的描述，50-80字]\n"
                "标签：[5-8个相关标签，用#开头]\n"
                "脚本：[包含开场hook→高潮转折→结尾引导的口播脚本]"
            )
            user_prompt = f"用户输入：{content[:500]}\n目标平台：{plat}\n文案风格：{stl}"

            raw = self._call_llm(system_prompt, user_prompt)
            if raw:
                parsed = self._parse_llm_response(raw, content)
                result = {
                    "input": inp,
                    "title": parsed.get("title", f"{content[:20]}"),
                    "description": parsed.get("description", content[:50]),
                    "tags": parsed.get("tags", f"#{plat} #短剧"),
                    "script": parsed.get("script", content[:30]),
                    "source": "llm",
                }
            else:
                # 回退模板
                from copy import deepcopy
                old_platform = self._platform_combo.currentText()
                old_style = self._style_combo.currentText()
                # 临时设置平台/风格然后调用模板
                temp_result = self._template_generate_inplace(content, plat, stl)
                result = {
                    "input": inp,
                    "title": temp_result.get("title", ""),
                    "description": temp_result.get("description", ""),
                    "tags": temp_result.get("tags", ""),
                    "script": temp_result.get("script", ""),
                    "source": "template",
                }

            results.append(result)
            if on_progress:
                on_progress(i + 1, total, result)

        return results

    def _template_generate_inplace(self, content: str, platform: str, style: str) -> dict:
        """不修改UI的模板生成 (供batch_generate内部使用)"""
        platform_tags = {
            "抖音": ["追剧", "上头短片", "热门推荐"],
            "快手": ["短剧推荐", "剧情", "爽文改编"],
            "视频号": ["短剧精选", "剧情推荐", "热播推荐"],
            "小红书": ["好看推荐", "好剧安利", "剧情种草"],
            "B站": ["必刷", "神作", "热门"],
        }
        style_prefix = {
            "爆款": ("🔥", "看完直呼过瘾！", "全程高能"),
            "剧情": ("📖", "剧情反转太绝了！", "代入感拉满"),
            "解说": ("🎙️", "深度解析来了！", "干货满满"),
            "情感": ("💕", "泪目了家人们！", "共鸣感爆棚"),
            "搞笑": ("😂", "笑不活了！", "快乐源泉"),
        }

        tags = platform_tags.get(platform, ["热门", "推荐", "短剧"])
        prefix, hook, end_tag = style_prefix.get(style, ("", "", ""))

        return {
            "title": f"{prefix}{content[:20]}，必看！",
            "description": f"{hook}\n{content[:80]}\n\n{' '.join(['#' + t for t in tags])}",
            "tags": " ".join(["#" + t for t in tags]),
            "script": f"[开场]\n{content[:50]}...\n[转折]\n高潮部分来啦！\n[结尾]\n{end_tag} 关注不迷路",
        }

    # ════════════════════════════════════════════════════════════════
    # C-3: A/B 文案对比生成 (ShortGPT 编辑 DSL 设计模式)
    # ════════════════════════════════════════════════════════════════

    def ab_generate(self, content: str = None, platform: str = None, style: str = None,
                    versions: int = 2) -> list:
        """生成多个版本文案并评分对比 (C-3)

        使用不同风格的 system_prompt 生成 A/B 或多版本，
        然后基于吸引力/点击率预估/完播率预估进行评分。

        Args:
            content: 输入内容 (默认取输入框)
            platform: 目标平台
            style: 基础风格
            versions: 生成版本数 (2-4)

        Returns:
            [{version:"A", title, description, tags, script, scores:{...}, total_score}]
        """
        if not content:
            content = self._content_input.toPlainText().strip()
        if not content:
            return [{"version": "A", "error": "无输入内容"}]

        if not platform:
            platform = self._platform_combo.currentText()
        if not style:
            style = self._style_combo.currentText()

        # 不同版本的生成策略
        version_strategies = {
            0: {
                "name": "A",
                "desc": f"生成{style}风格的标准爆款文案",
                "system_prompt": (
                    f"你是{platform}平台的顶级短剧文案专家。"
                    f"请生成{style}风格的爆款文案。"
                    "严格按格式输出：\n"
                    "标题：[吸睛标题，15字内]\n描述：[吸引描述，50-80字]\n"
                    "标签：[5-8个标签，#开头]\n脚本：[hook→转折→引导]"
                ),
            },
            1: {
                "name": "B",
                "desc": f"生成{style}风格的悬念反转版文案",
                "system_prompt": (
                    f"你是{platform}平台的悬念叙事专家。"
                    f"请生成悬念+反转风格的爆款文案，制造好奇心缺口。"
                    "严格按格式输出：\n"
                    "标题：[悬念标题，15字内，用？或...结尾]\n描述：[铺垫+钩子，50-80字]\n"
                    "标签：[5-8个标签，#开头]\n脚本：[悬念hook→揭秘→引导]"
                ),
            },
            2: {
                "name": "C",
                "desc": "生成情感共鸣版本",
                "system_prompt": (
                    f"你是{platform}平台的情感叙事专家。"
                    f"请生成情感共鸣风格的爆款文案，唤起用户共情。"
                    "严格按格式输出：\n"
                    "标题：[情感标题，15字内]\n描述：[共情描述，50-80字]\n"
                    "标签：[5-8个标签，#开头]\n脚本：[情感hook→共鸣转折→温柔引导]"
                ),
            },
            3: {
                "name": "D",
                "desc": "生成短平快爆款版本",
                "system_prompt": (
                    f"你是{platform}平台的短平快文案专家。"
                    f"请生成极简风格的爆款文案，用最短文字制造最大冲击。"
                    "严格按格式输出：\n"
                    "标题：[冲击标题，10字内]\n描述：[一句话描述，30字内]\n"
                    "标签：[3-5个标签，#开头]\n脚本：[冲击hook→快速反转→一句引导]"
                ),
            },
        }

        results = []
        versions = max(2, min(versions, 4))

        for v in range(versions):
            strategy = version_strategies.get(v, version_strategies[0])
            user_prompt = f"用户输入：{content[:500]}\n目标平台：{platform}"

            raw = self._call_llm(strategy["system_prompt"], user_prompt)
            if raw:
                parsed = self._parse_llm_response(raw, content)
            else:
                # 回退模板
                parsed = self._template_generate_inplace(
                    content, platform, f"{style}-{strategy['name']}"
                )

            # 评分系统 (基于文案质量指标)
            scores = self._score_copywriting(
                title=parsed.get("title", ""),
                description=parsed.get("description", ""),
                tags=parsed.get("tags", ""),
                platform=platform,
            )

            result = {
                "version": strategy["name"],
                "strategy": strategy["desc"],
                "title": parsed.get("title", ""),
                "description": parsed.get("description", ""),
                "tags": parsed.get("tags", ""),
                "script": parsed.get("script", ""),
                "source": "llm" if raw else "template",
                "scores": scores,
                "total_score": sum(scores.values()),
            }
            results.append(result)

        # 按总分排序
        results.sort(key=lambda r: r["total_score"], reverse=True)

        # 标记最佳
        if results:
            results[0]["best"] = True
            for r in results[1:]:
                r["best"] = False

        return results

    def _score_copywriting(self, title: str, description: str, tags: str, platform: str) -> dict:
        """对文案进行多维度评分 (C-3 评分引擎)

        Returns:
            {attractiveness, click_rate, completion, seo, conciseness}
        """
        scores = {}

        # 吸引力: 标题含情感词/数字/疑问/感叹
        attractive_chars = {"?","？","!","！","🔥","💕","😂","📖","🎙️","·","..."}
        scores["attractiveness"] = min(1.0, (
            0.3 * (len(title) <= 15) +
            0.3 * any(c in title for c in attractive_chars) +
            0.2 * any(c.isdigit() for c in title) +
            0.2 * len(title) / 15
        ))

        # 点击率预估: 描述长度适中 + 含引导词
        desc_len = len(description)
        scores["click_rate"] = min(1.0, (
            0.4 * (1.0 if 30 <= desc_len <= 100 else 0.5) +
            0.3 * any(w in description for w in ["必看", "推荐", "精彩", "高能"]) +
            0.3
        ))

        # 完播率: 脚本长度和结构
        scores["completion"] = min(1.0, 0.5 + 0.5 * (desc_len / 100 if desc_len < 100 else 1.0))

        # SEO: 标签数量和质量
        tag_list = [t.strip() for t in tags.replace("#", " #").split("#") if t.strip()]
        scores["seo"] = min(1.0, len(tag_list) / 8)

        # 简洁度: 标题越短越好
        scores["conciseness"] = min(1.0, max(0.3, 1.0 - len(title) / 30))

        return scores
