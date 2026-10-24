/**
 * @file video_engine.h
 * @brief C++ 视频处理核心引擎
 * @description 高性能视频处理引擎，集成 FFmpeg、GPU 加速、多线程处理
 */

#ifndef VIDEO_ENGINE_H
#define VIDEO_ENGINE_H

#include <string>
#include <vector>
#include <memory>
#include <functional>
#include <thread>
#include <mutex>
#include <atomic>
#include <queue>
#include <condition_variable>

// FFmpeg 头文件
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavfilter/avfilter.h>
#include <libavfilter/buffersink.h>
#include <libavfilter/buffersrc.h>
#include <libavutil/avutil.h>
#include <libavutil/imgutils.h>
#include <libavutil/opt.h>
#include <libswscale/swscale.h>
#include <libswresample/swresample.h>
}

namespace ai_editor {

// 视频帧结构
struct VideoFrame {
    uint8_t* data[4];
    int linesize[4];
    int width;
    int height;
    int64_t pts;
    int format;
    
    VideoFrame() : width(0), height(0), pts(0), format(AV_PIX_FMT_NONE) {
        for (int i = 0; i < 4; i++) {
            data[i] = nullptr;
            linesize[i] = 0;
        }
    }
};

// 音频帧结构
struct AudioFrame {
    uint8_t* data[8];
    int linesize;
    int nb_samples;
    int channels;
    int sample_rate;
    int64_t pts;
    int format;
    
    AudioFrame() : nb_samples(0), channels(0), sample_rate(0), pts(0), format(AV_SAMPLE_FMT_NONE) {
        for (int i = 0; i < 8; i++) {
            data[i] = nullptr;
        }
        linesize = 0;
    }
};

// 视频信息结构
struct VideoInfo {
    std::string filename;
    int width;
    int height;
    double fps;
    double duration;
    int64_t total_frames;
    std::string codec_name;
    std::string pixel_format;
    int video_stream_index;
    int audio_stream_index;
    bool has_audio;
    bool has_video;
};

// 导出配置
struct ExportConfig {
    std::string output_path;
    int width;
    int height;
    double fps;
    int bitrate;
    std::string codec;
    std::string preset;
    bool use_gpu;
    int audio_bitrate;
    int audio_sample_rate;
    int audio_channels;
};

// 剪辑片段
struct ClipSegment {
    std::string source_path;
    double start_time;
    double end_time;
    double position;  // 在时间轴上的位置
    double speed;
    double volume;
    int track_index;
};

// 进度回调
using ProgressCallback = std::function<void(double progress, const std::string& message)>;
using ErrorCallback = std::function<void(const std::string& error)>;

// C++ 视频处理引擎
class VideoEngine {
public:
    VideoEngine();
    ~VideoEngine();

    // 视频分析
    VideoInfo analyzeVideo(const std::string& filepath);
    
    // 视频提取
    bool extractFrame(const std::string& filepath, double timestamp, 
                     const std::string& output_path, int width = 0, int height = 0);
    
    // 批量提取缩略图
    std::vector<std::string> extractThumbnails(
        const std::string& filepath,
        int count,
        const std::string& output_dir,
        int width = 160,
        int height = 90
    );
    
    // 视频剪辑
    bool clipVideo(
        const std::string& input_path,
        const std::string& output_path,
        double start_time,
        double duration,
        double speed = 1.0,
        ProgressCallback progress_cb = nullptr
    );
    
    // 多片段合并
    bool mergeClips(
        const std::vector<ClipSegment>& clips,
        const std::string& output_path,
        const ExportConfig& config,
        ProgressCallback progress_cb = nullptr
    );
    
    // 添加水印
    bool addWatermark(
        const std::string& input_path,
        const std::string& output_path,
        const std::string& text,
        int font_size = 24,
        const std::string& color = "white",
        int x = -1,
        int y = -1
    );
    
