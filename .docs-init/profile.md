# 项目画像

## 基本信息
- 项目名：python-vxi11-server / VISA 设备映射工具
- 主要语言：Python；前端为 TypeScript + Vue
- 技术栈：Python socketserver / asyncio / xdrlib / pywebview；VXI-11、HiSLIP、raw SOCKET 协议转发；Vue 3 + Vite + Element Plus + pnpm
- 入口文件清单：
  - `app.py`：pywebview 桌面入口与映射控制 API
  - `vxi11_server/__init__.py`：Python 包公共导出入口
  - `demo_servers/*.py`：示例 VXI-11 服务端入口
  - `view/src/main.ts`：前端入口
  - `scripts/build_pyinstaller.py`：打包入口
- 配置文件清单：
  - `README.md`
  - `view/package.json`
  - `view/vite.config.ts`
  - `view/tsconfig*.json`
  - `view/eslint.config.ts`
  - `view/.oxfmtrc.json`
  - `view/.oxlintrc.json`
  - `view/pnpm-lock.yaml`

## 项目类型（勾选）
- [x] Web/桌面服务（pywebview 暴露 JS API，前端驱动后端）
- [x] 后台守护 / 长连接服务（多协议 relay source 持续监听）
- [x] 框架 / SDK / 库（VXI-11 server/client 基础库）
- [x] 消息消费者 / 事件驱动（RPC handler、HiSLIP/Socket 会话处理）

## 规模档位
- 总文件数（粗略）：64（排除 `.git`、`node_modules`、`__pycache__`）
- 业务文件数（估算）：42 个 Python/TypeScript/Vue 文件
- 档位：M
- 选定流水线策略：完整 5 阶段；核心 Python relay/VXI-11 与 `view/src/App.vue` 全量阅读，Vue 默认脚手架组件按低风险跳过

## 候选主环类型
基于项目类型，预期会找到的环（仅作探照灯方向，不是结论）：
- UI start/stop -> 后端映射生命周期 -> 状态/日志回传 UI
- 客户端协议请求 -> 本地 source -> 目标 target -> 响应回写客户端
- VXI-11 create_link/write/read/destroy_link 资源生命周期
- SRQ 异步通知 enable -> signal -> callback -> disable

## 已知风险
- 是否含动态分发 / 反射 / 元编程：是，RPC 使用 `handle_<proc>` 动态分发；VXI-11 relay 动态创建 `InstrumentDevice` 子类
- 是否含自动生成代码：是，`view/auto-imports.d.ts`、`view/components.d.ts`、`node_modules`、`__pycache__` 属于生成/依赖产物
- 是否含跨进程 / 跨服务调用：是，VXI-11/HiSLIP/SOCKET 均访问外部仪器或本机监听端口；pywebview 桥接浏览器 JS 与 Python
- 其他风险：无 Python 依赖清单；`app.py` 会 monkey patch `vxi11_server.rpc.TCPServer`；`instrument_server.py` 存在一个疑似未实现的 `lock.is_open` 调用路径

## 阶段 0 自检
- [x] profile.md 已生成
- [x] 规模档位已确定
- [x] 入口文件清单非空
