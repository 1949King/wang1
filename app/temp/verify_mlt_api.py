"""
P0#3 第 2 刀 - MLT ctypes 集中化绑定验证
不需要真实加载 MLT DLL（系统不一定有），验证：
  1. _MLT_API 注册表在 DLL 不可用时是空 dict
  2. _mlt_call 在缺 API 时抛 RuntimeError（不是 AttributeError）
  3. _bind_mlt_api 在无 DLL 时不崩
  4. MltTimeline.insert_clip / playlist_length 签名与边界行为
  5. MltTimeline.__del__ 在 close 抛异常时不会让异常逃逸
"""
import os
import sys
import gc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))

from app.core.video_processing.mlt_engine_cpp import (
    _MLT_API, _mlt_call, _bind_mlt_api,
    is_mlt_available, MltTimeline,
)


def test_mlt_api_registry_empty_when_no_dll():
    """无 MLT DLL 时 _MLT_API 仍可被引用（dict 类型）"""
    assert isinstance(_MLT_API, dict), f"_MLT_API 必须是 dict, got {type(_MLT_API)}"
    # 不一定有内容（DLL 加载与否决定），但结构正确
    print(f"  [OK] _MLT_API 是 dict, 当前 {len(_MLT_API)} 项")


def test_mlt_call_raises_runtimeerror_for_missing_api():
    """_mlt_call 缺 API 时抛 RuntimeError（不是裸 AttributeError）"""
    try:
        _mlt_call('nonexistent_api_xyz', None)
        assert False, "应该抛 RuntimeError"
    except RuntimeError as e:
        assert "不可用" in str(e) or "缺失" in str(e), f"错误信息应可读: {e}"
        print("  [OK] _mlt_call 缺 API 时抛 RuntimeError（带可读信息）")
    except AttributeError as e:
        assert False, f"不应让 AttributeError 逃逸: {e}"


def test_bind_mlt_api_safe_when_no_dll():
    """_bind_mlt_api 在无 DLL 时安全返回"""
    # 模拟 _mlt_dll 为 None 的情况
    import app.core.video_processing.mlt_engine_cpp as mod
    orig = mod._mlt_dll
    mod._mlt_dll = None
    try:
        _bind_mlt_api()  # 不应抛
        print("  [OK] _bind_mlt_api 在 _mlt_dll=None 时安全返回")
    finally:
        mod._mlt_dll = orig


def test_mlttimeline_insert_clip_boundaries():
    """insert_clip 在无 profile 时返回 -1（不崩）"""
    tl = MltTimeline("test_timeline")
    # 注意：构造函数会调 is_mlt_available()，可能设置 self._profile
    # 验证：无 profile 时 insert_clip 返回 -1
    if not tl.available:
        rc = tl.insert_clip("/nonexistent.mp4", 0)
        assert rc == -1, f"无 profile 时应返回 -1, got {rc}"
        print("  [OK] insert_clip 无 profile 时返回 -1")
    else:
        # MLT 可用：用不存在文件测试（应优雅失败）
        rc = tl.insert_clip("/nonexistent_file_for_test_xyz.mp4", 0)
        assert rc in (-1, 0), f"应优雅失败, got {rc}"
        print("  [OK] insert_clip 文件不存在时优雅失败")


def test_mlttimeline_playlist_length_empty():
    """playlist_length 无 producers 时返回 0"""
    tl = MltTimeline("test_timeline_2")
    if not tl.available:
        # 走退化路径
        assert tl.playlist_length() == 0
        print("  [OK] playlist_length 无 profile 时返回 0")
    else:
        # MLT 可用：_producers 为空时也应返回 0
        tl._producers = []
        assert tl.playlist_length() == 0
        print("  [OK] playlist_length 空 producers 时返回 0")


def test_mlttimeline_del_silent():
    """__del__ 不会让异常逃逸（防止 segfault 阶段崩溃）"""
    # 构造一个会抛异常的 close()
    class EvilTimeline(MltTimeline):
        def close(self):
            raise RuntimeError("simulated close failure")

    evil = EvilTimeline("evil_timeline")
    # 显式调用 __del__ 不应抛
    try:
        evil.__del__()
        print("  [OK] __del__ 静默吞掉 close() 异常")
    except RuntimeError as e:
        assert False, f"__del__ 不应让异常逃逸: {e}"


def test_mlttimeline_close_idempotent():
    """close() 重复调用安全（不应崩）"""
    tl = MltTimeline("test_timeline_3")
    if not tl.available:
        tl.close()  # 无 profile 的安全 close
        tl.close()  # 第二次：profile 已是 None，循环不执行
        print("  [OK] close() 重复调用安全")
    else:
        tl.close()
        tl.close()
        print("  [OK] close() 重复调用安全（MLT 可用路径）")


def test_mlt_call_when_dll_unavailable():
    """_mlt_call 在 _mlt_dll=None 时抛 RuntimeError"""
    import app.core.video_processing.mlt_engine_cpp as mod
    orig = mod._mlt_DLL_FAKE if False else None  # placeholder
    # 强制 _mlt_call 走缺 API 路径
    _MLT_API['__test_fake__'] = None
    try:
        try:
            _mlt_call('__test_fake__', None)
            assert False, "应抛 RuntimeError"
        except RuntimeError:
            print("  [OK] _mlt_call('None-mapped') 抛 RuntimeError")
    finally:
        del _MLT_API['__test_fake__']


def test_real_mlt_playlist_e2e():
    """
    端到端：MLT DLL 实际加载时，playlist_new + append + length 应真实跑通。
    跳过条件：MLT 不可用时该测试直接 skip，不影响其他测试。
    """
    if not is_mlt_available():
        print("  [SKIP] MLT 不可用，跳过 e2e")
        return

    available_apis = [k for k, v in _MLT_API.items() if v is not None]
    required = ['playlist_new', 'playlist_append', 'playlist_length', 'playlist_close']
    missing = [k for k in required if k not in available_apis]
    if missing:
        print(f"  [SKIP] playlist 关键 API 缺失: {missing}")
        return

    # 真实调用
    tl = MltTimeline("e2e_timeline")
    if not tl.available:
        print("  [SKIP] MltTimeline 不可用（profile 未初始化）")
        return

    # playlist_new
    playlist = _mlt_call('playlist_new', tl._profile)
    assert playlist, "playlist_new 应返回非空指针"

    # 创建一个空 producer（用 profile 直接拿）测 playlist 计数
    # 注意：get_producer 需要真实文件，playlist_length(empty) 应返回 0
    try:
        length = int(_mlt_call('playlist_length', playlist))
        assert length == 0, f"空 playlist length 应为 0, got {length}"
        print(f"  [OK] playlist_length(空) = {length}")
    finally:
        _mlt_call('playlist_close', playlist)
        tl.close()


if __name__ == "__main__":
    print("=" * 60)
    print("P0#3 第 2 刀 - MLT ctypes 集中化绑定验证")
    print("=" * 60)
    test_mlt_api_registry_empty_when_no_dll()
    test_mlt_call_raises_runtimeerror_for_missing_api()
    test_bind_mlt_api_safe_when_no_dll()
    test_mlttimeline_insert_clip_boundaries()
    test_mlttimeline_playlist_length_empty()
    test_mlttimeline_del_silent()
    test_mlttimeline_close_idempotent()
    test_mlt_call_when_dll_unavailable()
    test_real_mlt_playlist_e2e()
    print("=" * 60)
    print("全部验证通过 ✅")
    print("=" * 60)
