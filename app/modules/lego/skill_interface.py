"""
AI技能接口组件 (SkillInterfaceWidget)
======================================
从 model_management.py 拆分出来。
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QListWidget, QTabWidget
)

class SkillInterfaceWidget(QWidget):
    """AI技能接口组件"""

    def __init__(self):
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #252525; border-radius: 8px;
                background-color: #0d0d0d; margin-top: 2px;
            }
            QTabBar::tab {
                background-color: #1a1a1a; color: #888888; border: none;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
                padding: 8px 16px; font-size: 12px;
                min-width: 80px; height: 32px; margin-right: 2px;
            }
            QTabBar::tab:selected {
                color: #ffffff; background-color: #0d0d0d;
                border: 1px solid #252525; border-bottom: none;
            }
            QTabBar::tab:hover:!selected {
                background-color: #252525; color: #ffffff;
            }
        """)

        local_tab = QWidget()
        local_layout = QVBoxLayout(local_tab)
        local_layout.setContentsMargins(12, 12, 12, 12)
        local_layout.setSpacing(12)

        self._local_skills_list = QListWidget()
        self._local_skills_list.setMinimumHeight(180)
        self._local_skills_list.setStyleSheet("""
            QListWidget {
                background-color: #0d0d0d; border: 1px solid #252525; border-radius: 6px;
            }
            QListWidget::item {
                padding: 10px 12px; border-bottom: 1px solid #1a1a1a;
                color: #ffffff; font-size: 13px;
            }
            QListWidget::item:last { border-bottom: none; }
            QListWidget::item:selected { background-color: #1e6bde; color: #ffffff; }
        """)
        local_layout.addWidget(self._local_skills_list)

        local_btn_layout = QHBoxLayout()
        local_btn_layout.setSpacing(8)
        run_skill_btn = QPushButton("▶ 运行技能")
        run_skill_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde; color: white; border: none;
                border-radius: 4px; padding: 6px 14px; font-size: 12px;
            }
            QPushButton:hover { background-color: #2a7bef; }
        """)
        local_btn_layout.addWidget(run_skill_btn)
        refresh_skills_btn = QPushButton("🔄 刷新")
        refresh_skills_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a; color: white; border: none;
                border-radius: 4px; padding: 6px 14px; font-size: 12px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        local_btn_layout.addWidget(refresh_skills_btn)
        local_btn_layout.addStretch()
        local_layout.addLayout(local_btn_layout)

        clawhub_tab = QWidget()
        clawhub_layout = QVBoxLayout(clawhub_tab)
        clawhub_layout.setContentsMargins(12, 12, 12, 12)
        clawhub_layout.setSpacing(12)

        self._clawhub_skills_list = QListWidget()
        self._clawhub_skills_list.setMinimumHeight(180)
        self._clawhub_skills_list.setStyleSheet("""
            QListWidget {
                background-color: #0d0d0d; border: 1px solid #252525; border-radius: 6px;
            }
            QListWidget::item {
                padding: 10px 12px; border-bottom: 1px solid #1a1a1a;
                color: #ffffff; font-size: 13px;
            }
            QListWidget::item:last { border-bottom: none; }
            QListWidget::item:selected { background-color: #1e6bde; color: #ffffff; }
        """)
        clawhub_layout.addWidget(self._clawhub_skills_list)

        clawhub_btn_layout = QHBoxLayout()
        clawhub_btn_layout.setSpacing(8)
        install_skill_btn = QPushButton("📥 安装技能")
        install_skill_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50; color: white; border: none;
                border-radius: 4px; padding: 6px 14px; font-size: 12px;
            }
            QPushButton:hover { background-color: #5cbf60; }
        """)
        clawhub_btn_layout.addWidget(install_skill_btn)
        refresh_clawhub_btn = QPushButton("🔄 刷新")
        refresh_clawhub_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a; color: white; border: none;
                border-radius: 4px; padding: 6px 14px; font-size: 12px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        clawhub_btn_layout.addWidget(refresh_clawhub_btn)
        clawhub_btn_layout.addStretch()
        clawhub_layout.addLayout(clawhub_btn_layout)

        self._tabs.addTab(local_tab, "本地技能")
        self._tabs.addTab(clawhub_tab, "ClawHub技能")
        layout.addWidget(self._tabs)

        details_group = QGroupBox("技能详情")
        details_group.setStyleSheet("""
            QGroupBox {
                font-size: 13px; font-weight: 600; color: #ffffff;
                border: 1px solid #333333; border-radius: 8px;
                margin-top: 10px; padding-top: 20px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 8px;
            }
        """)
        details_layout = QVBoxLayout(details_group)
        details_layout.setSpacing(8)
        self._skill_desc = QLabel("选择一个技能查看详情")
        self._skill_desc.setStyleSheet("color: #888888; font-size: 12px; padding: 12px;")
        self._skill_desc.setWordWrap(True)
        details_layout.addWidget(self._skill_desc)
        layout.addWidget(details_group)

