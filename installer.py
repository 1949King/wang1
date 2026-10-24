"""
ShortPlayAI Engine V1.0 安装程序
支持Windows、macOS和Linux平台
"""

import os
import sys
import shutil
import subprocess
import platform
from pathlib import Path
import json
import hashlib


class Installer:
    """安装程序主类"""
    
    def __init__(self):
        self.system = platform.system()
        self.machine = platform.machine()
        self.install_dir = self._get_default_install_dir()
        self.config = {}
        
    def _get_default_install_dir(self):
        """获取默认安装目录"""
        if self.system == "Windows":
            return os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "ShortPlayAI")
        elif self.system == "Darwin":  # macOS
            return "/Applications/ShortPlayAI.app"
        else:  # Linux
            return "/opt/shortplayai"
    
    def check_system_requirements(self):
        """检查系统要求"""
        print("检查系统要求...")
        
        issues = []
        
        # 检查Python版本
        if sys.version_info < (3, 8):
            issues.append("Python版本过低，需要3.8+")
        
        # 检查磁盘空间
        if hasattr(os, 'statvfs'):
            stat = os.statvfs(self.install_dir)
            free_space = stat.f_frsize * stat.f_bavail
            if free_space < 10 * 1024 * 1024 * 1024:  # 10GB
                issues.append("磁盘空间不足，需要至少10GB可用空间")
        
        # 检查显卡支持
        try:
            import OpenGL.GL as gl
            print(f"OpenGL版本: {gl.glGetString(gl.GL_VERSION)}")
        except ImportError:
            print("警告: 无法检查OpenGL支持")
        
        return issues
    
    def create_install_directories(self):
        """创建安装目录"""
        print("创建安装目录...")
        
        dirs = [
            self.install_dir,
            os.path.join(self.install_dir, "app"),
            os.path.join(self.install_dir, "plugins"),
            os.path.join(self.install_dir, "docs"),
            os.path.join(self.install_dir, "config"),
            os.path.join(self.install_dir, "cache"),
            os.path.join(self.install_dir, "projects"),
        ]
        
        for directory in dirs:
            os.makedirs(directory, exist_ok=True)
            print(f"  创建目录: {directory}")
    
    def copy_application_files(self, source_dir):
        """复制应用程序文件"""
        print("复制应用程序文件...")
        
        # 复制主要文件
        app_files = [
            "main_qt6.py",
            "app",
            "license",
            "docs"
        ]
        
        for item in app_files:
            src = os.path.join(source_dir, item)
            dst = os.path.join(self.install_dir, item)
            
            if os.path.exists(src):
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                print(f"  复制: {item}")
    
    def create_desktop_shortcut(self):
        """创建桌面快捷方式"""
        print("创建桌面快捷方式...")
        
        if self.system == "Windows":
            self._create_windows_shortcut()
        elif self.system == "Darwin":
            self._create_macos_shortcut()
        else:
            self._create_linux_shortcut()
    
    def _create_windows_shortcut(self):
        """创建Windows快捷方式"""
        import win32com.client
        
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        shortcut_path = os.path.join(desktop, "ShortPlayAI.lnk")
        target = os.path.join(self.install_dir, "main_qt6.py")
        
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = target
        shortcut.WorkingDirectory = self.install_dir
        shortcut.Description = "ShortPlayAI Engine V1.0"
        shortcut.save()
        
        print(f"  创建快捷方式: {shortcut_path}")
    
    def _create_macos_shortcut(self):
        """创建macOS快捷方式"""
        applications = "/Applications"
        shortcut_path = os.path.join(applications, "ShortPlayAI.app")
        
        # 创建macOS应用包结构
        app_contents = os.path.join(shortcut_path, "Contents")
        os.makedirs(app_contents, exist_ok=True)
        
        # 创建Info.plist
        info_plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>main_qt6</string>
    <key>CFBundleIdentifier</key>
    <string>com.shortplayai.engine</string>
    <key>CFBundleName</key>
    <string>ShortPlayAI</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
"""
        
        with open(os.path.join(app_contents, "Info.plist"), "w") as f:
            f.write(info_plist)
        
        print(f"  创建应用包: {shortcut_path}")
    
    def _create_linux_shortcut(self):
        """创建Linux快捷方式"""
        desktop_file = os.path.join(os.path.expanduser("~"), ".local/share/applications/shortplayai.desktop")
        os.makedirs(os.path.dirname(desktop_file), exist_ok=True)
        
        desktop_entry = f"""[Desktop Entry]
