import gradio as gr
import os
from ai_video_editor_local import AIVideoEditorLocal

editor = AIVideoEditorLocal()

def process_videos(files, model_choice, progress=gr.Progress()):
    if not files:
        return "❌ 请至少上传一个视频文件。", None

    output_path = "./output/final_video.mp4"
    try:
        paths = [f.name for f in files]
        editor.process(paths, model_choice, output_path)
        if os.path.exists(output_path):
            return f"✅ 处理完成！文件已保存至 {output_path}", output_path
        else:
            return "❌ 处理失败，未生成输出文件。", None
    except Exception as e:
        return f"❌ 发生错误: {str(e)}", None

with gr.Blocks(title="AI视频自动剪辑器 (本地版)") as demo:
    gr.Markdown("# 🎬 AI视频自动剪辑软件 (本地版)")
    gr.Markdown("上传多个视频片段，AI将自动提取文案、生成脚本、定位高潮点并剪辑成爆款短剧。")

    with gr.Row():
        video_inputs = gr.File(file_count="multiple", file_types=["video"], label="上传视频片段")
        model_dropdown = gr.Dropdown(choices=["qwen", "claude", "chatglm"], value="qwen", label="选择AI模型")
        submit_btn = gr.Button("开始处理", variant="primary")

    with gr.Row():
        status_output = gr.Textbox(label="状态信息", interactive=False)
        download_output = gr.Video(label="成品视频", interactive=False)

    submit_btn.click(
        fn=process_videos,
        inputs=[video_inputs, model_dropdown],
        outputs=[status_output, download_output]
    )

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, share=False)