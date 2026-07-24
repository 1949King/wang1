/**
 * @file openshot_wrapper.cpp
 * @brief libopenshot C++ 引擎封装实现
 */

#include "openshot_wrapper.h"
#include <iostream>
#include <chrono>
#include <sstream>
#include <iomanip>

namespace ai_editor {

OpenshotWrapper::OpenshotWrapper() {
    last_render_stats_ = {};
}

OpenshotWrapper::~OpenshotWrapper() {
    destroyTimeline();
}

bool OpenshotWrapper::createTimeline(const TimelineConfig& config) {
    try {
        // 创建时间线
        timeline_ = std::make_shared<openshot::Timeline>(
            config.width,
            config.height,
            openshot::Fraction(config.fps, 1),
            config.sample_rate,
            config.channels,
            openshot::ChannelLayout::LAYOUT_STEREO
        );
        
        // 设置显示模式
        timeline_->info.display_mode = openshot::DISPLAY_COMPOSITE;
        
        return true;
    } catch (const std::exception& e) {
        std::cerr << "创建时间线失败: " << e.what() << std::endl;
        return false;
    }
}

bool OpenshotWrapper::destroyTimeline() {
    try {
        timeline_.reset();
        writer_.reset();
        return true;
    } catch (...) {
        return false;
    }
}

bool OpenshotWrapper::addClip(const OpenshotClipConfig& clip_config) {
    if (!timeline_) {
        std::cerr << "时间线未初始化" << std::endl;
        return false;
    }
    
    try {
        // 创建读取器
        auto reader = createReader(clip_config.source_path);
        if (!reader) {
            return false;
        }
        
        // 创建剪辑
        auto clip = createClip(clip_config);
        if (!clip) {
            return false;
        }
        
        // 设置读取器
        clip->Reader(reader);
        
        // 添加到时间线
        timeline_->AddClip(clip);
        
        return true;
    } catch (const std::exception& e) {
        std::cerr << "添加剪辑失败: " << e.what() << std::endl;
        return false;
    }
}

bool OpenshotWrapper::removeClip(int clip_id) {
    if (!timeline_) return false;
    
    try {
        timeline_->RemoveClip(clip_id);
        return true;
    } catch (...) {
        return false;
    }
}

bool OpenshotWrapper::updateClip(int clip_id, const OpenshotClipConfig& clip_config) {
    if (!timeline_) return false;
    
    try {
        auto clip = timeline_->GetClip(clip_id);
        if (!clip) return false;
        
        // 更新剪辑属性
        clip->Position(clip_config.position);
        clip->Layer(clip_config.layer);
        clip->Start(clip_config.start);
        clip->End(clip_config.end);
        
        // 更新音量
        openshot::KeyFrame volume_keyframe;
        volume_keyframe.AddPoint(0, clip_config.volume);
        clip->Volume(volume_keyframe);
        
        // 更新速度
        clip->Speed(clip_config.speed);
        
        return true;
    } catch (...) {
        return false;
    }
}

bool OpenshotWrapper::addEffect(const EffectConfig& effect_config) {
    if (!timeline_) return false;
    
    try {
        // 创建特效
        std::shared_ptr<openshot::EffectBase> effect;
        
        if (effect_config.effect_name == "brightness") {
            effect = std::make_shared<openshot::Brightness>();
        } else if (effect_config.effect_name == "saturation") {
            effect = std::make_shared<openshot::Saturation>();
        } else if (effect_config.effect_name == "blur") {
            effect = std::make_shared<openshot::Blur>();
        } else {
            std::cerr << "不支持的特效: " << effect_config.effect_name << std::endl;
            return false;
        }
        
        // 设置特效属性
        for (const auto& prop : effect_config.properties) {
            effect->SetProperty(prop.first, prop.second);
        }
        
        // 添加到时间线
        timeline_->AddEffect(effect, effect_config.track);
        
        return true;
    } catch (const std::exception& e) {
        std::cerr << "添加特效失败: " << e.what() << std::endl;
        return false;
    }
}

bool OpenshotWrapper::removeEffect(int effect_id) {
    if (!timeline_) return false;
    
    try {
        timeline_->RemoveEffect(effect_id);
        return true;
    } catch (...) {
        return false;
    }
}

bool OpenshotWrapper::addTransition(const TransitionConfig& transition_config) {
    if (!timeline_) return false;
    
    try {
        // 创建转场
        std::shared_ptr<openshot::EffectBase> transition;
        
        if (transition_config.transition_name == "fade") {
            transition = std::make_shared<openshot::Mask>();
        } else if (transition_config.transition_name == "wipe") {
            transition = std::make_shared<openshot::Mask>();
        } else {
            std::cerr << "不支持的转场: " << transition_config.transition_name << std::endl;
            return false;
        }
        
        // 设置转场属性
        transition->SetProperty("duration", transition_config.duration);
        
        // 添加到时间线
        timeline_->AddEffect(transition, transition_config.track);
        
        return true;
    } catch (const std::exception& e) {
        std::cerr << "添加转场失败: " << e.what() << std::endl;
        return false;
    }
}

bool OpenshotWrapper::render(const OpenshotExportConfig& export_config,
                             OpenshotProgressCallback progress_cb) {
    if (!timeline_) {
        std::cerr << "时间线未初始化" << std::endl;
        return false;
    }
    
    auto start_time = std::chrono::high_resolution_clock::now();
    
    try {
        // 创建写入器
        writer_ = std::make_shared<openshot::FFmpegWriter>(export_config.output_path);
        
        // 设置视频编码器
        if (export_config.use_gpu) {
            writer_->SetVideoOptions(true, export_config.video_codec,
                                    openshot::Fraction(30, 1),
                                    export_config.video_bitrate, 1, "", 0, 0);
        } else {
            writer_->SetVideoOptions(true, "libx264",
                                    openshot::Fraction(30, 1),
                                    export_config.video_bitrate, 1, "", 0, 0);
        }
        
        // 设置音频编码器
        writer_->SetAudioOptions(true, export_config.audio_codec,
                                44100, 2,
                                openshot::ChannelLayout::LAYOUT_STEREO,
                                export_config.audio_bitrate);
        
        // 设置预设
        writer_->SetOption("preset", export_config.preset);
        
        // 打开写入器
        writer_->Open();
        
        // 渲染帧
        int total_frames = (int)(timeline_->info.duration * timeline_->info.fps.ToDouble());
        size_t frames_rendered = 0;
        
        for (int frame_number = 1; frame_number <= total_frames; frame_number++) {
            // 获取帧
            std::shared_ptr<openshot::Frame> frame = timeline_->GetFrame(frame_number);
            
            // 写入帧
            writer_->WriteFrame(frame, frame_number);
            
            frames_rendered++;
            
            // 进度回调
            if (progress_cb) {
                double progress = (double)frame_number / total_frames;
                progress_cb(progress, "渲染中...");
            }
        }
        
        // 关闭写入器
        writer_->Close();
        
        // 计算统计信息
        auto end_time = std::chrono::high_resolution_clock::now();
        auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(
            end_time - start_time).count();
        
        last_render_stats_.render_time = duration / 1000.0;
        last_render_stats_.frames_rendered = frames_rendered;
        last_render_stats_.fps_rendered = frames_rendered / last_render_stats_.render_time;
        
        if (progress_cb) {
            progress_cb(1.0, "渲染完成");
        }
        
        return true;
    } catch (const std::exception& e) {
        std::cerr << "渲染失败: " << e.what() << std::endl;
        return false;
    }
}

bool OpenshotWrapper::startPreview() {
    // TODO: 实现预览功能
    return true;
}

bool OpenshotWrapper::stopPreview() {
    // TODO: 实现停止预览
    return true;
}

bool OpenshotWrapper::seek(double position) {
    // TODO: 实现跳转功能
    return true;
}

double OpenshotWrapper::getDuration() const {
    if (timeline_) {
        return timeline_->info.duration;
    }
    return 0;
}

int OpenshotWrapper::getClipCount() const {
    if (timeline_) {
        return timeline_->Clips.size();
    }
    return 0;
}

std::string OpenshotWrapper::getTimelineInfo() const {
    if (!timeline_) {
        return "时间线未初始化";
    }
    
    std::ostringstream oss;
    oss << "分辨率: " << timeline_->info.width << "x" << timeline_->info.height << "\n";
    oss << "帧率: " << timeline_->info.fps.ToDouble() << " fps\n";
    oss << "时长: " << timeline_->info.duration << " 秒\n";
    oss << "剪辑数: " << timeline_->Clips.size() << "\n";
    oss << "特效数: " << timeline_->Effects.size() << "\n";
    
    return oss.str();
}

std::shared_ptr<openshot::ReaderBase> OpenshotWrapper::createReader(const std::string& filepath) {
    try {
        return std::make_shared<openshot::FFmpegReader>(filepath);
    } catch (const std::exception& e) {
        std::cerr << "创建读取器失败: " << e.what() << std::endl;
        return nullptr;
    }
}

std::shared_ptr<openshot::Clip> OpenshotWrapper::createClip(const OpenshotClipConfig& config) {
    auto clip = std::make_shared<openshot::Clip>();
    
    clip->Position(config.position);
    clip->Layer(config.layer);
    clip->Start(config.start);
    clip->End(config.end);
    
    // 设置音量关键帧
    openshot::KeyFrame volume_keyframe;
    volume_keyframe.AddPoint(0, config.volume);
    clip->Volume(volume_keyframe);
    
    // 设置速度
    clip->Speed(config.speed);
    
    return clip;
}

void OpenshotWrapper::applyEffect(std::shared_ptr<openshot::Clip> clip, const EffectConfig& effect) {
    // TODO: 实现特效应用
}

} // namespace ai_editor
