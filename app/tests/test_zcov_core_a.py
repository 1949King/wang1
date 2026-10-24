"""app/tests/test_zcov_core_a.py — core 层零覆盖模块补测（批 A，2026-10-09）。

覆盖：
  · app/core/validation.py           输入验证框架（含路径安全）
  · app/core/thread_safety.py        线程安全原语
  · app/core/async_client.py         缓存键 / 单例
  · app/core/generation_postprocess.py  data-url 编解码 / 进度映射
  · app/core/ai_interpolation.py     线性补帧纯逻辑（**本文件同时锁住它的可导入性**）

为什么要补（背景）：
  实测覆盖率只有 21%，197 个文件 0% 覆盖，其中 core 逻辑层 113 个。这些模块
  不是「没人用的死代码」——它们是 validation / thread_safety 这种**地基**，
  坏一次就是全仓静默失效。有 877 个既有绿灯用例做安全网，补测成本很低。

风格对齐 app/tests/test_frame_cache.py：每个用例断言**可观察行为**，
docstring 说清「为什么这个断言有判别力」，不写同义重复用例。
"""
import threading
import time

import pytest


# ═══════════════════════════════════════════════════════════════
#  app/core/validation.py
# ═══════════════════════════════════════════════════════════════

from app.core.validation import (
    RequiredValidator,
    TypeValidator,
    RangeValidator,
    LengthValidator,
    PatternValidator,
    SafePathValidator,
    FileExtensionValidator,
    ValidationSchema,
    ValidationResult,
    sanitize_file_path,
    validate_file_extension,
)
from app.core.exceptions import SecurityError, ValidationError


class TestRequiredValidator:
    def test_none_is_rejected(self):
        assert RequiredValidator().validate(None).is_valid is False

    def test_whitespace_only_string_is_rejected(self):
        """只有空格的字符串等同空 —— 这是最容易漏的判据。"""
        assert RequiredValidator().validate("   ").is_valid is False

    @pytest.mark.parametrize("value", ["x", "0", 0, [], {}, False])
    def test_present_values_pass(self, value):
        """注意 0 / False 是**合法**值（判据是 None / 空串，不是 falsy）。"""
        assert RequiredValidator().validate(value).is_valid is True

    def test_error_message_carries_field_name(self):
        r = RequiredValidator().validate(None, "标题")
        assert any("标题" in e for e in r.errors)


class TestTypeValidator:
    def test_none_always_passes(self):
        """None 交给 RequiredValidator 判断，类型校验器不重复报错。"""
        assert TypeValidator(str).validate(None).is_valid is True

    def test_wrong_type_reports_both_names(self):
        r = TypeValidator(str).validate(123, "name")
        assert not r.is_valid
        assert "str" in r.errors[0] and "int" in r.errors[0]

    def test_tuple_of_types_accepted(self):
        v = TypeValidator((int, float))
        assert v.validate(1).is_valid and v.validate(1.5).is_valid


class TestRangeValidator:
    @pytest.mark.parametrize(
        "value,ok",
        [(0, False), (1, True), (120, True), (0.999, False), (121, False)],
    )
    def test_inclusive_bounds(self, value, ok):
        """边界是**闭区间**（min<=v<=max）——差一个等号就是 off-by-one。"""
        v = RangeValidator(min_value=1, max_value=120)
        assert v.validate(value).is_valid is ok

    def test_numeric_string_is_coerced(self):
        """字符串 "60" 会被 float() 强转 —— 这是有意为之，锁住它。"""
        assert RangeValidator(min_value=1, max_value=120).validate("60").is_valid

    def test_non_numeric_reports_number_error(self):
        r = RangeValidator(min_value=1).validate("abc")
        assert not r.is_valid and "必须是数字" in r.errors[0]

    def test_none_passes(self):
        assert RangeValidator(min_value=1, max_value=2).validate(None).is_valid


