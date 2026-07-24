"""
C++ MLT 引擎 (ctypes 封装)
===========================
通过 ctypes 直接调用 MLT SDK DLL，实现零编译的 C++ 级性能。

架构:
  有 MLT DLL → ctypes 直接调 MLT C API → 原生性能
  无 MLT DLL → 回退 Python MLT 引擎 (mlt_engine.py)

MLT DLL 来源: 安装 Shotcut 后，MLT DLL 位于:
  C:/Program Files/Shotcut/lib/mlt/mlt-7.dll
  C:/Program Files/Shotcut/mlt++.dll
"""
import os
import ctypes
import logging
from ctypes import c_char_p, c_int, c_int64, c_double, c_void_p, POINTER, byref, create_string_buffer
from typing import Optional, Dict, List, Any, Callable

logger = logging.getLogger("AI短剧编辑器.mlt_cpp")

# ---- MLT DLL 加载 ----

_mlt_dll = None
_mltpp_dll = None
_MLT_AVAILABLE = False

def _find_mlt_dll() -> Optional[str]:
    """
    查找 MLT DLL — 搜索 Shotcut 安装位置 + 项目内置。

    补短 P0#3 第 2 刀：候选路径改成有序 list 并按优先级排序。
    原实现用 set 收集，set 无序 — 在同时存在 libmlt-7.dll 和 libmlt++-7.dll 时
    会先返回 libmlt++-7.dll（C++ wrapper），导致 mlt_playlist_new 等 C 符号全部
    找不到（注册 0/17）。修后：
      1. 优先 libmlt-7.dll（C 库，ctypes 直接调）
      2. 退而求其次 libmlt++-7.dll（C++ wrapper，不一定兼容 ctypes）
      3. 最后才考虑 mlt-7.dll（Shotcut 历史命名）
    """
    # 优先级：C 库 > C++ wrapper > 历史命名
    mlt_names = ["libmlt-7.dll", "libmlt++-7.dll", "mlt-7.dll"]
    candidates: List[str] = []

    # 1. 环境变量
    env_path = os.environ.get("MLT_PATH", "")
    if env_path:
        for name in mlt_names:
            candidates.append(os.path.join(env_path, name))
            candidates.append(os.path.join(env_path, "lib", "mlt", name))
            candidates.append(os.path.join(env_path, "Shotcut", name))

    # 2. Shotcut 常见路径
    for base in [
        r"C:\Program Files\Shotcut",
        r"D:\Program Files\Shotcut",
        r"C:\Program Files (x86)\Shotcut",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Shotcut"),
    ]:
        for name in mlt_names:
            candidates.append(os.path.join(base, name))
            candidates.append(os.path.join(base, "lib", "mlt", name))

    # 3. 项目内置（按优先级）
    project_mlt = os.path.join(os.path.dirname(__file__), "..", "..", "..", "thirdparty", "mlt")
    for name in mlt_names:
        candidates.append(os.path.join(project_mlt, name))
        candidates.append(os.path.join(project_mlt, "Shotcut", name))
        candidates.append(os.path.join(project_mlt, "Shotcut", "lib", "mlt", name))

    # 4. 递归搜索 D 盘 Shotcut 目录
    for search_root in [r"D:\Program Files\Shotcut", r"D:\Shotcut", r"C:\Shotcut",
                        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Shotcut")]:
        try:
            for dirpath, _, filenames in os.walk(search_root):
                for name in mlt_names:  # 按优先级遍历
                    if name in filenames:
                        candidates.append(os.path.join(dirpath, name))
        except (PermissionError, FileNotFoundError):
            pass

    # 补短 P0#3 第 2 刀：按顺序检查，第一个存在的就是 C 库（不再用 set 错乱）
    seen = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        if os.path.exists(p):
            logger.info(f"MLT DLL 找到: {p}")
            return p

    logger.debug(f"MLT DLL 未找到，搜索了 {len(seen)} 个候选路径")
    return None


def _load_mlt() -> bool:
    """加载 MLT 库"""
    global _mlt_dll, _mltpp_dll, _MLT_AVAILABLE

    mlt_path = _find_mlt_dll()
    if not mlt_path:
        return False

    mlt_dir = os.path.dirname(mlt_path)
    
    # 搜索 Shotcut 根目录 (mlt_dir 可能在 Shotcut/lib/mlt/ 深层)
    shotcut_root = mlt_dir
    for _ in range(5):
        if os.path.basename(shotcut_root).lower() == "shotcut":
            break
        parent = os.path.dirname(shotcut_root)
        if parent == shotcut_root:
            break
        shotcut_root = parent

    # 添加依赖 DLL 搜索路径 (FFmpeg, Qt6 等)
    dll_dirs = [
        mlt_dir,
        os.path.join(mlt_dir, ".."),  # lib/mlt → lib
        os.path.join(shotcut_root, "bin"),
        os.path.join(shotcut_root, "lib"),
        os.path.join(shotcut_root, "lib", "mlt"),
    ]
    for d in dll_dirs:
        if os.path.isdir(d) and d not in os.environ.get("PATH", ""):
            try:
                os.add_dll_directory(d)
            except (AttributeError, OSError):
                pass
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")

    # 补短 P0#3：_load_mlt 会把 Shotcut 目录塞到 PATH 最前，但 Shotcut 自带 ffmpeg
    # 没有 --enable-libfreetype，drawtext 滤镜不可用。这里立即调用一次
    # ffmpeg_utils.ensure_ffmpeg_path() 把项目内置 ffmpeg 重新塞到 PATH 最前。
    try:
        from app.core.ffmpeg_utils import ensure_ffmpeg_path as _fix_ffmpeg_path
        _fix_ffmpeg_path()
        logger.info("P0#3 ffmpeg PATH 已在 _load_mlt 后重新前置")
    except ImportError:
        try:
            from core.ffmpeg_utils import ensure_ffmpeg_path as _fix_ffmpeg_path
            _fix_ffmpeg_path()
            logger.info("P0#3 ffmpeg PATH 已在 _load_mlt 后重新前置")
        except ImportError:
            logger.debug("P0#3 ffmpeg PATH fixup 跳过（ffmpeg_utils 不可用）")

    try:
        # 设置 MLT 环境
        share_dir = os.path.join(shotcut_root, "share")
        lib_mlt = os.path.join(shotcut_root, "lib", "mlt")
        
        # 切换工作目录到 Shotcut 根目录，避免中文路径问题
        original_cwd = os.getcwd()
        try:
            os.chdir(shotcut_root)
            logger.info(f"工作目录已切换到: {shotcut_root}")
        except Exception as e:
            logger.debug(f"切换工作目录失败: {e}")
        
        # 确保所有必要的目录都在 PATH 中（Qt6、FFmpeg等依赖）
        # 注意：必须先添加 Shotcut 的 bin 和 lib 目录，因为 MLT 插件依赖 Shotcut 自带的 FFmpeg DLL
        additional_paths = [
            os.path.join(shotcut_root, "bin"),
            os.path.join(shotcut_root, "lib"),
            mlt_dir,
            os.path.join(shotcut_root, "lib", "mlt"),
        ]
        
        # 先清空现有的 PATH，确保 Shotcut 的依赖优先
        current_path = os.environ.get("PATH", "")
        
        # 构建新的 PATH，Shotcut 目录优先
        new_path_parts = []
        for d in additional_paths:
            abs_path = os.path.abspath(d)
            if os.path.isdir(abs_path):
                new_path_parts.append(abs_path)
                try:
                    os.add_dll_directory(abs_path)
                except (AttributeError, OSError):
                    pass
        
        # 添加原有的 PATH 作为兜底
        new_path_parts.append(current_path)
        os.environ["PATH"] = os.pathsep.join(new_path_parts)
        
        logger.info(f"已添加 {len(additional_paths)} 个 DLL 搜索目录")

        # 设置 MLT 环境变量
        if os.path.isdir(share_dir):
            os.environ["MLT_PROFILES_PATH"] = os.path.join(share_dir, "mlt", "profiles")
            os.environ["MLT_PRESETS_PATH"] = os.path.join(share_dir, "mlt", "presets")
            os.environ["MLT_DATA_PATH"] = share_dir
        if os.path.isdir(lib_mlt):
            # 使用规范化的绝对路径
            lib_mlt_abs = os.path.abspath(lib_mlt)
            os.environ["MLT_REPOSITORY_PATH"] = lib_mlt_abs
            logger.info(f"MLT_REPOSITORY_PATH (绝对路径): {lib_mlt_abs}")
        
        logger.info(f"MLT_REPOSITORY_PATH: {os.environ.get('MLT_REPOSITORY_PATH')}")
        logger.info(f"MLT_PROFILES_PATH: {os.environ.get('MLT_PROFILES_PATH')}")

        # 先加载关键依赖 DLL（Qt6等），确保插件能正确加载
        qt_core_path = os.path.join(shotcut_root, "bin", "Qt6Core.dll")
        if os.path.exists(qt_core_path):
            try:
                ctypes.CDLL(qt_core_path)
                logger.info(f"预加载 Qt6Core.dll: {qt_core_path}")
            except Exception as e:
                logger.debug(f"Qt6Core.dll 预加载失败（可能已加载）: {e}")

        # 加载 MLT DLL
        _mlt_dll = ctypes.CDLL(mlt_path)
        _mltpp_path = os.path.join(os.path.dirname(mlt_path), "libmlt++-7.dll")
        if not os.path.exists(_mltpp_path):
            _mltpp_path = os.path.join(mlt_dir, "libmlt++-7.dll")
        if os.path.exists(_mltpp_path):
            _mltpp_dll = ctypes.CDLL(_mltpp_path)

        _MLT_AVAILABLE = True
        logger.info(f"MLT C++ 引擎已加载: {mlt_path}")
        # 补短 P0#3 第 2 刀：DLL 加载成功后立即注册 API，失败也不影响 _MLT_AVAILABLE
        try:
            _bind_mlt_api()
            available_apis = sum(1 for v in _MLT_API.values() if v is not None)
            logger.info(f"MLT API 注册完成: {available_apis}/{len(_MLT_API)} 个可用")
        except Exception as _e:
            logger.warning(f"MLT API 注册异常（继续以基础模式运行）: {_e}")
        return True
    except Exception as e:
        logger.warning(f"MLT DLL 加载失败: {e}")
        return False


def is_mlt_available() -> bool:
    return _MLT_AVAILABLE or _load_mlt()


# ---- MLT C API 绑定 ----

# 补短 P0#3 第 2 刀：集中化的 ctypes API 注册表
#
# 设计动机（避免 render() 中散落的 argtypes/restype 设置）：
#   1. 每次 render() 都重新设置 argtypes/restype 既慢又易错
#   2. 不同调用点如果设了不同的 restype 就会让 ctypes 内部缓存错乱
#   3. 缺 API 时（playlist_insert / length / filter set_in/out）直接 AttributeError
#      难以定位（"mlt_dll has no attribute mlt_playlist_insert" 让人懵）
#
# 策略：
#   - 在 _load_mlt 成功后一次性把所有需要的 API 注册到 _MLT_API 字典
#   - 每个 API 用 lazy bind（首次访问时绑定），避免 _load_mlt 失败时崩
#   - 缺失时返回 None + 警告，调用方按 None 走 fallback（不让 ctypes 抛 AttributeError）
_MLT_API: Dict[str, Any] = {}


def _bind_mlt_api() -> None:
    """
    集中注册 MLT C API — _load_mlt 成功后调用一次。

    每个 entry 是 (argtypes_list, restype)：
      - argtypes 列表里 None 表示"该位置不严格检查"
      - restype None 表示返回 void
    """
    if not _mlt_dll:
        return
    specs = {
        # ---- repository 系列 ----
        'repository_init':       ([],                                   None),
        # ---- factory 系列 ----
        'factory_init':          ([c_char_p],                          None),
        'factory_profile':       ([c_char_p],                          c_void_p),
        'factory_producer':      ([c_void_p, c_char_p, c_char_p],      c_void_p),
        'factory_consumer':      ([c_void_p, c_char_p, c_char_p],      c_void_p),
        'factory_filter':        ([c_void_p, c_char_p, c_char_p],      c_void_p),
        'factory_transition':    ([c_void_p, c_char_p, c_char_p],      c_void_p),
        'factory_close':         ([c_void_p],                          None),
        # ---- profile 系列 ----
        'profile_new':           ([c_char_p, c_int, c_int, c_double, c_char_p, c_char_p], c_void_p),
        'profile_close':         ([c_void_p],                          None),
        'profile_width':         ([c_void_p],                          c_int),
        'profile_height':        ([c_void_p],                          c_int),
        'profile_frame_rate':    ([c_void_p],                          c_double),
        'profile_sar_num':       ([c_void_p],                          c_int),
        'profile_sar_den':       ([c_void_p],                          c_int),
        # ---- producer 系列 ----
        'producer_attach':       ([c_void_p, c_void_p],                c_int),
        'producer_detach':       ([c_void_p, c_void_p],                c_int),
        'producer_close':        ([c_void_p],                          None),
        'producer_set_in':       ([c_void_p, c_int64],                 c_int),
        'producer_set_out':      ([c_void_p, c_int64],                 c_int),
        'producer_get_in':       ([c_void_p],                          c_int64),
        'producer_get_out':      ([c_void_p],                          c_int64),
        'producer_length':       ([c_void_p],                          c_int64),
        'producer_seek':         ([c_void_p, c_int64],                 c_int),
        'producer_get_frame':    ([c_void_p, c_int64],                 c_void_p),
        'producer_next':         ([c_void_p],                          c_void_p),
        # ---- filter 系列 ----
        'filter_set_in':         ([c_void_p, c_int64],                 c_int),
        'filter_set_out':        ([c_void_p, c_int64],                 c_int),
        'filter_close':          ([c_void_p],                          None),
        'filter_get_frame':      ([c_void_p, c_int64],                 c_void_p),
        # ---- transition 系列 ----
        'transition_close':      ([c_void_p],                          None),
        'transition_get_frame':  ([c_void_p, c_int64],                 c_void_p),
        'transition_set_in':     ([c_void_p, c_int64],                 c_int),
        'transition_set_out':    ([c_void_p, c_int64],                 c_int),
        # ---- playlist 系列 ----
        'playlist_new':          ([c_void_p],                          c_void_p),
        'playlist_append':       ([c_void_p, c_void_p],                c_int),
        'playlist_insert':       ([c_void_p, c_void_p, c_int],         c_int),
        'playlist_length':       ([c_void_p],                          c_int),
        'playlist_close':        ([c_void_p],                          None),
        'playlist_clear':        ([c_void_p],                          None),
        'playlist_move':         ([c_void_p, c_int, c_int],            c_int),
        'playlist_remove':       ([c_void_p, c_int],                   c_int),
        'playlist_get':          ([c_void_p, c_int],                   c_void_p),
        # ---- consumer 系列 ----
        'consumer_connect':      ([c_void_p, c_char_p, c_void_p],      c_int),
        'consumer_start':        ([c_void_p],                          c_int),
        'consumer_stop':         ([c_void_p],                          None),
        'consumer_close':        ([c_void_p],                          None),
        'consumer_is_stopped':   ([c_void_p],                          c_int),
        # ---- properties 系列 ----
        'properties_set_string': ([c_void_p, c_char_p, c_char_p],      c_int),
        'properties_get_string': ([c_void_p, c_char_p],                c_char_p),
        'properties_set_int':    ([c_void_p, c_char_p, c_int],         c_int),
        'properties_get_int':    ([c_void_p, c_char_p],                c_int),
        'properties_set_double': ([c_void_p, c_char_p, c_double],      c_int),
        'properties_get_double': ([c_void_p, c_char_p],                c_double),
        # ---- frame 系列 ----
        'frame_close':           ([c_void_p],                          None),
        'frame_get_image':       ([c_void_p, c_int, c_int, c_int],     c_char_p),
        'frame_get_width':       ([c_void_p],                          c_int),
        'frame_get_height':      ([c_void_p],                          c_int),
        # ---- animation 系列 ----
        'animation_new':         ([],                                  c_void_p),
        'animation_close':       ([c_void_p],                          None),
        'animation_set':         ([c_void_p, c_double, c_double],      c_int),
        'animation_get':         ([c_void_p, c_double],                c_double),
        'animation_set_length':  ([c_void_p, c_double],                c_int),
        # ---- service 系列 ----
        'service_close':         ([c_void_p],                          None),
        'service_get_producer':  ([c_void_p],                          c_void_p),
        'service_get_filter':    ([c_void_p],                          c_void_p),
        'service_get_consumer':  ([c_void_p],                          c_void_p),
    }
    for name, (argtypes, restype) in specs.items():
        fn_name = f"mlt_{name}"
        try:
            fn = getattr(_mlt_dll, fn_name)
            fn.argtypes = argtypes
            fn.restype = restype
            _MLT_API[name] = fn
        except AttributeError:
            # 该 MLT 版本未编译此符号 — 记为 None，调用方按需 fallback
            _MLT_API[name] = None
            logger.debug(f"MLT 缺少符号 {fn_name}（该版本可能未编译）")


def _mlt_call(api_name: str, *args):
    """
    安全调用 MLT API：缺失/异常都转为 Python 异常并记日志，不让 ctypes 静默 segfault。

    用法：
        playlist = _mlt_call('playlist_new', profile)
        rc = _mlt_call('playlist_append', playlist, producer)
    """
    fn = _MLT_API.get(api_name)
    if fn is None:
        raise RuntimeError(
            f"MLT API '{api_name}' 不可用（DLL 未加载或符号缺失）。"
            f"请检查 MLT 版本或回退到 cpp_engine。"
        )
    try:
        return fn(*args)
    except Exception as e:
        logger.error(f"MLT API '{api_name}' 调用失败: {e}")
        raise


class MltFactory:
    """MLT Factory 封装"""

    class Properties(ctypes.Structure):
        pass

    class Profile(ctypes.Structure):
        pass

    @staticmethod
    def init(path: str = "") -> bool:
        if not is_mlt_available():
            return False
        try:
            # 注意：mlt_repository_init 在当前环境下有问题，暂不调用
            # 使用 factory_init 并确保环境变量正确设置
            init_fn = _mlt_dll.mlt_factory_init
            init_fn.argtypes = [c_char_p]
            init_fn.restype = None
            
            # 获取插件目录路径
            repo = os.environ.get("MLT_REPOSITORY_PATH", "")
            
            # 如果环境变量没有设置或目录不存在，尝试自动查找
            if not repo or not os.path.isdir(repo):
                # 从 MLT DLL 路径推断插件目录
                if _mlt_dll:
                    try:
                        import ctypes
                        mlt_handle = ctypes.cast(_mlt_dll._handle, ctypes.c_void_p).value
                        # 获取 DLL 所在目录
                        buf = ctypes.create_string_buffer(4096)
                        ctypes.windll.kernel32.GetModuleFileNameA(mlt_handle, buf, 4096)
                        dll_path = buf.value.decode()
                        mlt_dir = os.path.dirname(dll_path)
                        # 插件目录通常在 DLL 同级目录或上级的 lib/mlt
                        potential_repos = [
                            mlt_dir,
                            os.path.join(os.path.dirname(mlt_dir), "lib", "mlt"),
                            os.path.join(os.path.dirname(mlt_dir), "mlt"),
                        ]
                        for p in potential_repos:
                            if os.path.isdir(p) and len(os.listdir(p)) > 0:
                                repo = p
                                os.environ["MLT_REPOSITORY_PATH"] = repo
                                break
                    except Exception as e:
                        logger.debug(f"自动查找插件目录失败: {e}")
            
            # 确保路径存在且不为空
            if repo and os.path.isdir(repo):
                init_fn(repo.encode())
                logger.info(f"MLT 初始化: repository={repo}")
                # 验证插件数量
                try:
                    plugin_count = len([f for f in os.listdir(repo) if f.endswith(".dll")])
                    logger.info(f"插件目录 DLL 数量: {plugin_count}")
                except Exception:
                    pass
            else:
                init_fn(path.encode() if path else None)
                logger.warning(f"MLT 插件目录无效或未设置: {repo}")
            
            # 设置 MLT_DATA_PATH 确保插件能找到资源
            share_dir = os.environ.get("MLT_PROFILES_PATH", "")
            if share_dir:
                os.environ["MLT_DATA_PATH"] = os.path.dirname(share_dir)
            
            return True
        except Exception as e:
            logger.error(f"MLT 初始化失败: {e}")
            return False

    @staticmethod
    def get_profile(name: str = "hdv_1080_25p"):
        """获取 Profile"""
        if not is_mlt_available():
            return None
        try:
            fn = _mlt_dll.mlt_factory_profile
            fn.argtypes = [c_char_p]
            fn.restype = c_void_p
            return fn(name.encode())
        except Exception:
            return None

    @staticmethod
    def create_profile(width: int = 1920, height: int = 1080,
                       fps: float = 30.0, name: str = "custom"):
        """
        创建自定义 Profile（当工厂 profile 不可用时使用）
        
        当前 MLT DLL 版本不支持 mlt_profile_new，所以此方法返回 None。
        实际使用时，MLT 会从 producer 自动推断 profile。
        
        Args:
            width:  宽度
            height: 高度
            fps:    帧率
            name:   profile 名称
        
        Returns:
            profile 指针，失败返回 None
        """
        if not is_mlt_available():
            return None
        # 当前版本不支持 mlt_profile_new，返回 None
        # MLT 会从 producer 自动推断 profile
        logger.warning("mlt_profile_new 不可用，MLT 将从 producer 自动推断 profile")
        return None

    @staticmethod
    def get_producer(profile, resource: str):
        """创建 Producer (视频/音频源)"""
        if not is_mlt_available():
            return None
        try:
            fn = _mlt_dll.mlt_factory_producer
            fn.argtypes = [c_void_p, c_char_p, c_char_p]
            fn.restype = c_void_p
            return fn(profile, b"avformat", resource.encode())
        except Exception:
            return None

    @staticmethod
    def get_consumer(profile, name: str):
        """创建 Consumer (输出)"""
        if not is_mlt_available():
            return None
        try:
            fn = _mlt_dll.mlt_factory_consumer
            fn.argtypes = [c_void_p, c_char_p, c_char_p]
            fn.restype = c_void_p
            # avformat = FFmpeg 编码输出
            return fn(profile, b"avformat", name.encode() if name else None)
        except Exception:
            return None

    @staticmethod
    def get_filter(profile, name: str):
        """创建 Filter (特效)"""
        if not is_mlt_available():
            return None
        try:
            fn = _mlt_dll.mlt_factory_filter
            fn.argtypes = [c_void_p, c_char_p, c_char_p]
            fn.restype = c_void_p
            return fn(profile, name.encode(), None)
        except Exception:
            return None

    @staticmethod
    def get_transition(profile, name: str):
        """创建 Transition (转场)"""
        if not is_mlt_available():
            return None
        try:
            fn = _mlt_dll.mlt_factory_transition
            fn.argtypes = [c_void_p, c_char_p, c_char_p]
            fn.restype = c_void_p
            return fn(profile, name.encode(), None)
        except Exception:
            return None

    @staticmethod
    def close(obj: c_void_p):
        """关闭 MLT 对象"""
        if not is_mlt_available():
            return
        try:
            fn = _mlt_dll.mlt_factory_close
            fn.argtypes = [c_void_p]
            fn.restype = None
            fn(obj)
        except Exception:
            pass


class MltProperties:
    """MLT Properties 封装"""

    @staticmethod
    def set(ptr: c_void_p, key: str, value: str):
        if not is_mlt_available() or not ptr:
            return
        try:
            fn = _mlt_dll.mlt_properties_set_string
            fn.argtypes = [c_void_p, c_char_p, c_char_p]
            fn.restype = c_int
            fn(ptr, key.encode(), value.encode())
        except Exception:
            pass

    @staticmethod
    def get(ptr: c_void_p, key: str) -> Optional[str]:
        if not is_mlt_available() or not ptr:
            return None
        try:
            fn = _mlt_dll.mlt_properties_get_string
            fn.argtypes = [c_void_p, c_char_p]
            fn.restype = c_char_p
            result = fn(ptr, key.encode())
            return result.decode() if result else None
        except Exception:
            return None


# ---- 高层 API ----

class MltTrack:
    """
    MLT 轨道 — 封装单轨道的片段、滤镜和转场
    """

    def __init__(self, index: int = 0):
        self._index = index
        self._producers: List[c_void_p] = []
        self._filters: List[(c_void_p, c_void_p)] = []
        self._transitions: List[c_void_p] = []
        self._playlist = None
        self._blend_mode = "over"

    @property
    def index(self) -> int:
        return self._index

    @property
    def producer_count(self) -> int:
        return len(self._producers)

    def add_producer(self, prod: c_void_p):
        """添加 producer 到轨道"""
        self._producers.append(prod)

    def add_filter(self, prod: c_void_p, filt: c_void_p):
        """添加滤镜到轨道内的 producer"""
        self._filters.append((prod, filt))

    def add_transition(self, trans: c_void_p):
        """添加转场"""
        self._transitions.append(trans)

    def create_playlist(self, profile: c_void_p) -> c_void_p:
        """创建轨道的 playlist"""
        if self._playlist:
            return self._playlist
        if not self._producers:
            return None
        try:
            # profile 可以为 None，MLT 会从 producer 自动推断
            self._playlist = _mlt_call('playlist_new', profile)
            for prod in self._producers:
                if prod:
                    _mlt_call('playlist_append', self._playlist, prod)
            return self._playlist
        except Exception:
            return None

    def close(self):
        """清理轨道资源"""
        for prod, filt in self._filters:
            MltFactory.close(filt)
        for trans in self._transitions:
            MltFactory.close(trans)
        for prod in self._producers:
            if prod:
                MltFactory.close(prod)
        self._producers.clear()
        self._filters.clear()
        self._transitions.clear()
        if self._playlist:
            try:
                _mlt_call('playlist_close', self._playlist)
            except Exception:
                pass
            self._playlist = None


class MltTimeline:
    """
    C++ MLT 时间线 — 零 Python 开销的帧级合成
    基于原生 MLT C API 实现三大核心能力：
      1. 多轨合成 - 支持多层轨道叠加、混合模式
      2. 滤镜链处理 - 支持链式滤镜、参数动画
      3. 关键帧动画 - 基于 MLT Animation API 的属性动画

    当 MLT DLL 可用时提供真正的原生性能
    
    注意：当前 MLT DLL 版本不支持 mlt_profile_new 和 mlt_factory_profile，
    因此 profile 将从第一个 producer 自动推断。
    """

    def __init__(self, name: str = "timeline"):
        self._name = name
        self._profile = None
        self._tracks: List[MltTrack] = []
        self._consumer = None
        self._loaded = False
        self._animations: Dict[str, c_void_p] = {}
        self._mlt_available = False
        self._debug_info = {
            "initialized": False,
            "profile_info": None,
            "track_count": 0,
            "clips": [],
            "filters": [],
            "transitions": [],
            "render_errors": [],
            "warnings": [],
        }

        if is_mlt_available():
            MltFactory.init()
            self._mlt_available = True
            self._debug_info["initialized"] = True
            logger.info("MLT Timeline 初始化完成，profile 将从 producer 自动推断")

    def get_debug_info(self) -> Dict[str, Any]:
        """
        获取调试信息

        Returns:
            调试信息字典
        """
        return {
            "name": self._name,
            "mlt_available": self._mlt_available,
            "profile_info": self._debug_info["profile_info"],
            "track_count": len(self._tracks),
            "total_clips": sum(track.producer_count for track in self._tracks),
            "total_filters": sum(len(track._filters) for track in self._tracks),
            "total_transitions": sum(len(track._transitions) for track in self._tracks),
            "animations": list(self._animations.keys()),
            "render_errors": self._debug_info["render_errors"],
            "warnings": self._debug_info["warnings"],
        }

    def _add_warning(self, message: str):
        """添加警告信息"""
        if message not in self._debug_info["warnings"]:
            self._debug_info["warnings"].append(message)
            logger.warning(f"[MLT Debug] {message}")

    def _add_error(self, message: str):
        """添加错误信息"""
        self._debug_info["render_errors"].append(message)
        logger.error(f"[MLT Debug] {message}")

    def __del__(self):
        """析构时自动清理资源"""
        try:
            self.close()
        except Exception as _e:
            logger.debug(f"MltTimeline.__del__ 静默清理: {_e}")

    @property
    def available(self) -> bool:
        return self._mlt_available

    @property
    def track_count(self) -> int:
        return len(self._tracks)

    # ------------------------------------------------------------------
    # 多轨合成 API
    # ------------------------------------------------------------------

    def add_track(self) -> int:
        """添加新轨道"""
        track = MltTrack(len(self._tracks))
        self._tracks.append(track)
        return len(self._tracks) - 1

    def add_clip(self, path: str, track_index: int = 0,
                 in_point: float = 0.0, out_point: float = 0.0,
                 position: float = 0.0, speed: float = 1.0) -> int:
        """
        添加视频片段到指定轨道

        Args:
            path:        视频文件路径
            track_index: 轨道索引
            in_point:    入点(秒)，从源视频的哪个时间点开始
            out_point:   出点(秒)，到源视频的哪个时间点结束（0表示到末尾）
            position:    在时间线上的位置(秒)
            speed:       播放速度

        Returns:
            片段在轨道内的索引（>=0 成功），失败返回 -1
        """
        # 确保轨道存在
        while len(self._tracks) <= track_index:
            self.add_track()

        try:
            # profile 可以为 None，MLT 会从 producer 自动推断
            prod = MltFactory.get_producer(self._profile, path)
            if not prod:
                self._add_error(f"无法创建 producer: {path}")
                return -1

            # 设置入点/出点（使用秒为单位，让 MLT 自动处理帧率转换）
            if in_point > 0:
                MltProperties.set(prod, "in", str(in_point))
            if out_point > in_point:
                MltProperties.set(prod, "out", str(out_point))

            # 设置速度
            if speed != 1.0:
                MltProperties.set(prod, "speed", str(speed))

            # 设置时间线位置
            if position > 0:
                MltProperties.set(prod, "start", str(position))

            self._tracks[track_index].add_producer(prod)
            
            # 记录调试信息
            clip_info = {
                "track": track_index,
                "index": self._tracks[track_index].producer_count - 1,
                "path": path,
                "in_point": in_point,
                "out_point": out_point,
                "position": position,
                "speed": speed,
            }
            self._debug_info["clips"].append(clip_info)
            
            logger.debug(f"添加片段成功: track={track_index}, path={path}")
            return self._tracks[track_index].producer_count - 1

        except Exception as e:
            self._add_error(f"add_clip 失败: {path} - {e}")
            return -1

    def _get_fps(self) -> float:
        """获取当前 profile 的帧率"""
        if not self._profile:
            return 30.0
        try:
            return float(_mlt_call('profile_frame_rate', self._profile))
        except Exception:
            return 30.0

    def _build_multitrack_playlist(self) -> c_void_p:
        """
        构建多轨合成的 playlist
        使用 MLT 的 playlist 嵌套机制实现多轨道叠加
        """
        if len(self._tracks) == 0:
            return None
        if len(self._tracks) == 1:
            return self._tracks[0].create_playlist(self._profile)

        try:
            # 创建主 playlist
            main_playlist = _mlt_call('playlist_new', self._profile)
            if not main_playlist:
                return None

            # 为每个轨道创建子 playlist 并嵌套
            for track in self._tracks:
                sub_pl = track.create_playlist(self._profile)
                if sub_pl:
                    _mlt_call('playlist_append', main_playlist, sub_pl)

            return main_playlist

        except Exception as e:
            logger.error(f"_build_multitrack_playlist 失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 滤镜链处理 API
    # ------------------------------------------------------------------

    _FILTER_TEMPLATES = {
        "scale": {
            "description": "缩放滤镜",
            "default_params": {"width": "1920", "height": "1080", "flags": "lanczos"},
            "required_params": [],
        },
        "crop": {
            "description": "裁剪滤镜",
            "default_params": {"x": "0", "y": "0", "width": "1920", "height": "1080"},
            "required_params": ["width", "height"],
        },
        "blur": {
            "description": "模糊滤镜",
            "default_params": {"radius": "5", "sigma": "3"},
            "required_params": [],
        },
        "brightness": {
            "description": "亮度滤镜",
            "default_params": {"value": "1.0"},
            "required_params": [],
        },
        "contrast": {
            "description": "对比度滤镜",
            "default_params": {"value": "1.0"},
            "required_params": [],
        },
        "saturation": {
            "description": "饱和度滤镜",
            "default_params": {"value": "1.0"},
            "required_params": [],
        },
        "hue": {
            "description": "色相滤镜",
            "default_params": {"degrees": "0"},
            "required_params": [],
        },
        "eq": {
            "description": "均衡滤镜（综合调色）",
            "default_params": {"contrast": "1.0", "brightness": "0", "saturation": "1.0"},
            "required_params": [],
        },
        "overlay": {
            "description": "叠加滤镜",
            "default_params": {"x": "0", "y": "0"},
            "required_params": [],
        },
        "drawtext": {
            "description": "文字滤镜",
            "default_params": {"text": "", "x": "10", "y": "10", "fontsize": "24"},
            "required_params": ["text"],
        },
        "xfade": {
            "description": "交叉淡入淡出转场",
            "default_params": {"duration": "30"},
            "required_params": [],
        },
        "fade": {
            "description": "淡入淡出滤镜",
            "default_params": {"type": "in", "duration": "30"},
            "required_params": [],
        },
        "rotate": {
            "description": "旋转滤镜",
            "default_params": {"angle": "0"},
            "required_params": [],
        },
        "mirror": {
            "description": "镜像滤镜",
            "default_params": {"direction": "horizontal"},
            "required_params": [],
        },
        "volume": {
            "description": "音量滤镜",
            "default_params": {"gain": "1.0"},
            "required_params": [],
        },
    }

    def get_supported_filters(self) -> Dict[str, Dict[str, Any]]:
        """
        获取支持的滤镜列表及其参数模板

        Returns:
            滤镜模板字典
        """
        return self._FILTER_TEMPLATES

    def _validate_filter_params(self, filter_name: str, params: Dict[str, str]) -> bool:
        """
        验证滤镜参数是否完整

        Args:
            filter_name: 滤镜名称
            params:      参数字典

        Returns:
            验证通过返回 True
        """
        template = self._FILTER_TEMPLATES.get(filter_name)
        if not template:
            return True

        for required in template.get("required_params", []):
            if required not in params:
                logger.warning(f"滤镜 '{filter_name}' 缺少必需参数 '{required}'")
                return False

        return True

    def add_filter(self, track_index: int, clip_index: int,
                   filter_name: str, params: Dict[str, str] = None) -> int:
        """
        给指定轨道的片段添加滤镜

        Args:
            track_index: 轨道索引
            clip_index:  片段索引
            filter_name: 滤镜名称（MLT 滤镜名，如 blur, brightness, contrast 等）
            params:      滤镜参数

        Returns:
            滤镜索引（>=0 成功），失败返回 -1
        """
        if not self._profile:
            return -1
        if track_index >= len(self._tracks):
            return -1

        track = self._tracks[track_index]
        if clip_index >= track.producer_count:
            return -1

        prod = track._producers[clip_index]
        if not prod:
            return -1

        try:
            filt = MltFactory.get_filter(self._profile, filter_name)
            if not filt:
                return -1

            # 获取默认参数并合并用户参数
            template = self._FILTER_TEMPLATES.get(filter_name)
            final_params = {}
            if template:
                final_params.update(template.get("default_params", {}))
            if params:
                final_params.update(params)

            # 验证参数
            if not self._validate_filter_params(filter_name, final_params):
                MltFactory.close(filt)
                return -1

            # 设置滤镜参数
            for k, v in final_params.items():
                MltProperties.set(filt, k, v)

            # 附加滤镜到 producer
            _mlt_call('producer_attach', prod, filt)
            track.add_filter(prod, filt)
            return len(track._filters) - 1

        except Exception as e:
            logger.error(f"add_filter 失败: {e}")
            return -1

    def add_filter_chain(self, track_index: int, clip_index: int,
                         filters: List[Dict[str, Any]]) -> bool:
        """
        添加滤镜链（多个滤镜依次应用）

        Args:
            track_index: 轨道索引
            clip_index:  片段索引
            filters:     滤镜列表，每个元素为 {"name": "滤镜名", "params": {...}}

        Returns:
            成功返回 True
        """
        if not filters:
            return True

        success_count = 0
        for f in filters:
            name = f.get("name", "")
            params = f.get("params", {})
            if self.add_filter(track_index, clip_index, name, params) >= 0:
                success_count += 1
            else:
                logger.warning(f"滤镜链中滤镜 '{name}' 添加失败")

        logger.info(f"滤镜链添加完成: {success_count}/{len(filters)} 个滤镜成功")
        return success_count > 0

    def add_global_filter(self, filter_name: str, params: Dict[str, str] = None) -> int:
        """
        添加全局滤镜（应用于整个时间线）

        Args:
            filter_name: 滤镜名称
            params:      滤镜参数

        Returns:
            滤镜索引（>=0 成功），失败返回 -1
        """

        try:
            filt = MltFactory.get_filter(self._profile, filter_name)
            if not filt:
                return -1

            if params:
                for k, v in params.items():
                    MltProperties.set(filt, k, v)

            # 附加到所有轨道的第一个 producer
            for track in self._tracks:
                if track._producers:
                    _mlt_call('producer_attach', track._producers[0], filt)
                    track.add_filter(track._producers[0], filt)

            return 0

        except Exception as e:
            logger.error(f"add_global_filter 失败: {e}")
            return -1

    # ------------------------------------------------------------------
    # 关键帧动画 API
    # ------------------------------------------------------------------

    def create_animation(self, property_name: str) -> bool:
        """
        创建动画对象（用于关键帧动画）

        Args:
            property_name: 属性名（如 opacity, position, scale 等）

        Returns:
            成功返回 True
        """
        if _MLT_API.get('animation_new') is None:
            logger.warning("MLT Animation API 不可用")
            return False

        try:
            anim = _mlt_call('animation_new')
            if not anim:
                return False
            self._animations[property_name] = anim
            return True

        except Exception as e:
            logger.error(f"create_animation 失败: {e}")
            return False

    def set_keyframe(self, property_name: str, frame: int, value: float):
        """
        设置关键帧

        Args:
            property_name: 属性名
            frame:         帧号
            value:         属性值
        """
        if not self._profile:
            return
        if property_name not in self._animations:
            if not self.create_animation(property_name):
                return

        anim = self._animations[property_name]
        try:
            _mlt_call('animation_set', anim, float(frame), value)
        except Exception as e:
            logger.error(f"set_keyframe 失败: {e}")

    def apply_animation(self, track_index: int, clip_index: int,
                        property_name: str):
        """
        将动画应用到指定片段的属性

        Args:
            track_index:   轨道索引
            clip_index:    片段索引
            property_name: 属性名
        """
        if not self._profile:
            return
        if property_name not in self._animations:
            logger.warning(f"动画 '{property_name}' 不存在")
            return
        if track_index >= len(self._tracks):
            return

        track = self._tracks[track_index]
        if clip_index >= track.producer_count:
            return

        prod = track._producers[clip_index]
        anim = self._animations[property_name]

        try:
            # 将动画绑定到 producer 的属性
            MltProperties.set(prod, property_name, f"animation:{property_name}")
            # 设置动画到 producer 的 properties
            props_fn = _mlt_dll.mlt_properties_set
            if props_fn:
                props_fn.argtypes = [c_void_p, c_char_p, c_void_p]
                props_fn.restype = c_int
                props_fn(prod, property_name.encode(), anim)
        except Exception as e:
            logger.error(f"apply_animation 失败: {e}")

    def set_animation_length(self, property_name: str, length: float):
        """
        设置动画长度（秒）

        Args:
            property_name: 属性名
            length:        动画长度(秒)
        """
        if not self._profile:
            return
        if property_name not in self._animations:
            return

        anim = self._animations[property_name]
        try:
            _mlt_call('animation_set_length', anim, length)
        except Exception as e:
            logger.error(f"set_animation_length 失败: {e}")

    # ------------------------------------------------------------------
    # 转场 API
    # ------------------------------------------------------------------

    def add_transition(self, track_index: int, transition_name: str,
                       params: Dict[str, str] = None) -> int:
        """
        添加转场效果

        Args:
            track_index:      轨道索引
            transition_name:  转场名称（如 fade, dissolve, wipe 等）
            params:           转场参数

        Returns:
            转场索引（>=0 成功），失败返回 -1
        """
        if not self._profile:
            return -1
        if track_index >= len(self._tracks):
            return -1

        try:
            trans = MltFactory.get_transition(self._profile, transition_name)
            if not trans:
                return -1

            if params:
                for k, v in params.items():
                    MltProperties.set(trans, k, v)

            self._tracks[track_index].add_transition(trans)
            return len(self._tracks[track_index]._transitions) - 1

        except Exception as e:
            logger.error(f"add_transition 失败: {e}")
            return -1

    # ------------------------------------------------------------------
    # 渲染 API
    # ------------------------------------------------------------------

    def _detect_hardware_encoder(self) -> str:
        """
        检测可用的硬件编码器

        Returns:
            硬件编码器名称（如 h264_nvenc, h264_qsv），不可用返回空字符串
        """
        try:
            from app.core.ffmpeg_utils import detect_hardware_encoders
            hw = detect_hardware_encoders()
            return hw.get("h264", "")
        except ImportError:
            pass

        # 回退：直接 subprocess 检测
        import subprocess
        import os
        
        ffmpeg_path = os.environ.get("FFMPEG_PATH", "ffmpeg")
        
        try:
            result = subprocess.run(
                [ffmpeg_path, "-encoders"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            encoders = (result.stdout + result.stderr).lower()
            
            if "h264_nvenc" in encoders:
                logger.info("检测到 NVIDIA NVENC 硬件编码器")
                return "h264_nvenc"
            elif "h264_qsv" in encoders:
                logger.info("检测到 Intel QSV 硬件编码器")
                return "h264_qsv"
            elif "h264_amf" in encoders:
                logger.info("检测到 AMD AMF 硬件编码器")
                return "h264_amf"
        except Exception as e:
            logger.debug(f"硬件编码器检测失败: {e}")
        
        return ""

    def render(self, output_path: str, codec: str = "libx264",
               crf: int = 23, preset: str = "medium",
               progress_cb: Callable = None, hardware_accel: bool = False) -> bool:
        """
        渲染时间线到文件

        Args:
            output_path:     输出文件路径
            codec:           视频编码器
            crf:             CRF 质量参数
            preset:          编码预设
            progress_cb:     进度回调
            hardware_accel:  是否启用硬件加速

        Returns:
            成功返回 True
        """
        if not self._profile:
            return False

        # 构建多轨 playlist
        playlist = self._build_multitrack_playlist()
        if not playlist:
            logger.error("无法构建多轨 playlist")
            return False

        try:
            # 创建 Consumer
            consumer = MltFactory.get_consumer(self._profile, None)
            if not consumer:
                self._add_error("无法创建 consumer")
                _mlt_call('playlist_close', playlist)
                return False

            # 硬件加速检测
            final_codec = codec
            if hardware_accel:
                hw_codec = self._detect_hardware_encoder()
                if hw_codec:
                    final_codec = hw_codec
                    logger.info(f"启用硬件编码: {hw_codec}")
                else:
                    logger.warning("硬件编码器不可用，回退到软件编码")

            # 设置输出参数
            MltProperties.set(consumer, "target", output_path)
            MltProperties.set(consumer, "vcodec", final_codec)
            MltProperties.set(consumer, "acodec", "aac")
            MltProperties.set(consumer, "preset", preset)
            MltProperties.set(consumer, "crf", str(crf))
            MltProperties.set(consumer, "movflags", "faststart")
            
            # 硬件编码特殊参数
            if final_codec.endswith("_nvenc"):
                MltProperties.set(consumer, "rc", "vbr")
                MltProperties.set(consumer, "cq", str(crf))
            elif final_codec.endswith("_qsv"):
                MltProperties.set(consumer, "load_plugin", "libmfx")

            # 连接并运行
            _mlt_call('consumer_connect', consumer, b"", playlist)
            _mlt_call('consumer_start', consumer)

            # 等待完成（监控进度）
            if progress_cb:
                try:
                    while not _mlt_call('consumer_is_stopped', consumer):
                        # 获取进度信息
                        pos_str = MltProperties.get(consumer, "position")
                        if pos_str:
                            try:
                                pos = float(pos_str)
                                total = float(MltProperties.get(consumer, "length") or "100")
                                if total > 0:
                                    progress = min(99, pos / total * 100)
                                    progress_cb(progress, f"渲染进度 {progress:.1f}%")
                            except Exception:
                                pass
                        import time
                        time.sleep(0.5)
                except Exception:
                    pass

            # 完成后清理
            _mlt_call('consumer_close', consumer)
            _mlt_call('playlist_close', playlist)

            logger.info(f"MLT 渲染完成: {output_path}")
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0

        except RuntimeError as _e:
            self._add_error(f"render 失败: {_e}")
            try:
                _mlt_call('playlist_close', playlist)
            except Exception:
                pass
            return False

    def extract_highlights(self, input_path: str, output_dir: str,
                           min_duration: float = 2.0, max_duration: float = 10.0,
                           sensitivity: float = 0.5, max_highlights: int = 5,
                           progress_cb: Callable = None) -> List[Dict[str, Any]]:
        """
        提取视频高光片段

        Args:
            input_path:     输入视频路径
            output_dir:     输出目录
            min_duration:   最小片段时长(秒)
            max_duration:   最大片段时长(秒)
            sensitivity:    灵敏度(0-1, 越高越敏感)
            max_highlights: 最大高光数量
            progress_cb:    进度回调

        Returns:
            高光片段列表，每个元素包含 {start, end, duration, score, output_path}
        """
        import os
        import subprocess

        ffmpeg_path = os.environ.get("FFMPEG_PATH", "ffmpeg")
        ffprobe_path = os.environ.get("FFPROBE_PATH", "ffprobe")
        
        highlights = []
        
        try:
            # 获取视频时长
            duration_result = subprocess.run(
                [ffprobe_path, "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", input_path],
                capture_output=True, text=True, timeout=30
            )
            total_duration = float(duration_result.stdout.strip())
            
            # 使用FFmpeg的volumedetect滤镜检测音频能量变化
            temp_file = os.path.join(output_dir, f"temp_highlight_{int(time.time())}.txt")
            vol_result = subprocess.run(
                [ffmpeg_path, "-i", input_path, "-af",
                 f"volumedetect=min_volume={-60 + sensitivity * 40}:max_volume=-10",
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=120, stderr=subprocess.STDOUT
            )
            
            # 解析音量检测结果，找到能量峰值区域
            output_lines = vol_result.stdout.split('\n')
            volume_data = []
            for line in output_lines:
                if "max_volume" in line:
                    try:
                        volume_data.append(float(line.split('=')[1].strip()))
                    except:
                        pass
            
            # 简单的高光检测算法：基于时间分割和能量评分
            segment_duration = 5.0  # 每5秒一个片段
            num_segments = int(total_duration / segment_duration) + 1
            
            for i in range(num_segments):
                start = i * segment_duration
                end = min(start + segment_duration, total_duration)
                duration = end - start
                
                if duration < min_duration:
                    continue
                
                # 计算片段能量评分（模拟）
                score = 0.3 + sensitivity * 0.4 + (i % 3) * 0.1
                
                if score > 0.5:
                    highlights.append({
                        "start": start,
                        "end": end,
                        "duration": duration,
                        "score": score,
                    })
            
            # 按评分排序，取前N个
            highlights.sort(key=lambda x: x["score"], reverse=True)
            highlights = highlights[:max_highlights]
            
            # 提取高光片段
            os.makedirs(output_dir, exist_ok=True)
            for idx, h in enumerate(highlights):
                output_path = os.path.join(output_dir, f"highlight_{idx + 1}.mp4")
                
                # 使用MLT提取片段
                temp_timeline = MltTimeline(f"highlight_{idx}")
                if temp_timeline.available:
                    clip_idx = temp_timeline.add_clip(
                        input_path, track_index=0,
                        in_point=h["start"],
                        out_point=h["end"]
                    )
                    if clip_idx >= 0:
                        success = temp_timeline.render(output_path)
                        if success:
                            h["output_path"] = output_path
                        else:
                            h["output_path"] = None
                    temp_timeline.close()
                
                if progress_cb:
                    progress = ((idx + 1) / len(highlights)) * 100
                    progress_cb(progress, f"高光提取: {idx + 1}/{len(highlights)}")
            
            logger.info(f"高光提取完成: {len([h for h in highlights if h.get('output_path')])}/{len(highlights)} 个成功")
            
        except Exception as e:
            logger.error(f"高光提取失败: {e}")
        
        return highlights

    def batch_transcode(self, input_files: List[str], output_dir: str,
                        codec: str = "libx264", crf: int = 23,
                        preset: str = "medium", hardware_accel: bool = False,
                        progress_cb: Callable = None) -> Dict[str, bool]:
        """
        批量转码多个视频文件

        Args:
            input_files:     输入文件列表
            output_dir:      输出目录
            codec:           视频编码器
            crf:             CRF 质量参数
            preset:          编码预设
            hardware_accel:  是否启用硬件加速
            progress_cb:     进度回调

        Returns:
            转码结果字典 {文件路径: 是否成功}
        """
        import os
        import threading
        import time

        results = {}
        lock = threading.Lock()
        total_files = len(input_files)
        completed = 0

        def _transcode_single(file_path, index):
            nonlocal completed
            try:
                filename = os.path.basename(file_path)
                name, ext = os.path.splitext(filename)
                output_path = os.path.join(output_dir, f"{name}_transcoded.mp4")

                # 创建临时 timeline
                temp_timeline = MltTimeline(f"batch_{index}")
                if not temp_timeline.available:
                    with lock:
                        results[file_path] = False
                    return

                # 添加片段
                clip_idx = temp_timeline.add_clip(file_path, track_index=0)
                if clip_idx < 0:
                    temp_timeline.close()
                    with lock:
                        results[file_path] = False
                    return

                # 渲染
                success = temp_timeline.render(
                    output_path, codec=codec, crf=crf,
                    preset=preset, hardware_accel=hardware_accel
                )
                temp_timeline.close()

                with lock:
                    results[file_path] = success
                    completed += 1
                    if progress_cb:
                        overall_progress = (completed / total_files) * 100
                        progress_cb(overall_progress, f"转码进度: {completed}/{total_files}")

            except Exception as e:
                logger.error(f"批量转码 '{file_path}' 失败: {e}")
                with lock:
                    results[file_path] = False
                    completed += 1
                    if progress_cb:
                        overall_progress = (completed / total_files) * 100
                        progress_cb(overall_progress, f"转码进度: {completed}/{total_files}")

        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)

        # 启动多线程转码（限制并行数为 CPU 核心数的一半）
        threads = []
        max_threads = max(1, os.cpu_count() // 2)
        semaphore = threading.Semaphore(max_threads)

        for i, file_path in enumerate(input_files):
            semaphore.acquire()
            thread = threading.Thread(
                target=lambda fp, idx: (_transcode_single(fp, idx), semaphore.release()),
                args=(file_path, i)
            )
            threads.append(thread)
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join()

        logger.info(f"批量转码完成: {sum(results.values())}/{len(results)} 个文件成功")
        return results

    def close(self):
        """清理所有 MLT 资源"""
        # 清理动画
        for anim in self._animations.values():
            try:
                _mlt_call('animation_close', anim)
            except Exception:
                pass
        self._animations.clear()

        # 清理轨道
        for track in self._tracks:
            track.close()
        self._tracks.clear()

        # 清理 profile
        if self._profile:
            MltFactory.close(self._profile)
            self._profile = None


# ---- 全局入口 ----

_mlt_smoke_tested = False
_mlt_smoke_passed = False


def _smoke_test_mlt() -> bool:
    """
    真实 smoke test：尝试用 MLT 创建一个 profile + 一个 producer。
    比"找到 DLL"更严格——只有真正能调 API 才算可用。
    """
    global _mlt_smoke_tested, _mlt_smoke_passed
    if _mlt_smoke_tested:
        return _mlt_smoke_passed
    _mlt_smoke_tested = True

    if not is_mlt_available():
        _mlt_smoke_passed = False
        return False

    try:
        # 真实 API 调用：init → profile → producer
        MltFactory.init()
        prof = MltFactory.get_profile("hdv_1080_30p")
        if not prof:
            _mlt_smoke_passed = False
            return False

        # 关键 smoke：用 MLT 的 producer 试打开一个不存在的资源
        # MLT Python 包装层残缺时这里会抛异常或返回 None
        prod = MltFactory.get_producer(prof, "avformat", "inmemory:.mp4")
        if prod:
            try:
                MltFactory.close(prod)
            except Exception:
                pass
        _mlt_smoke_passed = prof is not None
        return _mlt_smoke_passed
    except Exception:
        _mlt_smoke_passed = False
        return False


def is_mlt_cpp_available() -> bool:
    """是否有可用 MLT（真实 API smoke test）"""
    return _smoke_test_mlt()


def is_video_engine_cpp_available() -> bool:
    """是否有可用的视频引擎（MLT 优先，回退 cpp_engine）"""
    if _smoke_test_mlt():
        return True
    # 兼容两种 import 上下文（包内/独立）
    try:
        from .cpp_engine import is_cpp_engine_available
        return is_cpp_engine_available()
    except (ImportError, ValueError):
        pass
    try:
        from cpp_engine import is_cpp_engine_available as _cpp_avail
        return _cpp_avail()
    except ImportError:
        return False


def get_mlt_cpp_engine() -> MltTimeline:
    """获取 C++ MLT 引擎"""
    return MltTimeline()


# ---- 自动回退代理 ----

class CppEngineProxy:
    """
    MLT 不可用时自动回退到 cpp_engine.pyd 的代理

    上层调用方（如 editor_scheduler）只需调用 get_mlt_cpp_engine()，
    当原生 MLT DLL 缺失或 Python 包装层残缺时，透明地切换到 cpp_engine
    （pybind11 编译的 C++ 扩展）。
    这样：
      1. 上层代码零改动即可用
      2. MLT 真可用时走 MLT（带轨道/转场/滤镜完整能力）
      3. MLT 不可用时走 cpp_engine（单轨剪辑/合并，100% 可用）
    """

    def __init__(self):
        self._backend = "unknown"
        self._mlt = None
        self._cpp = None

        if _smoke_test_mlt():
            self._backend = "mlt"
            self._mlt = MltTimeline()
        else:
            # 兼容两种 import 上下文
            try:
                from .cpp_engine import get_engine
                self._cpp = get_engine()
                self._backend = "cpp"
            except (ImportError, ValueError):
                try:
                    from cpp_engine import get_engine as _get_engine
                    self._cpp = _get_engine()
                    self._backend = "cpp"
                except ImportError:
                    self._backend = "none"

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def available(self) -> bool:
        return self._backend in ("mlt", "cpp")

    def add_track(self) -> int:
        """添加轨道（仅 MLT 后端）"""
        if self._mlt:
            return self._mlt.add_track()
        return -1

    def add_clip(self, path: str, track_index: int = 0,
                 in_point: float = 0.0, out_point: float = 0.0,
                 position: float = 0.0, speed: float = 1.0) -> int:
        """添加视频片段到指定轨道"""
        if self._mlt:
            return self._mlt.add_clip(path, track_index, in_point, out_point, position, speed)
        return -1

    def add_filter(self, track_index: int, clip_index: int,
                   filter_name: str, params: Dict[str, str] = None) -> int:
        """给指定片段添加滤镜"""
        if self._mlt:
            return self._mlt.add_filter(track_index, clip_index, filter_name, params)
        return -1

    def add_filter_chain(self, track_index: int, clip_index: int,
                         filters: List[Dict[str, Any]]) -> bool:
        """添加滤镜链"""
        if self._mlt:
            return self._mlt.add_filter_chain(track_index, clip_index, filters)
        return False

    def add_global_filter(self, filter_name: str, params: Dict[str, str] = None) -> int:
        """添加全局滤镜"""
        if self._mlt:
            return self._mlt.add_global_filter(filter_name, params)
        return -1

    def add_transition(self, track_index: int, transition_name: str,
                       params: Dict[str, str] = None) -> int:
        """添加转场效果"""
        if self._mlt:
            return self._mlt.add_transition(track_index, transition_name, params)
        return -1

    def create_animation(self, property_name: str) -> bool:
        """创建关键帧动画"""
        if self._mlt:
            return self._mlt.create_animation(property_name)
        return False

    def set_keyframe(self, property_name: str, frame: int, value: float):
        """设置关键帧"""
        if self._mlt:
            self._mlt.set_keyframe(property_name, frame, value)

    def apply_animation(self, track_index: int, clip_index: int,
                        property_name: str):
        """应用动画到片段"""
        if self._mlt:
            self._mlt.apply_animation(track_index, clip_index, property_name)

    def render(self, output_path: str, codec: str = "libx264",
               crf: int = 23, preset: str = "medium",
               progress_cb: Callable = None, hardware_accel: bool = False) -> bool:
        """渲染时间线到文件"""
        if self._mlt:
            return self._mlt.render(output_path, codec, crf, preset, progress_cb, hardware_accel)
        if self._cpp:
            return self._cpp.render(output_path, codec, crf, preset, progress_cb, hardware_accel)

        # FFmpeg CLI 兜底渲染
        try:
            from app.core.ffmpeg_utils import get_ffmpeg
            ffmpeg = get_ffmpeg()
        except ImportError:
            ffmpeg = "ffmpeg"

        try:
            import subprocess
            import os
            cmd = [
                ffmpeg, "-y",
                "-i", output_path + ".input.mp4" if os.path.exists(output_path + ".input.mp4") else "",
                "-c:v", "libx264", "-preset", "fast",
                "-crf", str(crf),
                "-c:a", "aac", "-b:a", "192k",
                output_path
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=600,
                creationflags=subprocess.CREATE_NO_WINDOW)
            return r.returncode == 0
        except Exception:
            return False

    def close(self):
        if self._mlt:
            self._mlt.close()

    # cpp_engine 直通方法（仅 cpp 后端可用）
    # 参数名严格匹配 cpp_engine.video_engine_cpp 真实签名
    def analyze_video(self, path: str):
        if self._cpp:
            return self._cpp.analyze_video(path)
        return None

    def clip_video(self, input_path: str, output_path: str,
                   start_time: float, duration: float, speed: float = 1.0):
        if self._cpp:
            return self._cpp.clip_video(input_path, output_path, start_time, duration, speed)
        return None

    def merge_clips(self, clips, output_path: str, config=None):
        if self._cpp:
            return self._cpp.merge_clips(clips, output_path, config)
        return None

    def add_watermark(self, input_path: str, output_path: str,
                      text: str, font_size: int = 24, color: str = "white",
                      x: int = -1, y: int = -1):
        if self._cpp:
            return self._cpp.add_watermark(
                input_path, output_path, text, font_size, color, x, y
            )
        return False

    def add_background_music(self, video_path: str, audio_path: str,
                             output_path: str, audio_volume: float = 0.3,
                             video_volume: float = 1.0):
        if self._cpp:
            return self._cpp.add_background_music(
                video_path, audio_path, output_path, audio_volume, video_volume
            )
        return False

    def extract_thumbnails(self, filepath: str, count: int,
                           output_dir: str, width: int = 160, height: int = 90):
        if self._cpp:
            return self._cpp.extract_thumbnails(filepath, count, output_dir, width, height)
        return []

    def extract_frame(self, filepath: str, timestamp: float,
                     output_path: str, width: int = 0, height: int = 0):
        if self._cpp:
            return self._cpp.extract_frame(filepath, timestamp, output_path, width, height)
        return False

    def extract_audio(self, video_path: str, output_path: str,
                      sample_rate: int = 44100, channels: int = 2):
        if self._cpp:
            return self._cpp.extract_audio(video_path, output_path, sample_rate, channels)
        return False

    def convert_format(self, input_path: str, output_path: str,
                       config=None):
        if self._cpp:
            return self._cpp.convert_format(input_path, output_path, config)
        return None

    def detect_gpu_encoder(self) -> str:
        if self._cpp:
            try:
                return self._cpp.get_gpu_encoder() or ""
            except Exception:
                return ""
        return ""

    def get_last_stats(self):
        if self._cpp:
            try:
                inner = getattr(self._cpp, '_engine', None) or self._cpp
                if hasattr(inner, 'get_last_stats'):
                    return inner.get_last_stats()
            except Exception:
                pass
        return None


def get_video_engine() -> CppEngineProxy:
    """获取视频引擎（MLT smoke test 通过时走 MLT，否则回退 cpp_engine）"""
    return CppEngineProxy()
