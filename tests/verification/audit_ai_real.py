"""
AI 智能工坊 真假性审计
- 静态审计 8 个 AI 能力点：方法是否存在？源码多少行？真正调用后端还是只 print？
- 不启动 QApplication
"""
import os
import sys
import inspect

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))


def report_module(name, module_path, key_method):
    print(f"\n=== {name} ===")
    print(f"  module file: {module_path}")
    try:
        mod = __import__(module_path, fromlist=["."])
    except Exception as e:
        print(f"  ❌ IMPORT FAILED: {e}")
        return

    # 找主类
    classes = [c for c in dir(mod) if c[0].isupper() and not c.startswith("_")]
    if not classes:
        print(f"  ⚠️ No public class. Symbols: {[s for s in dir(mod) if not s.startswith('_')][:5]}")
        return
    cls_name = classes[0]
    cls = getattr(mod, cls_name)
    print(f"  main class: {cls_name}")

    # 检查关键方法
    if not hasattr(cls, key_method):
        print(f"  ❌ missing method: {key_method}")
        return

    method = getattr(cls, key_method)
    try:
        src = inspect.getsource(method)
    except Exception as e:
        print(f"  ⚠️ can't read source: {e}")
        return

    n_lines = len([l for l in src.split("\n") if l.strip()])
    # 关键信号：是不是只 print / pass
    has_print_only = "print(" in src and "return" not in src
    has_return = "return " in src
    has_real_call = any(k in src for k in [
        "subprocess.", "requests.", "urllib", "ffmpeg", "cv2.",
        "PIL.", "torch.", "transformers", "openai", "ollama",
        "whisper", "edge_tts", "pyttsx3", "azure",
        "PaddleOCR", "librosa", "WhisperModel",
    ])

    print(f"  source: {n_lines} lines")
    print(f"  has real call: {has_real_call}")
    print(f"  has return: {has_return}")
    print(f"  first 3 lines:")
    for line in src.split("\n")[1:4]:
        print(f"    {line.rstrip()}")


if __name__ == "__main__":
    print("=" * 60)
    print("AI 智能工坊 真假性审计报告")
    print("=" * 60)

    report_module(
        "Top0 一键爆款 (Top0VideoProcessor)",
        "app.modules.lego.top0_integration",
        "smart_clip",
    )
    report_module(
        "爆款预测 (ViralOptimizationEngine)",
        "app.modules.lego.viral_optimization_engine",
        "predict_viral_score",
    )
    report_module(
        "AI 剧情理解 (DramaUnderstandingEngine)",
        "app.modules.lego.drama_understanding_engine",
        "analyze_video",
    )
    report_module(
        "多 Agent 协作 (AgentWorkflow)",
        "app.modules.lego.agent_workflow",
        "run_workflow",
    )
    # 配音 / 字幕 / 数字人
    print("\n=== AI 配音 (VoiceGenerator) ===")
    try:
        from app.modules.lego import voice_generator
        print(f"  module: {voice_generator.__file__}")
        print(f"  public symbols: {[s for s in dir(voice_generator) if not s.startswith('_')][:8]}")
    except Exception as e:
        print(f"  ❌ import failed: {e}")

    print("\n=== 智能字幕 (SubtitleGenerator) ===")
    try:
        from app.modules.lego import subtitle_generator
        print(f"  module: {subtitle_generator.__file__}")
        print(f"  public symbols: {[s for s in dir(subtitle_generator) if not s.startswith('_')][:8]}")
    except Exception as e:
        print(f"  ❌ import failed: {e}")

    print("\n=== FunClip / AutoClip / Fusion / LoRA ===")
    for name in ["funclip_engine", "autoclip_engine", "videofusion_engine", "lora_editor"]:
        try:
            mod = __import__(f"app.modules.lego.{name}", fromlist=["."])
            print(f"  {name}: ✅ {mod.__file__}")
        except Exception as e:
            print(f"  {name}: ❌ {e}")

    print("\n" + "=" * 60)
    print("审计完成")
    print("=" * 60)
