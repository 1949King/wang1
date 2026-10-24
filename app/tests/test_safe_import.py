import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def setup_logger():
    """设置测试日志级别"""
    import logging
    logging.basicConfig(level=logging.DEBUG)


class TestResolveModulePath:
    """测试 _resolve_module_path 函数"""
    
    def test_with_app_prefix(self):
        """测试带 app. 前缀的路径解析"""
        from app.core.editor_scheduler import _resolve_module_path
        paths = _resolve_module_path("app.core.video_processing")
        assert paths == ["app.core.video_processing", "core.video_processing"]
    
    def test_without_app_prefix(self):
        """测试不带 app. 前缀的路径解析"""
        from app.core.editor_scheduler import _resolve_module_path
        paths = _resolve_module_path("core.video_processing")
        assert paths == ["app.core.video_processing", "core.video_processing"]


class TestSafeImport:
    """测试 _safe_import 函数"""
    
    def test_normal_import_success(self):
        """测试正常导入（带 app. 前缀）"""
        from app.core.editor_scheduler import _safe_import
        result = _safe_import("app.core.editor_scheduler", ["EditorKernel"])
        assert isinstance(result, tuple)
        assert len(result) == 1
        assert result[0].__name__ == "EditorKernel"
    
    def test_fallback_import_success(self):
        """测试前缀回退导入（第一次失败，第二次成功）"""
        from app.core.editor_scheduler import _safe_import
        
        real_import = __import__
        import_errors = []
        
        def mock_import(name, fromlist):
            if name == "app.nonexistent_module":
                import_errors.append("first attempt")
                raise ImportError("Module not found")
            elif name == "nonexistent_module":
                import_errors.append("second attempt")
                raise ImportError("Module not found")
            return real_import(name, fromlist=fromlist)
        
        with patch("builtins.__import__", side_effect=mock_import):
            result = _safe_import("app.core.editor_scheduler", ["EditorKernel"])
            assert isinstance(result, tuple)
            assert len(result) == 1
    
    def test_both_paths_fail(self):
        """测试双路径都失败抛 ImportError"""
        from app.core.editor_scheduler import _safe_import
        
        def mock_import(name, fromlist):
            raise ImportError(f"Module {name} not found")
        
        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError) as exc_info:
                _safe_import("nonexistent.module.path", ["some_function"])
            assert "无法从任何路径导入模块" in str(exc_info.value)
            assert "nonexistent.module.path" in str(exc_info.value)
    
    def test_missing_attribute(self):
        """测试属性缺失抛 ImportError"""
        from app.core.editor_scheduler import _safe_import
        
        with pytest.raises(ImportError) as exc_info:
            _safe_import("app.core.editor_scheduler", ["nonexistent_attribute"])
        assert "缺少属性" in str(exc_info.value)
        assert "nonexistent_attribute" in str(exc_info.value)
    
    def test_partial_missing_attribute(self):
        """测试部分属性缺失"""
        from app.core.editor_scheduler import _safe_import
        
        with pytest.raises(ImportError) as exc_info:
            _safe_import("app.core.editor_scheduler", ["EditorKernel", "nonexistent_attr"])
        assert "缺少属性" in str(exc_info.value)
        assert "nonexistent_attr" in str(exc_info.value)
    
    def test_multiple_attributes_success(self):
        """测试导入多个属性成功"""
        from app.core.editor_scheduler import _safe_import
        result = _safe_import("app.core.editor_scheduler", ["EditorKernel", "KernelSelection"])
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0].__name__ == "EditorKernel"
        assert result[1].__name__ == "KernelSelection"
    
    def test_attribute_missing_tries_alternate_path(self):
        """测试属性缺失时尝试替代路径，但最终失败"""
        import importlib.util
        from app.core.editor_scheduler import _safe_import

        # 确定性前提：两条候选路径各自对应 sys.modules 里独立的模块对象。
        # conftest 把 app/ 加进 sys.path 后，core.editor_scheduler 随时可解析；
        # 若它恰好已被缓存（或被现场导入成功）且属性完好，_safe_import 会在
        # 替代路径上意外成功 → 用例抖动（DID NOT RAISE）。故预导入两条路径、
        # 把属性从两个模块对象上一并摘除，并在结束后还原，杜绝顺序依赖。
        import app.core.editor_scheduler as mod_app
        saved_app = mod_app.__dict__["EditorKernel"]
        mod_alt = None
        saved_alt = None
        if importlib.util.find_spec("core.editor_scheduler") is not None:
            import core.editor_scheduler as mod_alt
            if mod_alt is not mod_app:
                saved_alt = mod_alt.__dict__["EditorKernel"]
            else:
                mod_alt = None

        real_import = __import__
        attempts = []

        def mock_import(name, fromlist):
            attempts.append(name)
            return real_import(name, fromlist=fromlist)

        try:
            del mod_app.__dict__["EditorKernel"]
            if mod_alt is not None:
                del mod_alt.__dict__["EditorKernel"]
            with patch("builtins.__import__", side_effect=mock_import):
                with pytest.raises(ImportError) as exc_info:
                    _safe_import("app.core.editor_scheduler", ["EditorKernel"])
                assert "缺少属性" in str(exc_info.value)
                assert "EditorKernel" in str(exc_info.value)
            # 两条路径（app.core.* 与 core.*）都被实际尝试过
            assert attempts == ["app.core.editor_scheduler", "core.editor_scheduler"]
        finally:
            mod_app.__dict__["EditorKernel"] = saved_app
            if mod_alt is not None:
                mod_alt.__dict__["EditorKernel"] = saved_alt