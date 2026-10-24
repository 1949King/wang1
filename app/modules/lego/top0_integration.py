"""
TOP 0级软件集成模块
==================
将AI剧情理解引擎和专业剪辑引擎集成到现有系统中

这是连接AI理解和实际剪辑的桥梁
"""

import os
from typing import List, Optional, Callable, Dict, Any
from datetime import datetime

from .drama_understanding_engine import (
    DramaUnderstandingEngine, 
    DramaStructure, 
    EditingStrategy,
    HighlightClip
)
from .professional_video_engine import (
    ProfessionalVideoEngine,
    VideoTask,
    ExportSettings,
    TaskResult
)


import logging
logger = logging.getLogger("AI短剧编辑器.modules.lego.top0_integration")

class Top0VideoProcessor:
    """
    TOP 0级视频处理器
    
    整合AI理解和专业剪辑，提供一键式智能剪辑体验
    """
    
    def __init__(self):
        """初始化处理器"""
        logger.info('🚀 初始化TOP 0级视频处理器...')
        
        # 初始化AI理解引擎
        self.drama_engine = DramaUnderstandingEngine(
            whisper_model="base",
            ollama_model="qwen2.5",
            use_local_ai=True
        )
        
        # 初始化专业剪辑引擎
        self.video_engine = ProfessionalVideoEngine(max_workers=4)
        
        logger.info('✅ TOP 0级处理器初始化完成')
    
    def smart_clip(self,
                   video_path: str,
                   target_platform: str = "抖音",
                   video_style: str = "高光剪辑",
                   target_duration: float = 60.0,
                   progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """
        智能剪辑 - TOP 0级核心功能
        
        流程：
        1. AI理解视频内容（4层理解）
        2. 生成剪辑策略
        3. 提取高光片段
        4. 批量剪辑生成
        
        Args:
            video_path: 输入视频路径
            target_platform: 目标平台
            video_style: 视频风格
            target_duration: 目标时长
            progress_callback: 进度回调
            
        Returns:
            Dict: 包含剪辑结果和元数据
        """
        logger.info(f"\n{'=' * 70}")
        logger.info(f'🎬 TOP 0级智能剪辑')
        logger.info(f'   视频: {os.path.basename(video_path)}')
        logger.info(f'   平台: {target_platform}')
        logger.info(f'   风格: {video_style}')
        logger.info(f"{'=' * 70}\n")
        
        result = {
            "success": False,
            "video_path": video_path,
            "platform": target_platform,
            "style": video_style,
            "analysis": None,
            "strategy": None,
            "output_videos": [],
            "errors": []
        }
        
        try:
            # Step 1: AI理解视频
            if progress_callback:
                progress_callback(10, "正在分析视频内容...")
            
            drama = self.drama_engine.analyze_video(video_path)
            result["analysis"] = {
                "title": drama.title,
                "genre": drama.genre,
                "characters": [c.name for c in drama.characters],
                "plot_points": len(drama.plot_points),
                "scenes": len(drama.scenes),
                "themes": drama.themes
            }
            
            # Step 2: 生成剪辑策略
            if progress_callback:
                progress_callback(30, "正在生成剪辑策略...")
            
            strategy = self.drama_engine.generate_editing_strategy(
                drama,
                target_platform=target_platform,
                video_style=video_style
            )
            result["strategy"] = {
                "structure": strategy.structure_template,
                "pacing": strategy.pacing,
                "bgm_style": strategy.bgm_style,
                "highlights_count": len(strategy.highlights)
            }
            
            # Step 3: 准备剪辑任务
            if progress_callback:
                progress_callback(40, "正在准备剪辑任务...")
            
            tasks = []
            output_dir = os.path.join(
                os.path.dirname(video_path),
                f"TOP0剪辑_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            os.makedirs(output_dir, exist_ok=True)
            
            # 获取平台最优设置
            settings = self.video_engine.get_optimal_settings(target_platform)
            
            # 为每个高光片段创建剪辑任务
            for i, highlight in enumerate(strategy.highlights):
                output_path = os.path.join(
                    output_dir,
                    f"{i+1:02d}_{highlight.suggested_title}_{highlight.start_time:.0f}s.mp4"
                )
                
                task = VideoTask(
                    task_id=f"highlight_{i}",
                    input_path=video_path,
                    output_path=output_path,
                    operation="cut_reencode",
                    params={
                        "start_time": highlight.start_time,
                        "end_time": highlight.end_time,
                        "settings": settings
                    },
                    priority=i
                )
                tasks.append(task)
            
            # Step 4: 批量剪辑
            if progress_callback:
                progress_callback(50, f"开始批量剪辑 {len(tasks)} 个片段...")
            
            def batch_progress(progress, task_result):
                overall_progress = 50 + (progress / 2)
                if progress_callback:
                    progress_callback(
                        overall_progress,
                        f"剪辑进度: {progress:.1f}%"
                    )
            
            clip_results = self.video_engine.batch_process(tasks, batch_progress)
            
            # 收集结果
            for i, (clip_result, highlight) in enumerate(zip(clip_results, strategy.highlights)):
                if clip_result.success:
                    result["output_videos"].append({
                        "path": clip_result.output_path,
                        "title": highlight.suggested_title,
                        "duration": highlight.duration,
                        "score": highlight.score,
                        "tags": highlight.suggested_tags,
                        "processing_time": clip_result.processing_time
                    })
                else:
                    result["errors"].append({
                        "clip_index": i,
                        "error": clip_result.error_message
                    })
            
            result["success"] = len(result["output_videos"]) > 0
            
            if progress_callback:
                progress_callback(100, "剪辑完成!")
            
            # 输出统计
            logger.info(f"\n{'=' * 70}")
            logger.info(f'✅ 智能剪辑完成!')
            logger.info(f"   成功: {len(result['output_videos'])} 个片段")
            logger.error(f"   失败: {len(result['errors'])} 个片段")
            logger.info(f'   输出目录: {output_dir}')
            logger.info(f"{'=' * 70}\n")
            
        except Exception as e:
            result["errors"].append({"error": str(e)})
            logger.error(f'\n❌ 智能剪辑失败: {e}')
        
        return result
    
    def batch_smart_clip(self,
                         video_paths: List[str],
                         target_platform: str = "抖音",
                         video_style: str = "高光剪辑",
                         progress_callback: Optional[Callable] = None) -> List[Dict[str, Any]]:
        """
        批量智能剪辑
        
        Args:
            video_paths: 视频路径列表
            target_platform: 目标平台
            video_style: 视频风格
            progress_callback: 进度回调
            
        Returns:
            List[Dict]: 每个视频的处理结果
        """
        logger.info(f'\n🚀 批量智能剪辑: {len(video_paths)} 个视频')
        
        results = []
        total = len(video_paths)
        
        for i, video_path in enumerate(video_paths):
            if progress_callback:
                overall_progress = (i / total) * 100
                progress_callback(overall_progress, f"处理视频 {i+1}/{total}: {os.path.basename(video_path)}")
            
            def video_progress(progress, message):
                if progress_callback:
                    overall = overall_progress + (progress / total)
                    progress_callback(overall, message)
            
            result = self.smart_clip(
                video_path,
                target_platform,
                video_style,
                progress_callback=video_progress
            )
            results.append(result)
        
        # 统计
        success_count = sum(1 for r in results if r["success"])
        logger.info(f'\n📊 批量处理完成:')
        logger.info(f'   成功: {success_count}/{total}')
        logger.error(f'   失败: {total - success_count}/{total}')
        
        return results
    
    def analyze_only(self, video_path: str) -> Dict[str, Any]:
        """
        仅分析视频，不剪辑
        
        Args:
            video_path: 视频路径
            
        Returns:
            Dict: 分析结果
        """
        logger.info(f'\n🔍 分析视频: {os.path.basename(video_path)}')
        
        drama = self.drama_engine.analyze_video(video_path)
        strategy = self.drama_engine.generate_editing_strategy(drama)
        
        return {
            "title": drama.title,
            "genre": drama.genre,
            "duration": drama.total_duration,
            "characters": [
                {
                    "name": c.name,
                    "role": c.role_type,
                    "traits": c.personality_traits
                }
                for c in drama.characters
            ],
            "plot_points": [
                {
                    "time": p.timestamp,
                    "type": p.plot_type.value,
                    "description": p.description,
                    "importance": p.importance
                }
                for p in drama.plot_points
            ],
            "emotional_curve": drama.emotional_curve,
            "pacing": drama.pacing_analysis,
            "themes": drama.themes,
            "highlights": [
                {
                    "start": h.start_time,
                    "end": h.end_time,
                    "title": h.suggested_title,
                    "score": h.score,
                    "type": h.clip_type
                }
                for h in strategy.highlights
            ],
            "strategy": {
                "structure": strategy.structure_template,
                "pacing": strategy.pacing,
                "bgm": strategy.bgm_style,
                "subtitles": strategy.subtitle_style
            }
        }
    
    def shutdown(self):
        """关闭处理器"""
        logger.info('\n🛑 关闭TOP 0级处理器...')
        self.video_engine.shutdown()
        logger.info('✅ 处理器已关闭')


# 与现有系统的集成
class Top0Skill:
    """
    TOP 0级Skill，用于集成到现有的Skill引擎
    """
    
    def __init__(self):
        self.processor = None
    
    def initialize(self):
        """初始化Skill"""
        self.processor = Top0VideoProcessor()
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行Skill
        
        Args:
            params: 执行参数
                - video_path: 视频路径
                - platform: 目标平台
                - style: 视频风格
                - target_duration: 目标时长
                
        Returns:
            Dict: 执行结果
        """
        if self.processor is None:
            self.initialize()
        
        video_path = params.get("video_path")
        platform = params.get("platform", "抖音")
        style = params.get("style", "高光剪辑")
        duration = params.get("target_duration", 60.0)
        
        if not video_path or not os.path.exists(video_path):
            return {
                "success": False,
                "error": f"视频文件不存在: {video_path}"
            }
        
        return self.processor.smart_clip(
            video_path,
            target_platform=platform,
            video_style=style,
            target_duration=duration
        )
    
    def shutdown(self):
        """关闭Skill"""
        if self.processor:
            self.processor.shutdown()


# 使用示例
if __name__ == "__main__":
    # 创建处理器
    processor = Top0VideoProcessor()
    
    # 测试视频
    test_video = "test_video.mp4"
    
    if os.path.exists(test_video):
        # 方式1: 完整智能剪辑
        result = processor.smart_clip(
            test_video,
            target_platform="抖音",
            video_style="高光剪辑",
            target_duration=60.0,
            progress_callback=lambda p, m: print(f"进度: {p:.1f}% - {m}")
        )
        
        print("\n剪辑结果:")
        print(f"成功: {result['success']}")
        print(f"输出视频: {len(result['output_videos'])} 个")
        for video in result['output_videos']:
            print(f"  - {video['title']}: {video['path']}")
        
        # 方式2: 仅分析
        print("\n" + "="*70)
        analysis = processor.analyze_only(test_video)
        print(f"\n视频分析:")
        print(f"标题: {analysis['title']}")
        print(f"类型: {analysis['genre']}")
        print(f"角色: {[c['name'] for c in analysis['characters']]}")
        print(f"情节点: {len(analysis['plot_points'])}")
        print(f"高光片段: {len(analysis['highlights'])}")
    else:
        print(f"测试视频不存在: {test_video}")
    
    # 关闭处理器
    processor.shutdown()
