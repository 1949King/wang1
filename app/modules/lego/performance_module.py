"""
性能监控模块 (PerformanceModule)
==================================
从 modules.py 拆分出来的独立模块文件。

功能:
- CPU / 内存 / GPU 实时监控
- 渲染性能统计（任务数/成功率/耗时/速率）
- 历史趋势面板（最近 5 分钟）
- 智能优化建议（负载阈值分析）
- GPU 多品牌检测（NVIDIA / AMD / Intel）
- 性能告警（CPU/GPU > 90% 时弹窗）
- 趋势数据导出（JSON）
"""

import json
import os
import time
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QGroupBox, QTextEdit, QPushButton,
    QListWidget, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer

from .base_module import BaseModule

logger = logging.getLogger("AI短剧编辑器.performance")


class PerformanceModule(BaseModule):
    """
    性能监控模块
    - CPU,内存,GPU,任务队列,导出速度
    """
    
    module_id = "performance"
    module_name = "性能监控"
    module_icon = "📊"
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        header = QLabel("📊 性能监控")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(header)
        
        stats_grid = QGridLayout()
        stats_grid.setSpacing(15)
        
        self._stat_labels = {}  # stat_name -> QLabel
        
        for i, (label, key, color) in enumerate([
            ("CPU 使用率", "cpu", "#1e6bde"),
            ("内存使用", "mem", "#4caf50"),
            ("GPU 使用率", "gpu", "#ff9800"),
            ("任务队列", "tasks", "#9c27b0"),
        ]):
            frame = QFrame()
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: #1a1a1a;
                    border: 2px solid {color}40;
                    border-radius: 12px;
                    padding: 20px;
                }}
            """)
            frame_layout = QVBoxLayout(frame)
            
            value_label = QLabel("--")
            value_label.setStyleSheet(f"font-size: 32px; font-weight: bold; color: {color};")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            frame_layout.addWidget(value_label)
            
            name_label = QLabel(label)
            name_label.setStyleSheet("color: #808080; font-size: 14px;")
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            frame_layout.addWidget(name_label)
            
            self._stat_labels[key] = value_label
            stats_grid.addWidget(frame, i // 2, i % 2)
        
        layout.addLayout(stats_grid)

        # ── 渲染性能面板 ──
        render_group = QGroupBox("🎬 渲染性能")
        render_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px; font-weight: bold; color: #ffffff;
                border: 1px solid #333333; border-radius: 8px;
                margin-top: 12px; padding-top: 12px;
                background-color: #1a1a1a;
            }
        """)
        render_layout = QVBoxLayout(render_group)
        render_layout.setSpacing(8)

        self._render_stats_grid = QGridLayout()
        self._render_stats_grid.setSpacing(10)
        self._render_labels = {}

        for i, (label, key, color) in enumerate([
            ("总任务", "total_tasks", "#1e6bde"),
            ("已完成", "completed", "#4caf50"),
            ("失败", "failed", "#ff5252"),
            ("成功率", "success_rate", "#ff9800"),
            ("平均耗时", "avg_time", "#9c27b0"),
            ("总耗时", "total_time", "#2196f3"),
            ("速率", "tasks_per_min", "#00bcd4"),
            ("活跃任务", "active_task", "#e91e63"),
        ]):
            frame = QFrame()
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: #121212;
                    border: 1px solid {color}30;
                    border-radius: 6px;
                    padding: 8px;
                }}
            """)
            f_layout = QVBoxLayout(frame)
            f_layout.setSpacing(2)

            vl = QLabel("--")
            vl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color};")
            vl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            f_layout.addWidget(vl)

            nl = QLabel(label)
            nl.setStyleSheet("color: #666; font-size: 10px;")
            nl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            f_layout.addWidget(nl)

            self._render_labels[key] = vl
            self._render_stats_grid.addWidget(frame, i // 4, i % 4)

        render_layout.addLayout(self._render_stats_grid)

        # 最近渲染记录
        self._recent_render_list = QListWidget()
        self._recent_render_list.setMaximumHeight(100)
        self._recent_render_list.setStyleSheet("""
            QListWidget {
                background-color: #0a0a0a; border: none;
                font-family: 'Consolas', monospace; font-size: 11px;
            }
            QListWidget::item { color: #888; padding: 2px 6px; }
        """)
        render_layout.addWidget(QLabel("最近渲染记录"))
        render_layout.addWidget(self._recent_render_list)

        layout.addWidget(render_group)
        
        log_group = QGroupBox("运行日志")
        log_group.setStyleSheet("""
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
        """)
        log_layout = QVBoxLayout(log_group)
        
        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setStyleSheet("""
            QTextEdit {
                background-color: #0a0a0a;
                color: #4caf50;
                font-family: 'Consolas', 'Courier New', monospace;
                border: none;
                border-radius: 4px;
                padding: 10px;
                font-size: 12px;
            }
        """)
        self._log_output.setText(
            "[INFO] 系统启动完成\n"
            "[INFO] 正在检测硬件配置...\n"
            "[INFO] 任务队列就绪\n"
            "[INFO] 性能监控就绪（每2秒自动刷新）"
        )
        log_layout.addWidget(self._log_output)

        layout.addWidget(log_group, 1)

        # ── 历史趋势 + 优化建议面板（13.4/13.5） ──
        trend_group = QGroupBox("📈 历史趋势 & 优化建议")
        trend_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px; font-weight: bold; color: #ffffff;
                border: 1px solid #333333; border-radius: 8px;
                margin-top: 12px; padding-top: 12px;
                background-color: #1a1a1a;
            }
        """)
        trend_layout = QVBoxLayout(trend_group)
        trend_layout.setSpacing(8)

        # 历史趋势文本区
        trend_header = QHBoxLayout()
        trend_title = QLabel("📈 历史趋势 (最近 5 分钟)")
        trend_title.setStyleSheet("font-size: 12px; color: #888; font-weight: normal;")
        trend_header.addWidget(trend_title)
        trend_header.addStretch()
        export_btn = QPushButton("📋 导出")
        export_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#888;border:1px solid #333;border-radius:4px;padding:3px 10px;font-size:10px;} QPushButton:hover{background:#3a3a3a;color:#ccc;}")
        export_btn.clicked.connect(self._export_trend_data)
        trend_header.addWidget(export_btn)
        trend_layout.addLayout(trend_header)

        self._trend_text = QTextEdit()
        self._trend_text.setReadOnly(True)
        self._trend_text.setMaximumHeight(100)
        self._trend_text.setStyleSheet("""
            QTextEdit {
                background-color: #0a0a0a; color: #00bcd4;
                font-family: 'Consolas', monospace; font-size: 11px;
                border: 1px solid #1e1e1e; border-radius: 4px; padding: 6px;
            }
        """)
        self._trend_text.setText("等待数据收集...")
        trend_layout.addWidget(self._trend_text)

        # 优化建议区
        suggest_label = QLabel("💡 优化建议")
        suggest_label.setStyleSheet("font-size: 12px; color: #888; font-weight: normal;")
        trend_layout.addWidget(suggest_label)

        self._suggest_text = QTextEdit()
        self._suggest_text.setReadOnly(True)
        self._suggest_text.setMaximumHeight(80)
        self._suggest_text.setStyleSheet("""
            QTextEdit {
                background-color: #0a0a0a; color: #4caf50;
                font-family: 'Consolas', monospace; font-size: 11px;
                border: 1px solid #1e1e1e; border-radius: 4px; padding: 6px;
            }
        """)
        self._suggest_text.setText("系统运行正常，暂无优化建议")
        trend_layout.addWidget(self._suggest_text)

        layout.addWidget(trend_group)

        # ── 历史数据 ──
        self._history_data = []  # list of {ts, cpu, mem, gpu}
        self._trend_counter = 0

        # 实时监控定时器（不在初始化时启动，由 on_activated 按需启停）
        self._perf_timer = QTimer(self)
        self._perf_timer.timeout.connect(self._refresh_stats)
        self._perf_timer.setInterval(2000)  # 每 2 秒刷新
        self._perf_active = False
        self._alert_shown = {}  # 防止重复告警 {"cpu": timestamp, "mem": timestamp}
    
    def _refresh_stats(self):
        """实时刷新系统性能数据（CPU / 内存 / GPU 利用率+显存+温度 / 任务队列）"""
        import threading
        
        def _poll():
            cpu = ""; mem = ""; gpu = ""; tasks = ""
            try:
                import psutil
                cpu = f"{psutil.cpu_percent(interval=0.5):.0f}%"
                mem_info = psutil.virtual_memory()
                mem = f"{mem_info.used / (1024**3):.1f}/{mem_info.total / (1024**3):.1f} GB"
            except (ImportError, OSError, RuntimeError):
                cpu = "N/A"; mem = "N/A"
            
            try:
                gpu = self._query_gpu_stats()
            except Exception:
                gpu = "N/A"
            
            try:
                # 获取真实任务队列状态
                from .batch_task_manager import BatchTaskManager
                # 尝试访问全局单例获取活跃任务数
                active_count = 0
                try:
                    mgr = BatchTaskManager.get_instance() if hasattr(BatchTaskManager, 'get_instance') else None
                    if mgr:
                        for queue in mgr.task_queues.values():
                            for bt in queue.tasks:
                                if bt.status.value in ("running",):
                                    active_count += 1
                except Exception:
                    pass
                if active_count > 0:
                    tasks = f"{active_count}活跃"
                else:
                    tasks = "就绪"
            except Exception:
                tasks = "就绪"
            
            return cpu, mem, gpu, tasks
        
        cpu, mem, gpu, tasks_val = ("--", "--", "--", "--")
        try:
            cpu, mem, gpu, tasks_val = _poll()
        except Exception:
            pass

        if "cpu" in self._stat_labels:
            self._stat_labels["cpu"].setText(cpu)
        if "mem" in self._stat_labels:
            self._stat_labels["mem"].setText(mem)
        if "gpu" in self._stat_labels:
            self._stat_labels["gpu"].setText(gpu)
        if "tasks" in self._stat_labels:
            self._stat_labels["tasks"].setText(tasks_val)

        # 性能告警检测
        from datetime import datetime
        now_ts = datetime.now().timestamp()
        if not hasattr(self, '_alert_shown'):
            self._alert_shown = {}

        def _check_alert(label: str, pct_str: str, threshold: int, icon: str):
            """检测单个指标是否超过阈值，避免重复告警"""
            try:
                val = float(pct_str.replace("%", ""))
            except (ValueError, AttributeError):
                return
            if val > threshold:
                last_alert = self._alert_shown.get(label, 0)
                if now_ts - last_alert > 60:  # 60秒内不重复告警
                    self._alert_shown[label] = now_ts
                    self._log_output.append(
                        f"<span style='color:#ff5252;'>[{datetime.now().strftime('%H:%M:%S')}] "
                        f"{icon} 告警: {label} {pct_str} (阈值 {threshold}%)</span>"
                    )
            else:
                # 指标恢复正常后清除告警记录
                self._alert_shown.pop(label, None)

        _check_alert("CPU", cpu, 90, "⚠️")
        _check_alert("GPU", gpu, 90, "⚠️")

        # ── 渲染性能数据 ──
        self._refresh_render_perf()

        # 追加实时日志（每 5 次写入一条，避免日志爆炸）
        if not hasattr(self, '_log_counter'):
            self._log_counter = 0
        self._log_counter += 1
        if self._log_counter % 5 == 0:
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_output.append(f"[{ts}] CPU:{cpu} MEM:{mem} GPU:{gpu}")

        # ── 历史趋势收集 + 优化建议（13.4/13.5）──
        self._collect_history_and_suggest(cpu, mem, gpu)

    def _collect_history_and_suggest(self, cpu: str, mem: str, gpu: str):
        """收集性能历史数据，生成趋势和优化建议"""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")

        # 解析数值
        try:
            cpu_val = float(cpu.replace("%", "")) if "%" in str(cpu) else 0
        except (ValueError, AttributeError):
            cpu_val = 0
        try:
            mem_str = str(mem)
            parts = mem_str.split("/")
            mem_used = float(parts[0].strip()) if parts and parts[0].strip().replace(".", "").isdigit() else 0
            mem_total = float(parts[1].replace("GB", "").replace("gb", "").strip()) if len(parts) > 1 else 0
            mem_pct = (mem_used / mem_total * 100) if mem_total > 0 else 0
        except (ValueError, AttributeError, IndexError):
            mem_pct = 0
        try:
            gpu_str = str(gpu).split("|")[0].strip() if "|" in str(gpu) else str(gpu)
            gpu_val = float(gpu_str.replace("%", "").replace("GPU:", "").replace("GPU0:", "").strip()) if gpu_str.replace(".", "").replace("N/A", "").strip().isdigit() or any(c.isdigit() for c in gpu_str) else 0
            if gpu_val == 0 and "N/A" not in str(gpu):
                import re
                nums = re.findall(r'(\d+)%', str(gpu))
                if nums:
                    gpu_val = float(nums[0])
        except (ValueError, AttributeError):
            gpu_val = 0

        # 存入历史（最多保留 12 个采样点，约 2 分钟）
        self._history_data.append({"ts": ts, "cpu": cpu_val, "mem": mem_pct, "gpu": gpu_val})
        if len(self._history_data) > 12:
            self._history_data = self._history_data[-12:]

        # 每 5 次刷新更新趋势显示
        self._trend_counter += 1
        if self._trend_counter % 5 == 0 and self._history_data:
            self._update_trend_display()

    def _update_trend_display(self):
        """更新历史趋势文本和优化建议"""
        if not hasattr(self, '_trend_text') or not hasattr(self, '_suggest_text'):
            return
        if not self._history_data:
            return

        # ── 历史趋势 ──
        lines = []
        lines.append(f"{'时间':<10} {'CPU':<10} {'内存':<10} {'GPU':<10}")
        lines.append("-" * 42)
        for h in self._history_data:
            cpu_bar = "█" * int(h["cpu"] / 10) + "░" * (10 - int(h["cpu"] / 10))
            mem_bar = "█" * int(h["mem"] / 10) + "░" * (10 - int(h["mem"] / 10))
            gpu_bar = "█" * int(h["gpu"] / 10) + ("░" * (10 - int(h["gpu"] / 10))) if h["gpu"] > 0 else "  N/A      "
            lines.append(f"{h['ts']:<10} {cpu_bar} {mem_bar} {gpu_bar}")
        self._trend_text.setText("\n".join(lines))

        # ── 优化建议 ──
        suggestions = []

        # 分析最近 6 个采样点
        recent = self._history_data[-6:]
        avg_cpu = sum(h["cpu"] for h in recent) / len(recent)
        avg_mem = sum(h["mem"] for h in recent) / len(recent)
        avg_gpu = sum(h["gpu"] for h in recent) / len(recent) if any(h["gpu"] > 0 for h in recent) else 0

        # CPU 建议
        if avg_cpu > 85:
            suggestions.append("🔴 CPU持续高负载(>85%)：建议降低并行任务数、关闭后台渲染预览、限制同时导出数")
        elif avg_cpu > 60:
            suggestions.append("🟡 CPU中等负载(>60%)：多任务时注意控制导出队列长度，避免CPU过热降频")

        # 内存建议
        if avg_mem > 85:
            suggestions.append("🔴 内存使用率过高(>85%)：建议清理未使用的素材缓存、降低预览分辨率、关闭不必要模块")
        elif avg_mem > 65:
            suggestions.append("🟡 内存偏高(>65%)：处理4K素材后建议保存并重启编辑器释放内存")

        # GPU 建议
        if avg_gpu > 85:
            suggestions.append("🔴 GPU负载过高(>85%)：考虑降低渲染分辨率、关闭硬件加速特效、批量导出使用CPU编码")
        elif avg_gpu > 60:
            suggestions.append("🟡 GPU中等负载(>60%)：渲染时可关闭GPU预览以释放显存")

        # CPU/GPU 趋势分析
        if len(recent) >= 3:
            cpu_trend = recent[-1]["cpu"] - recent[0]["cpu"]
            if cpu_trend > 15:
                suggestions.append("📈 CPU使用率快速上升(+{:.0f}%)：检查是否有新任务启动或内存泄漏".format(cpu_trend))
            gpu_trend = recent[-1]["gpu"] - recent[0]["gpu"] if avg_gpu > 0 else 0
            if gpu_trend > 15:
                suggestions.append("📈 GPU使用率快速上升(+{:.0f}%)：确认渲染队列是否堆积".format(gpu_trend))

        if not suggestions:
            suggestions.append("✅ 系统运行正常：CPU/内存/GPU 均在合理范围，无需干预")

        self._suggest_text.setText("\n".join(suggestions))

    def _export_trend_data(self):
        """导出历史趋势数据为 JSON"""
        if not self._history_data:
            QMessageBox.information(self, "提示", "暂无数据可导出")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "导出性能数据", "performance_trend.json", "JSON Files (*.json)")
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(self._history_data, f, ensure_ascii=False, indent=2)
                QMessageBox.information(self, "成功", f"已导出到 {file_path}")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"导出失败: {e}")

    def _refresh_render_perf(self):
        """从 RenderManager 拉取渲染性能统计并更新 UI"""
        try:
            from app.core.render_manager import RenderManager
            # 尝试获取全局实例
            mgr = None
            try:
                from app.core.render_manager import get_render_manager
                mgr = get_render_manager()
            except Exception:
                pass
            if mgr is None:
                return

            perf = mgr.get_render_performance()

            def _set(key: str, val: str):
                if key in self._render_labels:
                    self._render_labels[key].setText(str(val))

            _set("total_tasks", perf.get("total_tasks", 0))
            _set("completed", perf.get("completed", 0))
            _set("failed", perf.get("failed", 0))
            _set("success_rate", f"{perf.get('success_rate', 0)}%")
            _set("avg_time", f"{perf.get('avg_time_sec', 0)}s")
            _set("total_time", f"{perf.get('total_time_sec', 0)}s")
            _set("tasks_per_min", f"{perf.get('avg_tasks_per_min', 0)}/min")
            active = perf.get("active_task")
            if active:
                pct = perf.get("active_progress", 0)
                _set("active_task", f"{pct:.0f}%")
            else:
                _set("active_task", "空闲")

            # 最近渲染记录
            self._recent_render_list.clear()
            for r in perf.get("recent_5", []):
                status_icon = "✅" if r.get("success") else "❌"
                self._recent_render_list.addItem(
                    f"{status_icon} {r.get('task_id','?')} "
                    f"| {r.get('time',0):.1f}s | {r.get('size_mb',0)}MB"
                )

        except Exception:
            pass  # 渲染统计非关键，静默失败
    
    def _query_gpu_stats(self) -> str:
        """查询 GPU 利用率、显存、温度（支持 NVIDIA / AMD / Intel）"""
        import subprocess
        
        # ── NVIDIA GPU ──
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split("\n")
                parts = []
                for idx, line in enumerate(lines[:2]):  # 最多显示2个GPU
                    values = [v.strip() for v in line.split(",")]
                    if len(values) >= 4:
                        gpu_label = f"GPU{idx}" if len(lines) > 1 else "GPU"
                        parts.append(
                            f"{gpu_label}: {values[0]}% | "
                            f"显存 {values[1]}/{values[2]}MB | "
                            f"{values[3]}°C"
                        )
                    elif values:
                        parts.append(f"GPU: {values[0]}%")
                return "\n".join(parts) if parts else "N/A"
        except FileNotFoundError:
            pass
        except Exception:
            pass
        
        # ── AMD GPU (rocm-smi) ──
        try:
            result = subprocess.run(
                ["rocm-smi", "--showuse", "--showmeminfo", "vram"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and "GPU" in result.stdout:
                return "AMD GPU (已检测)"
        except FileNotFoundError:
            pass
        except Exception:
            pass
        
        # ── Intel GPU ──
        try:
            result = subprocess.run(
                ["intel_gpu_top", "-J", "-s", "1"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                return "Intel GPU (已检测)"
        except FileNotFoundError:
            pass
        except Exception:
            pass
        
        return "N/A"

    def on_activated(self):
        """切换到性能监控页时启动定时器"""
        if hasattr(self, '_perf_timer') and self._perf_timer is not None:
            if not self._perf_timer.isActive():
                self._perf_timer.start(2000)
    
    def on_deactivated(self):
        """离开性能监控页时暂停定时器，节省 CPU"""
        if hasattr(self, '_perf_timer') and self._perf_timer is not None:
            self._perf_timer.stop()
