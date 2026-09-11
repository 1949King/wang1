import sys
import traceback
import os
from datetime import datetime

import logging
logger = logging.getLogger("AI短剧编辑器.modules.utils.error_handling")

# ===================== 崩溃容错与异常处理 =====================
def setup_exception_handler():
    """设置全局异常处理器"""
    def exception_handler(exc_type, exc_value, exc_traceback):
        """全局异常处理函数"""
        if issubclass(exc_type, KeyboardInterrupt):
            # 处理键盘中断
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        # 记录错误信息到日志文件
        error_log = os.path.join("短剧AI剪辑输出", "error_log.txt")
        try:
            with open(error_log, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now()}] 错误类型: {exc_type.__name__}\n")
                f.write(f"错误信息: {exc_value}\n")
                f.write("堆栈跟踪:\n")
                traceback.print_tb(exc_traceback, file=f)
                f.write("\n" + "="*80 + "\n")
        except Exception as e:
            # 日志写入失败时至少打印到 stderr，避免异常信息完全丢失
            logger.error(f'[CRASH] 全局异常处理器写入日志失败: {e}')
        
        # 打印错误信息
        logger.error(f'\n未捕获的异常: {exc_type.__name__}: {exc_value}')
        traceback.print_tb(exc_traceback)
    
    # 设置全局异常处理器
    sys.excepthook = exception_handler

# 设置全局异常处理器
setup_exception_handler()
