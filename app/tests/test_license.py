"""授权管理 LicenseManager 测试 (pytest 风格)

覆盖 P1: 激活码格式校验、授权级别、功能权限映射。
仅测纯逻辑, 通过 object.__new__ 绕过 __init__ 的文件落盘与打印,
避免污染用户目录 ~/.ai_short_drama_editor/license.json。
目标模块: license/license_manager.py (打包/入口实际引用的授权模块)。
运行: pytest app/tests/test_license.py -v
"""

import pytest

from license.license_manager import LicenseManager, LicenseLevel, LicenseStatus


@pytest.fixture
def license_manager(tmp_path):
    """构造隔离的 LicenseManager：固定硬件 ID + 临时授权文件，避免写真实授权目录"""
    manager = object.__new__(LicenseManager)
    manager.hardware_id = "0123456789abcdef"
    manager.license_file = str(tmp_path / "license.json")
    manager.current_license = None
    return manager


class TestActivationCode:
    """激活码校验测试"""

    def test_too_few_parts(self, license_manager):
        ok, _ = license_manager.validate_activation_code("PER-ABCD", "张三", "a@qq.com")
        assert ok is False

    def test_invalid_version_code(self, license_manager):
        ok, _ = license_manager.validate_activation_code(
            "XYZ-0123-ABCD-EFGH-IJKL", "张三", "a@qq.com"
        )
        assert ok is False

    def test_hardware_mismatch(self, license_manager):
        ok, msg = license_manager.validate_activation_code(
            "PER-9999-ABCD-EFGH-IJKL", "张三", "a@qq.com"
        )
        assert ok is False
        assert "设备" in msg

    def test_valid_activation(self, license_manager):
        code = f"PRO-{license_manager.hardware_id[:4]}-ABCD-EFGH-IJKL"
        ok, _ = license_manager.validate_activation_code(code, "张三", "a@qq.com")
        assert ok is True
        assert license_manager.current_license.level == LicenseLevel.PROFESSIONAL
        assert license_manager.current_license.status == LicenseStatus.ACTIVE


class TestFeaturePermissions:
    """功能权限映射测试"""

    def test_free_level_limits(self, license_manager):
        assert license_manager.get_current_level() == LicenseLevel.FREE
        assert license_manager.has_permission("basic_editing") is True
        assert license_manager.has_permission("ai_understanding") is False
        assert license_manager.has_permission("commercial_use") is False

    def test_personal_unlocks_ai_but_no_batch(self):
        perms = LicenseManager.FEATURE_PERMISSIONS[LicenseLevel.PERSONAL]
        assert perms["ai_understanding"] is True
        assert perms["batch_processing"] is False

    def test_enterprise_all_features(self):
        perms = LicenseManager.FEATURE_PERMISSIONS[LicenseLevel.ENTERPRISE]
        assert all(perms.values()) is True