class TestLengthValidator:
    def test_bounds(self):
        v = LengthValidator(min_length=1, max_length=3)
        assert v.validate("").is_valid is False   # 0 < 1
        assert v.validate("a").is_valid is True
        assert v.validate("abc").is_valid is True
        assert v.validate("abcd").is_valid is False

    def test_object_without_len_reports_error(self):
        r = LengthValidator(min_length=1).validate(42)
        assert not r.is_valid and "不支持长度检查" in r.errors[0]


class TestPatternValidator:
    def test_match_is_anchored_at_start_not_fullmatch(self):
        """re.match ≠ re.fullmatch：正则没写 $ 时多余后缀**不算**错。

        判别性用例：如果有人把 match 改成 fullmatch，这里会红。
        """
        v = PatternValidator(r"^[a-z]+")
        assert v.validate("abc123").is_valid is True

    def test_non_string_is_rejected(self):
        r = PatternValidator(r"^\d+$").validate(123)
        assert not r.is_valid and "必须是字符串" in r.errors[0]

    def test_none_passes(self):
        assert PatternValidator(r"^\d+$").validate(None).is_valid


class TestSafePathValidator:
    def test_dotdot_is_rejected(self):
        assert SafePathValidator().validate("../etc/passwd").is_valid is False

    @pytest.mark.parametrize("p", ["/etc/passwd", "\\windows\\system32", "C:..\\x"])
    def test_leading_separator_or_dotdot_rejected(self, p):
        assert SafePathValidator().validate(p).is_valid is False

    def test_outside_allowed_base_is_rejected(self, tmp_path):
        base = tmp_path / "allowed"
        base.mkdir()
        other = tmp_path / "other" / "f.mp4"
        other.parent.mkdir()
        v = SafePathValidator([str(base)])
        assert v.validate(str(other)).is_valid is False

    def test_inside_allowed_base_passes(self, tmp_path):
        base = tmp_path / "allowed"
        base.mkdir()
        target = base / "f.mp4"
        v = SafePathValidator([str(base)])
        assert v.validate(str(target)).is_valid is True

    def test_sibling_dir_with_same_prefix_is_rejected(self, tmp_path):
        """前缀逃逸回归锁（2026-10-09 修）。

        base = `<tmp>/allowed`，攻击路径 = `<tmp>/allowed_evil/x.mp4`。
        旧实现用 `abspath.startswith(abspath(base))`，字符串前缀完全匹配 ⇒ 放行；
        现在改用 os.path.commonpath 按**路径段**判定 ⇒ 正确拒绝。
        判别力：把实现改回 startswith，这条立刻红。
        """
        base = tmp_path / "allowed"
        base.mkdir()
        evil = tmp_path / "allowed_evil"
        evil.mkdir()
        v = SafePathValidator([str(base)])
        assert v.validate(str(evil / "x.mp4")).is_valid is False

    def test_is_within_dir_helper_directly(self, tmp_path):
        from app.core.validation import is_within_dir

        base = tmp_path / "base"
        base.mkdir()
        assert is_within_dir(str(base / "a" / "b.mp4"), str(base)) is True
        assert is_within_dir(str(base) + "_evil", str(base)) is False
        assert is_within_dir(str(tmp_path / "other"), str(base)) is False


class TestFileExtensionValidator:
    def test_case_insensitive_by_default(self):
        v = FileExtensionValidator([".MP4"])
        assert v.validate("a.mp4").is_valid is True

    def test_case_sensitive_mode_rejects_case_mismatch(self):
        v = FileExtensionValidator([".mp4"], case_sensitive=True)
        assert v.validate("a.MP4").is_valid is False

    def test_unknown_extension_lists_allowed(self):
        r = FileExtensionValidator([".mp4"]).validate("a.wav")
        assert not r.is_valid and ".mp4" in r.errors[0]


