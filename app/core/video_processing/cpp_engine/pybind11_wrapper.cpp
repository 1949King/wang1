/**
 * @file pybind11_wrapper.cpp
 * @brief Pybind11 Python 绑定接口
 * @description 将 C++ 视频引擎暴露给 Python
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>
#include "video_engine.h"

namespace py = pybind11;

using namespace ai_editor;

PYBIND11_MODULE(video_engine_cpp, m) {
    m.doc() = "AI短剧编辑器 C++ 视频处理引擎";
    
    // VideoFrame 绑定
    py::class_<VideoFrame>(m, "VideoFrame")
        .def(py::init<>())
        .def_readwrite("width", &VideoFrame::width)
        .def_readwrite("height", &VideoFrame::height)
        .def_readwrite("pts", &VideoFrame::pts)
        .def_readwrite("format", &VideoFrame::format);
    
    // AudioFrame 绑定
    py::class_<AudioFrame>(m, "AudioFrame")
        .def(py::init<>())
        .def_readwrite("nb_samples", &AudioFrame::nb_samples)
        .def_readwrite("channels", &AudioFrame::channels)
        .def_readwrite("sample_rate", &AudioFrame::sample_rate)
        .def_readwrite("pts", &AudioFrame::pts)
        .def_readwrite("format", &AudioFrame::format);
    
    // VideoInfo 绑定
    py::class_<VideoInfo>(m, "VideoInfo")
        .def(py::init<>())
        .def_readwrite("filename", &VideoInfo::filename)
        .def_readwrite("width", &VideoInfo::width)
        .def_readwrite("height", &VideoInfo::height)
        .def_readwrite("fps", &VideoInfo::fps)
        .def_readwrite("duration", &VideoInfo::duration)
        .def_readwrite("total_frames", &VideoInfo::total_frames)
        .def_readwrite("codec_name", &VideoInfo::codec_name)
        .def_readwrite("pixel_format", &VideoInfo::pixel_format)
        .def_readwrite("video_stream_index", &VideoInfo::video_stream_index)
        .def_readwrite("audio_stream_index", &VideoInfo::audio_stream_index)
        .def_readwrite("has_audio", &VideoInfo::has_audio)
        .def_readwrite("has_video", &VideoInfo::has_video);
    
    // ExportConfig 绑定
    py::class_<ExportConfig>(m, "ExportConfig")
        .def(py::init<>())
        .def_readwrite("output_path", &ExportConfig::output_path)
        .def_readwrite("width", &ExportConfig::width)
        .def_readwrite("height", &ExportConfig::height)
        .def_readwrite("fps", &ExportConfig::fps)
        .def_readwrite("bitrate", &ExportConfig::bitrate)
        .def_readwrite("codec", &ExportConfig::codec)
        .def_readwrite("preset", &ExportConfig::preset)
        .def_readwrite("use_gpu", &ExportConfig::use_gpu)
        .def_readwrite("audio_bitrate", &ExportConfig::audio_bitrate)
        .def_readwrite("audio_sample_rate", &ExportConfig::audio_sample_rate)
        .def_readwrite("audio_channels", &ExportConfig::audio_channels);
    
    // ClipSegment 绑定
    py::class_<ClipSegment>(m, "ClipSegment")
        .def(py::init<>())
        .def_readwrite("source_path", &ClipSegment::source_path)
        .def_readwrite("start_time", &ClipSegment::start_time)
        .def_readwrite("end_time", &ClipSegment::end_time)
        .def_readwrite("position", &ClipSegment::position)
        .def_readwrite("speed", &ClipSegment::speed)
        .def_readwrite("volume", &ClipSegment::volume)
        .def_readwrite("track_index", &ClipSegment::track_index);
    
    // PerformanceStats 绑定
    py::class_<VideoEngine::PerformanceStats>(m, "PerformanceStats")
        .def(py::init<>())
        .def_readwrite("processing_time", &VideoEngine::PerformanceStats::processing_time)
        .def_readwrite("fps_processed", &VideoEngine::PerformanceStats::fps_processed)
        .def_readwrite("frames_processed", &VideoEngine::PerformanceStats::frames_processed)
        .def_readwrite("bytes_processed", &VideoEngine::PerformanceStats::bytes_processed)
        .def_readwrite("cpu_usage", &VideoEngine::PerformanceStats::cpu_usage)
        .def_readwrite("gpu_usage", &VideoEngine::PerformanceStats::gpu_usage)
        .def_readwrite("memory_usage", &VideoEngine::PerformanceStats::memory_usage);
    
    // VideoEngine 绑定
    py::class_<VideoEngine>(m, "VideoEngine")
        .def(py::init<>())
        
        // 视频分析
        .def("analyze_video", &VideoEngine::analyzeVideo,
             py::arg("filepath"),
             "分析视频文件信息")
        
        // 帧提取
        .def("extract_frame", &VideoEngine::extractFrame,
             py::arg("filepath"),
             py::arg("timestamp"),
             py::arg("output_path"),
             py::arg("width") = 0,
             py::arg("height") = 0,
             "提取指定时间戳的视频帧")
        
        // 缩略图提取
        .def("extract_thumbnails", &VideoEngine::extractThumbnails,
             py::arg("filepath"),
             py::arg("count"),
             py::arg("output_dir"),
             py::arg("width") = 160,
             py::arg("height") = 90,
             "批量提取视频缩略图")
        
        // 视频剪辑
        .def("clip_video", &VideoEngine::clipVideo,
             py::arg("input_path"),
             py::arg("output_path"),
             py::arg("start_time"),
             py::arg("duration"),
             py::arg("speed") = 1.0,
             py::arg("progress_cb") = nullptr,
             "剪辑视频片段")
        
        // 多片段合并
        .def("merge_clips", &VideoEngine::mergeClips,
             py::arg("clips"),
             py::arg("output_path"),
             py::arg("config"),
             py::arg("progress_cb") = nullptr,
             "合并多个视频片段")
        
        // 添加水印
        .def("add_watermark", &VideoEngine::addWatermark,
             py::arg("input_path"),
             py::arg("output_path"),
             py::arg("text"),
             py::arg("font_size") = 24,
             py::arg("color") = "white",
             py::arg("x") = -1,
             py::arg("y") = -1,
             "添加文字水印")
        
        // 添加背景音乐
        .def("add_background_music", &VideoEngine::addBackgroundMusic,
             py::arg("video_path"),
             py::arg("audio_path"),
             py::arg("output_path"),
             py::arg("audio_volume") = 0.3,
             py::arg("video_volume") = 1.0,
             "添加背景音乐")
        
        // GPU 编码器检测
        .def("detect_gpu_encoder", &VideoEngine::detectGpuEncoder,
             py::arg("encoder_name"),
             "检测可用的 GPU 编码器")
        
        // 格式转换
        .def("convert_format", &VideoEngine::convertFormat,
             py::arg("input_path"),
             py::arg("output_path"),
             py::arg("config"),
             py::arg("progress_cb") = nullptr,
             "转换视频格式")
        
        // 音频提取
        .def("extract_audio", &VideoEngine::extractAudio,
             py::arg("video_path"),
             py::arg("output_path"),
             py::arg("sample_rate") = 44100,
             py::arg("channels") = 2,
             "提取视频音频")
        
        // 获取元数据
        .def("get_video_metadata", &VideoEngine::getVideoMetadata,
             py::arg("filepath"),
             "获取视频元数据信息")
        
        // 性能统计
        .def("get_last_stats", &VideoEngine::getLastStats,
             "获取上次操作的性能统计")
        
        // 线程池管理
        .def("set_thread_pool_size", &VideoEngine::setThreadPoolSize,
             py::arg("size"),
             "设置线程池大小")
        
        .def("get_thread_pool_size", &VideoEngine::getThreadPoolSize,
             "获取线程池大小")
        
        // 取消操作
        .def("cancel", &VideoEngine::cancel,
             "取消当前操作")
        
        .def("is_cancelled", &VideoEngine::isCancelled,
             "检查是否已取消");
    
    // 单例管理器
    m.def("get_video_engine", &VideoEngineManager::getInstance,
          py::return_value_policy::reference,
          "获取视频引擎单例");
}
