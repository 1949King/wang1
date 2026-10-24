"""
B6 单元测试: 3 大总线 (EventBus / MasterClock / DataBus)
=====================================================
盲区 #1 修复: 三大总线此前零单元测试, 改动无回归保护

注意: 直接 import core.py 文件路径, 绕过 modules.lego/__init__.py 的链式导入,
      避免触发 core.editor_scheduler 等可选依赖
"""
import sys
import threading
import time
import importlib.util
from pathlib import Path

# 把 app/ 加进 sys.path
APP_ROOT = Path(__file__).resolve().parents[2] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# 直接 load core.py 文件, 绕过 modules.lego/__init__.py
_core_path = APP_ROOT / "modules" / "lego" / "core.py"
_spec = importlib.util.spec_from_file_location("lego_core", _core_path)
lego_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lego_core)

EventBus = lego_core.EventBus
MasterClock = lego_core.MasterClock
DataBus = lego_core.DataBus
EventType = lego_core.EventType

# 强制重置 3 大总线 (避免上一次测试残留)
EventBus._instance = None
MasterClock._instance = None
DataBus._instance = None

import pytest


# ============== EventBus 测试 ==============

class TestEventBus:
    """EventBus 单例 + 订阅/发布 + 历史回溯"""

    def setup_method(self):
        EventBus._instance = None
        self.bus = EventBus()

    def test_singleton(self):
        """单例模式: 多次创建返回同一实例"""
        b1 = EventBus()
        b2 = EventBus()
        assert b1 is b2
        print("  ✅ 单例模式生效")

    def test_on_emit(self):
        """on/emit 基础流"""
        received = []
        self.bus.on(EventType.PROJECT_CREATED, lambda e: received.append(e.data))
        self.bus.emit(EventType.PROJECT_CREATED, {"name": "test.prj"})
        assert received == [{"name": "test.prj"}]
        print("  ✅ on/emit 正常")

    def test_once(self):
        """once: 一次性监听, 触发后自动移除"""
        count = [0]
        def once_cb(e):
            count[0] += 1
        self.bus.once(EventType.PROJECT_CREATED, once_cb)
        self.bus.emit(EventType.PROJECT_CREATED)
        self.bus.emit(EventType.PROJECT_CREATED)
        self.bus.emit(EventType.PROJECT_CREATED)
        assert count[0] == 1, f"once 应只触发 1 次, 实际 {count[0]}"
        print("  ✅ once 一次性生效 (触发 3 次 → 执行 1 次)")

    def test_off(self):
        """off: 取消订阅"""
        received = []
        cb = lambda e: received.append(e.data)
        self.bus.on(EventType.PROJECT_CREATED, cb)
        self.bus.emit(EventType.PROJECT_CREATED, {"a": 1})
        self.bus.off(EventType.PROJECT_CREATED, cb)
        self.bus.emit(EventType.PROJECT_CREATED, {"a": 2})
        assert received == [{"a": 1}], f"off 后不应收到, 实际 {received}"
        print("  ✅ off 取消订阅生效")

    def test_history(self):
        """get_history: 历史回溯"""
        for i in range(5):
            self.bus.emit(EventType.PROJECT_CREATED, {"i": i})
        history = self.bus.get_history(EventType.PROJECT_CREATED)
        assert len(history) == 5
        assert history[-1].data == {"i": 4}
        print(f"  ✅ 历史回溯 {len(history)} 条")

    def test_max_history(self):
        """历史超过 _max_history 时自动截断"""
        bus = self.bus
        bus._max_history = 10
        for i in range(20):
            bus.emit(EventType.PROJECT_CREATED, {"i": i})
        history = bus.get_history()
        assert len(history) == 10
        print(f"  ✅ 历史截断生效 (20 → {len(history)})")

    def test_emit_with_no_listener(self):
        """emit 无监听器不应崩溃"""
        self.bus.emit(EventType.PROJECT_CREATED, {"a": 1})  # 无监听器
        print("  ✅ 无监听器 emit 正常")

    def test_callback_error_isolation(self):
        """监听器异常不应影响其他监听器"""
        results = []
        def bad_cb(e): raise RuntimeError("boom")
        def good_cb(e): results.append("ok")
        self.bus.on(EventType.PROJECT_CREATED, bad_cb)
        self.bus.on(EventType.PROJECT_CREATED, good_cb)
        self.bus.emit(EventType.PROJECT_CREATED)  # bad_cb 抛错, good_cb 仍应执行
        assert "ok" in results, f"异常隔离失败: {results}"
        print("  ✅ 异常隔离生效 (1 个监听器抛错不影响其他)")

    def test_concurrent_emit(self):
        """并发 emit 应线程安全"""
        bus = self.bus
        count = [0]
        lock = threading.Lock()
        def cb(e):
            with lock:
                count[0] += 1
        bus.on(EventType.PROJECT_CREATED, cb)
        threads = []
        def emit_cb():
            bus.emit(EventType.PROJECT_CREATED)
        for _ in range(10):
            t = threading.Thread(target=emit_cb)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        assert count[0] == 10, f"并发应触发 10 次, 实际 {count[0]}"
        print(f"  ✅ 并发 emit 安全 (10 线程 → 10 触发)")


# ============== MasterClock 测试 ==============

