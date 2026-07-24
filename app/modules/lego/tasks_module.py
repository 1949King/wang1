"""
多任务管理模块 (TasksModule)
===============================
从 modules.py 拆分出来的独立模块文件。

功能:
- 批量任务管理（剪辑/AI生成/导出/转码）
- 已完成/未完成分类筛选
- 任务详情面板（进度/参数/日志）
- 5个预设任务模板
- BatchTaskManager 后端集成（线程池+进度跟踪）
- T-1: 任务依赖关系
- T-3: 失败自动重试
- T-6: 定时任务调度
"""

import os
import logging
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QComboBox, QLineEdit, QGroupBox, QTextEdit,
    QFileDialog, QMessageBox, QFormLayout, QDialog, QMenu,
    QApplication, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt, QTimer

from .base_module import BaseModule

logger = logging.getLogger("AI短剧编辑器.tasks")


class TasksModule(BaseModule):
    """
    多任务管理模块
    - 批量剪辑,AI生成,导出,转码,下载
    - 支持已完成/未完成分类筛选
    """
    
    module_id = "tasks"
    module_name = "多任务"
    module_icon = "📋"
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # 初始化任务管理器
        self._init_task_manager()
        
        header_layout = QHBoxLayout()
        header = QLabel("📋 任务管理")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(header)
        header_layout.addStretch()
        
        add_btn = QPushButton("+ 新建任务")
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        add_btn.clicked.connect(self._new_task_dialog)
        header_layout.addWidget(add_btn)

        # 任务模板下拉按钮
        tmpl_btn = QPushButton("📋 模板 ▾")
        tmpl_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: #ccc;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 10px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #3a3a3a; color: #fff; }
        """)
        tmpl_btn.clicked.connect(self._show_task_templates)
        header_layout.addWidget(tmpl_btn)
        layout.addLayout(header_layout)
        
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)
        
        filter_label = QLabel("筛选:")
        filter_label.setStyleSheet("color: #808080; font-size: 14px;")
        filter_layout.addWidget(filter_label)
        
        self._filter_buttons = {}
        filter_items = [
            ("all", "全部", "#1e6bde"),
            ("pending", "未完成", "#808080"),
            ("completed", "已完成", "#22c55e"),
        ]
        
        for key, text, color in filter_items:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {'#1e6bde' if key == 'all' else 'transparent'};
                    color: {'white' if key == 'all' else '#808080'};
                    border: 1px solid #333333;
                    border-radius: 16px;
                    padding: 6px 16px;
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background-color: #2a2a2a;
                    color: white;
                }}
                QPushButton:checked {{
                    background-color: #1e6bde;
                    color: white;
                    border-color: #1e6bde;
                }}
            """)
            btn.clicked.connect(lambda checked, k=key: self._on_filter_clicked(k))
            filter_layout.addWidget(btn)
            self._filter_buttons[key] = btn
        
        filter_layout.addStretch()
        
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(20)
        
        self._total_label = QLabel("总计: 4")
        self._total_label.setStyleSheet("color: #808080; font-size: 13px;")
        stats_layout.addWidget(self._total_label)
        
        self._pending_label = QLabel("未完成: 3")
        self._pending_label.setStyleSheet("color: #ff9800; font-size: 13px;")
        stats_layout.addWidget(self._pending_label)
        
        self._completed_label = QLabel("已完成: 1")
        self._completed_label.setStyleSheet("color: #22c55e; font-size: 13px;")
        stats_layout.addWidget(self._completed_label)
        
        filter_layout.addLayout(stats_layout)
        layout.addLayout(filter_layout)
        
        self._task_table = QTableWidget()
        self._task_table.setColumnCount(6)
        self._task_table.setHorizontalHeaderLabels(["任务名称", "类型", "状态", "进度", "创建时间", "操作"])
        self._task_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._task_table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 8px;
                color: #ffffff;
            }
            QTableWidget::item {
                border: none;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                padding: 10px;
                border: none;
                border-bottom: 1px solid #333333;
                font-weight: bold;
                color: #808080;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #2a2a2a;
            }
            QTableWidget::item:selected {
                background-color: #1e6bde;
            }
        """)
        layout.addWidget(self._task_table, 1)
        # 双击任务行查看详情
        self._task_table.cellDoubleClicked.connect(self._show_task_detail)
        
        self._tasks = []
        self._current_filter = "all"
        # 任务日志存储 {task_name: [log_lines]}
        self._task_logs: dict = {}
        self._add_sample_tasks()
    
    def _on_filter_clicked(self, filter_key: str):
        for key, btn in self._filter_buttons.items():
            btn.setChecked(key == filter_key)
        self._current_filter = filter_key
        self._refresh_table()
    
    def _refresh_table(self):
        self._task_table.setRowCount(0)
        
        filtered_tasks = self._tasks
        if self._current_filter == "pending":
            filtered_tasks = [t for t in self._tasks if t["status"] != "已完成"]
        elif self._current_filter == "completed":
            filtered_tasks = [t for t in self._tasks if t["status"] == "已完成"]
        
        self._task_table.setRowCount(len(filtered_tasks))
        for i, task in enumerate(filtered_tasks):
            self._task_table.setItem(i, 0, QTableWidgetItem(task["name"]))
            self._task_table.setItem(i, 1, QTableWidgetItem(task["type"]))
            
            status_item = QTableWidgetItem(task["status"])
            if task["status"] == "已完成":
                status_item.setForeground(Qt.GlobalColor.green)
            elif task["status"] == "进行中":
                status_item.setForeground(Qt.GlobalColor.blue)
            else:
                status_item.setForeground(Qt.GlobalColor.gray)
            self._task_table.setItem(i, 2, status_item)
            
            progress_bar = QProgressBar()
            progress_bar.setValue(task["progress"])
            progress_bar.setStyleSheet("""
                QProgressBar {
                    background-color: #2a2a2a;
                    border: none;
                    border-radius: 4px;
                    text-align: center;
                    color: white;
                }
                QProgressBar::chunk {
                    background-color: #1e6bde;
                    border-radius: 4px;
                }
            """)
            self._task_table.setCellWidget(i, 3, progress_bar)
            
            self._task_table.setItem(i, 4, QTableWidgetItem(task["time"]))
            
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.setSpacing(4)
            
            task_idx = i  # 闭包捕获
            if task["status"] != "已完成":
                for text, color in [("暂停", "#ff9800"), ("取消", "#f44336")]:
                    btn = QPushButton(text)
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {color};
                            color: white;
                            border: none;
                            border-radius: 4px;
                            padding: 4px 8px;
                            font-size: 12px;
                        }}
                    """)
                    if text == "暂停":
                        btn.clicked.connect(lambda checked, t=task: self._toggle_pause_task(t))
                    elif text == "取消":
                        btn.clicked.connect(lambda checked, t=task: self._cancel_task(t))
                    btn_layout.addWidget(btn)
            else:
                clear_btn = QPushButton("清除")
                clear_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #808080;
                        color: white;
                        border: none;
                        border-radius: 4px;
                        padding: 4px 8px;
                        font-size: 12px;
                    }
                """)
                clear_btn.clicked.connect(lambda checked, t=task: self._clear_task(t))
                btn_layout.addWidget(clear_btn)
            
            self._task_table.setCellWidget(i, 5, btn_widget)
        
        self._update_stats()
    
    def _update_stats(self):
        total = len(self._tasks)
        completed = len([t for t in self._tasks if t["status"] == "已完成"])
        pending = total - completed
        
        self._total_label.setText(f"总计: {total}")
        self._pending_label.setText(f"未完成: {pending}")
        self._completed_label.setText(f"已完成: {completed}")
    
    def _init_task_manager(self):
        """初始化底层任务管理器 — 注册真实处理器"""
        try:
            from .batch_task_manager import BatchTaskManager, TaskStatus, TaskPriority
            self._batch_mgr = BatchTaskManager(max_workers=2)
            self._batch_mgr.register_processor("剪辑", self._clip_processor)
            self._batch_mgr.register_processor("AI生成", self._ai_gen_processor)
            self._batch_mgr.register_processor("导出", self._export_processor)
            self._batch_mgr.register_processor("转码", self._transcode_processor)
            # 定时同步后台任务进度到 UI（每秒刷新）
            from PyQt6.QtCore import QTimer
            self._progress_timer = QTimer(self)
            self._progress_timer.timeout.connect(self._sync_task_progress)
            self._progress_timer.start(1000)
        except Exception as e:
            logger.warning(f"批量任务管理器初始化失败: {e}")
            self._batch_mgr = None
    
    def _clip_processor(self, params, progress_callback):
        """剪辑处理器 — 统一走 EditorScheduler 自主选择内核"""
        video_path = params.get("video_path", "")
        if video_path and os.path.exists(video_path):
            try:
                from app.core.editor_scheduler import editor_scheduler
                start_t = params.get("start_time", 0)
                end_t = params.get("end_time", params.get("duration", 60))
                progress_callback(10, "启动统一剪辑内核...")
                result = editor_scheduler.cut_video(
                    video_path, start_t, end_t,
                    progress_callback=lambda p: progress_callback(p, f"编码中 {p}%")
                )
                progress_callback(100, "剪辑完成")
                return {"status": "success", "output": getattr(result, 'output_path', '')}
            except Exception as e:
                logger.warning(f"剪辑处理器出错: {e}")
                progress_callback(100, f"处理完成(部分失败): {e}")
                return {"status": "partial", "error": str(e)}
        
        # 无输入视频时返回明确状态，不伪造进度
        return {
            "status": "pending",
            "note": "请先选择视频文件再启动剪辑任务",
            "requires_input": True,
        }
    
    def _ai_gen_processor(self, params, progress_callback):
        """AI生成处理器 — 统一走 EditorScheduler 智能剪辑入口"""
        video_path = params.get("video_path", "")
        if video_path and os.path.exists(video_path):
            try:
                from app.core.editor_scheduler import editor_scheduler
                progress_callback(10, "AI理解视频内容...")
                result = editor_scheduler.smart_clip(
                    video_path,
                    target_platform=params.get("platform", "抖音"),
                    video_style=params.get("style", "高光剪辑"),
                    target_duration=params.get("target_duration", 60),
                    progress_callback=lambda p, msg="": progress_callback(p, msg or f"AI处理中 {p}%")
                )
                if result.get("success"):
                    progress_callback(100, "AI生成完成")
                else:
                    progress_callback(100, f"处理完成: {result.get('errors', ['部分失败'])}")
                return {"status": "success" if result.get("success") else "partial", "result": result}
            except Exception as e:
                logger.warning(f"AI生成处理器出错: {e}")
                progress_callback(100, f"AI处理出错: {e}")
                return {"status": "error", "error": str(e)}
        
        # 无输入视频时返回明确状态
        return {
            "status": "pending",
            "note": "请先选择视频文件再启动 AI 生成任务",
            "requires_input": True,
        }
    
    def _export_processor(self, params, progress_callback):
        """导出处理器 — 统一走 EditorScheduler 导出入口"""
        video_path = params.get("video_path", "")
        if video_path and os.path.exists(video_path):
            try:
                from app.core.editor_scheduler import editor_scheduler
                progress_callback(20, "准备导出参数...")
                result = editor_scheduler.export_video(
                    video_path,
                    output_path=params.get("output_path"),
                    platform=params.get("platform", "通用HD"),
                    params=params,
                    progress_callback=lambda p: progress_callback(p, f"导出中 {p}%")
                )
                success = result.get("success") if isinstance(result, dict) else getattr(result, "success", False)
                if success:
                    progress_callback(100, "导出完成")
                    output = result.get("output_path", "") if isinstance(result, dict) else getattr(result, "output_path", "")
                    return {"status": "success", "output": output}
                error = result.get("error_message", "") if isinstance(result, dict) else getattr(result, "error_message", "")
                progress_callback(100, f"导出失败: {error or '未知错误'}")
                return {"status": "error", "error": error or "导出失败"}
            except Exception as e:
                logger.warning(f"导出处理器出错: {e}")
                progress_callback(100, f"导出出错: {e}")
                return {"status": "error", "error": str(e)}
        
        # 无输入视频时返回明确状态
        return {
            "status": "pending",
            "note": "请先选择视频文件再启动导出任务",
            "requires_input": True,
        }
    
    def _transcode_processor(self, params, progress_callback):
        """转码处理器 — 统一走 EditorScheduler 轻量操作链"""
        video_path = params.get("video_path", "")
        if video_path and os.path.exists(video_path):
            try:
                from app.core.editor_scheduler import editor_scheduler
                ops = []
                w, h = params.get("width"), params.get("height")
                if w and h:
                    ops.append({"type": "resize", "width": w, "height": h})
                speed = params.get("speed")
                if speed:
                    ops.append({"type": "speed", "speed": speed})
                if ops:
                    progress_callback(10, "启动统一转码内核...")
                    out = params.get("output_path") or (os.path.splitext(video_path)[0] + "_transcoded.mp4")
                    result = editor_scheduler.transcode_video(
                        video_path,
                        out,
                        ops,
                        progress_callback=lambda p: progress_callback(p, f"转码中 {p}%")
                    )
                    if result.get("status") == "success":
                        progress_callback(100, "转码完成")
                        return result
                    progress_callback(100, "转码失败")
                    return result
            except Exception as e:
                logger.warning(f"转码处理器出错: {e}")
                progress_callback(100, f"转码出错: {e}")
                return {"status": "error", "error": str(e)}
        
        # 无输入视频时返回明确状态
        return {
            "status": "pending",
            "note": "请先选择视频文件再启动转码任务",
            "requires_input": True,
        }
    
    def _new_task_dialog(self):
        """新建任务对话框 — 支持选择视频路径"""
        from PyQt6.QtWidgets import QDialog, QFormLayout, QMessageBox
        dialog = QDialog(self)
        dialog.setWindowTitle("新建任务")
        dialog.setMinimumWidth(450)
        dialog.setStyleSheet("QDialog{background:#121212;}")
        dlo = QVBoxLayout(dialog)
        dlo.setContentsMargins(20, 20, 20, 20)
        dlo.setSpacing(12)
        
        fl = QFormLayout()
        fl.setSpacing(8)
        name_input = QLineEdit()
        name_input.setPlaceholderText("如：批量剪辑#5")
        name_input.setStyleSheet("QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:6px;padding:8px 12px;font-size:13px;}")
        fl.addRow("任务名称:", name_input)
        
        type_combo = QComboBox()
        type_combo.addItems(["剪辑", "AI生成", "导出", "转码"])
        type_combo.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:6px;padding:8px 12px;font-size:13px;} QComboBox::drop-down{border:none;} QComboBox QAbstractItemView{background:#0a0a0a;color:#fff;selection-background-color:#1e6bde;}")
        fl.addRow("任务类型:", type_combo)
        
        # 视频路径选择
        video_row = QHBoxLayout()
        video_row.setSpacing(6)
        video_input = QLineEdit()
        video_input.setPlaceholderText("选择视频文件（可选）...")
        video_input.setStyleSheet("QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:6px;padding:8px 12px;font-size:13px;}")
        video_row.addWidget(video_input, 1)
        browse_btn = QPushButton("📁")
        browse_btn.setFixedWidth(36)
        browse_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:6px;}QPushButton:hover{background:#3a3a3a;}")
        browse_btn.clicked.connect(lambda: video_input.setText(
            QFileDialog.getOpenFileName(dialog, "选择视频文件", "",
                "视频文件 (*.mp4 *.avi *.mov *.mkv *.flv *.wmv *.webm)")[0] or video_input.text()))
        video_row.addWidget(browse_btn)
        fl.addRow("视频文件:", video_row)
        
        dlo.addLayout(fl)
        
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("取消")
        cancel.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:none;border-radius:6px;padding:8px 20px;}")
        cancel.clicked.connect(dialog.reject)
        btns.addWidget(cancel)
        ok = QPushButton("✅ 创建")
        ok.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;padding:8px 20px;font-weight:600;}")
        ok.clicked.connect(dialog.accept)
        btns.addWidget(ok)
        dlo.addLayout(btns)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = name_input.text().strip() or "未命名任务"
            task_type = type_combo.currentText()
            video_path = video_input.text().strip()
            self._add_task_to_queue(name, task_type, video_path)
    
    def _add_task_to_queue(self, name: str, task_type: str, video_path: str = ""):
        """将任务加入底层管理器（每个任务独立队列，暂停/取消互不影响）"""
        from datetime import datetime
        
        queue_id = None
        batch_task_id = None
        
        if self._batch_mgr:
            try:
                from .batch_task_manager import TaskPriority
                # 每个任务独立队列，实现真正的单任务暂停/取消
                queue_id = self._batch_mgr.create_queue(name)
                
                def _on_task_complete(batch_task):
                    """任务完成回调 — 由 BatchTaskManager 在工作线程调用，通过 invokeMethod 切回主线程"""
                    from PyQt6.QtCore import QMetaObject, Qt, Q_ARG
                    QMetaObject.invokeMethod(
                        self, "_on_batch_task_finished",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, queue_id),
                        Q_ARG(str, batch_task.task_id),
                    )
                
                # 构建任务参数，包含视频路径
                task_params = {"steps": 5}
                if video_path:
                    task_params["video_path"] = video_path
                
                batch_task_id = self._batch_mgr.add_task(
                    queue_id, name, task_type,
                    params=task_params,
                    priority=TaskPriority.NORMAL,
                    callback=_on_task_complete
                )
                self._batch_mgr.start_queue(queue_id)
            except Exception as e:
                logger.warning(f"添加任务到队列失败 ({name}): {e}")
        
        self._tasks.append({
            "name": name, "type": task_type,
            "status": "等待中", "progress": 0,
            "time": datetime.now().strftime("%H:%M"),
            "queue_id": queue_id,
            "batch_task_id": batch_task_id,
        })
        self._refresh_table()
    
    def _toggle_pause_task(self, task: dict):
        """暂停/恢复任务（仅影响当前任务的独立队列）"""
        queue_id = task.get("queue_id")
        if not self._batch_mgr or not queue_id:
            return
        if task["status"] == "进行中":
            task["status"] = "已暂停"
            self._batch_mgr.pause_queue(queue_id)
        elif task["status"] == "已暂停":
            task["status"] = "进行中"
            self._batch_mgr.resume_queue(queue_id)
        self._refresh_table()
    
    def _cancel_task(self, task: dict):
        """取消任务（仅取消当前任务的队列）"""
        queue_id = task.get("queue_id")
        if self._batch_mgr and queue_id:
            try:
                self._batch_mgr.cancel_queue(queue_id)
            except Exception as e:
                logger.warning(f"取消任务队列失败: {e}")
        task["status"] = "已取消"
        task["progress"] = 0
        self._refresh_table()
    
    def _clear_task(self, task: dict):
        """清除已完成/已取消的任务"""
        self._tasks = [t for t in self._tasks if t != task]
        # 同时清理对应日志
        self._task_logs.pop(task.get("name", ""), None)
        self._refresh_table()
    
    # ── 任务模板 ──

    TASK_TEMPLATES = [
        ("🎬 批量剪辑视频", "剪辑", "选择多个视频文件，统一添加片头/片尾/水印并导出"),
        ("✍️ AI批量生成文案", "AI生成", "批量输入关键词，AI自动生成短视频标题和文案"),
        ("📤 批量导出多格式", "导出", "选择视频，一键导出抖音/B站/小红书等多平台格式"),
        ("🔄 视频格式转码", "转码", "批量转换视频格式/分辨率/帧率，支持 GPU 加速"),
        ("🔊 音频提取+降噪", "音频", "从视频中提取人声，AI降噪并导出MP3"),
    ]

    def _show_task_templates(self):
        """弹出任务模板菜单，选择后自动填充新建对话框"""
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("QMenu{background:#1a1a1a;color:#ccc;border:1px solid #333;padding:4px;} QMenu::item{padding:8px 24px;font-size:12px;} QMenu::item:selected{background:#1e6bde;color:#fff;}")
        for name, ttype, desc in self.TASK_TEMPLATES:
            action = menu.addAction(f"{name} — {desc}")
            action.triggered.connect(lambda checked, n=name, t=ttype: self._new_from_template(n, t))
        menu.exec(self.sender().mapToGlobal(self.sender().rect().bottomLeft()))

    def _new_from_template(self, name: str, task_type: str):
        """从模板创建任务 — 使用模板名称和类型填充"""
        from datetime import datetime
        self._tasks.append({
            "name": name, "type": task_type,
            "status": "等待中", "progress": 0,
            "time": datetime.now().strftime("%H:%M"),
        })
        self._refresh_table()

    # ── 任务详情与日志 ──

    def _show_task_detail(self, row: int, col: int):
        """双击任务行 → 弹出详情面板（进度/参数/日志）"""
        from PyQt6.QtWidgets import QDialog, QTextEdit, QFormLayout

        # 找到对应任务（考虑筛选状态）
        filtered = self._tasks
        if self._current_filter == "pending":
            filtered = [t for t in self._tasks if t["status"] != "已完成"]
        elif self._current_filter == "completed":
            filtered = [t for t in self._tasks if t["status"] == "已完成"]
        if row >= len(filtered):
            return
        task = filtered[row]

        dialog = QDialog(self)
        dialog.setWindowTitle(f"任务详情 - {task.get('name', '?')}")
        dialog.setMinimumSize(550, 420)
        dialog.setStyleSheet("QDialog{background:#121212;}")
        dlo = QVBoxLayout(dialog)
        dlo.setContentsMargins(20, 20, 20, 20)
        dlo.setSpacing(12)

        # 基本信息
        info_group = QGroupBox("基本信息")
        info_group.setStyleSheet("QGroupBox{color:#ccc;font-weight:bold;border:1px solid #222;border-radius:6px;margin-top:8px;padding-top:14px;background:#0a0a0a;} QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 6px;}")
        fl = QFormLayout(info_group)
        fl.setSpacing(6)
        for label, key in [("任务名称", "name"), ("类型", "type"), ("状态", "status"), ("创建时间", "time")]:
            lbl = QLabel(str(task.get(key, "-")))
            lbl.setStyleSheet("color:#ccc;font-size:12px;")
            fl.addRow(QLabel(f"{label}:"), lbl)
        # 进度
        prog = QProgressBar()
        prog.setValue(task.get("progress", 0))
        prog.setStyleSheet("QProgressBar{background:#2a2a2a;border:none;border-radius:4px;text-align:center;color:#fff;} QProgressBar::chunk{background:#1e6bde;border-radius:4px;}")
        fl.addRow("进度:", prog)
        # 队列信息
        for label, key in [("队列ID", "queue_id"), ("批任务ID", "batch_task_id")]:
            val = task.get(key)
            if val:
                lbl = QLabel(str(val))
                lbl.setStyleSheet("color:#666;font-size:11px;")
                fl.addRow(QLabel(f"{label}:"), lbl)
        dlo.addWidget(info_group)

        # 任务日志
        log_group = QGroupBox("📋 任务日志")
        log_group.setStyleSheet("QGroupBox{color:#ccc;font-weight:bold;border:1px solid #222;border-radius:6px;margin-top:8px;padding-top:14px;background:#0a0a0a;} QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 6px;}")
        log_layout = QVBoxLayout(log_group)

        log_output = QTextEdit()
        log_output.setReadOnly(True)
        log_output.setStyleSheet("QTextEdit{background:#000;color:#4caf50;font-family:'Consolas',monospace;font-size:11px;border:none;border-radius:4px;padding:8px;}")
        task_name = task.get("name", "")
        logs = self._task_logs.get(task_name, [])
        if logs:
            log_output.setText("\n".join(logs))
        else:
            status = task.get("status", "")
            if status == "已完成":
                log_output.setText(f"[INFO] 任务已完成\n[INFO] 名称: {task_name}\n[INFO] 类型: {task.get('type', '-')}\n（详细日志将在任务运行时生成）")
            elif status == "进行中":
                log_output.setText(f"[INFO] 任务正在运行中...\n[INFO] 名称: {task_name}\n（等待日志更新...）")
            else:
                log_output.setText(f"[INFO] 任务状态: {status}\n[INFO] 名称: {task_name}")
        log_layout.addWidget(log_output)

        # 手动刷新按钮
        refresh_btn = QPushButton("🔄 刷新日志")
        refresh_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:4px;padding:4px 12px;font-size:11px;} QPushButton:hover{background:#3a3a3a;}")
        refresh_btn.clicked.connect(lambda: self._refresh_task_log(log_output, task_name))
        log_layout.addWidget(refresh_btn)
        dlo.addWidget(log_group, 1)

        dialog.exec()

    def _refresh_task_log(self, log_widget: QTextEdit, task_name: str):
        """手动刷新任务日志显示"""
        logs = self._task_logs.get(task_name, [])
        if logs:
            log_widget.setText("\n".join(logs))
        else:
            log_widget.append("[INFO] 暂无新日志")

    def _append_task_log(self, task_name: str, message: str):
        """向指定任务的日志追加一行（线程安全）"""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        if task_name not in self._task_logs:
            self._task_logs[task_name] = []
        self._task_logs[task_name].append(line)
        # 限制日志行数，防止内存溢出
        if len(self._task_logs[task_name]) > 500:
            self._task_logs[task_name] = self._task_logs[task_name][-500:]
    
    def _add_sample_tasks(self):
        """初始化示例任务（仅在 BatchTaskManager 不可用时显示占位数据）"""
        if self._batch_mgr is None:
            self._tasks = [
                {"name": "批量剪辑任务 #1", "type": "剪辑", "status": "进行中", "progress": 65, "time": "刚刚"},
                {"name": "文案生成任务 #2", "type": "AI生成", "status": "已完成", "progress": 100, "time": "5分钟前"},
                {"name": "视频导出任务 #3", "type": "导出", "status": "等待中", "progress": 0, "time": "10分钟前"},
                {"name": "格式转换任务 #4", "type": "转码", "status": "进行中", "progress": 30, "time": "30分钟前"},
            ]
        else:
            self._tasks = []
        self._refresh_table()
    
    def _sync_task_progress(self):
        """定时将后台 BatchTaskManager 的任务进度同步到 UI 列表"""
        if not self._batch_mgr:
            return
        try:
            changed = False
            for task in self._tasks:
                queue_id = task.get("queue_id")
                batch_task_id = task.get("batch_task_id")
                if not queue_id or not batch_task_id:
                    continue
                queue = self._batch_mgr.task_queues.get(queue_id)
                if not queue:
                    continue
                for bt in queue.tasks:
                    if bt.task_id == batch_task_id:
                        status_map = {
                            "pending": "等待中", "running": "进行中",
                            "completed": "已完成", "failed": "失败",
                            "cancelled": "已取消", "paused": "已暂停",
                        }
                        new_status = status_map.get(bt.status.value, "等待中")
                        new_progress = int(bt.progress)
                        if task["status"] != new_status or task["progress"] != new_progress:
                            task["status"] = new_status
                            task["progress"] = new_progress
                            changed = True
                        break
            if changed:
                self._refresh_table()
        except Exception as e:
            logger.debug(f"同步任务进度失败: {e}")
    
    def _on_batch_task_finished(self, queue_id: str, batch_task_id: str):
        """任务完成槽函数（主线程安全，由 QMetaObject.invokeMethod 调度）"""
        for task in self._tasks:
            if task.get("queue_id") == queue_id:
                task["status"] = "已完成"
                task["progress"] = 100
        self._refresh_table()
