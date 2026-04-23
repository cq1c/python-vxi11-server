#!/usr/bin/env python3
"""VXI-11 设备转发器 - 图形化界面"""

import socket
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 导入 VXI-11 服务器库
import vxi11_server as Vxi11
from vxi11_server.instrument_device import ReadRespReason

# 尝试导入 VXI-11 客户端库
try:
    import vxi11
    VXI11_CLIENT_AVAILABLE = True
except ImportError:
    VXI11_CLIENT_AVAILABLE = False
    print("警告: python-vxi11 客户端库不可用，只能使用模拟模式")

# 从环境变量读取配置
USE_MOCK_MODE = os.getenv('USE_MOCK_MODE', 'True').lower() == 'true'


class ForwardingDevice(Vxi11.InstrumentDevice):
    """转发设备 - 将请求转发到实际的 VXI-11 设备"""
    
    def __init__(self, device_name, device_lock, forward_host, forward_device, log_callback, use_mock):
        super().__init__(device_name, device_lock)
        self.forward_host = forward_host
        self.forward_device = forward_device
        self.log_callback = log_callback
        self.use_mock = use_mock
        self.target_instr = None
        
        if not self.use_mock and VXI11_CLIENT_AVAILABLE:
            try:
                connect_str = f"TCPIP::{forward_host}::{forward_device}::INSTR"
                self.log(f"正在连接到真实设备: {connect_str}")
                self.target_instr = vxi11.Instrument(connect_str)
                self.log("真实设备连接成功")
            except Exception as e:
                self.log(f"连接真实设备失败: {e}，将切换到模拟模式")
                self.use_mock = True
        else:
            self.log(f"使用模拟模式，目标: {forward_host}::{forward_device}")
    
    def log(self, message):
        """记录日志"""
        if self.log_callback:
            timestamp = time.strftime('%H:%M:%S')
            self.log_callback(f"[{timestamp}] {message}")
    
    def device_init(self):
        """设备初始化"""
        self.log(f"设备初始化: {self.forward_host}::{self.forward_device}")
    
    def device_write(self, opaque_data, flags, io_timeout):
        """转发写操作"""
        self.log(f"写入请求: {len(opaque_data)} 字节")
        try:
            if self.use_mock or not self.target_instr:
                self.log(f"[模拟] 写入数据: {opaque_data}")
                return Vxi11.vxi11.ERR_NO_ERROR
            else:
                self.log(f"[真实] 写入数据: {opaque_data}")
                self.target_instr.write_raw(opaque_data)
                return Vxi11.vxi11.ERR_NO_ERROR
        except Exception as e:
            self.log(f"写入错误: {e}")
            return Vxi11.vxi11.ERR_IO_ERROR
    
    def device_read(self, request_size, term_char, flags, io_timeout):
        """转发读操作"""
        self.log(f"读取请求: {request_size} 字节")
        try:
            if self.use_mock or not self.target_instr:
                response = f"Read from {self.forward_host}::{self.forward_device}".encode('ascii')
                self.log(f"[模拟] 读取数据: {response}")
                return Vxi11.vxi11.ERR_NO_ERROR, ReadRespReason.END, response
            else:
                response = self.target_instr.read_raw(request_size)
                self.log(f"[真实] 读取数据: {response}")
                return Vxi11.vxi11.ERR_NO_ERROR, ReadRespReason.END, response
        except Exception as e:
            self.log(f"读取错误: {e}")
            return Vxi11.vxi11.ERR_IO_ERROR, ReadRespReason.END, b''
    
    def device_readstb(self, flags, io_timeout):
        """读取状态字节"""
        self.log("读取状态字节请求")
        try:
            if self.use_mock or not self.target_instr:
                return Vxi11.vxi11.ERR_NO_ERROR, 0
            else:
                stb = self.target_instr.read_stb()
                return Vxi11.vxi11.ERR_NO_ERROR, stb
        except Exception as e:
            self.log(f"读取状态字节错误: {e}")
            return Vxi11.vxi11.ERR_IO_ERROR, 0
    
    def device_trigger(self, flags, io_timeout):
        """触发请求"""
        self.log("触发请求")
        try:
            if not self.use_mock and self.target_instr:
                self.target_instr.trigger()
            return Vxi11.vxi11.ERR_NO_ERROR
        except Exception as e:
            self.log(f"触发错误: {e}")
            return Vxi11.vxi11.ERR_IO_ERROR
    
    def device_clear(self, flags, io_timeout):
        """清除请求"""
        self.log("清除请求")
        try:
            if not self.use_mock and self.target_instr:
                self.target_instr.clear()
            return Vxi11.vxi11.ERR_NO_ERROR
        except Exception as e:
            self.log(f"清除错误: {e}")
            return Vxi11.vxi11.ERR_IO_ERROR
    
    def device_remote(self, flags, io_timeout):
        """远程模式"""
        self.log("远程模式请求")
        return Vxi11.vxi11.ERR_NO_ERROR
    
    def device_local(self, flags, io_timeout):
        """本地模式"""
        self.log("本地模式请求")
        return Vxi11.vxi11.ERR_NO_ERROR
    
    def device_enable_srq(self, enable, handle):
        """启用/禁用 SRQ"""
        self.log(f"SRQ 启用: {enable}")
        return Vxi11.vxi11.ERR_NO_ERROR
    
    def device_docmd(self, flags, io_timeout, cmd, network_order, data_size, opaque_data_in):
        """执行命令"""
        self.log(f"执行命令: {cmd}")
        return Vxi11.vxi11.ERR_NO_ERROR, b""