class TestMasterClock:
    """MasterClock 单例 + 帧/时间码互转 + 播放控制"""

    def setup_method(self):
        MasterClock._instance = None
        self.clock = MasterClock()

    def test_singleton(self):
        c1 = MasterClock()
        c2 = MasterClock()
        assert c1 is c2
        print("  ✅ MasterClock 单例")

    def test_set_frame_bounds(self):
        """set_frame 应夹在 [0, total_frames]"""
        self.clock._total_frames = 100
        self.clock.set_frame(50)
        assert self.clock._current_frame == 50
        self.clock.set_frame(200)  # 越界 → 截断到 total
        assert self.clock._current_frame == 100
        self.clock.set_frame(-10)  # 越界 → 截断到 0
        assert self.clock._current_frame == 0
        print("  ✅ 帧边界夹紧生效 (负→0, 超→total)")

    def test_set_time_to_frame(self):
        """set_time 应正确转换为帧"""
        self.clock._fps = 30
        self.clock._total_frames = 300
        self.clock.set_time(2.5)  # 2.5 秒 = 75 帧 @30fps
        assert self.clock._current_frame == 75
        print(f"  ✅ 时间→帧转换 (2.5s @ 30fps = {self.clock._current_frame} 帧)")

    def test_frame_to_timecode(self):
        """frame_to_timecode: HH:MM:SS:FF"""
        self.clock._fps = 30
        self.clock._current_frame = 0
        assert self.clock.frame_to_timecode() == "00:00:00:00"
        self.clock._current_frame = 30  # 1 秒
        assert self.clock.frame_to_timecode() == "00:00:01:00"
        self.clock._current_frame = 30 * 60 * 5 + 15 * 30  # 5 分 15 秒
        assert self.clock.frame_to_timecode() == "00:05:15:00"
        print("  ✅ 帧→时间码 (00:05:15:00 @ 30fps)")

    def test_timecode_to_frame(self):
        """timecode_to_frame: HH:MM:SS:FF"""
        self.clock._fps = 30
        assert self.clock.timecode_to_frame("00:00:00:00") == 0
        assert self.clock.timecode_to_frame("00:00:01:00") == 30
        assert self.clock.timecode_to_frame("00:01:00:00") == 1800
        print("  ✅ 时间码→帧 正常")

    def test_play_pause_stop(self):
        """play/pause/stop 状态机"""
        self.clock._total_frames = 100
        self.clock._fps = 30
        assert self.clock._playing is False
        self.clock.play()
        assert self.clock._playing is True
        self.clock.pause()
        assert self.clock._playing is False
        self.clock.play()
        self.clock.stop()
        assert self.clock._playing is False
        assert self.clock._current_frame == 0
        print("  ✅ play/pause/stop 状态机")

    def test_seek_operations(self):
        """seek/step_forward/step_backward"""
        self.clock._total_frames = 100
        self.clock._fps = 30
        self.clock.seek(50)
        assert self.clock._current_frame == 50
        self.clock.step_forward(10)
        assert self.clock._current_frame == 60
        self.clock.step_backward(5)
        assert self.clock._current_frame == 55
        self.clock.seek_to_start()
        assert self.clock._current_frame == 0
        self.clock.seek_to_end()
        assert self.clock._current_frame == 100
        print("  ✅ seek / step_forward / step_backward / to_start / to_end")


# ============== DataBus 测试 ==============

class TestDataBus:
    """DataBus 单例 + CRUD + 线程安全"""

    def setup_method(self):
        DataBus._instance = None
        self.bus = DataBus()

    def test_singleton(self):
        b1 = DataBus()
        b2 = DataBus()
        assert b1 is b2
        print("  ✅ DataBus 单例")

    def test_set_get(self):
        self.bus.set("key1", "value1")
        assert self.bus.get("key1") == "value1"
        assert self.bus.get("not_exist", "default") == "default"
        print("  ✅ set/get 正常")

    def test_has_delete(self):
        self.bus.set("k", "v")
        assert self.bus.has("k") is True
        self.bus.delete("k")
        assert self.bus.has("k") is False
        print("  ✅ has/delete 正常")

    def test_clear(self):
        self.bus.set("a", 1)
        self.bus.set("b", 2)
        self.bus.clear()
        assert self.bus.keys() == []
        print("  ✅ clear 清空")

    def test_to_from_dict(self):
        self.bus.from_dict({"x": 10, "y": 20, "z": 30})
        d = self.bus.to_dict()
        assert d == {"x": 10, "y": 20, "z": 30}
        print("  ✅ to_dict/from_dict 双向正常")

    def test_overwrite(self):
        self.bus.set("k", "v1")
        self.bus.set("k", "v2")
        assert self.bus.get("k") == "v2"
        print("  ✅ 重复 set 覆盖")

    def test_concurrent_access(self):
        """并发 set 应线程安全"""
        bus = self.bus
        errors = []

        def writer(i):
            try:
                for j in range(100):
                    bus.set(f"key_{i}_{j}", j)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"并发 set 抛错: {errors}"
        # 验证所有写入都成功
        for i in range(5):
            for j in range(100):
                assert bus.has(f"key_{i}_{j}"), f"key_{i}_{j} 丢失"
        print(f"  ✅ 并发 set 安全 (5 线程 × 100 次写入)")


# ============== pytest 入口 ==============

if __name__ == "__main__":
    """支持 python -m pytest 或 python tests/test_event_bus.py 两种方式"""
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
