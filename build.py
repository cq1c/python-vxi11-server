#!/usr/bin/env python3
"""VXI-11 转发器打包脚本"""

import os
import sys
import platform
from pathlib import Path


def main():
    """主打包函数"""
    # 检查 PyInstaller 是否已安装
    try:
        import PyInstaller
    except ImportError:
        print("错误: 请先安装 PyInstaller: pip install pyinstaller")
        sys.exit(1)
    
    # 设置基本参数
    script_path = Path("vxi11_forwarder.py").absolute()
    icon_path = Path("icon").absolute()
    
    # 选择图标文件
    system = platform.system()
    if system == "Windows":
        icon_file = icon_path / "app.ico"
    elif system == "Darwin":  # macOS
        icon_file = icon_path / "app.icns"
    else:
        icon_file = icon_path / "app.png"
    
    # 检查图标文件是否存在
    if not icon_file.exists():
        print(f"警告: 图标文件 {icon_file} 不存在，将使用默认图标")
        icon_option = []
    else:
        print(f"使用图标: {icon_file}")
        icon_option = [f"--icon={icon_file}"]
    
    # 构建 PyInstaller 命令
    cmd = [
        "pyinstaller",
        "--name=VXI11Forwarder",
        "--windowed",  # 无控制台窗口
        "--onefile",  # 单个可执行文件
        "--clean",    # 清理临时文件
    ]
    
    # 添加图标选项
    cmd.extend(icon_option)
    
    # 添加隐藏导入
    hidden_imports = [
        "vxi11_server",
        "vxi11_server.instrument_device",
        "vxi11_server.instrument_server",
        "vxi11_server.vxi11",
        "vxi11_server.rpc",
        "dotenv",
        "vxi11",  # 可选的客户端库
    ]
    
    for imp in hidden_imports:
        cmd.append(f"--hidden-import={imp}")
    
    # 添加数据文件（.env 文件）
    if Path(".env").exists():
        if platform.system() == "Windows":
            cmd.append("--add-data=.env;.")
        else:
            cmd.append("--add-data=.env:.")
    
    # 添加主脚本
    cmd.append(str(script_path))
    
    # 打印命令
    print("\n打包命令:")
    print(" ".join(cmd))
    print("\n开始打包...\n")
    
    # 执行命令
    import subprocess
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("\n打包成功！")
        print(f"可执行文件位于: dist/VXI11Forwarder")
    else:
        print(f"\n打包失败，错误代码: {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