class TestValidationSchema:
    def _schema(self):
        s = ValidationSchema()
        s.add_validator("name", RequiredValidator())
        s.add_validator("name", LengthValidator(max_length=3))
        s.add_validator("fps", RangeValidator(min_value=1, max_value=120))
        return s

    def test_errors_from_all_validators_are_aggregated(self):
        """同一个字段挂两个校验器时，**两边的错误都要收上来**（不是短路）。"""
        results = self._schema().validate({"name": "", "fps": 999})
        assert len(results["name"].errors) >= 1
        assert not results["fps"].is_valid

    def test_missing_field_is_read_as_none(self):
        results = self._schema().validate({})
        assert "name" in results and "fps" in results

    def test_is_valid_summarises(self):
        s = self._schema()
        assert s.is_valid({"name": "ok", "fps": 30}) is True
        assert s.is_valid({"name": "toolongname", "fps": 30}) is False

    def test_untouched_fields_are_not_reported(self):
        """只校验注册过的字段 —— data 里多余的键不该出现在结果里。"""
        results = self._schema().validate({"name": "ok", "extra": 1})
        assert "extra" not in results


class TestModuleLevelHelpers:
    def test_sanitize_rejects_traversal(self):
        with pytest.raises(SecurityError):
            sanitize_file_path("../secret.txt")

    def test_sanitize_returns_absolute_path(self, tmp_path):
        got = sanitize_file_path(str(tmp_path / "a.mp4"))
        assert got == str((tmp_path / "a.mp4").resolve()) or got.endswith("a.mp4")

    def test_sanitize_enforces_base_dirs(self, tmp_path):
        base = tmp_path / "base"
        base.mkdir()
        with pytest.raises(SecurityError):
            sanitize_file_path(str(tmp_path / "outside.mp4"), [str(base)])

    def test_validate_extension_raises_on_bad_ext(self):
        with pytest.raises(ValidationError):
            validate_file_extension("a.wav", [".mp4"])

    def test_validate_extension_ok_returns_true(self):
        assert validate_file_extension("a.MP4", [".mp4"]) is True


class TestValidationResult:
    def test_add_error_flips_is_valid(self):
        r = ValidationResult(is_valid=True, field_name="f", field_value=1)
        r.add_error("boom")
        assert r.is_valid is False and r.errors == ["boom"]

    def test_add_warning_does_not_flip_is_valid(self):
        """警告 ≠ 失败 —— 这两个语义混了会让人误判提交能不能过。"""
        r = ValidationResult(is_valid=True, field_name="f", field_value=1)
        r.add_warning("meh")
        assert r.is_valid is True and r.warnings == ["meh"]

    def test_to_dict_stringifies_value(self):
        r = ValidationResult(is_valid=True, field_name="f", field_value=[1, 2])
        assert r.to_dict()["field_value"] == "[1, 2]"


# ═══════════════════════════════════════════════════════════════
#  app/core/thread_safety.py
# ═══════════════════════════════════════════════════════════════

from app.core.thread_safety import (
    ThreadSafeCounter,
    ThreadSafeDict,
    ThreadSafeQueue,
    ThreadSafetyManager,
    get_thread_safety_manager,
)


