"""
utils/thread_pool.py
====================
B1 第一刀: 抽取 modules.py:98-135 ThreadPool 到独立文件
最小侵入: 在 modules.py 顶部 `from ..utils.thread_pool import ThreadPool`
"""
import queue
import threading


class ThreadPool:
    """轻量级线程池 (原 modules.py:98-135)"""
    def __init__(self, max_workers=4):
        self.max_workers = max_workers
        self.tasks = queue.Queue()
        self.workers = []
        self.running = False

    def start(self):
        self.running = True
        for i in range(self.max_workers):
            worker = threading.Thread(target=self._worker, daemon=True)
            worker.start()
            self.workers.append(worker)

    def _worker(self):
        while self.running:
            try:
                task = self.tasks.get(timeout=0.1)
                task()
                self.tasks.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"线程池工作线程错误: {e}")

    def submit(self, task):
        self.tasks.put(task)

    def shutdown(self):
        self.running = False
        self.tasks.join()
        for worker in self.workers:
            worker.join(timeout=1)
