"""
授权管理模块
=============
管理软件授权、激活码验证、版本控制

功能：
1. 登录窗口 - 用户登录和注册
2. 激活码升级 - 验证激活码
3. 购买按钮 - 链接到收款页面
4. 版本区分 - 个人版、专业版、企业版
5. 权限控制 - 基于版本的功能控制
6. 按钮自动隐藏/显示 - 根据权限控制界面元素
"""

import os
import json
import time
import hashlib
import logging
import uuid
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import webbrowser

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QMessageBox, QTabWidget, QFormLayout, QComboBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon

logger = logging.getLogger(__name__)


class LicenseLevel(Enum):
    """授权级别"""
    FREE = "免费版"
    PERSONAL = "个人版"
    PROFESSIONAL = "专业版"
    ENTERPRISE = "企业版"


class LicenseStatus(Enum):
    """授权状态"""
    INACTIVE = "未激活"
    ACTIVE = "已激活"
    EXPIRED = "已过期"
    INVALID = "无效"


@dataclass
class LicenseInfo:
    """授权信息"""
    license_key: str
    level: LicenseLevel
    status: LicenseStatus
    activation_date: float
    expiration_date: float
    user_name: str
    email: str
    hardware_id: str
    features: Dict[str, bool] = field(default_factory=dict)


