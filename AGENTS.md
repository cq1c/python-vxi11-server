# python-vxi11-server

> 本文件是给 AI 编码助手（Claude Code / Cursor / Codex / Copilot 等）的项目说明。
> 跨工具标准：AGENTS.md 是单一真相源；其他工具文件应由软链接指向它。

## 项目一句话
Python VXI-11 服务端库与 VISA 多协议映射桌面工具。

## 关键技术决策（最先读）
- 包管理：Python 端暂无 `requirements.txt`；前端使用 `pnpm`
- 运行时：Python 3.10+；前端 Node `^20.19.0 || >=22.12.0`
- 框架：pywebview 桌面壳；Vue 3 + Vite + Element Plus 前端
- 协议：VXI-11、HiSLIP、raw TCP SOCKET；VXI-11 依赖 portmap/rpcbind 语义
- 打包：`scripts/build_pyinstaller.py` 先构建 `view/dist`，再用 PyInstaller 打包 `app.py`

## 不可违反的约束
> Agent 修改代码前必读。违反这些约束的改动必须显式说明理由。

- `app.py` 是 pywebview 控制面入口，`JsApi` 方法名必须与 `view/src/App.vue` 的 `PyApi` 类型同步。
- 映射启动/停止必须经过 `JsApi.start_mapping()` / `JsApi.stop_mapping()`，保持锁保护、失败清理和 `_running` 状态一致。
- 新增协议必须同时实现 `RelayClient`、`RelaySource`、`make_target()`、`make_source()`，并更新 UI endpoint 配置。
- 协议 fallback 顺序是 HiSLIP > VXI-11 > SOCKET；修改顺序会改变跨协议映射行为。
- VXI-11 device handler 传入的是类，不是实例；`InstrumentServer` 会为每个 link 创建新 device 实例。
- VXI-11 link id、`DeviceLock`、device instance 是会话隔离边界，禁止把同一个 target client 跨外部客户端共享。
- SOCKET 与 HiSLIP source 的**协议级 relay 路径**靠 `?` 启发式触发上游 read（VXI-11 source 走显式 `device_read` RPC，不受影响）；改变它会影响 SCPI 请求/响应节奏。"同协议直连"开关启用 TCP passthrough 路径会绕开此启发式。
- `app.py` monkey patch 了 `vxi11_server.rpc.TCPServer` 的 portmap 注册地址处理；删除前必须验证 Windows 与 `0.0.0.0` 场景。
- `vxi11_server/vxi11.py` 与 `vxi11_server/rpc.py` 是协议/移植代码，优先做小范围修补并保留线缆协议兼容性。
- 不确定的外部仪器行为、动态 RPC 分发和未覆盖协议语义必须标 `⚠️`，不要猜。

## 业务核心
**本项目的核心是“映射生命周期控制环”和“多协议 relay 会话环”。修改业务代码前，先读 `LOOPS.md`。**

主要模块：
- `app.py` — pywebview 后端、配置持久化、source 生命周期管理、日志回推
- `view/src/App.vue` — 桌面 UI 控制面，调用 Python bridge 并展示状态/日志
- `vxi11_server/transports/` — 协议无关 relay 抽象与 VXI-11/HiSLIP/SOCKET 实现；含同协议 TCP passthrough 路径（`passthrough.py`）
- `vxi11_server/instrument_server.py` — VXI-11 server、device registry、link lifecycle
- `vxi11_server/instrument_device.py` — 可继承的仪器 hook 与默认仪器行为
- `vxi11_server/vxi11.py` / `rpc.py` — VXI-11 客户端、RPC 编解码与 portmap 客户端
- `vxi11_server/portmap_server.py` — 内置最小 portmap，用于无系统 rpcbind 的场景

## 常用命令
```bash
# 前端依赖
cd view && pnpm install

# 前端开发服务，供 app.py 的默认 http://localhost:5173 使用
cd view && pnpm run dev

# 启动桌面映射工具
python app.py

# 前端构建
cd view && pnpm run build

# PyInstaller 打包
python scripts/build_pyinstaller.py
```

