"""
MLT API 检测脚本
=================
检测当前系统中 MLT DLL 实际可用的 API 符号，
为后续实现提供准确的能力清单。

用法:
    python -m app.core.video_processing.mlt_api_detect

输出:
    - 可用 API 列表（按模块分类）
    - 缺失 API 列表
    - 总统计
"""
import os
import sys
import ctypes

import logging
logger = logging.getLogger("AI短剧编辑器.core.video_processing.mlt_api_detect")

def find_mlt_dll():
    mlt_names = ["libmlt-7.dll", "libmlt++-7.dll", "mlt-7.dll"]
    candidates = []
    
    env_path = os.environ.get("MLT_PATH", "")
    if env_path:
        for name in mlt_names:
            candidates.append(os.path.join(env_path, name))
            candidates.append(os.path.join(env_path, "lib", "mlt", name))
    
    for base in [
        r"C:\Program Files\Shotcut",
        r"D:\Program Files\Shotcut",
        r"C:\Program Files (x86)\Shotcut",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Shotcut"),
    ]:
        for name in mlt_names:
            candidates.append(os.path.join(base, name))
            candidates.append(os.path.join(base, "lib", "mlt", name))
    
    project_mlt = os.path.join(os.path.dirname(__file__), "..", "..", "thirdparty", "mlt")
    for name in mlt_names:
        candidates.append(os.path.join(project_mlt, name))
    
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

def detect_apis(dll_path):
    logger.info(f'\n📦 加载 MLT DLL: {dll_path}')
    dll = ctypes.CDLL(dll_path)
    
    dll_dir = os.path.dirname(dll_path)
    for d in [dll_dir, os.path.join(dll_dir, "..")]:
        if os.path.isdir(d):
            try:
                os.add_dll_directory(d)
            except Exception as e:
                logger.debug(f"[MLTAPI] 添加DLL目录失败 {d}: {e}")
    
    api_categories = {
        "factory": [
            "mlt_factory_init", "mlt_factory_profile", "mlt_factory_producer",
            "mlt_factory_consumer", "mlt_factory_filter", "mlt_factory_transition",
            "mlt_factory_close",
        ],
        "profile": [
            "mlt_profile_new", "mlt_profile_close", "mlt_profile_width",
            "mlt_profile_height", "mlt_profile_frame_rate",
            "mlt_profile_sar_num", "mlt_profile_sar_den",
        ],
        "producer": [
            "mlt_producer_attach", "mlt_producer_detach", "mlt_producer_close",
            "mlt_producer_set_in", "mlt_producer_set_out",
            "mlt_producer_get_in", "mlt_producer_get_out",
            "mlt_producer_length", "mlt_producer_seek",
            "mlt_producer_get_frame", "mlt_producer_next",
        ],
        "filter": [
            "mlt_filter_set_in", "mlt_filter_set_out", "mlt_filter_close",
            "mlt_filter_get_frame",
        ],
        "transition": [
            "mlt_transition_close", "mlt_transition_get_frame",
            "mlt_transition_set_in", "mlt_transition_set_out",
        ],
        "playlist": [
            "mlt_playlist_new", "mlt_playlist_append", "mlt_playlist_insert",
            "mlt_playlist_length", "mlt_playlist_close",
            "mlt_playlist_clear", "mlt_playlist_move", "mlt_playlist_remove",
            "mlt_playlist_get",
        ],
        "consumer": [
            "mlt_consumer_connect", "mlt_consumer_start", "mlt_consumer_stop",
            "mlt_consumer_close", "mlt_consumer_is_stopped",
        ],
        "properties": [
            "mlt_properties_set_string", "mlt_properties_get_string",
            "mlt_properties_set_int", "mlt_properties_get_int",
            "mlt_properties_set_double", "mlt_properties_get_double",
        ],
        "frame": [
            "mlt_frame_close", "mlt_frame_get_image",
            "mlt_frame_get_width", "mlt_frame_get_height",
        ],
        "animation": [
            "mlt_animation_new", "mlt_animation_close", "mlt_animation_set",
            "mlt_animation_get", "mlt_animation_set_length",
        ],
        "service": [
            "mlt_service_close", "mlt_service_get_producer",
            "mlt_service_get_filter", "mlt_service_get_consumer",
        ],
    }
    
    available = {}
    missing = {}
    
    for category, apis in api_categories.items():
        avail_list = []
        miss_list = []
        for api in apis:
            try:
                getattr(dll, api)
                avail_list.append(api)
            except AttributeError:
                miss_list.append(api)
        available[category] = avail_list
        missing[category] = miss_list
    
    return available, missing

def print_report(available, missing):
    total_avail = sum(len(v) for v in available.values())
    total_missing = sum(len(v) for v in missing.values())
    
    logger.info(f"\n{'=' * 60}")
    logger.info(f' MLT API 检测报告')
    logger.info(f"{'=' * 60}")
    logger.info(f' 可用: {total_avail} / {total_avail + total_missing}')
    logger.info(f' 缺失: {total_missing} / {total_avail + total_missing}')
    logger.info(f"{'=' * 60}\n")
    
    for category, apis in available.items():
        if apis:
            logger.info(f' ✅ {category} ({len(apis)}):')
            for api in apis:
                logger.info(f'    {api}')
    
    logger.info(f"\n{'=' * 60}")
    logger.info(f' 缺失 API（按模块）')
    logger.info(f"{'=' * 60}")
    
    for category, apis in missing.items():
        if apis:
            logger.info(f' ❌ {category} ({len(apis)}):')
            for api in apis:
                logger.info(f'    {api}')
    
    logger.info(f"\n{'=' * 60}")

def main():
    dll_path = find_mlt_dll()
    if not dll_path:
        logger.info('❌ 未找到 MLT DLL')
        logger.info('请安装 Shotcut 或设置 MLT_PATH 环境变量')
        return
    
    available, missing = detect_apis(dll_path)
    print_report(available, missing)

if __name__ == "__main__":
    main()
