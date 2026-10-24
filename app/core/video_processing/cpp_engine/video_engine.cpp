/**
 * @file video_engine.cpp
 * @brief C++ 视频处理核心引擎实现
 */

#include "video_engine.h"
#include <iostream>
#include <fstream>
#include <chrono>
#include <algorithm>
#include <sstream>
#include <iomanip>

namespace ai_editor {

VideoEngine::VideoEngine() 
    : format_ctx_(nullptr),
      codec_ctx_(nullptr),
      sws_ctx_(nullptr),
      swr_ctx_(nullptr),
      thread_pool_size_(4),
      stop_(false),
      cancelled_(false) {
    
    last_stats_ = {};
    initFFmpeg();
}

VideoEngine::~VideoEngine() {
    cleanupFFmpeg();
    stop_ = true;
    condition_.notify_all();
    for (auto& worker : workers_) {
        if (worker.joinable()) {
            worker.join();
        }
    }
}

bool VideoEngine::initFFmpeg() {
    // FFmpeg 4.0+: av_register_all(), avcodec_register_all(), avfilter_register_all() 
    // are deprecated and removed. Initialization is automatic.
    
    // 初始化网络（用于网络流）
    avformat_network_init();
    
    return true;
}

void VideoEngine::cleanupFFmpeg() {
    if (sws_ctx_) {
        sws_freeContext(sws_ctx_);
        sws_ctx_ = nullptr;
    }
    if (swr_ctx_) {
        swr_free(&swr_ctx_);
        swr_ctx_ = nullptr;
    }
    if (codec_ctx_) {
        avcodec_free_context(&codec_ctx_);
        codec_ctx_ = nullptr;
    }
    if (format_ctx_) {
        avformat_close_input(&format_ctx_);
        format_ctx_ = nullptr;
    }
}

VideoInfo VideoEngine::analyzeVideo(const std::string& filepath) {
    VideoInfo info;
    info.filename = filepath;
    info.video_stream_index = -1;
    info.audio_stream_index = -1;
    info.has_audio = false;
    info.has_video = false;
    
    AVFormatContext* fmt_ctx = nullptr;
    if (avformat_open_input(&fmt_ctx, filepath.c_str(), nullptr, nullptr) < 0) {
        return info;
    }
    
    if (avformat_find_stream_info(fmt_ctx, nullptr) < 0) {
        avformat_close_input(&fmt_ctx);
        return info;
    }
    
    // 查找视频流和音频流
    for (unsigned int i = 0; i < fmt_ctx->nb_streams; i++) {
        AVStream* stream = fmt_ctx->streams[i];
        AVCodecParameters* codecpar = stream->codecpar;
        
        if (codecpar->codec_type == AVMEDIA_TYPE_VIDEO && info.video_stream_index == -1) {
            info.video_stream_index = i;
            info.width = codecpar->width;
            info.height = codecpar->height;
            info.fps = av_q2d(stream->avg_frame_rate);
            info.codec_name = avcodec_get_name(codecpar->codec_id);
            
            // 获取像素格式
            const AVCodec* codec = avcodec_find_decoder(codecpar->codec_id);
            if (codec) {
                info.pixel_format = av_get_pix_fmt_name(static_cast<AVPixelFormat>(codecpar->format));
            }
            
            info.has_video = true;
        } else if (codecpar->codec_type == AVMEDIA_TYPE_AUDIO && info.audio_stream_index == -1) {
            info.audio_stream_index = i;
            info.has_audio = true;
        }
    }
    
    // 计算总时长和帧数
    info.duration = (double)fmt_ctx->duration / AV_TIME_BASE;
    if (info.fps > 0) {
        info.total_frames = (int64_t)(info.duration * info.fps);
    }
    
    avformat_close_input(&fmt_ctx);
    return info;
}

bool VideoEngine::extractFrame(const std::string& filepath, double timestamp,
                               const std::string& output_path, int width, int height) {
    AVFormatContext* fmt_ctx = nullptr;
    if (avformat_open_input(&fmt_ctx, filepath.c_str(), nullptr, nullptr) < 0) {
        return false;
    }
    
    if (avformat_find_stream_info(fmt_ctx, nullptr) < 0) {
        avformat_close_input(&fmt_ctx);
        return false;
    }
    
    // 查找视频流
    int video_stream = -1;
    for (unsigned int i = 0; i < fmt_ctx->nb_streams; i++) {
        if (fmt_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
            video_stream = i;
            break;
        }
    }
    
    if (video_stream == -1) {
        avformat_close_input(&fmt_ctx);
        return false;
    }
    
    // 查找解码器
    AVCodecParameters* codecpar = fmt_ctx->streams[video_stream]->codecpar;
    const AVCodec* codec = avcodec_find_decoder(codecpar->codec_id);
    if (!codec) {
        avformat_close_input(&fmt_ctx);
        return false;
    }
    
    // 创建解码器上下文
    AVCodecContext* codec_ctx = avcodec_alloc_context3(codec);
    avcodec_parameters_to_context(codec_ctx, codecpar);
    
    if (avcodec_open2(codec_ctx, codec, nullptr) < 0) {
        avcodec_free_context(&codec_ctx);
        avformat_close_input(&fmt_ctx);
        return false;
    }
    
    // 定位到指定时间戳
    int64_t target_ts = (int64_t)(timestamp * AV_TIME_BASE);
    av_seek_frame(fmt_ctx, -1, target_ts, AVSEEK_FLAG_BACKWARD);
    
    // 解码帧
    AVFrame* frame = av_frame_alloc();
    AVPacket* packet = av_packet_alloc();
    bool found = false;
    
    while (av_read_frame(fmt_ctx, packet) >= 0) {
        if (packet->stream_index == video_stream) {
            avcodec_send_packet(codec_ctx, packet);
            
            while (avcodec_receive_frame(codec_ctx, frame) >= 0) {
                found = true;
                break;
            }
        }
        av_packet_unref(packet);
        if (found) break;
    }
    
    if (!found) {
        av_frame_free(&frame);
        av_packet_free(&packet);
        avcodec_free_context(&codec_ctx);
        avformat_close_input(&fmt_ctx);
        return false;
    }
    
    // 缩放帧
    int out_width = width > 0 ? width : frame->width;
    int out_height = height > 0 ? height : frame->height;
    
    AVFrame* scaled_frame = av_frame_alloc();
    scaled_frame->format = AV_PIX_FMT_RGB24;
    scaled_frame->width = out_width;
    scaled_frame->height = out_height;
    av_frame_get_buffer(scaled_frame, 32);
    
    SwsContext* sws_ctx = sws_getContext(
        frame->width, frame->height, (AVPixelFormat)frame->format,
        out_width, out_height, AV_PIX_FMT_RGB24,
        SWS_BILINEAR, nullptr, nullptr, nullptr
    );
    
    sws_scale(sws_ctx, frame->data, frame->linesize, 0, frame->height,
              scaled_frame->data, scaled_frame->linesize);
    
    // 保存为 BMP
    std::ofstream bmp_file(output_path, std::ios::binary);
    if (bmp_file.is_open()) {
        int row_size = out_width * 3;
        int padding = (4 - (row_size % 4)) % 4;
        int padded_row_size = row_size + padding;
        int data_size = padded_row_size * out_height;
        int file_size = 54 + data_size;
        
        // BMP 文件头
        uint8_t file_header[14] = {0};
        file_header[0] = 'B';
        file_header[1] = 'M';
        *(uint32_t*)(file_header + 2) = file_size;
        *(uint32_t*)(file_header + 10) = 54;
        
        // BMP 信息头
        uint8_t info_header[40] = {0};
        *(uint32_t*)(info_header + 0) = 40;
        *(int32_t*)(info_header + 4) = out_width;
        *(int32_t*)(info_header + 8) = out_height;
        *(uint16_t*)(info_header + 12) = 1;
        *(uint16_t*)(info_header + 14) = 24;
        *(uint32_t*)(info_header + 20) = data_size;
        
        bmp_file.write((char*)file_header, 14);
        bmp_file.write((char*)info_header, 40);
        
        // 写入像素数据（BMP 是从下到上存储的）
        std::vector<uint8_t> row_buffer(row_size);
        for (int y = out_height - 1; y >= 0; y--) {
            for (int x = 0; x < out_width; x++) {
                int src_idx = y * scaled_frame->linesize[0] + x * 3;
                row_buffer[x * 3 + 0] = scaled_frame->data[0][src_idx + 2]; // B
                row_buffer[x * 3 + 1] = scaled_frame->data[0][src_idx + 1]; // G
                row_buffer[x * 3 + 2] = scaled_frame->data[0][src_idx + 0]; // R
            }
            bmp_file.write((char*)row_buffer.data(), row_size);
            if (padding > 0) {
                uint8_t pad[4] = {0};
                bmp_file.write((char*)pad, padding);
            }
        }
        
        bmp_file.close();
    }
    
    // 清理
    sws_freeContext(sws_ctx);
    av_frame_free(&scaled_frame);
    av_frame_free(&frame);
    av_packet_free(&packet);
    avcodec_free_context(&codec_ctx);
    avformat_close_input(&fmt_ctx);
    
    return true;
}

std::vector<std::string> VideoEngine::extractThumbnails(
    const std::string& filepath,
    int count,
    const std::string& output_dir,
    int width,
    int height
) {
    std::vector<std::string> thumbnails;
    
    VideoInfo info = analyzeVideo(filepath);
    if (!info.has_video || info.duration <= 0) {
        return thumbnails;
    }
    
    double interval = info.duration / count;
    
    for (int i = 0; i < count; i++) {
        double timestamp = i * interval;
        std::string output_path = output_dir + "/thumb_" + std::to_string(i) + ".bmp";
        
        if (extractFrame(filepath, timestamp, output_path, width, height)) {
            thumbnails.push_back(output_path);
        }
    }
    
    return thumbnails;
}

bool VideoEngine::clipVideo(
    const std::string& input_path,
    const std::string& output_path,
    double start_time,
    double duration,
    double speed,
    ProgressCallback progress_cb
) {
    auto start = std::chrono::high_resolution_clock::now();
    
    AVFormatContext* ifmt_ctx = nullptr;
    AVFormatContext* ofmt_ctx = nullptr;
    AVCodecContext* ictx = nullptr;
    AVCodecContext* octx = nullptr;
    AVFrame* frame = nullptr;
    AVPacket* pkt = nullptr;
    SwsContext* sws_ctx = nullptr;
    
    int video_stream = -1;
    int audio_stream = -1;
    bool success = false;
    
    try {
        if (avformat_open_input(&ifmt_ctx, input_path.c_str(), nullptr, nullptr) < 0) {
            throw std::runtime_error("无法打开输入文件");
        }
        
        if (avformat_find_stream_info(ifmt_ctx, nullptr) < 0) {
            throw std::runtime_error("无法获取流信息");
        }
        
        for (unsigned int i = 0; i < ifmt_ctx->nb_streams; i++) {
            if (ifmt_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO && video_stream == -1) {
                video_stream = i;
            } else if (ifmt_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_AUDIO && audio_stream == -1) {
                audio_stream = i;
            }
        }
        
        if (video_stream == -1) {
            throw std::runtime_error("未找到视频流");
        }
        
        AVCodecParameters* icodecpar = ifmt_ctx->streams[video_stream]->codecpar;
        const AVCodec* idecoder = avcodec_find_decoder(icodecpar->codec_id);
        if (!idecoder) {
            throw std::runtime_error("未找到解码器");
        }
        
        ictx = avcodec_alloc_context3(idecoder);
        avcodec_parameters_to_context(ictx, icodecpar);
        if (avcodec_open2(ictx, idecoder, nullptr) < 0) {
            throw std::runtime_error("无法打开解码器");
        }
        
        if (avformat_alloc_output_context2(&ofmt_ctx, nullptr, nullptr, output_path.c_str()) < 0) {
            throw std::runtime_error("无法创建输出上下文");
        }
        
        AVStream* ost = avformat_new_stream(ofmt_ctx, nullptr);
        const AVCodec* oencoder = selectHardwareEncoder();
        if (!oencoder) {
            throw std::runtime_error("未找到编码器");
        }
        
        octx = avcodec_alloc_context3(oencoder);
        octx->codec_id = oencoder->id;
        octx->codec_type = AVMEDIA_TYPE_VIDEO;
        octx->pix_fmt = AV_PIX_FMT_YUV420P;
        octx->width = ictx->width;
        octx->height = ictx->height;
        octx->time_base = av_inv_q(ifmt_ctx->streams[video_stream]->r_frame_rate);
        octx->framerate = ifmt_ctx->streams[video_stream]->r_frame_rate;
        octx->bit_rate = 5000000;
        
        AVDictionary* opts = nullptr;
        av_dict_set(&opts, "preset", "fast", 0);
        av_dict_set(&opts, "crf", "23", 0);
        
        std::string encoder_name = avcodec_get_name(oencoder->id);
        setHardwareEncoderOptions(octx, encoder_name);
        
        if (avcodec_open2(octx, oencoder, &opts) < 0) {
            throw std::runtime_error("无法打开编码器");
        }
        av_dict_free(&opts);
        
        avcodec_parameters_from_context(ost->codecpar, octx);
        ost->time_base = octx->time_base;
        
        if (!(ofmt_ctx->oformat->flags & AVFMT_NOFILE)) {
            if (avio_open(&ofmt_ctx->pb, output_path.c_str(), AVIO_FLAG_WRITE) < 0) {
                throw std::runtime_error("无法打开输出文件");
            }
        }
        
        if (avformat_write_header(ofmt_ctx, nullptr) < 0) {
            throw std::runtime_error("无法写入头部");
        }
        
        int64_t start_ts = (int64_t)(start_time * AV_TIME_BASE);
        av_seek_frame(ifmt_ctx, video_stream, start_ts, AVSEEK_FLAG_BACKWARD);
        
        frame = av_frame_alloc();
        pkt = av_packet_alloc();
        
        int64_t end_ts = start_ts + (int64_t)(duration * AV_TIME_BASE);
        int frame_count = 0;
        
        while (av_read_frame(ifmt_ctx, pkt) >= 0) {
            if (pkt->stream_index != video_stream) {
                av_packet_unref(pkt);
                continue;
            }
            
            if (avcodec_send_packet(ictx, pkt) < 0) {
                av_packet_unref(pkt);
                continue;
            }
            
            while (avcodec_receive_frame(ictx, frame) >= 0) {
                if (frame->pts * av_q2d(ifmt_ctx->streams[video_stream]->time_base) > duration + start_time) {
                    success = true;
                    goto cleanup;
                }
                
                AVFrame* out_frame = av_frame_alloc();
                out_frame->format = octx->pix_fmt;
                out_frame->width = octx->width;
                out_frame->height = octx->height;
                av_frame_get_buffer(out_frame, 32);
                
                sws_ctx = sws_getContext(
                    frame->width, frame->height, (AVPixelFormat)frame->format,
                    octx->width, octx->height, octx->pix_fmt,
                    SWS_BILINEAR, nullptr, nullptr, nullptr
                );
                
                sws_scale(sws_ctx, frame->data, frame->linesize, 0, frame->height,
                          out_frame->data, out_frame->linesize);
                
                out_frame->pts = frame_count++;
                
                if (avcodec_send_frame(octx, out_frame) < 0) {
                    av_frame_free(&out_frame);
                    continue;
                }
                
                AVPacket* opkt = av_packet_alloc();
                while (avcodec_receive_packet(octx, opkt) >= 0) {
                    av_interleaved_write_frame(ofmt_ctx, opkt);
                    av_packet_unref(opkt);
                }
                av_packet_free(&opkt);
                av_frame_free(&out_frame);
                
                if (progress_cb) {
                    double p = std::min(1.0, frame_count / (duration * av_q2d(ifmt_ctx->streams[video_stream]->r_frame_rate)));
                    progress_cb(p, "剪辑中...");
                }
            }
            
            av_packet_unref(pkt);
        }
        
        success = true;
        
    cleanup:
        while (avcodec_receive_packet(octx, pkt) >= 0) {
            av_interleaved_write_frame(ofmt_ctx, pkt);
            av_packet_unref(pkt);
        }
        
        av_write_trailer(ofmt_ctx);
        
    } catch (const std::exception& e) {
        if (progress_cb) {
            progress_cb(-1.0, std::string("剪辑失败: ") + e.what());
        }
    }
    
    if (sws_ctx) sws_freeContext(sws_ctx);
    if (pkt) av_packet_free(&pkt);
    if (frame) av_frame_free(&frame);
    if (octx) avcodec_free_context(&octx);
    if (ictx) avcodec_free_context(&ictx);
    if (ofmt_ctx && !(ofmt_ctx->oformat->flags & AVFMT_NOFILE)) {
        avio_closep(&ofmt_ctx->pb);
    }
    if (ofmt_ctx) avformat_free_context(ofmt_ctx);
    if (ifmt_ctx) avformat_close_input(&ifmt_ctx);
    
    auto end = std::chrono::high_resolution_clock::now();
    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
    last_stats_.processing_time = elapsed / 1000.0;
    
    if (progress_cb && success) {
        progress_cb(1.0, "剪辑完成");
    }
    
    return success;
}

bool VideoEngine::mergeClips(
    const std::vector<ClipSegment>& clips,
    const std::string& output_path,
    const ExportConfig& config,
    ProgressCallback progress_cb
) {
    if (clips.empty()) return false;
    
    AVFormatContext* ofmt_ctx = nullptr;
    AVCodecContext* octx = nullptr;
    AVFrame* frame = nullptr;
    AVPacket* pkt = nullptr;
    SwsContext* sws_ctx = nullptr;
    
    bool success = false;
    
    try {
        if (avformat_alloc_output_context2(&ofmt_ctx, nullptr, nullptr, output_path.c_str()) < 0) {
            throw std::runtime_error("无法创建输出上下文");
        }
        
        const AVCodec* oencoder = selectHardwareEncoder();
        if (!oencoder) {
            throw std::runtime_error("未找到编码器");
        }
        
        octx = avcodec_alloc_context3(oencoder);
        octx->codec_id = oencoder->id;
        octx->codec_type = AVMEDIA_TYPE_VIDEO;
        octx->pix_fmt = AV_PIX_FMT_YUV420P;
        octx->width = config.width > 0 ? config.width : 1920;
        octx->height = config.height > 0 ? config.height : 1080;
        octx->time_base = {1, 30};
        octx->framerate = {30, 1};
        octx->bit_rate = config.bitrate > 0 ? config.bitrate * 1000 : 5000000;
        
        AVDictionary* opts = nullptr;
        av_dict_set(&opts, "preset", config.preset.c_str(), 0);
        av_dict_set(&opts, "crf", "23", 0);
        
        std::string encoder_name = avcodec_get_name(oencoder->id);
        setHardwareEncoderOptions(octx, encoder_name);
        
        if (avcodec_open2(octx, oencoder, &opts) < 0) {
            throw std::runtime_error("无法打开编码器");
        }
        av_dict_free(&opts);
        
        AVStream* ost = avformat_new_stream(ofmt_ctx, nullptr);
        avcodec_parameters_from_context(ost->codecpar, octx);
        ost->time_base = octx->time_base;
        
        if (!(ofmt_ctx->oformat->flags & AVFMT_NOFILE)) {
            if (avio_open(&ofmt_ctx->pb, output_path.c_str(), AVIO_FLAG_WRITE) < 0) {
                throw std::runtime_error("无法打开输出文件");
            }
        }
        
        if (avformat_write_header(ofmt_ctx, nullptr) < 0) {
            throw std::runtime_error("无法写入头部");
        }
        
        frame = av_frame_alloc();
        pkt = av_packet_alloc();
        
        int global_frame_count = 0;
        double total_frames = 0;
        
        for (const auto& clip : clips) {
            VideoInfo info = analyzeVideo(clip.source_path);
            total_frames += info.duration * info.fps;
        }
        
        for (size_t i = 0; i < clips.size(); i++) {
            const auto& clip = clips[i];
            
            AVFormatContext* ifmt_ctx = nullptr;
            AVCodecContext* ictx = nullptr;
            int video_stream = -1;
            
            if (avformat_open_input(&ifmt_ctx, clip.source_path.c_str(), nullptr, nullptr) < 0) {
                continue;
            }
            
            if (avformat_find_stream_info(ifmt_ctx, nullptr) < 0) {
                avformat_close_input(&ifmt_ctx);
                continue;
            }
            
            for (unsigned int j = 0; j < ifmt_ctx->nb_streams; j++) {
                if (ifmt_ctx->streams[j]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
                    video_stream = j;
                    break;
                }
            }
            
            if (video_stream == -1) {
                avformat_close_input(&ifmt_ctx);
                continue;
            }
            
            AVCodecParameters* icodecpar = ifmt_ctx->streams[video_stream]->codecpar;
            const AVCodec* idecoder = avcodec_find_decoder(icodecpar->codec_id);
            
            ictx = avcodec_alloc_context3(idecoder);
            avcodec_parameters_to_context(ictx, icodecpar);
            avcodec_open2(ictx, idecoder, nullptr);
            
            int64_t start_ts = (int64_t)(clip.start_time * AV_TIME_BASE);
            av_seek_frame(ifmt_ctx, video_stream, start_ts, AVSEEK_FLAG_BACKWARD);
            
            double end_time = clip.end_time > clip.start_time ? clip.end_time : clip.start_time + clip.duration;
            
            while (av_read_frame(ifmt_ctx, pkt) >= 0) {
                if (pkt->stream_index != video_stream) {
                    av_packet_unref(pkt);
                    continue;
                }
                
                if (avcodec_send_packet(ictx, pkt) < 0) {
                    av_packet_unref(pkt);
                    continue;
                }
                
                while (avcodec_receive_frame(ictx, frame) >= 0) {
                    double frame_time = frame->pts * av_q2d(ifmt_ctx->streams[video_stream]->time_base);
                    if (frame_time > end_time) {
                        goto next_clip;
                    }
                    
                    AVFrame* out_frame = av_frame_alloc();
                    out_frame->format = octx->pix_fmt;
                    out_frame->width = octx->width;
                    out_frame->height = octx->height;
                    av_frame_get_buffer(out_frame, 32);
                    
                    sws_ctx = sws_getContext(
                        frame->width, frame->height, (AVPixelFormat)frame->format,
                        octx->width, octx->height, octx->pix_fmt,
                        SWS_BILINEAR, nullptr, nullptr, nullptr
                    );
                    
                    sws_scale(sws_ctx, frame->data, frame->linesize, 0, frame->height,
                              out_frame->data, out_frame->linesize);
                    
                    out_frame->pts = global_frame_count++;
                    
                    if (avcodec_send_frame(octx, out_frame) >= 0) {
                        AVPacket* opkt = av_packet_alloc();
                        while (avcodec_receive_packet(octx, opkt) >= 0) {
                            av_interleaved_write_frame(ofmt_ctx, opkt);
                            av_packet_unref(opkt);
                        }
                        av_packet_free(&opkt);
                    }
                    
                    av_frame_free(&out_frame);
                    
                    if (progress_cb) {
                        double p = std::min(1.0, global_frame_count / total_frames);
                        progress_cb(p, "合并中...");
                    }
                }
                
                av_packet_unref(pkt);
            }
            
        next_clip:
            if (sws_ctx) {
                sws_freeContext(sws_ctx);
                sws_ctx = nullptr;
            }
            if (ictx) avcodec_free_context(&ictx);
            if (ifmt_ctx) avformat_close_input(&ifmt_ctx);
        }
        
        while (avcodec_receive_packet(octx, pkt) >= 0) {
            av_interleaved_write_frame(ofmt_ctx, pkt);
            av_packet_unref(pkt);
        }
        
        av_write_trailer(ofmt_ctx);
        success = true;
        
    } catch (const std::exception& e) {
        if (progress_cb) {
            progress_cb(-1.0, std::string("合并失败: ") + e.what());
        }
    }
    
    if (sws_ctx) sws_freeContext(sws_ctx);
    if (pkt) av_packet_free(&pkt);
    if (frame) av_frame_free(&frame);
    if (octx) avcodec_free_context(&octx);
    if (ofmt_ctx && !(ofmt_ctx->oformat->flags & AVFMT_NOFILE)) {
        avio_closep(&ofmt_ctx->pb);
    }
    if (ofmt_ctx) avformat_free_context(ofmt_ctx);
    
    if (progress_cb && success) {
        progress_cb(1.0, "合并完成");
    }
    
    return success;
}

bool VideoEngine::addWatermark(
    const std::string& input_path,
    const std::string& output_path,
    const std::string& text,
    int font_size,
    const std::string& color,
    int x,
    int y
) {
    AVFormatContext* ifmt_ctx = nullptr;
    AVFormatContext* ofmt_ctx = nullptr;
    AVCodecContext* ictx = nullptr;
    AVCodecContext* octx = nullptr;
    AVCodecContext* aictx = nullptr;
    AVCodecContext* aoctx = nullptr;
    AVFrame* frame = nullptr;
    AVPacket* pkt = nullptr;
    
    AVFilterGraph* filter_graph = nullptr;
    AVFilterContext* buffersrc_ctx = nullptr;
    AVFilterContext* drawtext_ctx = nullptr;
    AVFilterContext* buffersink_ctx = nullptr;
    
    int video_stream = -1;
    int audio_stream = -1;
    bool success = false;
    
    try {
        if (avformat_open_input(&ifmt_ctx, input_path.c_str(), nullptr, nullptr) < 0) {
            throw std::runtime_error("无法打开输入文件");
        }
        
        if (avformat_find_stream_info(ifmt_ctx, nullptr) < 0) {
            throw std::runtime_error("无法获取流信息");
        }
        
        for (unsigned int i = 0; i < ifmt_ctx->nb_streams; i++) {
            if (ifmt_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO && video_stream == -1) {
                video_stream = i;
            } else if (ifmt_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_AUDIO && audio_stream == -1) {
                audio_stream = i;
            }
        }
        
        if (video_stream == -1) {
            throw std::runtime_error("未找到视频流");
        }
        
        AVCodecParameters* icodecpar = ifmt_ctx->streams[video_stream]->codecpar;
        const AVCodec* idecoder = avcodec_find_decoder(icodecpar->codec_id);
        
        ictx = avcodec_alloc_context3(idecoder);
        avcodec_parameters_to_context(ictx, icodecpar);
        avcodec_open2(ictx, idecoder, nullptr);
        
        if (audio_stream != -1) {
            AVCodecParameters* aicodecpar = ifmt_ctx->streams[audio_stream]->codecpar;
            const AVCodec* aidecoder = avcodec_find_decoder(aicodecpar->codec_id);
            
            aictx = avcodec_alloc_context3(aidecoder);
            avcodec_parameters_to_context(aictx, aicodecpar);
            avcodec_open2(aictx, aidecoder, nullptr);
        }
        
        filter_graph = createFilterGraph();
        if (!filter_graph) {
            throw std::runtime_error("无法创建滤镜图");
        }
        
        buffersrc_ctx = createBufferSource(filter_graph, ictx, "in");
        if (!buffersrc_ctx) {
            throw std::runtime_error("无法创建 buffer 源");
        }
        
        buffersink_ctx = createBufferSink(filter_graph, AVMEDIA_TYPE_VIDEO, "out");
        if (!buffersink_ctx) {
            throw std::runtime_error("无法创建 buffer sink");
        }
        
        char drawtext_args[1024];
        const char* x_expr = (x >= 0) ? std::to_string(x).c_str() : "(w-text_w)/2";
        const char* y_expr = (y >= 0) ? std::to_string(y).c_str() : "(h-text_h)/2";
        
        snprintf(drawtext_args, sizeof(drawtext_args),
                 "text='%s':fontsize=%d:fontcolor=%s:x=%s:y=%s",
                 text.c_str(), font_size, color.c_str(), x_expr, y_expr);
        
        const AVFilter* drawtext = avfilter_get_by_name("drawtext");
        if (!drawtext) {
            throw std::runtime_error("drawtext 滤镜不可用");
        }
        
        if (avfilter_graph_create_filter(&drawtext_ctx, drawtext, "drawtext",
                                         drawtext_args, nullptr, filter_graph) < 0) {
            throw std::runtime_error("无法创建 drawtext 滤镜");
        }
        
        if (avfilter_link(buffersrc_ctx, 0, drawtext_ctx, 0) < 0) {
            throw std::runtime_error("无法链接 buffersrc -> drawtext");
        }
        
        if (avfilter_link(drawtext_ctx, 0, buffersink_ctx, 0) < 0) {
            throw std::runtime_error("无法链接 drawtext -> buffersink");
        }
        
        if (!configureFilterGraph(filter_graph)) {
            throw std::runtime_error("无法配置滤镜图");
        }
        
        if (avformat_alloc_output_context2(&ofmt_ctx, nullptr, nullptr, output_path.c_str()) < 0) {
            throw std::runtime_error("无法创建输出上下文");
        }
        
        const AVCodec* oencoder = selectHardwareEncoder();
        
        octx = avcodec_alloc_context3(oencoder);
        octx->codec_id = oencoder->id;
        octx->codec_type = AVMEDIA_TYPE_VIDEO;
        octx->pix_fmt = AV_PIX_FMT_YUV420P;
        octx->width = ictx->width;
        octx->height = ictx->height;
        octx->time_base = ifmt_ctx->streams[video_stream]->time_base;
        octx->framerate = ifmt_ctx->streams[video_stream]->r_frame_rate;
        octx->bit_rate = 5000000;
        
        AVDictionary* opts = nullptr;
        av_dict_set(&opts, "preset", "fast", 0);
        av_dict_set(&opts, "crf", "23", 0);
        
        if (avcodec_open2(octx, oencoder, &opts) < 0) {
            throw std::runtime_error("无法打开编码器");
        }
        av_dict_free(&opts);
        
        AVStream* v_ost = avformat_new_stream(ofmt_ctx, nullptr);
        avcodec_parameters_from_context(v_ost->codecpar, octx);
        v_ost->time_base = octx->time_base;
        
        if (audio_stream != -1) {
            const AVCodec* aoencoder = avcodec_find_encoder(AV_CODEC_ID_AAC);
            
            aoctx = avcodec_alloc_context3(aoencoder);
            aoctx->codec_id = AV_CODEC_ID_AAC;
            aoctx->codec_type = AVMEDIA_TYPE_AUDIO;
            aoctx->sample_fmt = AV_SAMPLE_FMT_FLTP;
            aoctx->sample_rate = aictx->sample_rate;
            aoctx->channels = aictx->channels;
            aoctx->bit_rate = 128000;
            
            AVDictionary* aopts = nullptr;
            avcodec_open2(aoctx, aoencoder, &aopts);
            av_dict_free(&aopts);
            
            AVStream* a_ost = avformat_new_stream(ofmt_ctx, nullptr);
            avcodec_parameters_from_context(a_ost->codecpar, aoctx);
            a_ost->time_base = {1, aoctx->sample_rate};
        }
        
        if (!(ofmt_ctx->oformat->flags & AVFMT_NOFILE)) {
            if (avio_open(&ofmt_ctx->pb, output_path.c_str(), AVIO_FLAG_WRITE) < 0) {
                throw std::runtime_error("无法打开输出文件");
            }
        }
        
        if (avformat_write_header(ofmt_ctx, nullptr) < 0) {
            throw std::runtime_error("无法写入头部");
        }
        
        frame = av_frame_alloc();
        pkt = av_packet_alloc();
        
        int frame_count = 0;
        
        while (av_read_frame(ifmt_ctx, pkt) >= 0) {
            if (pkt->stream_index == video_stream) {
                if (avcodec_send_packet(ictx, pkt) >= 0) {
                    while (avcodec_receive_frame(ictx, frame) >= 0) {
                        AVFrame* filtered_frame = av_frame_clone(frame);
                        
                        if (av_buffersrc_add_frame_flags(buffersrc_ctx, filtered_frame, AV_BUFFERSRC_FLAG_KEEP_REF) < 0) {
                            av_frame_free(&filtered_frame);
                            continue;
                        }
                        
                        AVFrame* out_frame = av_frame_alloc();
                        while (av_buffersink_get_frame(buffersink_ctx, out_frame) >= 0) {
                            AVFrame* encoded_frame = av_frame_alloc();
                            encoded_frame->format = octx->pix_fmt;
                            encoded_frame->width = octx->width;
                            encoded_frame->height = octx->height;
                            av_frame_get_buffer(encoded_frame, 32);
                            
                            SwsContext* sws_ctx = sws_getContext(
                                out_frame->width, out_frame->height, (AVPixelFormat)out_frame->format,
                                octx->width, octx->height, octx->pix_fmt,
                                SWS_BILINEAR, nullptr, nullptr, nullptr
                            );
                            
                            sws_scale(sws_ctx, out_frame->data, out_frame->linesize, 0, out_frame->height,
                                      encoded_frame->data, encoded_frame->linesize);
                            
                            sws_freeContext(sws_ctx);
                            
                            encoded_frame->pts = frame_count++;
                            
                            if (avcodec_send_frame(octx, encoded_frame) >= 0) {
                                AVPacket* opkt = av_packet_alloc();
                                while (avcodec_receive_packet(octx, opkt) >= 0) {
                                    av_interleaved_write_frame(ofmt_ctx, opkt);
                                    av_packet_unref(opkt);
                                }
                                av_packet_free(&opkt);
                            }
                            
                            av_frame_free(&encoded_frame);
                            av_frame_unref(out_frame);
                        }
                        
                        av_frame_free(&out_frame);
                        av_frame_free(&filtered_frame);
                    }
                }
            } else if (pkt->stream_index == audio_stream && audio_stream != -1) {
                if (avcodec_send_packet(aictx, pkt) >= 0) {
                    while (avcodec_receive_frame(aictx, frame) >= 0) {
                        AVFrame* out_frame = av_frame_clone(frame);
                        
                        if (avcodec_send_frame(aoctx, out_frame) >= 0) {
                            AVPacket* opkt = av_packet_alloc();
                            while (avcodec_receive_packet(aoctx, opkt) >= 0) {
                                av_interleaved_write_frame(ofmt_ctx, opkt);
                                av_packet_unref(opkt);
                            }
                            av_packet_free(&opkt);
                        }
                        
                        av_frame_free(&out_frame);
                    }
                }
            }
            
            av_packet_unref(pkt);
        }
        
        while (avcodec_receive_packet(octx, pkt) >= 0) {
            av_interleaved_write_frame(ofmt_ctx, pkt);
            av_packet_unref(pkt);
        }
        
        if (audio_stream != -1) {
            while (avcodec_receive_packet(aoctx, pkt) >= 0) {
                av_interleaved_write_frame(ofmt_ctx, pkt);
                av_packet_unref(pkt);
            }
        }
        
        av_write_trailer(ofmt_ctx);
        success = true;
        
    } catch (const std::exception& e) {
        // 忽略水印添加失败
    }
    
    freeFilterGraph(filter_graph);
    if (pkt) av_packet_free(&pkt);
    if (frame) av_frame_free(&frame);
    if (aoctx) avcodec_free_context(&aoctx);
    if (octx) avcodec_free_context(&octx);
    if (aictx) avcodec_free_context(&aictx);
    if (ictx) avcodec_free_context(&ictx);
    if (ofmt_ctx && !(ofmt_ctx->oformat->flags & AVFMT_NOFILE)) {
        avio_closep(&ofmt_ctx->pb);
    }
    if (ofmt_ctx) avformat_free_context(ofmt_ctx);
    if (ifmt_ctx) avformat_close_input(&ifmt_ctx);
    
    return success;
}

bool VideoEngine::addBackgroundMusic(
    const std::string& video_path,
    const std::string& audio_path,
    const std::string& output_path,
    double audio_volume,
    double video_volume
) {
    AVFormatContext* vf_ctx = nullptr;
    AVFormatContext* af_ctx = nullptr;
    AVFormatContext* ofmt_ctx = nullptr;
    AVCodecContext* vctx = nullptr;
    AVCodecContext* a1ctx = nullptr;
    AVCodecContext* a2ctx = nullptr;
    AVCodecContext* o_vctx = nullptr;
    AVCodecContext* o_actx = nullptr;
    AVFrame* frame = nullptr;
    AVPacket* pkt = nullptr;
    SwsContext* sws_ctx = nullptr;
    
    AVFilterGraph* filter_graph = nullptr;
    AVFilterContext* abuffer1_ctx = nullptr;
    AVFilterContext* abuffer2_ctx = nullptr;
    AVFilterContext* volume1_ctx = nullptr;
    AVFilterContext* volume2_ctx = nullptr;
    AVFilterContext* amix_ctx = nullptr;
    AVFilterContext* abuffersink_ctx = nullptr;
    
    int video_stream = -1;
    int audio1_stream = -1;
    int audio2_stream = -1;
    bool success = false;
    
    try {
        if (avformat_open_input(&vf_ctx, video_path.c_str(), nullptr, nullptr) < 0) {
            throw std::runtime_error("无法打开视频文件");
        }
        if (avformat_find_stream_info(vf_ctx, nullptr) < 0) {
            throw std::runtime_error("无法获取视频流信息");
        }
        
        for (unsigned int i = 0; i < vf_ctx->nb_streams; i++) {
            if (vf_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
                video_stream = i;
            } else if (vf_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_AUDIO) {
                audio1_stream = i;
            }
        }
        
        if (avformat_open_input(&af_ctx, audio_path.c_str(), nullptr, nullptr) < 0) {
            throw std::runtime_error("无法打开音频文件");
        }
        if (avformat_find_stream_info(af_ctx, nullptr) < 0) {
            throw std::runtime_error("无法获取音频流信息");
        }
        
        for (unsigned int i = 0; i < af_ctx->nb_streams; i++) {
            if (af_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_AUDIO) {
                audio2_stream = i;
                break;
            }
        }
        
        if (video_stream == -1) {
            throw std::runtime_error("未找到视频流");
        }
        
        AVCodecParameters* vpar = vf_ctx->streams[video_stream]->codecpar;
        const AVCodec* vdecoder = avcodec_find_decoder(vpar->codec_id);
        vctx = avcodec_alloc_context3(vdecoder);
        avcodec_parameters_to_context(vctx, vpar);
        avcodec_open2(vctx, vdecoder, nullptr);
        
        if (audio1_stream != -1) {
            AVCodecParameters* a1par = vf_ctx->streams[audio1_stream]->codecpar;
            const AVCodec* a1decoder = avcodec_find_decoder(a1par->codec_id);
            a1ctx = avcodec_alloc_context3(a1decoder);
            avcodec_parameters_to_context(a1ctx, a1par);
            avcodec_open2(a1ctx, a1decoder, nullptr);
        }
        
        if (audio2_stream != -1) {
            AVCodecParameters* a2par = af_ctx->streams[audio2_stream]->codecpar;
            const AVCodec* a2decoder = avcodec_find_decoder(a2par->codec_id);
            a2ctx = avcodec_alloc_context3(a2decoder);
            avcodec_parameters_to_context(a2ctx, a2par);
            avcodec_open2(a2ctx, a2decoder, nullptr);
        }
        
        if (audio1_stream != -1 || audio2_stream != -1) {
            filter_graph = createFilterGraph();
            if (!filter_graph) {
                throw std::runtime_error("无法创建滤镜图");
            }
            
            int sample_rate = 44100;
            int channels = 2;
            
            if (audio1_stream != -1) {
                sample_rate = a1ctx->sample_rate;
                channels = a1ctx->channels;
            } else if (audio2_stream != -1) {
                sample_rate = a2ctx->sample_rate;
                channels = a2ctx->channels;
            }
            
            if (audio1_stream != -1) {
                char abuffer1_args[512];
                snprintf(abuffer1_args, sizeof(abuffer1_args),
                         "time_base=%d/%d:sample_rate=%d:sample_fmt=%d:channel_layout=0x%" PRIx64,
                         a1ctx->time_base.num, a1ctx->time_base.den,
                         a1ctx->sample_rate,
                         a1ctx->sample_fmt,
                         a1ctx->channel_layout);
                
                const AVFilter* abuffer = avfilter_get_by_name("abuffer");
                if (avfilter_graph_create_filter(&abuffer1_ctx, abuffer, "abuffer1",
                                                 abuffer1_args, nullptr, filter_graph) < 0) {
                    throw std::runtime_error("无法创建 abuffer1");
                }
            }
            
            if (audio2_stream != -1) {
                char abuffer2_args[512];
                snprintf(abuffer2_args, sizeof(abuffer2_args),
                         "time_base=%d/%d:sample_rate=%d:sample_fmt=%d:channel_layout=0x%" PRIx64,
                         a2ctx->time_base.num, a2ctx->time_base.den,
                         a2ctx->sample_rate,
                         a2ctx->sample_fmt,
                         a2ctx->channel_layout);
                
                const AVFilter* abuffer = avfilter_get_by_name("abuffer");
                if (avfilter_graph_create_filter(&abuffer2_ctx, abuffer, "abuffer2",
                                                 abuffer2_args, nullptr, filter_graph) < 0) {
                    throw std::runtime_error("无法创建 abuffer2");
                }
            }
            
            if (audio1_stream != -1) {
                char volume1_args[64];
                snprintf(volume1_args, sizeof(volume1_args), "%f", video_volume);
                
                const AVFilter* volume = avfilter_get_by_name("volume");
                if (avfilter_graph_create_filter(&volume1_ctx, volume, "volume1",
                                                 volume1_args, nullptr, filter_graph) < 0) {
                    throw std::runtime_error("无法创建 volume1");
                }
                
                if (avfilter_link(abuffer1_ctx, 0, volume1_ctx, 0) < 0) {
                    throw std::runtime_error("无法链接 abuffer1 -> volume1");
                }
            }
            
            if (audio2_stream != -1) {
                char volume2_args[64];
                snprintf(volume2_args, sizeof(volume2_args), "%f", audio_volume);
                
                const AVFilter* volume = avfilter_get_by_name("volume");
                if (avfilter_graph_create_filter(&volume2_ctx, volume, "volume2",
                                                 volume2_args, nullptr, filter_graph) < 0) {
                    throw std::runtime_error("无法创建 volume2");
                }
                
                if (avfilter_link(abuffer2_ctx, 0, volume2_ctx, 0) < 0) {
                    throw std::runtime_error("无法链接 abuffer2 -> volume2");
                }
            }
            
            char amix_args[64];
            int inputs = 0;
            if (audio1_stream != -1) inputs++;
            if (audio2_stream != -1) inputs++;
            snprintf(amix_args, sizeof(amix_args), "inputs=%d:duration=first", inputs);
            
            const AVFilter* amix = avfilter_get_by_name("amix");
            if (avfilter_graph_create_filter(&amix_ctx, amix, "amix",
                                             amix_args, nullptr, filter_graph) < 0) {
                throw std::runtime_error("无法创建 amix");
            }
            
            if (audio1_stream != -1) {
                if (avfilter_link(volume1_ctx, 0, amix_ctx, 0) < 0) {
                    throw std::runtime_error("无法链接 volume1 -> amix");
                }
            }
            
            if (audio2_stream != -1) {
                int pad_idx = (audio1_stream != -1) ? 1 : 0;
                if (avfilter_link(volume2_ctx, 0, amix_ctx, pad_idx) < 0) {
                    throw std::runtime_error("无法链接 volume2 -> amix");
                }
            }
            
            abuffersink_ctx = createBufferSink(filter_graph, AVMEDIA_TYPE_AUDIO, "abuffersink");
            if (!abuffersink_ctx) {
                throw std::runtime_error("无法创建 abuffersink");
            }
            
            if (avfilter_link(amix_ctx, 0, abuffersink_ctx, 0) < 0) {
                throw std::runtime_error("无法链接 amix -> abuffersink");
            }
            
            if (!configureFilterGraph(filter_graph)) {
                throw std::runtime_error("无法配置滤镜图");
            }
        }
        
        if (avformat_alloc_output_context2(&ofmt_ctx, nullptr, nullptr, output_path.c_str()) < 0) {
            throw std::runtime_error("无法创建输出上下文");
        }
        
        const AVCodec* o_vencoder = selectHardwareEncoder();
        o_vctx = avcodec_alloc_context3(o_vencoder);
        o_vctx->codec_id = o_vencoder->id;
        o_vctx->codec_type = AVMEDIA_TYPE_VIDEO;
        o_vctx->pix_fmt = AV_PIX_FMT_YUV420P;
        o_vctx->width = vctx->width;
        o_vctx->height = vctx->height;
        o_vctx->time_base = {1, 30};
        o_vctx->framerate = {30, 1};
        o_vctx->bit_rate = 5000000;
        
        AVDictionary* vopts = nullptr;
        av_dict_set(&vopts, "preset", "fast", 0);
        av_dict_set(&vopts, "crf", "23", 0);
        avcodec_open2(o_vctx, o_vencoder, &vopts);
        av_dict_free(&vopts);
        
        AVStream* v_ost = avformat_new_stream(ofmt_ctx, nullptr);
        avcodec_parameters_from_context(v_ost->codecpar, o_vctx);
        v_ost->time_base = o_vctx->time_base;
        
        const AVCodec* o_aencoder = avcodec_find_encoder(AV_CODEC_ID_AAC);
        o_actx = avcodec_alloc_context3(o_aencoder);
        o_actx->codec_id = AV_CODEC_ID_AAC;
        o_actx->codec_type = AVMEDIA_TYPE_AUDIO;
        o_actx->sample_fmt = AV_SAMPLE_FMT_FLTP;
        o_actx->sample_rate = 44100;
        o_actx->channels = 2;
        o_actx->bit_rate = 128000;
        
        AVDictionary* aopts = nullptr;
        avcodec_open2(o_actx, o_aencoder, &aopts);
        av_dict_free(&aopts);
        
        AVStream* a_ost = avformat_new_stream(ofmt_ctx, nullptr);
        avcodec_parameters_from_context(a_ost->codecpar, o_actx);
        a_ost->time_base = {1, o_actx->sample_rate};
        
        if (!(ofmt_ctx->oformat->flags & AVFMT_NOFILE)) {
            if (avio_open(&ofmt_ctx->pb, output_path.c_str(), AVIO_FLAG_WRITE) < 0) {
                throw std::runtime_error("无法打开输出文件");
            }
        }
        
        if (avformat_write_header(ofmt_ctx, nullptr) < 0) {
            throw std::runtime_error("无法写入头部");
        }
        
        frame = av_frame_alloc();
        pkt = av_packet_alloc();
        
        int frame_count = 0;
        bool a1_done = (audio1_stream == -1);
        bool a2_done = (audio2_stream == -1);
        
        while (!a1_done || !a2_done) {
            if (!a1_done) {
                if (av_read_frame(vf_ctx, pkt) >= 0) {
                    if (pkt->stream_index == audio1_stream) {
                        if (avcodec_send_packet(a1ctx, pkt) >= 0) {
                            while (avcodec_receive_frame(a1ctx, frame) >= 0) {
                                AVFrame* filtered_frame = av_frame_clone(frame);
                                av_buffersrc_add_frame_flags(abuffer1_ctx, filtered_frame, AV_BUFFERSRC_FLAG_KEEP_REF);
                                av_frame_free(&filtered_frame);
                            }
                        }
                    }
                    av_packet_unref(pkt);
                } else {
                    a1_done = true;
                    av_buffersrc_close(abuffer1_ctx, 0, 0);
                }
            }
            
            if (!a2_done) {
                if (av_read_frame(af_ctx, pkt) >= 0) {
                    if (pkt->stream_index == audio2_stream) {
                        if (avcodec_send_packet(a2ctx, pkt) >= 0) {
                            while (avcodec_receive_frame(a2ctx, frame) >= 0) {
                                AVFrame* filtered_frame = av_frame_clone(frame);
                                av_buffersrc_add_frame_flags(abuffer2_ctx, filtered_frame, AV_BUFFERSRC_FLAG_KEEP_REF);
                                av_frame_free(&filtered_frame);
                            }
                        }
                    }
                    av_packet_unref(pkt);
                } else {
                    a2_done = true;
                    av_buffersrc_close(abuffer2_ctx, 0, 0);
                }
            }
            
            if (filter_graph) {
                AVFrame* out_frame = av_frame_alloc();
                while (av_buffersink_get_frame(abuffersink_ctx, out_frame) >= 0) {
                    AVFrame* encoded_frame = av_frame_alloc();
                    encoded_frame->format = o_actx->sample_fmt;
                    encoded_frame->sample_rate = o_actx->sample_rate;
                    encoded_frame->channels = o_actx->channels;
                    encoded_frame->nb_samples = out_frame->nb_samples;
                    av_frame_get_buffer(encoded_frame, 0);
                    
                    SwrContext* swr_ctx = swr_alloc_set_opts(
                        nullptr,
                        av_get_default_channel_layout(o_actx->channels),
                        o_actx->sample_fmt,
                        o_actx->sample_rate,
                        av_get_default_channel_layout(out_frame->channels),
                        (AVSampleFormat)out_frame->format,
                        out_frame->sample_rate,
                        0, nullptr
                    );
                    swr_init(swr_ctx);
                    
                    swr_convert(swr_ctx, encoded_frame->data, encoded_frame->nb_samples,
                               (const uint8_t**)out_frame->data, out_frame->nb_samples);
                    
                    swr_free(&swr_ctx);
                    
                    if (avcodec_send_frame(o_actx, encoded_frame) >= 0) {
                        AVPacket* opkt = av_packet_alloc();
                        while (avcodec_receive_packet(o_actx, opkt) >= 0) {
                            av_interleaved_write_frame(ofmt_ctx, opkt);
                            av_packet_unref(opkt);
                        }
                        av_packet_free(&opkt);
                    }
                    
                    av_frame_free(&encoded_frame);
                    av_frame_unref(out_frame);
                }
                av_frame_free(&out_frame);
            }
        }
        
        avformat_seek_file(vf_ctx, video_stream, 0, 0, 0, 0);
        
        while (av_read_frame(vf_ctx, pkt) >= 0) {
            if (pkt->stream_index == video_stream) {
                if (avcodec_send_packet(vctx, pkt) >= 0) {
                    while (avcodec_receive_frame(vctx, frame) >= 0) {
                        AVFrame* out_frame = av_frame_alloc();
                        out_frame->format = o_vctx->pix_fmt;
                        out_frame->width = o_vctx->width;
                        out_frame->height = o_vctx->height;
                        av_frame_get_buffer(out_frame, 32);
                        
                        sws_ctx = sws_getContext(
                            frame->width, frame->height, (AVPixelFormat)frame->format,
                            o_vctx->width, o_vctx->height, o_vctx->pix_fmt,
                            SWS_BILINEAR, nullptr, nullptr, nullptr
                        );
                        
                        sws_scale(sws_ctx, frame->data, frame->linesize, 0, frame->height,
                                  out_frame->data, out_frame->linesize);
                        
                        sws_freeContext(sws_ctx);
                        
                        out_frame->pts = frame_count++;
                        
                        if (avcodec_send_frame(o_vctx, out_frame) >= 0) {
                            AVPacket* opkt = av_packet_alloc();
                            while (avcodec_receive_packet(o_vctx, opkt) >= 0) {
                                av_interleaved_write_frame(ofmt_ctx, opkt);
                                av_packet_unref(opkt);
                            }
                            av_packet_free(&opkt);
                        }
                        
                        av_frame_free(&out_frame);
                    }
                }
            }
            
            av_packet_unref(pkt);
        }
        
        while (avcodec_receive_packet(o_vctx, pkt) >= 0) {
            av_interleaved_write_frame(ofmt_ctx, pkt);
            av_packet_unref(pkt);
        }
        
        while (avcodec_receive_packet(o_actx, pkt) >= 0) {
            av_interleaved_write_frame(ofmt_ctx, pkt);
            av_packet_unref(pkt);
        }
        
        av_write_trailer(ofmt_ctx);
        success = true;
        
    } catch (const std::exception& e) {
        // 忽略背景音乐添加失败
    }
    
    freeFilterGraph(filter_graph);
    if (sws_ctx) sws_freeContext(sws_ctx);
    if (pkt) av_packet_free(&pkt);
    if (frame) av_frame_free(&frame);
    if (o_actx) avcodec_free_context(&o_actx);
    if (o_vctx) avcodec_free_context(&o_vctx);
    if (a2ctx) avcodec_free_context(&a2ctx);
    if (a1ctx) avcodec_free_context(&a1ctx);
    if (vctx) avcodec_free_context(&vctx);
    if (ofmt_ctx && !(ofmt_ctx->oformat->flags & AVFMT_NOFILE)) {
        avio_closep(&ofmt_ctx->pb);
    }
    if (ofmt_ctx) avformat_free_context(ofmt_ctx);
    if (af_ctx) avformat_close_input(&af_ctx);
    if (vf_ctx) avformat_close_input(&vf_ctx);
    
    return success;
}

bool VideoEngine::detectGpuEncoder(std::string& encoder_name) {
    // 检测 NVIDIA NVENC
    if (checkNvenc()) {
        encoder_name = "h264_nvenc";
        return true;
    }
    
    // 检测 AMD AMF
    if (checkAmf()) {
        encoder_name = "h264_amf";
        return true;
    }
    
    // 检测 Intel QSV
    if (checkQsv()) {
        encoder_name = "h264_qsv";
        return true;
    }
    
    encoder_name = "libx264";
    return false;
}

bool VideoEngine::checkNvenc() {
    const AVCodec* codec = avcodec_find_encoder_by_name("h264_nvenc");
    return codec != nullptr;
}

bool VideoEngine::checkAmf() {
    const AVCodec* codec = avcodec_find_encoder_by_name("h264_amf");
    return codec != nullptr;
}

bool VideoEngine::checkQsv() {
    const AVCodec* codec = avcodec_find_encoder_by_name("h264_qsv");
    return codec != nullptr;
}

bool VideoEngine::convertFormat(
    const std::string& input_path,
    const std::string& output_path,
    const ExportConfig& config,
    ProgressCallback progress_cb
) {
    AVFormatContext* ifmt_ctx = nullptr;
    AVFormatContext* ofmt_ctx = nullptr;
    AVCodecContext* ictx = nullptr;
    AVCodecContext* octx = nullptr;
    AVFrame* frame = nullptr;
    AVPacket* pkt = nullptr;
    SwsContext* sws_ctx = nullptr;
    
    int video_stream = -1;
    bool success = false;
    
    try {
        if (avformat_open_input(&ifmt_ctx, input_path.c_str(), nullptr, nullptr) < 0) {
            throw std::runtime_error("无法打开输入文件");
        }
        
        if (avformat_find_stream_info(ifmt_ctx, nullptr) < 0) {
            throw std::runtime_error("无法获取流信息");
        }
        
        for (unsigned int i = 0; i < ifmt_ctx->nb_streams; i++) {
            if (ifmt_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
                video_stream = i;
                break;
            }
        }
        
        if (video_stream == -1) {
            throw std::runtime_error("未找到视频流");
        }
        
        AVCodecParameters* icodecpar = ifmt_ctx->streams[video_stream]->codecpar;
        const AVCodec* idecoder = avcodec_find_decoder(icodecpar->codec_id);
        
        ictx = avcodec_alloc_context3(idecoder);
        avcodec_parameters_to_context(ictx, icodecpar);
        avcodec_open2(ictx, idecoder, nullptr);
        
        if (avformat_alloc_output_context2(&ofmt_ctx, nullptr, nullptr, output_path.c_str()) < 0) {
            throw std::runtime_error("无法创建输出上下文");
        }
        
        const AVCodec* oencoder = selectHardwareEncoder();
        if (!oencoder) {
            throw std::runtime_error("未找到编码器");
        }
        
        octx = avcodec_alloc_context3(oencoder);
        octx->codec_id = oencoder->id;
        octx->codec_type = AVMEDIA_TYPE_VIDEO;
        octx->pix_fmt = AV_PIX_FMT_YUV420P;
        octx->width = config.width > 0 ? config.width : ictx->width;
        octx->height = config.height > 0 ? config.height : ictx->height;
        octx->time_base = {1, static_cast<int>(config.fps > 0 ? config.fps : av_q2d(ifmt_ctx->streams[video_stream]->r_frame_rate))};
        octx->framerate = {static_cast<int>(config.fps > 0 ? config.fps : av_q2d(ifmt_ctx->streams[video_stream]->r_frame_rate)), 1};
        octx->bit_rate = config.bitrate > 0 ? config.bitrate * 1000 : 5000000;
        
        AVDictionary* opts = nullptr;
        av_dict_set(&opts, "preset", config.preset.c_str(), 0);
        av_dict_set(&opts, "crf", "23", 0);
        
        std::string encoder_name = avcodec_get_name(oencoder->id);
        setHardwareEncoderOptions(octx, encoder_name);
        
        if (avcodec_open2(octx, oencoder, &opts) < 0) {
            throw std::runtime_error("无法打开编码器");
        }
        av_dict_free(&opts);
        
        AVStream* ost = avformat_new_stream(ofmt_ctx, nullptr);
        avcodec_parameters_from_context(ost->codecpar, octx);
        ost->time_base = octx->time_base;
        
        if (!(ofmt_ctx->oformat->flags & AVFMT_NOFILE)) {
            if (avio_open(&ofmt_ctx->pb, output_path.c_str(), AVIO_FLAG_WRITE) < 0) {
                throw std::runtime_error("无法打开输出文件");
            }
        }
        
        if (avformat_write_header(ofmt_ctx, nullptr) < 0) {
            throw std::runtime_error("无法写入头部");
        }
        
        frame = av_frame_alloc();
        pkt = av_packet_alloc();
        
        int frame_count = 0;
        VideoInfo info = analyzeVideo(input_path);
        double total_frames = info.duration * info.fps;
        
        while (av_read_frame(ifmt_ctx, pkt) >= 0) {
            if (pkt->stream_index != video_stream) {
                av_packet_unref(pkt);
                continue;
            }
            
            if (avcodec_send_packet(ictx, pkt) < 0) {
                av_packet_unref(pkt);
                continue;
            }
            
            while (avcodec_receive_frame(ictx, frame) >= 0) {
                AVFrame* out_frame = av_frame_alloc();
                out_frame->format = octx->pix_fmt;
                out_frame->width = octx->width;
                out_frame->height = octx->height;
                av_frame_get_buffer(out_frame, 32);
                
                sws_ctx = sws_getContext(
                    frame->width, frame->height, (AVPixelFormat)frame->format,
                    octx->width, octx->height, octx->pix_fmt,
                    SWS_BILINEAR, nullptr, nullptr, nullptr
                );
                
                sws_scale(sws_ctx, frame->data, frame->linesize, 0, frame->height,
                          out_frame->data, out_frame->linesize);
                
                out_frame->pts = frame_count++;
                
                if (avcodec_send_frame(octx, out_frame) >= 0) {
                    AVPacket* opkt = av_packet_alloc();
                    while (avcodec_receive_packet(octx, opkt) >= 0) {
                        av_interleaved_write_frame(ofmt_ctx, opkt);
                        av_packet_unref(opkt);
                    }
                    av_packet_free(&opkt);
                }
                
                av_frame_free(&out_frame);
                
                if (progress_cb) {
                    double p = std::min(1.0, frame_count / total_frames);
                    progress_cb(p, "转换中...");
                }
            }
            
            av_packet_unref(pkt);
        }
        
        while (avcodec_receive_packet(octx, pkt) >= 0) {
            av_interleaved_write_frame(ofmt_ctx, pkt);
            av_packet_unref(pkt);
        }
        
        av_write_trailer(ofmt_ctx);
        success = true;
        
    } catch (const std::exception& e) {
        if (progress_cb) {
            progress_cb(-1.0, std::string("转换失败: ") + e.what());
        }
    }
    
    if (sws_ctx) sws_freeContext(sws_ctx);
    if (pkt) av_packet_free(&pkt);
    if (frame) av_frame_free(&frame);
    if (octx) avcodec_free_context(&octx);
    if (ictx) avcodec_free_context(&ictx);
    if (ofmt_ctx && !(ofmt_ctx->oformat->flags & AVFMT_NOFILE)) {
        avio_closep(&ofmt_ctx->pb);
    }
    if (ofmt_ctx) avformat_free_context(ofmt_ctx);
    if (ifmt_ctx) avformat_close_input(&ifmt_ctx);
    
    if (progress_cb && success) {
        progress_cb(1.0, "转换完成");
    }
    
    return success;
}

bool VideoEngine::extractAudio(
    const std::string& video_path,
    const std::string& output_path,
    int sample_rate,
    int channels
) {
    AVFormatContext* ifmt_ctx = nullptr;
    AVFormatContext* ofmt_ctx = nullptr;
    AVCodecContext* ictx = nullptr;
    AVCodecContext* octx = nullptr;
    AVFrame* frame = nullptr;
    AVPacket* pkt = nullptr;
    SwrContext* swr_ctx = nullptr;
    
    int audio_stream = -1;
    bool success = false;
    
    try {
        if (avformat_open_input(&ifmt_ctx, video_path.c_str(), nullptr, nullptr) < 0) {
            throw std::runtime_error("无法打开输入文件");
        }
        
        if (avformat_find_stream_info(ifmt_ctx, nullptr) < 0) {
            throw std::runtime_error("无法获取流信息");
        }
        
        for (unsigned int i = 0; i < ifmt_ctx->nb_streams; i++) {
            if (ifmt_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_AUDIO) {
                audio_stream = i;
                break;
            }
        }
        
        if (audio_stream == -1) {
            throw std::runtime_error("未找到音频流");
        }
        
        AVCodecParameters* icodecpar = ifmt_ctx->streams[audio_stream]->codecpar;
        const AVCodec* idecoder = avcodec_find_decoder(icodecpar->codec_id);
        
        ictx = avcodec_alloc_context3(idecoder);
        avcodec_parameters_to_context(ictx, icodecpar);
        avcodec_open2(ictx, idecoder, nullptr);
        
        if (avformat_alloc_output_context2(&ofmt_ctx, nullptr, nullptr, output_path.c_str()) < 0) {
            throw std::runtime_error("无法创建输出上下文");
        }
        
        const AVCodec* oencoder = avcodec_find_encoder(AV_CODEC_ID_PCM_S16LE);
        
        octx = avcodec_alloc_context3(oencoder);
        octx->codec_id = AV_CODEC_ID_PCM_S16LE;
        octx->codec_type = AVMEDIA_TYPE_AUDIO;
        octx->sample_fmt = AV_SAMPLE_FMT_S16;
        octx->sample_rate = sample_rate > 0 ? sample_rate : ictx->sample_rate;
        octx->channels = channels > 0 ? channels : ictx->channels;
        
        if (avcodec_open2(octx, oencoder, nullptr) < 0) {
            throw std::runtime_error("无法打开编码器");
        }
        
        AVStream* ost = avformat_new_stream(ofmt_ctx, nullptr);
        avcodec_parameters_from_context(ost->codecpar, octx);
        ost->time_base = {1, octx->sample_rate};
        
        if (!(ofmt_ctx->oformat->flags & AVFMT_NOFILE)) {
            if (avio_open(&ofmt_ctx->pb, output_path.c_str(), AVIO_FLAG_WRITE) < 0) {
                throw std::runtime_error("无法打开输出文件");
            }
        }
        
        if (avformat_write_header(ofmt_ctx, nullptr) < 0) {
            throw std::runtime_error("无法写入头部");
        }
        
        frame = av_frame_alloc();
        pkt = av_packet_alloc();
        
        while (av_read_frame(ifmt_ctx, pkt) >= 0) {
            if (pkt->stream_index != audio_stream) {
                av_packet_unref(pkt);
                continue;
            }
            
            if (avcodec_send_packet(ictx, pkt) < 0) {
                av_packet_unref(pkt);
                continue;
            }
            
            while (avcodec_receive_frame(ictx, frame) >= 0) {
                AVFrame* out_frame = av_frame_alloc();
                out_frame->format = octx->sample_fmt;
                out_frame->sample_rate = octx->sample_rate;
                out_frame->channels = octx->channels;
                out_frame->nb_samples = frame->nb_samples;
                av_frame_get_buffer(out_frame, 0);
                
                swr_ctx = swr_alloc_set_opts(
                    nullptr,
                    av_get_default_channel_layout(octx->channels),
                    octx->sample_fmt,
                    octx->sample_rate,
                    av_get_default_channel_layout(ictx->channels),
                    ictx->sample_fmt,
                    ictx->sample_rate,
                    0, nullptr
                );
                swr_init(swr_ctx);
                
                swr_convert(swr_ctx, out_frame->data, out_frame->nb_samples,
                           (const uint8_t**)frame->data, frame->nb_samples);
                
                if (avcodec_send_frame(octx, out_frame) >= 0) {
                    AVPacket* opkt = av_packet_alloc();
                    while (avcodec_receive_packet(octx, opkt) >= 0) {
                        av_interleaved_write_frame(ofmt_ctx, opkt);
                        av_packet_unref(opkt);
                    }
                    av_packet_free(&opkt);
                }
                
                av_frame_free(&out_frame);
            }
            
            av_packet_unref(pkt);
        }
        
        while (avcodec_receive_packet(octx, pkt) >= 0) {
            av_interleaved_write_frame(ofmt_ctx, pkt);
            av_packet_unref(pkt);
        }
        
        av_write_trailer(ofmt_ctx);
        success = true;
        
    } catch (const std::exception& e) {
        // 忽略音频提取失败
    }
    
    if (swr_ctx) swr_free(&swr_ctx);
    if (pkt) av_packet_free(&pkt);
    if (frame) av_frame_free(&frame);
    if (octx) avcodec_free_context(&octx);
    if (ictx) avcodec_free_context(&ictx);
    if (ofmt_ctx && !(ofmt_ctx->oformat->flags & AVFMT_NOFILE)) {
        avio_closep(&ofmt_ctx->pb);
    }
    if (ofmt_ctx) avformat_free_context(ofmt_ctx);
    if (ifmt_ctx) avformat_close_input(&ifmt_ctx);
    
    return success;
}

std::string VideoEngine::getVideoMetadata(const std::string& filepath) {
    VideoInfo info = analyzeVideo(filepath);
    
    std::ostringstream oss;
    oss << "文件: " << info.filename << "\n";
    oss << "分辨率: " << info.width << "x" << info.height << "\n";
    oss << "帧率: " << std::fixed << std::setprecision(2) << info.fps << " fps\n";
    oss << "时长: " << std::fixed << std::setprecision(2) << info.duration << " 秒\n";
    oss << "总帧数: " << info.total_frames << "\n";
    oss << "编码器: " << info.codec_name << "\n";
    oss << "像素格式: " << info.pixel_format << "\n";
    oss << "有音频: " << (info.has_audio ? "是" : "否") << "\n";
    
    return oss.str();
}

void VideoEngine::setThreadPoolSize(int size) {
    thread_pool_size_ = size;
}

void VideoEngine::cancel() {
    cancelled_.store(true);
}

// 单例实现
VideoEngine VideoEngineManager::engine_;

VideoEngine& VideoEngineManager::getInstance() {
    return engine_;
}

// ======== 滤镜管线辅助函数 ========

AVFilterGraph* VideoEngine::createFilterGraph() {
    AVFilterGraph* graph = avfilter_graph_alloc();
    return graph;
}

AVFilterContext* VideoEngine::createBufferSource(AVFilterGraph* graph, AVCodecContext* codec_ctx, const char* name) {
    if (!graph || !codec_ctx) return nullptr;
    
    AVFilterContext* buffersrc_ctx = nullptr;
    const AVFilter* buffersrc = nullptr;
    
    if (codec_ctx->codec_type == AVMEDIA_TYPE_VIDEO) {
        buffersrc = avfilter_get_by_name("buffer");
        if (!buffersrc) return nullptr;
        
        char args[512];
        snprintf(args, sizeof(args),
                 "video_size=%dx%d:pix_fmt=%d:time_base=%d/%d:pixel_aspect=%d/%d",
                 codec_ctx->width, codec_ctx->height,
                 codec_ctx->pix_fmt,
                 codec_ctx->time_base.num, codec_ctx->time_base.den,
                 codec_ctx->sample_aspect_ratio.num, codec_ctx->sample_aspect_ratio.den);
        
        if (avfilter_graph_create_filter(&buffersrc_ctx, buffersrc, name, args, nullptr, graph) < 0) {
            return nullptr;
        }
    } else if (codec_ctx->codec_type == AVMEDIA_TYPE_AUDIO) {
        buffersrc = avfilter_get_by_name("abuffer");
        if (!buffersrc) return nullptr;
        
        char args[512];
        snprintf(args, sizeof(args),
                 "time_base=%d/%d:sample_rate=%d:sample_fmt=%d:channel_layout=0x%" PRIx64,
                 codec_ctx->time_base.num, codec_ctx->time_base.den,
                 codec_ctx->sample_rate,
                 codec_ctx->sample_fmt,
                 codec_ctx->channel_layout);
        
        if (avfilter_graph_create_filter(&buffersrc_ctx, buffersrc, name, args, nullptr, graph) < 0) {
            return nullptr;
        }
    }
    
    return buffersrc_ctx;
}

AVFilterContext* VideoEngine::createBufferSink(AVFilterGraph* graph, enum AVMediaType media_type, const char* name) {
    if (!graph) return nullptr;
    
    AVFilterContext* buffersink_ctx = nullptr;
    const AVFilter* buffersink = nullptr;
    
    if (media_type == AVMEDIA_TYPE_VIDEO) {
        buffersink = avfilter_get_by_name("buffersink");
    } else if (media_type == AVMEDIA_TYPE_AUDIO) {
        buffersink = avfilter_get_by_name("abuffersink");
    }
    
    if (!buffersink) return nullptr;
    
    if (avfilter_graph_create_filter(&buffersink_ctx, buffersink, name, nullptr, nullptr, graph) < 0) {
        return nullptr;
    }
    
    return buffersink_ctx;
}

AVFilterContext* VideoEngine::addFilter(AVFilterGraph* graph, const char* filter_name, const char* instance_name, AVDictionary* options) {
    if (!graph || !filter_name) return nullptr;
    
    const AVFilter* filter = avfilter_get_by_name(filter_name);
    if (!filter) return nullptr;
    
    AVFilterContext* filter_ctx = nullptr;
    if (avfilter_graph_create_filter(&filter_ctx, filter, instance_name, nullptr, options, graph) < 0) {
        return nullptr;
    }
    
    return filter_ctx;
}

bool VideoEngine::linkFilters(AVFilterContext* src, AVFilterContext* dst, int src_pad, int dst_pad) {
    if (!src || !dst) return false;
    
    if (avfilter_link(src, src_pad, dst, dst_pad) < 0) {
        return false;
    }
    
    return true;
}

bool VideoEngine::configureFilterGraph(AVFilterGraph* graph) {
    if (!graph) return false;
    
    if (avfilter_graph_config(graph, nullptr) < 0) {
        return false;
    }
    
    return true;
}

void VideoEngine::freeFilterGraph(AVFilterGraph* graph) {
    if (graph) {
        avfilter_graph_free(&graph);
    }
}

// ======== 硬件编码辅助函数 ========

const AVCodec* VideoEngine::selectHardwareEncoder() {
    std::string encoder_name;
    if (detectGpuEncoder(encoder_name)) {
        return avcodec_find_encoder_by_name(encoder_name.c_str());
    }
    
    return avcodec_find_encoder(AV_CODEC_ID_H264);
}

void VideoEngine::setHardwareEncoderOptions(AVCodecContext* codec_ctx, const std::string& encoder_name) {
    if (!codec_ctx || encoder_name.empty()) return;
    
    if (encoder_name.find("nvenc") != std::string::npos) {
        av_opt_set(codec_ctx->priv_data, "preset", "p4", 0);
        av_opt_set(codec_ctx->priv_data, "rc", "cbr", 0);
        av_opt_set(codec_ctx->priv_data, "gpu", "0", 0);
    } else if (encoder_name.find("qsv") != std::string::npos) {
        av_opt_set(codec_ctx->priv_data, "preset", "veryfast", 0);
        av_opt_set(codec_ctx->priv_data, "init_qpP", "24", 0);
    } else if (encoder_name.find("amf") != std::string::npos) {
        av_opt_set(codec_ctx->priv_data, "preset", "fast", 0);
    }
}

} // namespace ai_editor