    // 添加背景音乐
    bool addBackgroundMusic(
        const std::string& video_path,
        const std::string& audio_path,
        const std::string& output_path,
        double audio_volume = 0.3,
        double video_volume = 1.0
    );
    
    // GPU 加速检测
    bool detectGpuEncoder(std::string& encoder_name);
    
    // 格式转换
    bool convertFormat(
        const std::string& input_path,
        const std::string& output_path,
        const ExportConfig& config,
        ProgressCallback progress_cb = nullptr
    );
    
    // 音频提取
    bool extractAudio(
        const std::string& video_path,
        const std::string& output_path,
        int sample_rate = 44100,
        int channels = 2
    );
    
    // 视频信息获取
    std::string getVideoMetadata(const std::string& filepath);
    
    // 性能统计
    struct PerformanceStats {
        double processing_time;
        double fps_processed;
        size_t frames_processed;
        size_t bytes_processed;
        double cpu_usage;
        double gpu_usage;
        size_t memory_usage;
    };
    
    PerformanceStats getLastStats() const { return last_stats_; }
    
    // 线程池管理
    void setThreadPoolSize(int size);
    int getThreadPoolSize() const { return thread_pool_size_; }
    
    // 取消操作
    void cancel();
    bool isCancelled() const { return cancelled_.load(); }

private:
    // FFmpeg 上下文
    AVFormatContext* format_ctx_;
    AVCodecContext* codec_ctx_;
    SwsContext* sws_ctx_;
    SwrContext* swr_ctx_;
    
    // 线程池
    int thread_pool_size_;
    std::vector<std::thread> workers_;
    std::queue<std::function<void()>> tasks_;
    std::mutex queue_mutex_;
    std::condition_variable condition_;
    bool stop_;
    
    // 性能统计
    PerformanceStats last_stats_;
    
    // 取消标志
    std::atomic<bool> cancelled_;
    
    // 内部方法
    bool initFFmpeg();
    void cleanupFFmpeg();
    bool openInputFile(const std::string& filepath);
    void closeInputFile();
    bool setupEncoder(const ExportConfig& config);
    void cleanupEncoder();
    
    // GPU 编码器检测
    bool checkNvenc();
    bool checkAmf();
    bool checkQsv();
    
    // 帧处理
    bool processFrame(AVFrame* frame, AVPacket* packet);
    bool scaleFrame(AVFrame* src, AVFrame* dst, int width, int height);
    
    // 音频处理
    bool resampleAudio(AVFrame* src, AVFrame* dst, int sample_rate, int channels);
    
    // 滤镜管线辅助函数
    AVFilterGraph* createFilterGraph();
    AVFilterContext* createBufferSource(AVFilterGraph* graph, AVCodecContext* codec_ctx, const char* name);
    AVFilterContext* createBufferSink(AVFilterGraph* graph, enum AVMediaType media_type, const char* name);
    AVFilterContext* addFilter(AVFilterGraph* graph, const char* filter_name, const char* instance_name, AVDictionary* options);
    bool linkFilters(AVFilterContext* src, AVFilterContext* dst, int src_pad, int dst_pad);
    bool configureFilterGraph(AVFilterGraph* graph);
    void freeFilterGraph(AVFilterGraph* graph);
    
    // 硬件编码辅助函数
    const AVCodec* selectHardwareEncoder();
    void setHardwareEncoderOptions(AVCodecContext* codec_ctx, const std::string& encoder_name);
};

// 单例模式
class VideoEngineManager {
public:
    static VideoEngine& getInstance();
    
private:
    VideoEngineManager() = default;
    ~VideoEngineManager() = default;
    
    VideoEngineManager(const VideoEngineManager&) = delete;
    VideoEngineManager& operator=(const VideoEngineManager&) = delete;
    
    static VideoEngine engine_;
};

} // namespace ai_editor

#endif // VIDEO_ENGINE_H