class VXI11ForwarderGUI:
    """VXI-11 转发器图形界面"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("VXI-11 设备转发器")
        self.root.geometry("700x650")
        
        self.server = None
        self.server_thread = None
        self.running = False
        
        self.setup_ui()
    
    def get_local_ip(self):
        """获取本机 IPv4 地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return "127.0.0.1"
    
    def setup_ui(self):
        """设置用户界面"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="wens")
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # 标题
        title_label = ttk.Label(main_frame, text="VXI-11 设备转发器", font=('Arial', 14, 'bold'))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 10))
        
        # 模式选择
        mode_frame = ttk.Frame(main_frame)
        mode_frame.grid(row=1, column=0, columnspan=4, pady=(0, 10), sticky="w")
        
        self.use_mock_var = tk.BooleanVar(value=USE_MOCK_MODE)
        ttk.Label(mode_frame, text="运行模式:").pack(side=tk.LEFT)
        
        ttk.Radiobutton(mode_frame, text="模拟模式", variable=self.use_mock_var, 
                       value=True).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="真实模式", variable=self.use_mock_var, 
                       value=False).pack(side=tk.LEFT, padx=5)
        
        if not VXI11_CLIENT_AVAILABLE:
            real_mode_radio = [child for child in mode_frame.winfo_children() 
                              if isinstance(child, ttk.Radiobutton) and '真实' in str(child)]
            if real_mode_radio:
                real_mode_radio[0].config(state=tk.DISABLED)
        
        # 源设备地址
        ttk.Label(main_frame, text="源设备地址:").grid(row=2, column=0, sticky="w", pady=5)
        self.source_host = ttk.Entry(main_frame, width=30)
        self.source_host.grid(row=2, column=1, sticky="we", pady=5)
        self.source_host.insert(0, "192.168.1.100")
        
        ttk.Label(main_frame, text="::").grid(row=2, column=2, padx=5)
        
        self.source_device = ttk.Entry(main_frame, width=15)
        self.source_device.grid(row=2, column=3, pady=5)
        self.source_device.insert(0, "inst0")
        
        # 目标地址
        ttk.Label(main_frame, text="本机监听地址:").grid(row=3, column=0, sticky="w", pady=5)
        self.target_host = ttk.Entry(main_frame, width=30)
        self.target_host.grid(row=3, column=1, sticky="we", pady=5)
        self.target_host.insert(0, self.get_local_ip())
        
        ttk.Label(main_frame, text="::").grid(row=3, column=2, padx=5)
        
        self.target_device = ttk.Entry(main_frame, width=15)
        self.target_device.grid(row=3, column=3, pady=5)
        self.target_device.insert(0, "inst1")
        
        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=4, pady=15)
        
        self.start_button = ttk.Button(button_frame, text="启动转发", command=self.start_forwarding)
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        self.stop_button = ttk.Button(button_frame, text="停止转发", command=self.stop_forwarding, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        # 状态标签
        self.status_var = tk.StringVar(value=f"状态: 未运行 (当前模式: {'模拟' if USE_MOCK_MODE else '真实'})")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, font=('Arial', 10, 'bold'))
        status_label.grid(row=5, column=0, columnspan=4, pady=(0, 10))
        
        # 日志区域
        ttk.Label(main_frame, text="连接日志:").grid(row=6, column=0, sticky="w", pady=(10, 5))
        
        self.log_text = scrolledtext.ScrolledText(main_frame, height=15, width=80, wrap=tk.WORD)
        self.log_text.grid(row=7, column=0, columnspan=4, sticky="wens")
        
        main_frame.rowconfigure(7, weight=1)

        # 配置日志文本的样式
        self.log_text.tag_config('info', foreground='blue')
        self.log_text.tag_config('success', foreground='green')
        self.log_text.tag_config('error', foreground='red')
        self.log_text.tag_config('warning', foreground='orange')
    
    def log(self, message, tag='info'):
        """添加日志"""
        self.log_text.insert(tk.END, message + "\n", tag)
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def start_forwarding(self):
        """启动转发"""
        source_host = self.source_host.get().strip()
        source_device = self.source_device.get().strip()
        target_device_name = self.target_device.get().strip()
        use_mock = self.use_mock_var.get()
        
        if not source_host or not source_device or not target_device_name:
            self.log("错误: 请填写所有字段", 'error')
            return
        
        try:
            mode_str = "模拟" if use_mock else "真实"
            self.log(f"正在启动转发器 ({mode_str}模式)...", 'info')
            self.log(f"源设备: {source_host}::{source_device}", 'info')
            self.log(f"目标监听: {self.get_local_ip()}::{target_device_name}", 'info')
            
            # 创建转发设备类 - 使用闭包
            log_callback = lambda msg: self.log(msg, 'info')
            
            class ForwardingDeviceWrapper(ForwardingDevice):
                def __init__(self, device_name, device_lock):
                    super().__init__(device_name, device_lock, source_host, 
                                    source_device, log_callback, use_mock)
            
            # 启动服务器
            self.server = Vxi11.InstrumentServer()
            self.server.add_device_handler(ForwardingDeviceWrapper, target_device_name)
            
            # 在单独线程中运行服务器
            self.running = True
            self.server_thread = threading.Thread(target=self.run_server, daemon=True)
            self.server_thread.start()
            
            # 更新 UI 状态
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.status_var.set(f"状态: 运行中 ({mode_str}模式)")
            self.log("转发器启动成功!", 'success')
            
        except Exception as e:
            self.log(f"启动失败: {e}", 'error')
            self.running = False
    
    def run_server(self):
        """运行服务器的线程函数"""
        try:
            self.server.listen()
            # listen() 会启动守护线程，我们只需要保持这个线程存活
            while self.running:
                time.sleep(0.5)
        except Exception as e:
            if self.running:
                self.log(f"服务器错误: {e}", 'error')
    
    def stop_forwarding(self):
        """停止转发"""
        self.log("正在停止转发器...", 'warning')
        self.running = False
        
        # 停止服务器
        if self.server:
            try:
                self.server.close()
            except Exception as e:
                self.log(f"关闭服务器时出错: {e}", 'error')
            self.server = None
        
        if self.server_thread:
            self.server_thread.join(timeout=2.0)
            self.server_thread = None
        
        # 更新 UI 状态
        mode_str = "模拟" if self.use_mock_var.get() else "真实"
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.status_var.set(f"状态: 未运行 (当前模式: {mode_str})")
        self.log("转发器已停止", 'warning')


def main():
    """主函数"""
    root = tk.Tk()
    app = VXI11ForwarderGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