Name=ShortPlayAI Engine
Comment=AI短剧编辑器
Exec=python3 {os.path.join(self.install_dir, "main_qt6.py")}
Icon={os.path.join(self.install_dir, "docs/icon.png")}
Terminal=false
Type=Application
Categories=Video;AudioVideo;
"""
        
        with open(desktop_file, "w") as f:
            f.write(desktop_entry)
        
        print(f"  创建桌面文件: {desktop_file}")
    
    def register_file_associations(self):
        """注册文件关联"""
        print("注册文件关联...")
        
        if self.system == "Windows":
            self._register_windows_associations()
        elif self.system == "Darwin":
            self._register_macos_associations()
        else:
            self._register_linux_associations()
    
    def _register_windows_associations(self):
        """注册Windows文件关联"""
        import winreg
        
        extensions = [".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav"]
        
        for ext in extensions:
            try:
                key_path = f"Software\\Classes\\{ext[1:]}\\shell\\open\\command"
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
                winreg.SetValue(key, "", winreg.REG_SZ, f'"{os.path.join(self.install_dir, "main_qt6.py")}" "%1"')
                winreg.CloseKey(key)
                print(f"  注册关联: {ext}")
            except Exception as e:
                print(f"  警告: 无法注册 {ext}: {e}")
    
    def _register_macos_associations(self):
        """注册macOS文件关联"""
        # macOS文件关联通常在应用包中处理
        print("  macOS文件关联在应用包中处理")
    
    def _register_linux_associations(self):
        """注册Linux文件关联"""
        # Linux文件关联通过.desktop文件处理
        print("  Linux文件关联在.desktop文件中处理")
    
    def create_uninstaller(self):
        """创建卸载程序"""
        print("创建卸载程序...")
        
        uninstaller_script = f"""#!/bin/bash
# ShortPlayAI Engine 卸载程序

INSTALL_DIR="{self.install_dir}"

echo "正在卸载 ShortPlayAI Engine..."

# 删除桌面快捷方式
rm -f ~/Desktop/ShortPlayAI.lnk 2>/dev/null
rm -f ~/.local/share/applications/shortplayai.desktop 2>/dev/null

# 删除安装目录
rm -rf "$INSTALL_DIR"

echo "卸载完成"
"""
        
        uninstaller_path = os.path.join(self.install_dir, "uninstall.sh")
        with open(uninstaller_path, "w") as f:
            f.write(uninstaller_script)
        
        os.chmod(uninstaller_path, 0o755)
        print(f"  创建卸载程序: {uninstaller_path}")
    
    def save_install_config(self):
        """保存安装配置"""
        print("保存安装配置...")
        
        config = {
            "version": "1.0.0",
            "install_date": "2026-03-29",
            "install_dir": self.install_dir,
            "system": self.system,
            "machine": self.machine,
            "components": {
                "core": True,
                "plugins": True,
                "docs": True,
                "examples": False
            }
        }
        
        config_path = os.path.join(self.install_dir, "config", "install.json")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        print(f"  保存配置: {config_path}")
    
    def verify_installation(self):
        """验证安装"""
        print("验证安装...")
        
        checks = []
        
        # 检查主程序
        main_program = os.path.join(self.install_dir, "main_qt6.py")
        if os.path.exists(main_program):
            checks.append(("主程序", True))
        else:
            checks.append(("主程序", False))
        
        # 检查核心目录
        core_dir = os.path.join(self.install_dir, "app")
        if os.path.exists(core_dir):
            checks.append(("核心目录", True))
        else:
            checks.append(("核心目录", False))
        
        # 检查插件目录
        plugins_dir = os.path.join(self.install_dir, "plugins")
        if os.path.exists(plugins_dir):
            checks.append(("插件目录", True))
        else:
            checks.append(("插件目录", False))
        
        # 检查配置文件
        config_file = os.path.join(self.install_dir, "config", "install.json")
        if os.path.exists(config_file):
            checks.append(("配置文件", True))
        else:
            checks.append(("配置文件", False))
        
        # 打印验证结果
        print("\n安装验证结果:")
        for name, success in checks:
            status = "✓" if success else "✗"
            print(f"  {status} {name}")
        
        return all(success for _, success in checks)
    
    def install(self, source_dir):
        """执行安装"""
        print("="*60)
        print("ShortPlayAI Engine V1.0 安装程序")
        print("="*60)
        
        try:
            # 1. 检查系统要求
            issues = self.check_system_requirements()
            if issues:
                print("\n系统要求检查失败:")
                for issue in issues:
                    print(f"  ✗ {issue}")
                print("\n请解决以上问题后重试。")
                return False
            
            print("  ✓ 系统要求检查通过")
            
            # 2. 创建安装目录
            self.create_install_directories()
            
            # 3. 复制应用程序文件
            self.copy_application_files(source_dir)
            
            # 4. 创建快捷方式
            self.create_desktop_shortcut()
            
            # 5. 注册文件关联
            self.register_file_associations()
            
            # 6. 创建卸载程序
            self.create_uninstaller()
            
            # 7. 保存安装配置
            self.save_install_config()
            
            # 8. 验证安装
            print("\n" + "="*60)
            if self.verify_installation():
                print("✓ 安装成功完成！")
                print("="*60)
                print("\n您现在可以启动 ShortPlayAI Engine V1.0")
                print(f"安装位置: {self.install_dir}")
                print("\n如需卸载，请运行卸载程序或手动删除安装目录。")
                return True
            else:
                print("✗ 安装验证失败")
                print("="*60)
                return False
                
        except Exception as e:
            print(f"\n✗ 安装过程中发生错误: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("使用方法: python installer.py <源目录>")
        print("示例: python installer.py /path/to/source")
        sys.exit(1)
    
    source_dir = sys.argv[1]
    
    if not os.path.exists(source_dir):
        print(f"错误: 源目录不存在: {source_dir}")
        sys.exit(1)
    
    installer = Installer()
    success = installer.install(source_dir)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()