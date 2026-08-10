import os
import time
import threading
import sys

# 添加app目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

# app/ai_short_drama_editor.py
import subprocess

def detect_gpu_encoder():
    """模拟GPU编码器检测"""
    try:
        # 示例：调用nvidia-smi检测GPU
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        if result.returncode == 0:
            return "NVIDIA GPU Encoder"
        else:
            return "CPU Encoder"
    except FileNotFoundError:
        return "CPU Encoder"

GPU_ENCODER = detect_gpu_encoder()
MAX_PARALLEL = 4  # 最大并行线程数

class TestAIEditor:
    def __init__(self):
        self.test_results = []
    
    def run_all_tests(self):
        """运行所有测试"""
        print("=== AI短剧编辑器测试 ===")
        print(f"Python版本: {sys.version}")
        print(f"当前目录: {os.getcwd()}")
        print(f"GPU编码器: {GPU_ENCODER}")
        print(f"最大线程数: {MAX_PARALLEL}")
        print()
        
        # 测试GPU检测
        self.test_gpu_detection()
        
        # 测试多线程
        self.test_multithreading()
        
        # 测试依赖
        self.test_dependencies()
        
        # 测试目录结构
        self.test_directory_structure()
        
        # 输出测试结果
        self.print_test_results()
    
    def test_gpu_detection(self):
        """测试GPU检测功能"""
        try:
            encoder = detect_gpu_encoder()
            print(f"✅ GPU检测成功: {encoder}")
            self.test_results.append({"test": "GPU检测", "status": "成功", "message": f"检测到GPU编码器: {encoder}"})
        except Exception as e:
            print(f"❌ GPU检测失败: {e}")
            self.test_results.append({"test": "GPU检测", "status": "失败", "message": str(e)})
    
    def test_multithreading(self):
        """测试多线程功能"""
        try:
            def test_thread(i):
                time.sleep(0.1)
                return i
            
            threads = []
            results = []
            
            # 测试线程池
            for i in range(5):
                t = threading.Thread(target=lambda i=i: results.append(test_thread(i)))
                threads.append(t)
                t.start()
            
            for t in threads:
                t.join()
            
            if len(results) == 5:
                print("✅ 多线程测试成功")
                self.test_results.append({"test": "多线程", "status": "成功", "message": f"成功创建并运行5个线程"})
            else:
                print(f"❌ 多线程测试失败: 只运行了{len(results)}个线程")
                self.test_results.append({"test": "多线程", "status": "失败", "message": f"线程运行数量不足"})
        except Exception as e:
            print(f"❌ 多线程测试失败: {e}")
            self.test_results.append({"test": "多线程", "status": "失败", "message": str(e)})
    
    def test_dependencies(self):
        """测试依赖项"""
        required_deps = [
            'tkinter',
            'subprocess',
            'threading',
            'requests',
            'json',
            'os',
            'time',
            'random'
        ]
        
        missing_deps = []
        for dep in required_deps:
            try:
                __import__(dep)
            except ImportError:
                missing_deps.append(dep)
        
        if not missing_deps:
            print("✅ 依赖项测试成功")
            self.test_results.append({"test": "依赖项", "status": "成功", "message": "所有必需依赖都已安装"})
        else:
            print(f"❌ 依赖项测试失败: 缺少 {missing_deps}")
            self.test_results.append({"test": "依赖项", "status": "失败", "message": f"缺少依赖: {missing_deps}"})
    
    def test_directory_structure(self):
        """测试目录结构"""
        required_dirs = [
            'app',
            '短剧AI剪辑输出'
        ]
        
        missing_dirs = []
        for dir_name in required_dirs:
            if not os.path.exists(dir_name):
                missing_dirs.append(dir_name)
        
        if not missing_dirs:
            print("✅ 目录结构测试成功")
            self.test_results.append({"test": "目录结构", "status": "成功", "message": "所有必需目录都已存在"})
        else:
            print(f"⚠️  目录结构测试: 缺少 {missing_dirs}")
            self.test_results.append({"test": "目录结构", "status": "警告", "message": f"缺少目录: {missing_dirs}"})
    
    def print_test_results(self):
        """打印测试结果"""
        print()
        print("=== 测试结果汇总 ===")
        
        success_count = 0
        fail_count = 0
        warn_count = 0
        
        for result in self.test_results:
            status = result["status"]
            if status == "成功":
                success_count += 1
                print(f"✅ {result['test']}: {result['message']}")
            elif status == "失败":
                fail_count += 1
                print(f"❌ {result['test']}: {result['message']}")
            else:
                warn_count += 1
                print(f"⚠️  {result['test']}: {result['message']}")
        
        print()
        print(f"测试完成: 成功={success_count}, 失败={fail_count}, 警告={warn_count}")
        
        if fail_count == 0:
            print("🎉 所有测试通过！")
        else:
            print("💡 请检查失败的测试项并修复")

if __name__ == "__main__":
    tester = TestAIEditor()
    tester.run_all_tests()
