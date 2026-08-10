"""截屏查看 Qt6 主窗口和 Agent 面板（一次性脚本）。

工作流：
1. 截取全屏 → 保存为 qt6_fullscreen.png
2. 尝试用 win32gui 找到 Qt6 主窗口并截取 → qt6_mainwindow.png
3. 输出窗口标题和位置信息
"""
import os
import time
import sys

try:
    from PIL import ImageGrab, Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("Pillow 未安装，无法截图")

try:
    import win32gui
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    print("pywin32 未安装，无法枚举窗口")


def find_qt6_windows():
    """枚举所有可见窗口，找到 Qt6 主窗口。"""
    results = []

    def _enum(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True
        try:
            rect = win32gui.GetWindowRect(hwnd)
        except Exception:
            return True
        # 过滤明显不相关的窗口
        if title in ('Settings', 'Microsoft Text Input Application', 'Program Manager',
                     'Windows Input Experience', 'MSCTFIME UI', 'Default IME'):
            return True
        results.append({
            'hwnd': hwnd,
            'title': title,
            'rect': rect,  # (left, top, right, bottom)
            'size': (rect[2] - rect[0], rect[3] - rect[1]),
        })
        return True

    win32gui.EnumWindows(_enum, None)
    return results


def capture_window(hwnd, save_path):
    """截取指定窗口的画面。"""
    rect = win32gui.GetWindowRect(hwnd)
    # 扩展一点边界，避免边框被裁
    box = (rect[0], rect[1], rect[2], rect[3])
    img = ImageGrab.grab(bbox=box, all_screens=True)
    img.save(save_path)
    return img.size


if __name__ == "__main__":
    out_dir = r"d:\拾光剪影\tests\_screenshots"
    os.makedirs(out_dir, exist_ok=True)

    if not HAS_PIL:
        sys.exit(1)

    # 1. 全屏截图
    fullscreen_path = os.path.join(out_dir, "qt6_fullscreen.png")
    img = ImageGrab.grab(all_screens=True)
    img.save(fullscreen_path)
    print(f"全屏截图: {fullscreen_path} ({img.size})")

    if not HAS_WIN32:
        sys.exit(0)

    # 2. 枚举窗口
    windows = find_qt6_windows()
    print(f"\n=== 可见窗口 {len(windows)} 个 ===")
    # 找出可能是 Qt6 主窗口的（标题含中文关键字或大小较大）
    candidates = []
    for w in windows:
        title = w['title']
        size = w['size']
        # 主窗口一般宽度 > 800
        if size[0] > 800 and size[1] > 500:
            candidates.append(w)
        print(f"  hwnd={w['hwnd']:#x} size={size} title={title!r}")

    print(f"\n=== 候选主窗口 {len(candidates)} 个（尺寸>800x500）===")
    for i, w in enumerate(candidates):
        print(f"  [{i}] hwnd={w['hwnd']:#x} size={w['size']} title={w['title']!r}")

    # 3. 截取最大的候选窗口
    if candidates:
        # 选面积最大的
        biggest = max(candidates, key=lambda w: w['size'][0] * w['size'][1])
        main_path = os.path.join(out_dir, "qt6_mainwindow.png")
        try:
            captured_size = capture_window(biggest['hwnd'], main_path)
            print(f"\n主窗口截图: {main_path} ({captured_size})")
            print(f"窗口标题: {biggest['title']!r}")
            print(f"窗口位置: {biggest['rect']}")
        except Exception as e:
            print(f"\n主窗口截图失败: {e}")
