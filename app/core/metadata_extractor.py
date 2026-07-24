import json
import subprocess
from typing import Dict, Any, Optional


class MetadataExtractor:
    """元数据提取器"""

    @staticmethod
    def extract_metadata(file_path: str) -> Dict[str, Any]:
        """提取素材元数据"""
        metadata = {}

        try:
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                ffprobe_data = json.loads(result.stdout)
                metadata["ffprobe"] = ffprobe_data
        except Exception as e:
            print(f"提取元数据失败: {e}")

        return metadata

    @staticmethod
    def analyze_asset(file_path: str) -> Dict[str, Any]:
        """深度分析素材"""
        analysis = {
            "technical_info": {}
        }

        try:
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                ffprobe_data = json.loads(result.stdout)
                analysis["technical_info"]["ffprobe"] = ffprobe_data

                if "streams" in ffprobe_data:
                    for stream in ffprobe_data["streams"]:
                        if stream.get("codec_type") == "video":
                            analysis["technical_info"]["video"] = {
                                "codec": stream.get("codec_name"),
                                "resolution": f"{stream.get('width')}x{stream.get('height')}",
                                "frame_rate": stream.get("r_frame_rate"),
                                "bit_rate": stream.get("bit_rate")
                            }
                        elif stream.get("codec_type") == "audio":
                            analysis["technical_info"]["audio"] = {
                                "codec": stream.get("codec_name"),
                                "sample_rate": stream.get("sample_rate"),
                                "channels": stream.get("channels"),
                                "bit_rate": stream.get("bit_rate")
                            }
        except Exception as e:
            print(f"分析素材失败: {e}")

        return analysis

    @staticmethod
    def get_video_info(file_path: str) -> Optional[Dict[str, Any]]:
        """获取视频信息"""
        try:
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "video":
                        return {
                            "codec": stream.get("codec_name"),
                            "width": stream.get("width"),
                            "height": stream.get("height"),
                            "frame_rate": stream.get("r_frame_rate"),
                            "bit_rate": stream.get("bit_rate")
                        }
        except Exception as e:
            print(f"获取视频信息失败: {e}")
        return None

    @staticmethod
    def get_audio_info(file_path: str) -> Optional[Dict[str, Any]]:
        """获取音频信息"""
        try:
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "audio":
                        return {
                            "codec": stream.get("codec_name"),
                            "sample_rate": stream.get("sample_rate"),
                            "channels": stream.get("channels"),
                            "bit_rate": stream.get("bit_rate")
                        }
        except Exception as e:
            print(f"获取音频信息失败: {e}")
        return None