class LicenseManager:
    """
    授权管理类
    处理授权验证、激活码验证、版本控制等
    """
    
    # 收款链接
    PAYMENT_LINKS = {
        LicenseLevel.PERSONAL: "https://buy.stripe.com/test_4gw9Dd06a49Xh6Y145",  # 个人版 299元
        LicenseLevel.PROFESSIONAL: "https://buy.stripe.com/test_8wM3cD39XcU89nG14a",  # 专业版 599元
        LicenseLevel.ENTERPRISE: "https://buy.stripe.com/test_4gw9Dd39XcU89nG3cf"   # 企业版 1999元
    }
    
    # 功能权限映射
    FEATURE_PERMISSIONS = {
        LicenseLevel.FREE: {
            "basic_editing": True,
            "ai_understanding": False,
            "professional_editing": False,
            "batch_processing": False,
            "viral_prediction": False,
            "smart_editing": False,
            "cloud_api": False,
            "commercial_use": False
        },
        LicenseLevel.PERSONAL: {
            "basic_editing": True,
            "ai_understanding": True,
            "professional_editing": True,
            "batch_processing": False,
            "viral_prediction": True,
            "smart_editing": True,
            "cloud_api": True,
            "commercial_use": True
        },
        LicenseLevel.PROFESSIONAL: {
            "basic_editing": True,
            "ai_understanding": True,
            "professional_editing": True,
            "batch_processing": True,
            "viral_prediction": True,
            "smart_editing": True,
            "cloud_api": True,
            "commercial_use": True
        },
        LicenseLevel.ENTERPRISE: {
            "basic_editing": True,
            "ai_understanding": True,
            "professional_editing": True,
            "batch_processing": True,
            "viral_prediction": True,
            "smart_editing": True,
            "cloud_api": True,
            "commercial_use": True
        }
    }
    
    def __init__(self):
        """初始化授权管理器"""
        self.license_file = os.path.join(
            os.path.expanduser("~"), ".ai_short_drama_editor", "license.json"
        )
        self.hardware_id = self._get_hardware_id()
        self.current_license: Optional[LicenseInfo] = None
        
        # 确保授权目录存在
        os.makedirs(os.path.dirname(self.license_file), exist_ok=True)
        
        # 加载现有授权
        self._load_license()
        
        print("🔐 授权管理器初始化完成")
        print(f"   硬件ID: {self.hardware_id}")
        if self.current_license:
            print(f"   当前授权: {self.current_license.level.value} - {self.current_license.status.value}")
        else:
            print("   当前授权: 未激活")
    
    def _get_hardware_id(self) -> str:
        """获取硬件ID"""
        try:
            import platform
            import uuid
            
            # 生成基于系统信息的硬件ID
            info = platform.system() + platform.node() + platform.machine()
            return hashlib.md5(info.encode()).hexdigest()[:16]
        except Exception as e:
            logger.debug("生成硬件ID失败，回退到UUID: %s", e)
            return str(uuid.uuid4())[:16]
    
    def _load_license(self):
        """加载授权信息"""
        try:
            if os.path.exists(self.license_file):
                with open(self.license_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.current_license = LicenseInfo(
                    license_key=data['license_key'],
                    level=LicenseLevel(data['level']),
                    status=LicenseStatus(data['status']),
                    activation_date=data['activation_date'],
                    expiration_date=data['expiration_date'],
                    user_name=data['user_name'],
                    email=data['email'],
                    hardware_id=data['hardware_id'],
                    features=data.get('features', {})
                )
                
                # 检查授权是否过期
                if time.time() > self.current_license.expiration_date:
                    self.current_license.status = LicenseStatus.EXPIRED
                    self._save_license()
                    print("⚠️ 授权已过期")
                    
        except Exception as e:
            print(f"加载授权失败: {e}")
    
    def _save_license(self):
        """保存授权信息"""
        if self.current_license:
            data = {
                'license_key': self.current_license.license_key,
                'level': self.current_license.level.value,
                'status': self.current_license.status.value,
                'activation_date': self.current_license.activation_date,
                'expiration_date': self.current_license.expiration_date,
                'user_name': self.current_license.user_name,
                'email': self.current_license.email,
                'hardware_id': self.current_license.hardware_id,
                'features': self.current_license.features
            }
            
            with open(self.license_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    
    def validate_activation_code(self, activation_code: str, 
                               user_name: str, 
                               email: str) -> Tuple[bool, str]:
        """
        验证激活码
        
        Args:
            activation_code: 激活码
            user_name: 用户名
            email: 邮箱
            
        Returns:
            (是否成功, 错误信息)
        """
        try:
            # 本地激活码验证
            
            # 简单的激活码验证逻辑
            if len(activation_code) != 20:
                return False, "激活码格式错误"
            
            # 解析激活码
            code_parts = activation_code.split('-')
            if len(code_parts) != 5:
                return False, "激活码格式错误"
            
            # 提取版本信息
            version_code = code_parts[0]
            
            # 版本映射
            version_map = {
                "PER": LicenseLevel.PERSONAL,
                "PRO": LicenseLevel.PROFESSIONAL,
                "ENT": LicenseLevel.ENTERPRISE
            }
            
            if version_code not in version_map:
                return False, "无效的激活码"
            
            level = version_map[version_code]
            
            # 验证硬件ID
            if code_parts[1] != self.hardware_id[:4]:
                return False, "激活码与当前设备不匹配"
            
            # 计算过期时间（永久授权）
            activation_date = time.time()
            expiration_date = activation_date + (365 * 24 * 60 * 60 * 10)  # 10年
            
            # 创建授权信息
            self.current_license = LicenseInfo(
                license_key=activation_code,
                level=level,
                status=LicenseStatus.ACTIVE,
                activation_date=activation_date,
                expiration_date=expiration_date,
                user_name=user_name,
                email=email,
                hardware_id=self.hardware_id,
                features=self.FEATURE_PERMISSIONS[level]
            )
            
            # 保存授权
            self._save_license()
            
            # 如实说明：这里只做本地格式校验（版本前缀 + 本机硬件ID前4位匹配），
            # 没有任何服务器端验证，理论上只要凑对格式就能激活——不是正式的
            # 授权鉴权机制。消息里明确标注"本地试用模式"，避免用户误以为
            # 这是经过后端核验的正式授权。
            return True, f"激活成功！已升级到 {level.value}（本地试用模式：仅校验激活码格式，未连接服务器验证）"
            
        except Exception as e:
            return False, f"激活失败: {str(e)}"
    
    def get_current_level(self) -> LicenseLevel:
        """获取当前授权级别"""
        if self.current_license and self.current_license.status == LicenseStatus.ACTIVE:
            return self.current_license.level
        return LicenseLevel.FREE
    
    def has_permission(self, feature: str) -> bool:
        """
        检查是否有权限使用某个功能
        
        Args:
            feature: 功能名称
            
        Returns:
            bool: 是否有权限
        """
        level = self.get_current_level()
        return self.FEATURE_PERMISSIONS[level].get(feature, False)
    
    def open_payment_link(self, level: LicenseLevel):
        """
        打开购买链接
        
        Args:
            level: 授权级别
        """
        if level in self.PAYMENT_LINKS:
            payment_link = self.PAYMENT_LINKS[level]
            print(f"打开购买链接: {payment_link}")
            webbrowser.open(payment_link)
        else:
            print(f"未找到 {level.value} 的购买链接")
    
    def get_license_info(self) -> Optional[Dict[str, Any]]:
        """获取授权信息"""
        if not self.current_license:
            return None
        
        return {
            'license_key': self.current_license.license_key,
            'level': self.current_license.level.value,
            'status': self.current_license.status.value,
            'user_name': self.current_license.user_name,
            'email': self.current_license.email,
            'activation_date': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.current_license.activation_date)),
            'expiration_date': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.current_license.expiration_date)),
            'features': self.current_license.features
        }
    
    def reset_license(self):
        """重置授权"""
        if os.path.exists(self.license_file):
            os.remove(self.license_file)
        self.current_license = None
        print("🔄 授权已重置")


