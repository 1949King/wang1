/**
 * @file openshot_wrapper.h
 * @brief libopenshot C++ 引擎封装
 * @description 封装 libopenshot 核心功能，提供高性能时间线渲染
 */

#ifndef OPENSHOT_WRAPPER_H
#define OPENSHOT_WRAPPER_H

#include <string>
#include <vector>
#include <memory>
#include <functional>

// libopenshot 头文件
#include "Timeline.h"
#include "Clip.h"
#include "FFmpegReader.h"
#include "FFmpegWriter.h"
#include "Frame.h"
#include "KeyFrame.h"
#include "Effects.h"

namespace ai_editor {

// 时间线配置
struct TimelineConfig {
    int width;
    int height;
    double fps;
    int sample_rate;
    int channels;
    std::string profile;
    
    TimelineConfig() : width(1920), height(1080), fps(30.0),
                       sample_rate(44100), channels(2), profile("HD 1080p 30 fps" {}
};

// 剪辑配置
struct OpenshotClipConfig {
    std::string source_path;
    double start;
    double end;
    double position;
    double layer;
    double volume;
    double speed;
    std::string title;
    
    OpenshotClipConfig() : start(0), end(0), position(0), layer(0),
                           volume(1.0), speed(1.0) {}
};

// 特效配置
struct EffectConfig {
    std::string effect_name;
    std::map<std::string, double> properties;
    double start;
    double end;
    int track;
    
    EffectConfig() : start(0), end(0), track(0) {}
};

// 转场配置
struct TransitionConfig {
    std::string transition_name;
    double duration;
    double position;
    int track;
    
    TransitionConfig() : duration(1.0), position(0), track(0) {}
};

// 导出配置
struct OpenshotExportConfig {
    std::string output_path;
    std::string video_codec;
    std::string audio_codec;
    int video_bitrate;
    int audio_bitrate;
    std::string preset;
    bool use_gpu;
    
    OpenshotExportConfig() : video_bitrate(5000000), audio_bitrate(128000),
                             preset("fast", use_gpu(false) {}
};

// 进度回调
using OpenshotProgressCallback = std::function<void(double progress, const std::string& message)>;

// libopenshot 封装类
class OpenshotWrapper {
public:
    OpenshotWrapper();
    ~OpenshotWrapper();

    // 时间线管理
    bool createTimeline(const TimelineConfig& config);
    bool destroyTimeline();
    
    // 剪辑管理
    bool addClip(const OpenshotClipConfig& clip_config);
    bool removeClip(int clip_id);
    bool updateClip(int clip_id, const OpenshotClipConfig& clip_config);
    
    // 特效管理
    bool addEffect(const EffectConfig& effect_config);
    bool removeEffect(int effect_id);
    
    // 转场管理
    bool addTransition(const TransitionConfig& transition_config);
    
    // 渲染导出
    bool render(const OpenshotExportConfig& export_config,
                OpenshotProgressCallback progress_cb = nullptr);
    
    // 预览
    bool startPreview();
    bool stopPreview();
    bool seek(double position);
    
    // 时间线信息
    double getDuration() const;
    int getClipCount() const;
    std::string getTimelineInfo() const;
    
    // 性能统计
    struct RenderStats {
        double render_time;
        double fps_rendered;
        size_t frames_rendered;
        double cpu_usage;
        double gpu_usage;
    };
    
    RenderStats getLastRenderStats() const { return last_render_stats_; }

private:
    std::shared_ptr<openshot::Timeline> timeline_;
    std::shared_ptr<openshot::FFmpegWriter> writer_;
    
    RenderStats last_render_stats_;
    
    // 内部方法
    std::shared_ptr<openshot::ReaderBase> createReader(const std::string& filepath);
    std::shared_ptr<openshot::Clip> createClip(const OpenshotClipConfig& config);
    void applyEffect(std::shared_ptr<openshot::Clip> clip, const EffectConfig& effect);
};

} // namespace ai_editor

#endif // OPENSHOT_WRAPPER_H
