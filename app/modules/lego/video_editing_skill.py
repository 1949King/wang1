"""
视频编辑技能模块
================
提供各种视频编辑相关的AI技能
"""

from .skill_engine import Skill, skill_registry, StepResult
from typing import Dict, Any
import os
import subprocess
import json
from datetime import datetime


class AutoSubtitleSkill(Skill):
    """自动生成字幕技能"""
    
    skill_id = "auto-subtitle"
    skill_name = "自动生成字幕"
    skill_description = "自动为视频生成字幕，支持多语言"
    skill_category = "字幕工具"
    skill_icon = "📝"
    skill_version = "1.0.0"
    
    def _setup_steps(self):
        self.add_step(
            name="检查输入文件",
            handler=self._check_input_file
        ).add_step(
            name="提取音频",
            handler=self._extract_audio
        ).add_step(
            name="识别语音",
            handler=self._recognize_speech
        ).add_step(
            name="生成字幕文件",
            handler=self._generate_subtitle
        ).add_step(
            name="完成",
            handler=self._complete
        )
    
    def _check_input_file(self, context):
        """检查输入文件"""
        input_file = context.get_input("input_file")
        if not input_file or not os.path.exists(input_file):
            return StepResult(success=False, error="输入文件不存在")
        context.set_variable("input_file", input_file)
        return StepResult(success=True)
    
    def _extract_audio(self, context):
        """提取音频"""
        input_file = context.get_variable("input_file")
        audio_file = os.path.splitext(input_file)[0] + ".wav"
        
        try:
            # 使用ffmpeg提取音频（避免shell=True，防止命令注入）
            cmd = [
                "ffmpeg", "-i", input_file,
                "-vn", "-acodec", "pcm_s16le",
                "-ar", "16000", "-ac", "1",
                audio_file
            ]
            subprocess.run(cmd, shell=False, check=True,
                         capture_output=True,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            context.set_variable("audio_file", audio_file)
            return StepResult(success=True, output={"audio_file": audio_file})
        except Exception as e:
            return StepResult(success=False, error=f"提取音频失败: {e}")
    
    def _recognize_speech(self, context):
        """识别语音 - 使用统一的 whisper_asr 共享模块"""
        audio_file = context.get_variable("audio_file")
        language = context.get_input("language", "zh")

        try:
            from app.core.ai.whisper_asr import transcribe
        except ImportError:
            try:
                from core.ai.whisper_asr import transcribe
            except ImportError:
                # 修复：此前 whisper 不可用时会伪造一条占位字幕并 success=True，
                # 后续步骤据此生成一个"看起来完成了"的 SRT 文件，但内容完全不是
                # 真实转写——用户拿到"成功"提示和一个只有一行提示文本的字幕文件，
                # 容易被当成真实识别结果使用。这里如实标记为失败，而不是
                # 制造一个假的成功产物。
                return StepResult(success=False, error="Whisper 语音识别模块不可用（未安装或导入失败），无法生成真实字幕，请先安装 whisper 依赖")

        result = transcribe(audio_file, model_size="base", language=language)
        if result:
            context.set_variable("subtitles", result)
            return StepResult(success=True, output={"subtitles": result})
        return StepResult(success=False, error="语音识别返回空结果")
    
    def _generate_subtitle(self, context):
        """生成字幕文件"""
        input_file = context.get_variable("input_file")
        subtitles = context.get_variable("subtitles")
        output_file = context.get_input("output_file") or os.path.splitext(input_file)[0] + ".srt"
        
        try:
            # 生成SRT字幕文件
            with open(output_file, 'w', encoding='utf-8') as f:
                for i, subtitle in enumerate(subtitles, 1):
                    start = self._format_time(subtitle["start"])
                    end = self._format_time(subtitle["end"])
                    f.write(f"{i}\n")
                    f.write(f"{start} --> {end}\n")
                    f.write(f"{subtitle['text']}\n\n")
            
            context.set_variable("output_file", output_file)
            return StepResult(success=True, output={"output_file": output_file})
        except Exception as e:
            return StepResult(success=False, error=f"生成字幕失败: {e}")
    
    def _complete(self, context):
        """完成"""
        output_file = context.get_variable("output_file")
        return StepResult(success=True, output={"result": f"字幕生成成功，保存到 {output_file}"})
    
    def _format_time(self, seconds):
        """格式化时间"""
        ms = int((seconds % 1) * 1000)
        s = int(seconds % 60)
        m = int(seconds // 60 % 60)
        h = int(seconds // 3600)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class SmartClipSkill(Skill):
    """智能剪辑技能"""
    
    skill_id = "smart-clip"
    skill_name = "智能剪辑"
    skill_description = "AI驱动的智能剪辑，自动识别精彩片段"
    skill_category = "视频处理"
    skill_icon = "🎬"
    skill_version = "1.0.0"
    
    def _setup_steps(self):
        self.add_step(
            name="检查输入文件",
            handler=self._check_input_file
        ).add_step(
            name="分析视频内容",
            handler=self._analyze_video
        ).add_step(
            name="识别精彩片段",
            handler=self._identify_clips
        ).add_step(
            name="剪辑视频",
            handler=self._clip_video
        ).add_step(
            name="完成",
            handler=self._complete
        )
    
    def _check_input_file(self, context):
        """检查输入文件"""
        input_file = context.get_input("input_file")
        if not input_file or not os.path.exists(input_file):
            return StepResult(success=False, error="输入文件不存在")
        context.set_variable("input_file", input_file)
        return StepResult(success=True)
    
    def _analyze_video(self, context):
        """分析视频内容

        修复：此前不管输入什么视频都写死 duration=60.0，后续片段全部基于
        这个假时长挑选，短视频会挑出超出实际长度的区间。这里改为用
        ffprobe 读取真实时长/分辨率/帧率；ffprobe 不可用时才回退默认值，
        并在 video_info 里标注 is_estimated=True，供下游诚实展示。
        """
        input_file = context.get_variable("input_file")

        try:
            video_info = self._probe_video_info(input_file)
            context.set_variable("video_info", video_info)
            return StepResult(success=True, output={"video_info": video_info})
        except Exception as e:
            return StepResult(success=False, error=f"分析视频失败: {e}")

    def _probe_video_info(self, input_file: str) -> dict:
        try:
            cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                "-of", "json", input_file,
            ]
            result = subprocess.run(
                cmd, shell=False, capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                stream = (data.get("streams") or [{}])[0]
                duration = float((data.get("format") or {}).get("duration", 0) or 0)
                width = stream.get("width")
                height = stream.get("height")
                fps_raw = stream.get("r_frame_rate", "0/1")
                num, _, den = fps_raw.partition("/")
                fps = round(float(num) / float(den), 2) if den and float(den) else 0
                if duration > 0 and width and height:
                    return {
                        "duration": duration,
                        "resolution": f"{width}x{height}",
                        "fps": fps,
                        "is_estimated": False,
                    }
        except Exception:
            pass
        # ffprobe 不可用/失败时的诚实兜底：明确标注为估计值，不冒充真实探测结果
        return {"duration": 60.0, "resolution": "未知（ffprobe 不可用）", "fps": 0, "is_estimated": True}

    def _identify_clips(self, context):
        """识别精彩片段

        如实说明：这里没有接入真实的精彩片段识别模型（例如基于音量/运动量/
        人脸的启发式算法，或视觉-语言模型打分），只是把视频均匀切成 3 段
        作为占位片段。score 字段是固定值，不代表真实置信度。
        """
        video_info = context.get_variable("video_info")

        try:
            duration = max(float(video_info.get("duration") or 0), 3.0)
            seg = duration / 4.0
            clips = [
                {"start": round(seg * 0.5, 2), "end": round(seg * 1.2, 2), "score": None},
                {"start": round(seg * 1.8, 2), "end": round(seg * 2.5, 2), "score": None},
                {"start": round(seg * 3.0, 2), "end": round(min(seg * 3.7, duration), 2), "score": None},
            ]
            context.set_variable("clips", clips)
            context.set_variable("clips_are_heuristic", True)
            return StepResult(success=True, output={
                "clips": clips,
                "note": "⚠️ 暂未接入真实精彩片段识别模型，以下为均匀切分的占位片段",
            })
        except Exception as e:
            return StepResult(success=False, error=f"识别精彩片段失败: {e}")

    def _clip_video(self, context):
        """剪辑视频

        修复：此前只把输出路径塞进变量就 success=True，从未调用任何视频
        处理逻辑，output_file 实际上不存在——是彻底的假成功。这里改为真正
        用 ffmpeg 按 clips 逐段裁剪并 concat 成一个输出文件；任何一步失败
        都如实返回 success=False，不再假装完成。
        """
        input_file = context.get_variable("input_file")
        clips = context.get_variable("clips") or []
        output_file = context.get_input("output_file") or os.path.splitext(input_file)[0] + "_clipped.mp4"

        if not clips:
            return StepResult(success=False, error="没有可用的剪辑片段")

        segment_files = []
        try:
            tmp_dir = os.path.join(os.path.dirname(output_file) or ".", ".smart_clip_tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            for i, clip in enumerate(clips):
                seg_path = os.path.join(tmp_dir, f"seg_{i}.mp4")
                cmd = [
                    "ffmpeg", "-y", "-ss", str(clip["start"]), "-to", str(clip["end"]),
                    "-i", input_file, "-c", "copy", "-avoid_negative_ts", "make_zero",
                    seg_path,
                ]
                r = subprocess.run(cmd, shell=False, capture_output=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                if r.returncode != 0 or not os.path.exists(seg_path):
                    raise RuntimeError(f"片段 {i} 裁剪失败: {(r.stderr or b'').decode('utf-8', errors='ignore')[-300:]}")
                segment_files.append(seg_path)

            concat_list = os.path.join(tmp_dir, "concat_list.txt")
            with open(concat_list, "w", encoding="utf-8") as f:
                for seg_path in segment_files:
                    f.write(f"file '{os.path.abspath(seg_path)}'\n")

            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", output_file]
            r = subprocess.run(cmd, shell=False, capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if r.returncode != 0 or not os.path.exists(output_file):
                raise RuntimeError(f"合并片段失败: {(r.stderr or b'').decode('utf-8', errors='ignore')[-300:]}")

            context.set_variable("output_file", output_file)
            return StepResult(success=True, output={"output_file": output_file})
        except Exception as e:
            return StepResult(success=False, error=f"剪辑视频失败: {e}")
        finally:
            for seg_path in segment_files:
                try:
                    os.remove(seg_path)
                except OSError:
                    pass

    def _complete(self, context):
        """完成"""
        output_file = context.get_variable("output_file")
        clips = context.get_variable("clips")
        result_msg = f"智能剪辑完成，保存到 {output_file}"
        if context.get_variable("clips_are_heuristic"):
            result_msg += "（片段为均匀切分的占位选择，非真实AI精彩片段识别）"
        return StepResult(success=True, output={"result": result_msg, "clips": clips})


class CoverGeneratorSkill(Skill):
    """智能生成封面图技能"""
    
    skill_id = "cover-generator"
    skill_name = "智能生成封面图"
    skill_description = "根据视频内容智能生成封面图"
    skill_category = "视频处理"
    skill_icon = "🖼️"
    skill_version = "1.0.0"
    
    def _setup_steps(self):
        self.add_step(
            name="检查输入文件",
            handler=self._check_input_file
        ).add_step(
            name="提取关键帧",
            handler=self._extract_keyframes
        ).add_step(
            name="分析内容",
            handler=self._analyze_content
        ).add_step(
            name="生成封面图",
            handler=self._generate_cover
        ).add_step(
            name="完成",
            handler=self._complete
        )
    
    def _check_input_file(self, context):
        """检查输入文件"""
        input_file = context.get_input("input_file")
        if not input_file or not os.path.exists(input_file):
            return StepResult(success=False, error="输入文件不存在")
        context.set_variable("input_file", input_file)
        return StepResult(success=True)
    
    def _extract_keyframes(self, context):
        """提取关键帧

        修复：此前不管视频多长都写死 10s/25s/40s 三个时间点、且从不真正
        提取任何图片文件——短视频（比如 20 秒）会挑出超出实际时长的时间点。
        这里先用 ffprobe 读真实时长，按比例选取候选时间点；真正的图片提取
        放到 _generate_cover 里对最终选中的一帧执行（没必要为三个候选都真提
        取，只在确定用哪帧当封面时才落盘）。
        """
        input_file = context.get_variable("input_file")

        try:
            duration = self._probe_duration(input_file)
            candidates = [round(duration * r, 2) for r in (0.2, 0.5, 0.75)]
            keyframes = [{"time": t, "path": None} for t in candidates]
            context.set_variable("keyframes", keyframes)
            context.set_variable("video_duration", duration)
            return StepResult(success=True, output={"keyframes": keyframes})
        except Exception as e:
            return StepResult(success=False, error=f"提取关键帧失败: {e}")

    def _probe_duration(self, input_file: str) -> float:
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", input_file]
            r = subprocess.run(cmd, shell=False, capture_output=True, text=True, timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if r.returncode == 0 and r.stdout:
                duration = float(json.loads(r.stdout).get("format", {}).get("duration", 0) or 0)
                if duration > 0:
                    return duration
        except Exception:
            pass
        return 30.0  # ffprobe 不可用时的保守默认值

    def _analyze_content(self, context):
        """分析内容

        如实说明：没有接入真实的计算机视觉模型分析画面内容，这里只是
        固定的占位标签，仅用于决定选取哪个候选关键帧（取中间时间点），
        不代表对视频内容的真实理解。
        """
        keyframes = context.get_variable("keyframes")

        try:
            content_analysis = {
                "main_subject": "未识别（未接入CV模型，占位值）",
                "scene": "未识别（未接入CV模型，占位值）",
                "mood": "未识别（未接入CV模型，占位值）",
                "keywords": [],
                "is_placeholder": True,
            }
            # 占位策略：选取候选关键帧中间的一帧作为封面
            chosen = keyframes[len(keyframes) // 2] if keyframes else {"time": 1.0}
            context.set_variable("chosen_keyframe", chosen)
            context.set_variable("content_analysis", content_analysis)
            return StepResult(success=True, output={"content_analysis": content_analysis})
        except Exception as e:
            return StepResult(success=False, error=f"分析内容失败: {e}")

    def _generate_cover(self, context):
        """生成封面图

        修复：此前只把输出路径塞进变量就 success=True，从未调用任何图像
        处理逻辑，output_file 实际上是不存在的文件——彻底的假成功。这里
        改为真正用 ffmpeg 在选中的时间点截取一帧并保存为 jpg；失败时如实
        返回 success=False。
        """
        input_file = context.get_variable("input_file")
        content_analysis = context.get_variable("content_analysis")
        chosen = context.get_variable("chosen_keyframe") or {"time": 1.0}
        output_file = context.get_input("output_file") or os.path.splitext(input_file)[0] + "_cover.jpg"

        try:
            cmd = [
                "ffmpeg", "-y", "-ss", str(chosen.get("time", 1.0)),
                "-i", input_file, "-frames:v", "1", "-q:v", "2",
                output_file,
            ]
            r = subprocess.run(cmd, shell=False, capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if r.returncode != 0 or not os.path.exists(output_file):
                raise RuntimeError((r.stderr or b"").decode("utf-8", errors="ignore")[-300:])

            context.set_variable("output_file", output_file)
            return StepResult(success=True, output={"output_file": output_file})
        except Exception as e:
            return StepResult(success=False, error=f"生成封面图失败: {e}")

    def _complete(self, context):
        """完成"""
        output_file = context.get_variable("output_file")
        content_analysis = context.get_variable("content_analysis")
        result_msg = f"封面图已提取，保存到 {output_file}"
        if content_analysis and content_analysis.get("is_placeholder"):
            result_msg += "（选帧策略为占位策略，非真实内容理解）"
        return StepResult(success=True, output={"result": result_msg, "content_analysis": content_analysis})


# 注册技能
def register_skills():
    """注册视频编辑技能（由 main_qt6.py _show_main_window 显式调用）

    修复：之前此函数从未被调用，导致 Skill 工坊列表为空。
    现在包含 5 个 Skill：3 个原视频处理 Skill + 全功能型 AI 导演 Skill + 畸形根治闭环 Skill。
    """
    skill_registry.register(AutoSubtitleSkill)
    skill_registry.register(SmartClipSkill)
    skill_registry.register(CoverGeneratorSkill)
    # 新增：全功能型 AI 导演 Skill（独立文件，延迟导入避免循环依赖）
    from .director_skill import DirectorSkill
    skill_registry.register(DirectorSkill)
    # 新增：畸形根治四层闭环 Skill（前置约束→生成管控→插帧补偿→质检修复→入库）
    from .deformity_repair_skill import DeformityRepairSkill
    skill_registry.register(DeformityRepairSkill)