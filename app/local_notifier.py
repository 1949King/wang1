import logging
import time

# --- 日志配置 (同时输出到控制台和文件) ---
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 控制台处理器
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

# 文件处理器
file_handler = logging.FileHandler("notification_log.log", encoding="utf-8")
file_handler.setFormatter(log_formatter)

# 获取 logger 实例
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(console_handler)
logger.addHandler(file_handler)

def send_local_notification(message: str):
    """
    将通知消息打印到控制台并写入日志文件
    
    Args:
        message (str): 要发送的通知内容
    """
    logger.info(message)
    # 可选：再额外打印一次，确保在所有控制台上都可见
    logger.info(f'[NOTIFICATION] {message}')

def main():
    """主函数"""
    logger.info("--- 程序启动 ---")
    
    # 模拟一些操作...
    time.sleep(1)
    
    # 您需要发送的通知消息放在这里
    notification_content = "测试消息，如果看到则说明本地通知运行正常！"
    
    send_local_notification(notification_content)
    
    # 更多业务逻辑...
    time.sleep(1)
    send_local_notification("程序任务已完成。")
    
    logger.info("--- 程序执行完毕 ---")

if __name__ == "__main__":
    main()