## Agent 行为约定
- 修改前先 grep `LOOPS.md` 中的语义节点名，确认是否影响控制面或数据面环。
- 不要在稳定文档里记录具体行号；需要证据时使用 `.docs-init/findings.md`。
- 遇到动态 RPC handler、外部仪器、HiSLIP 高级语义时显式标 `⚠️`。
- 大型重构前先与人类确认，尤其是协议抽象、link lifecycle、portmap、pywebview bridge。

## 文档地图
- `LOOPS.md` — 业务/协议逻辑环，修改业务前必读
- `.docs-init/profile.md` — 项目画像
- `.docs-init/skeleton.md` — 文件骨架与阅读标签
- `.docs-init/findings.md` — 带行号的原始证据库
- `.docs-init/loops_draft.md` — 逻辑环推导草稿

## 已知限制（relay 行为）

下面这些场景是协议层面的固有限制，不是代码缺陷；改动相关代码前需要先理解为什么是这样。

- **HiSLIP/SOCKET source + VXI-11 target，且载荷不是 SCPI 文本**：协议级 relay 会卡住或丢响应。原因：HiSLIP/SOCKET 协议本身没有"客户端想读"的 wire-level 动词，relay 必须靠 `?` 启发式决定是否调用上游 `device_read`；VXI-11 target 又是严格的请求-响应（不调 `device_read` 不会推数据），所以加 reader 线程也救不了。**绕过方式**：让 target 也启用 HiSLIP 或 SOCKET，并打开"同协议直连"，passthrough 路径不看字节内容。
- **HiSLIP/SOCKET 同协议跨网段 + `?` 出现在二进制载荷里**：协议级 relay 会误把它当成查询并尝试 read，可能阻塞到超时。**绕过方式**：勾选"同协议直连"。
- **VXI-11 passthrough 下的 `create_intr_chan`（中断通道）**：客户端在 RPC 里把自己的 IP/port 直接写进 payload，target 会试图**直连**客户端，不经过 relay。多数 SCPI 客户端不开中断；如果用到了，请退到协议级 relay。
- **同协议直连 + target 不可达**：passthrough 不会走"HiSLIP > VXI-11 > SOCKET" fallback——勾上开关后等于承诺该协议的 target 可用。需要 fallback 时关掉开关。
- **VXI-11 passthrough 与 target portmap 端口漂移**：每次新连接都会重查远端 portmap，所以 target 重启后能恢复；但单次连接进行中 target 重启会断开（与直连真实仪器行为一致）。

## 跨工具兼容
本项目使用 `AGENTS.md` 作为单一真相源。其他工具的配置文件可由脚本创建软链接：
```bash
bash setup_agent_links.sh
```

## 文档维护规则

### 默认行为：不更新文档
绝大多数代码修改不需要改文档。**默认不更新**。

### 必须更新的触发条件
- 修改 `Transport` 取值、新增/删除协议、改变 fallback 顺序。
- 新增/删除 `LOOPS.md` 中任一语义节点，例如 source lifecycle、target session、VXI-11 link lifecycle。
- 改变 pywebview API 方法名、前端 endpoint 配置结构或持久化格式。
- 改变 portmap/rpcbind 处理、VXI-11 link/lock/SRQ 生命周期。
- 新增核心命令、切换包管理器、引入新的主框架或打包方式。

### 不触发文档更新
- 保持语义节点不变的内部重构。
- 修复局部 bug。
- 优化性能。
- 重命名局部变量或调整样式。
- 修改 demo 或默认 Vue 脚手架组件但不影响主环。

### 提交时声明
每次提交描述末尾加一行：
```text
docs: [none|loops|agents|both] - <说明>
```

## 文档维护元信息
- 初始化时间：2026-05-08
- 文档版本：v1
- 初始化覆盖率：核心业务路径约 85%；按文件数约 52%
- 已知盲点：动态 RPC 分发、外部仪器行为、HiSLIP 高级语义、Python 依赖未清单化、`DeviceLock.is_open` 疑似缺失
- 上次大型更新：2026-05-08
