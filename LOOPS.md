# 业务逻辑环

> 修改业务代码前必读。每个环描述一段“数据/状态如何在模块间流转并闭合”。
> 破坏闭合 = 破坏映射工具或协议库的正确性。

## 环索引
| 环名 | 类型 | 重要性 | 涉及模块 |
|------|------|--------|----------|
| 映射生命周期控制环 | UI 请求-响应 + 生命周期 | 主环 | `view/src` / `app.py` / `transports` |
| 多协议 relay 会话环 | 协议转发 + 长连接会话 | 主环 | `transports` / `vxi11_server` |
| VXI-11 link/RPC 生命周期环 | 协议生命周期 | 核心支撑 | `instrument_server` / `instrument_device` / `rpc` / `vxi11` |
| SRQ 异步通知环 | 异步事件 | 辅助 | `instrument_device` / `vxi11` |

---

## 环 1：映射生命周期控制环

### 概括
前端 UI 发起开始/停止映射，后端校验配置、创建协议 source、记录运行状态，并把日志/状态回推给 UI。

### 节点序列（语义级，不写行号）
```text
[起点] 用户点击开始映射
   -> Vue 通过 pywebview bridge 调用 Python JsApi
   -> 后端校验源/目标 endpoint，并转换为 AddressInfo
   -> 后端按源协议创建 source，按目标协议创建 target factory
   -> 每个 source start，后端进入 running 状态
   -> 后端 push_log 回推 UI，UI 展示状态与日志
   -> [闭合] 用户点击停止映射，后端 stop 所有 source 并清空 running 状态
```

### 流转载体
Endpoint config、`JsApi` 运行状态、source 列表、日志事件。

### 终止条件
用户停止映射、source 启动失败、窗口进程退出。

### 设计意图
让 `app.py` 成为映射 source 生命周期的单一执行者。UI 只提交配置和展示状态，不直接管理 socket 或协议对象。

### 修改提示
- 新增 UI 字段时，同时更新 Vue `PyApi` 类型、后端 endpoint 校验和持久化兼容。
- 启动失败必须停止已启动 source，避免留下半开的 portmap、server 或 socket。
- 改变 fallback 顺序会影响跨协议映射，必须同步更新本环说明。

---

## 环 2：多协议 relay 会话环

### 概括
本地 source 接受外部客户端连接，将客户端命令写入目标仪器 target；查询型消息再读取目标响应并回写客户端。

### 节点序列
```text
[起点] 外部 VISA/SCPI 客户端连接本地映射 endpoint
   -> Source server 为该连接/会话创建 target client
   -> Source 将客户端 bytes 写入 target
   -> 对查询型消息，source 从 target 读取响应
   -> Source 将响应按源协议封装回写客户端
   -> [闭合] 客户端收到目标仪器响应；会话可继续处理下一条消息
```

### 流转载体
SCPI/VISA 原始 bytes、每会话 target client、source session/thread。

### 终止条件
客户端断开、target 连接异常、用户停止映射、进程退出。

### 设计意图
在客户端与真实仪器之间建立协议适配层，允许 VXI-11、HiSLIP、SOCKET 源/目标按配置组合。

### 修改提示
- 每个外部客户端会话必须拥有自己的 target client，避免跨客户端响应串线。
- SOCKET 与 HiSLIP 当前以 `?` 判断是否读取响应；改变该规则需要覆盖非查询命令与二进制块响应。
- VXI-11 source 复用 `InstrumentServer`，修改它会影响库模式和映射工具两种运行方式。

---

## 环 3：VXI-11 link / RPC 生命周期环

### 概括
VXI-11 客户端通过 create_link 建立 link，后续 write/read/lock/SRQ 等 RPC 都围绕该 link id 与 device 实例运行，destroy_link 负责释放资源。

### 节点序列
```text
[起点] VXI-11 客户端打开 instrument resource
   -> 客户端通过 portmap 找到 core server
   -> create_link 创建 device 实例并登记 link id
   -> write/read RPC 经动态 handler 分发到 device hook
   -> DeviceLock 保护需要锁定的访问路径
   -> destroy_link 禁用 SRQ、销毁 interrupt channel、释放 lock、删除 link
   -> [闭合] link id 与该 device 实例的生命周期结束
```

### 流转载体
Link id、device 实例、DeviceLock、core/abort server 共享 registry。

### 终止条件
客户端 close/destroy_link、server close、连接断开。

### 设计意图
把 VXI-11 协议资源生命周期映射成可继承的 Python device hook，同时隔离每个客户端 link。

### 修改提示
- 注册 device handler 时传类，不传实例；状态放在每个 device 实例上。
- 修改 `handle_*` 或 RPC proc 常量时，同步检查 packer/unpacker 与客户端 wrapper。
- portmap 注册路径同时服务系统 rpcbind 与内置 portmap 场景，改动后要验证两类运行方式。

---

## 环 4：SRQ 异步通知环

### 概括
客户端启用 SRQ 后，设备可通过 interrupt channel 反向通知客户端 callback；关闭 link 时应撤销该通道。

### 节点序列
```text
[起点] 客户端注册 SRQ callback
   -> 客户端建立本地 interrupt server，并向仪器启用 SRQ
   -> 仪器 device 保存 SRQ handle 与 enabled 状态
   -> 设备事件调用 signal_srq
   -> interrupt RPC 到达客户端 IntrHandler
   -> IntrServer registry 按 handle 调用 callback
   -> [闭合] callback 执行；close/disable 时撤销 handle 与 interrupt channel
```

### 流转载体
SRQ handle、`srq_enabled`、`srq_active`、IntrServer registry。

### 终止条件
客户端 disable/close、destroy_intr_chan、server 关闭。

### 设计意图
在普通请求/响应 RPC 之外提供异步服务请求通知。

### 修改提示
- SRQ handler 不等待 RPC reply，这是为避免死锁的协议选择。
- 任何 close/destroy 路径都必须考虑撤销 SRQ 注册和 interrupt channel。

## 待确认环（盲点）
- ⚠️ VXI-11 remote/local 控制路径：当前阅读发现 remote handler 触达疑似不存在的 lock API，需用测试或修复确认。
- ⚠️ 完整 HiSLIP 控制语义：当前实现声明未覆盖 lock、SRQ、trigger、TLS/credentials 等高级行为。
- ⚠️ 外部仪器行为：目标设备对 SCPI 命令、二进制块、超时和错误码的响应不可由本仓库静态保证。

## 反模式清单
- 绕过 `JsApi.start_mapping()` 直接启动 source，会破坏失败清理和 UI 状态同步。
- 在 source 间共享 target client，会破坏每客户端会话隔离。
- 在 VXI-11 handler 中绕过 `DeviceLock` 直接调用 device hook，会破坏锁语义。
- 修改 RPC 动态分发却不检查全部 `handle_*`，会造成协议 proc 隐式失效。
- 只改前端 endpoint 结构不改后端校验/持久化，会导致 bridge 调用失败或旧配置无法恢复。

## 元信息
- 初始化时间：2026-05-08
- 初始化覆盖率：核心业务路径约 85%；按文件数约 52%
- 主要识别方法：入口反查 + 生命周期追踪 + 共享资源闭合 + 错误处理路径
- 证据库：`.docs-init/findings.md`