class LicenseDialog(QDialog):
    """授权管理对话框"""
    
    def __init__(self, license_manager: LicenseManager, parent=None):
        super().__init__(parent)
        self.license_manager = license_manager
        self.setWindowTitle("授权管理")
        self.setMinimumSize(400, 400)
        self.setWindowIcon(QIcon("icon.png"))
        
        self._setup_ui()
        self._update_license_info()
    
    def _setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout(self)
        
        # 标签页
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # 授权信息标签页
        info_tab = QWidget()
        info_layout = QVBoxLayout(info_tab)
        
        self.license_info_text = QLabel("未激活")
        self.license_info_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.license_info_text.setWordWrap(True)
        info_layout.addWidget(self.license_info_text)
        
        self.tabs.addTab(info_tab, "授权信息")
        
        # 激活标签页
        activate_tab = QWidget()
        activate_layout = QFormLayout(activate_tab)
        
        self.user_name_edit = QLineEdit()
        self.email_edit = QLineEdit()
        self.activation_code_edit = QLineEdit()
        
        activate_layout.addRow("用户名:", self.user_name_edit)
        activate_layout.addRow("邮箱:", self.email_edit)
        activate_layout.addRow("激活码:", self.activation_code_edit)
        
        self.activate_button = QPushButton("激活")
        self.activate_button.clicked.connect(self._activate)
        activate_layout.addRow(self.activate_button)
        
        self.tabs.addTab(activate_tab, "激活")
        
        # 购买标签页
        buy_tab = QWidget()
        buy_layout = QVBoxLayout(buy_tab)
        
        buy_layout.addWidget(QLabel("选择版本购买:"))
        
        self.version_combo = QComboBox()
        for level in [LicenseLevel.PERSONAL, LicenseLevel.PROFESSIONAL, LicenseLevel.ENTERPRISE]:
            self.version_combo.addItem(level.value, level)
        buy_layout.addWidget(self.version_combo)
        
        self.buy_button = QPushButton("立即购买")
        self.buy_button.clicked.connect(self._buy)
        buy_layout.addWidget(self.buy_button)

        # 如实说明：PAYMENT_LINKS 目前配置的是 Stripe 测试环境链接（test_ 前缀），
        # 不是正式收款渠道，点击不会产生真实交易——加一行提示避免用户误以为
        # 已经完成真实付款
        test_link_notice = QLabel("⚠️ 当前为测试环境购买链接，暂不支持真实付款")
        test_link_notice.setStyleSheet("color:#ff9800;font-size:10px;")
        buy_layout.addWidget(test_link_notice)

        buy_layout.addWidget(QLabel("\n价格："))
        buy_layout.addWidget(QLabel("• 个人版: ¥299（终身授权）"))
        buy_layout.addWidget(QLabel("• 专业版: ¥599（终身授权）"))
        buy_layout.addWidget(QLabel("• 企业版: ¥1999（终身授权）"))
        
        self.tabs.addTab(buy_tab, "购买")
        
        # 重置按钮
        reset_button = QPushButton("重置授权")
        reset_button.clicked.connect(self._reset)
        layout.addWidget(reset_button)
    
    def _update_license_info(self):
        """更新授权信息"""
        info = self.license_manager.get_license_info()
        
        if info:
            text = f"""
当前授权：{info['level']}（本地试用模式，未接入服务器验证）
状态：{info['status']}
用户名：{info['user_name']}
邮箱：{info['email']}
激活时间：{info['activation_date']}
到期时间：{info['expiration_date']}

功能权限：
"""
            
            for feature, has_permission in info['features'].items():
                text += f"• {feature}: {'✓' if has_permission else '✗'}\n"
        else:
            text = '''未激活 - 当前为免费版

功能限制：
• 基础剪辑：✓
• AI理解：✗
• 专业剪辑：✗
• 批量处理：✗
• 爆款预测：✗
• 智能剪辑：✗
• 云端API：✗
• 商业使用：✗'''
        
        self.license_info_text.setText(text)
    
    def _activate(self):
        """激活"""
        user_name = self.user_name_edit.text().strip()
        email = self.email_edit.text().strip()
        activation_code = self.activation_code_edit.text().strip()
        
        if not user_name or not email or not activation_code:
            QMessageBox.warning(self, "错误", "请填写完整信息")
            return
        
        success, message = self.license_manager.validate_activation_code(
            activation_code, user_name, email
        )
        
        if success:
            QMessageBox.information(self, "成功", message)
            self._update_license_info()
        else:
            QMessageBox.warning(self, "失败", message)
    
    def _buy(self):
        """购买"""
        level = self.version_combo.currentData()
        self.license_manager.open_payment_link(level)
    
    def _reset(self):
        """重置授权"""
        if QMessageBox.question(
            self, "确认", "确定要重置授权吗？\n这将清除当前的激活状态。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.license_manager.reset_license()
            self._update_license_info()
            QMessageBox.information(self, "成功", "授权已重置")


# 全局授权管理器实例
_license_manager_instance = None

def get_license_manager() -> LicenseManager:
    """获取授权管理器实例"""
    global _license_manager_instance
    if _license_manager_instance is None:
        _license_manager_instance = LicenseManager()
    return _license_manager_instance


def check_permission(feature: str) -> bool:
    """检查权限的便捷函数"""
    return get_license_manager().has_permission(feature)


def get_current_level() -> LicenseLevel:
    """获取当前授权级别的便捷函数"""
    return get_license_manager().get_current_level()


# 使用示例
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    
    license_manager = get_license_manager()
    dialog = LicenseDialog(license_manager)
    
    # 测试权限检查
    print(f"基础剪辑权限: {check_permission('basic_editing')}")
    print(f"AI理解权限: {check_permission('ai_understanding')}")
    print(f"专业剪辑权限: {check_permission('professional_editing')}")
    
    dialog.exec()
    sys.exit(app.exec())