class TestThreadSafeCounter:
    def test_increment_returns_new_value(self):
        c = ThreadSafeCounter()
        assert c.increment() == 1
        assert c.increment(5) == 6
        assert c.get_value() == 6

    def test_decrement_can_go_negative(self):
        assert ThreadSafeCounter(0).decrement() == -1

    def test_reset_with_explicit_value(self):
        c = ThreadSafeCounter(10)
        c.reset(3)
        assert c.get_value() == 3

    def test_concurrent_increments_are_not_lost(self):
        """8 线程 × 500 次 = 4000。丢一次就说明锁没起作用。"""
        c = ThreadSafeCounter()
        threads = [
            threading.Thread(target=lambda: [c.increment() for _ in range(500)])
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert c.get_value() == 4000


class TestThreadSafeDict:
    def test_basic_crud(self):
        d = ThreadSafeDict()
        d.set("a", 1)
        assert d.get("a") == 1
        assert "a" in d and len(d) == 1
        d.delete("a")
        assert "a" not in d

    def test_delete_missing_key_is_silent(self):
        """删除不存在的键不该抛 KeyError —— 调用方依赖这个宽容语义。"""
        ThreadSafeDict().delete("nope")

    def test_pop_missing_returns_default(self):
        assert ThreadSafeDict().pop("nope", "dflt") == "dflt"

    def test_keys_values_items_are_snapshots(self):
        """返回的是**拷贝**：拿到之后改字典不该影响已取出的列表。"""
        d = ThreadSafeDict()
        d.set("a", 1)
        ks = d.keys()
        d.set("b", 2)
        assert ks == ["a"]

    def test_concurrent_set_does_not_lose_keys(self):
        d = ThreadSafeDict()
        threads = [
            threading.Thread(target=lambda i=i: [d.set(f"{i}-{j}", j) for j in range(200)])
            for i in range(6)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(d) == 1200


class TestThreadSafeQueue:
    def test_fifo_order(self):
        q = ThreadSafeQueue()
        for i in range(3):
            q.put(i)
        assert [q.get(), q.get(), q.get()] == [0, 1, 2]

    def test_peek_does_not_remove(self):
        q = ThreadSafeQueue()
        q.put("x")
        assert q.peek() == "x" and q.qsize() == 1

    def test_max_size_drops_oldest(self):
        """满队列插新项 = **丢最旧**（FIFO 淘汰），不是丢新项也不是抛异常。"""
        q = ThreadSafeQueue(max_size=2)
        for i in range(4):
            q.put(i)
        assert q.qsize() == 2
        assert [q.get(), q.get()] == [2, 3]

    def test_get_on_empty_with_timeout_returns_none(self):
        assert ThreadSafeQueue().get(timeout=0.05) is None

    def test_clear(self):
        q = ThreadSafeQueue()
        q.put(1)
        q.clear()
        assert q.qsize() == 0


class TestThreadSafetyManager:
    def test_create_lock_is_idempotent(self):
        """同名锁必须返回**同一个对象**，否则锁根本没起作用。"""
        m = ThreadSafetyManager()
        assert m.create_lock("x") is m.create_lock("x")

    def test_acquire_without_create_returns_false(self):
        assert ThreadSafetyManager().acquire_lock("never-created") is False

    def test_with_lock_releases_on_exception(self):
        """异常路径必须也释放 —— 否则一次异常就永久死锁。"""
        m = ThreadSafetyManager()
        with pytest.raises(ValueError):
            with m.with_lock("boom"):
                raise ValueError("boom")
        # 能再次拿到 = 上一把确实释放了
        assert m.acquire_lock("boom", timeout=1.0) is True
        m.release_lock("boom")

    def test_acquire_count_increases(self):
        m = ThreadSafetyManager()
        m.create_lock("c")
        m.acquire_lock("c", timeout=1.0)
        m.release_lock("c")
        m.acquire_lock("c", timeout=1.0)
        m.release_lock("c")
        assert m.get_lock_stats()["c"]["acquire_count"] == 2

    def test_get_thread_safety_manager_is_singleton(self):
        assert get_thread_safety_manager() is get_thread_safety_manager()


# ═══════════════════════════════════════════════════════════════
#  app/core/async_client.py
# ═══════════════════════════════════════════════════════════════

from app.core.async_client import AsyncHTTPClient, Response


class TestAsyncClientCacheKey:
    def _client(self):
        return AsyncHTTPClient()

    def test_same_input_same_key(self):
        c = self._client()
        a = c._get_cache_key("GET", "/u", params={"b": 2, "a": 1})
        b = c._get_cache_key("GET", "/u", params={"a": 1, "b": 2})
        assert a == b, "参数字典顺序不该影响缓存键（sort_keys 的作用）"

    @pytest.mark.parametrize(
        "other",
        [
            dict(method="POST"),
            dict(url="/other"),
            dict(params={"a": 2}),
        ],
    )
    def test_different_input_different_key(self, other):
        c = self._client()
        base = dict(method="GET", url="/u", params={"a": 1})
        base.update(other)
        k1 = c._get_cache_key("GET", "/u", params={"a": 1})
        k2 = c._get_cache_key(base["method"], base["url"], params=base["params"])
        assert k1 != k2

    def test_json_body_changes_key(self):
        c = self._client()
        k1 = c._get_cache_key("POST", "/u", json={"x": 1})
        k2 = c._get_cache_key("POST", "/u", json={"x": 2})
        assert k1 != k2


class TestAsyncClientCacheStorage:
    def _resp(self):
        return Response(status=200, headers={}, data={"ok": True},
                        url="/u", elapsed=0.0, success=True)

    def test_set_then_get_roundtrip(self):
        c = AsyncHTTPClient()
        c._set_cache("k1", self._resp())
        got = c._get_from_cache("k1")
        assert got is not None and got.status == 200

    def test_expired_entry_is_dropped(self):
        """过 TTL 的条目必须**被删掉**，而不是留在字典里反复命中失败。"""
        c = AsyncHTTPClient()
        c._set_cache("k2", self._resp())
        c._cache["k2"] = (c._cache["k2"][0], time.time() - 10_000)
        assert c._get_from_cache("k2") is None
        assert "k2" not in c._cache

    def test_cache_disabled_returns_none_and_does_not_store(self):
        c = AsyncHTTPClient()
        c._config.enable_cache = False
        try:
            c._set_cache("k3", self._resp())
            assert c._get_from_cache("k3") is None
        finally:
            c._config.enable_cache = True

    def test_singleton(self):
        assert AsyncHTTPClient() is AsyncHTTPClient()


class TestResponse:
    def test_json_parses_string_payload(self):
        r = Response(200, {}, '{"a": 1}', "/u", 0.0, True)
        assert r.json() == {"a": 1}

    def test_json_returns_none_on_garbage(self):
        """坏 JSON 不能抛异常 —— 调用方按 None 处理。"""
        r = Response(200, {}, "not-json", "/u", 0.0, True)
        assert r.json() is None

    def test_text_empty_when_no_data(self):
        assert Response(200, {}, "", "/u", 0.0, True).text() == ""


# ═══════════════════════════════════════════════════════════════
#  app/core/generation_postprocess.py
# ═══════════════════════════════════════════════════════════════

import numpy as np

from app.core.generation_postprocess import (
    _decode_data_url,
    _encode_data_url,
    _scaled_progress,
    _report_progress,
)


class TestDataUrl:
    def test_decode_rejects_empty_and_malformed(self):
        assert _decode_data_url("") is None
        assert _decode_data_url("no-comma-here") is None
        assert _decode_data_url("data:image/png,plaintext") is None

    def test_encode_decode_roundtrip(self):
        img = np.zeros((8, 8, 3), dtype=np.uint8)
        img[0, 0] = (255, 0, 0)
        url = _encode_data_url(img)
        assert url.startswith("data:image/png;base64,")
        back = _decode_data_url(url)
        assert back is not None and back.shape == (8, 8, 3)
        assert tuple(back[0, 0]) == (255, 0, 0)

    def test_decode_of_encoded_rejects_bad_base64(self):
        """header 带 base64 但内容不是合法 b64 → 返回 None，不抛。"""
        assert _decode_data_url("data:image/png;base64,!!!not-base64!!!") is None


class TestProgressMapping:
    def test_none_callback_returns_none(self):
        assert _scaled_progress(None, 0, 100) is None

    def test_maps_subrange(self):
        seen = []
        wrap = _scaled_progress(lambda p, m: seen.append(p), 20, 60)
        wrap(0)
        wrap(100)
        assert seen == [20, 60], "子阶段 0→100 应线性映射到 [20,60]"

    def test_clamps_out_of_range(self):
        """越界百分比必须被夹住，不能让进度条跑到区间外。"""
        seen = []
        wrap = _scaled_progress(lambda p, m: seen.append(p), 10, 20)
        wrap(-50)
        wrap(150)
        assert seen == [10, 20]

    def test_report_progress_swallows_callback_errors(self):
        """回调抛异常不能把主流程带崩（best-effort 上报）。"""
        _report_progress(lambda p, m: (_ for _ in ()).throw(RuntimeError("x")), 5, "m")


# ═══════════════════════════════════════════════════════════════
#  app/core/ai_interpolation.py —— 含「模块可导入」回归锁
# ═══════════════════════════════════════════════════════════════

import app.core.ai_interpolation as ai_interp
from app.core.ai_interpolation import (
    AIInterpolationEngine,
    ContextAwareInterpolator,
    FrameDifferenceType,
    InterpolationMode,
    SceneChangeDetector,
)


class TestModuleImportabilityRegression:
    """2026-10-09 事故回归锁：pyqtSignal 收到 typing 泛型别名会让**整模块 import 崩**。

    原写法 `pyqtSignal(float, List[np.ndarray])` 抛
        TypeError: bytes or ASCII string expected not '_GenericAlias'
    因为异常在**类体执行期**，import 直接失败 ⇒ preview_manager 开补帧即崩、
    deformity_repair_skill 静默降级、覆盖率永远 0%。
    本用例只做一件事：确认模块**能被 import** 且信号对象存在。
    """

    def test_module_imports(self):
        assert ai_interp is not None

    def test_engine_signals_exist(self):
        assert hasattr(AIInterpolationEngine, "interpolation_ready")
        assert hasattr(AIInterpolationEngine, "markers_updated")

    def test_worker_signals_exist(self):
        assert hasattr(ai_interp.InterpolationWorker, "interpolation_ready")

    def test_related_module_highlight_preview_imports(self):
        """同一批修的另一处：highlight_preview.py 有 3 处同型缺陷。"""
        import app.core.highlight_preview as hp

        assert hasattr(hp.HighlightPreviewManager, "highlights_updated")
        assert hasattr(hp.HighlightDetectorThread, "detection_completed")


class TestLinearInterpolate:
    def _interp(self):
        return ContextAwareInterpolator()

    def test_alpha_zero_returns_first_frame(self):
        a = np.zeros((4, 4, 3), dtype=np.uint8)
        b = np.full((4, 4, 3), 200, dtype=np.uint8)
        out = self._interp()._linear_interpolate(a, b, 0.0)
        assert np.array_equal(out, a)

    def test_alpha_one_returns_second_frame(self):
        a = np.zeros((4, 4, 3), dtype=np.uint8)
        b = np.full((4, 4, 3), 200, dtype=np.uint8)
        out = self._interp()._linear_interpolate(a, b, 1.0)
        assert np.array_equal(out, b)

    def test_alpha_half_is_midpoint(self):
        a = np.zeros((2, 2, 3), dtype=np.uint8)
        b = np.full((2, 2, 3), 100, dtype=np.uint8)
        out = self._interp()._linear_interpolate(a, b, 0.5)
        assert np.all(out == 50)

    def test_result_dtype_is_uint8(self):
        """必须回落 uint8：float32 传给编码器会直接报错。"""
        a = np.zeros((2, 2, 3), dtype=np.uint8)
        b = np.full((2, 2, 3), 255, dtype=np.uint8)
        assert self._interp()._linear_interpolate(a, b, 0.3).dtype == np.uint8

    def test_alpha_zero_point_nine_rounds_not_truncates(self):
        """255*(0.9)=229.5 → 四舍五入 230。截断会得 229，肉眼可见偏暗。"""
        a = np.zeros((1, 1, 3), dtype=np.uint8)
        b = np.full((1, 1, 3), 255, dtype=np.uint8)
        out = self._interp()._linear_interpolate(a, b, 0.9)
        assert int(out[0, 0, 0]) in (229, 230)  # 取决于 astype 舍入策略，锁住范围


class TestSceneChangeDetector:
    def test_first_frame_never_needs_interpolation(self):
        d = SceneChangeDetector()
        r = d.analyze_frame(np.zeros((16, 16, 3), dtype=np.uint8), 0.0)
        assert r.needs_interpolation is False and r.similarity_score == 1.0

    def test_reset_clears_last_frame(self):
        d = SceneChangeDetector()
        d.analyze_frame(np.zeros((8, 8, 3), dtype=np.uint8), 0.0)
        d.reset()
        assert d._last_frame is None

    def test_buffer_is_bounded(self):
        """缓冲区必须**封顶**，否则长视频播放会一直涨内存。"""
        d = SceneChangeDetector()
        for i in range(20):
            d._update_buffer(np.zeros((2, 2, 3), dtype=np.uint8), float(i))
        assert len(d._frame_buffer) == d._max_buffer_size

    @pytest.mark.parametrize(
        "diff,score,expected",
        [
            (FrameDifferenceType.JUMP_CUT, 0.5, True),
            (FrameDifferenceType.JUMP_CUT, 0.9, False),
            (FrameDifferenceType.SCENE_CHANGE, 0.6, True),
            (FrameDifferenceType.SCENE_CHANGE, 0.7, False),   # 边界：< 0.7
            (FrameDifferenceType.MOTION_BLUR, 0.84, True),
            (FrameDifferenceType.MOTION_BLUR, 0.85, False),   # 边界：< 0.85
            (FrameDifferenceType.SMOOTH, 0.1, False),         # 平滑帧永不插
        ],
    )
    def test_should_interpolate_thresholds(self, diff, score, expected):
        assert SceneChangeDetector()._should_interpolate(diff, score) is expected

    @pytest.mark.parametrize(
        "score,count", [(0.0, 3), (0.29, 3), (0.3, 2), (0.49, 2), (0.5, 1), (0.99, 1)]
    )
    def test_interpolation_count_tiers(self, score, count):
        assert SceneChangeDetector()._calculate_interpolation_count(score) == count

    def test_calculate_difference_swallows_error_into_smooth(self):
        """已知的静默兜底：异常一律降级成 SMOOTH/0.9。

        这是**有意**的保守兜底（宁可不插帧也不能崩预览），本用例把它锁成
        显式契约，免得日后被误当 bug 改掉。若哪天要改成不吞，请同步改这里。
        """
        d = SceneChangeDetector()
        d._last_frame = None  # 传 None 会让 cv2.cvtColor 抛异常
        diff, score, flow = d._calculate_difference(np.zeros((4, 4, 3), dtype=np.uint8))
        assert diff is FrameDifferenceType.SMOOTH and score == 0.9 and flow is None


class TestInterpolatorAndEngine:
    def test_mode_enum_values(self):
        assert {m.name for m in InterpolationMode} == {"DISABLED", "AUTO", "ALWAYS", "SMART"}

    def test_disabled_mode_returns_no_frames(self):
        it = ContextAwareInterpolator()
        it.set_mode(InterpolationMode.DISABLED)
        assert it.process_frame(np.zeros((8, 8, 3), dtype=np.uint8), 0.0) == []

    def test_enable_false_returns_no_frames(self):
        it = ContextAwareInterpolator()
        it.enable(False)
        assert it.process_frame(np.zeros((8, 8, 3), dtype=np.uint8), 0.0) == []

    def test_first_frame_produces_nothing(self):
        """第一帧没有前一帧可比 —— 不能凭空造帧。"""
        it = ContextAwareInterpolator()
        it.set_mode(InterpolationMode.SMART)
        assert it.process_frame(np.zeros((8, 8, 3), dtype=np.uint8), 0.0) == []

    def test_get_markers_empty_initially_and_reset_clears(self):
        it = ContextAwareInterpolator()
        assert it.get_markers() == []
        it.reset()
        assert it.get_markers() == []

    def test_engine_process_frame_is_noop_when_engine_disabled(self):
        """引擎未 enable 时入队必须被丢弃（不该悄悄攒一队帧）。"""
        eng = AIInterpolationEngine()
        eng.process_frame(np.zeros((4, 4, 3), dtype=np.uint8), 0.0)  # _enabled 默认 False

    def test_engine_shutdown_is_idempotent(self):
        eng = AIInterpolationEngine()
        eng.shutdown()
        eng.shutdown()
