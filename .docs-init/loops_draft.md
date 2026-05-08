# 候选逻辑环（草稿）

## 已确认环

### 环 A：映射生命周期控制环
- 类型：UI 请求-响应环 + 生命周期环
- 重要性：主环
- 证据：F005, F006, F011, F012, F013, F014, F015, F018, F019
- 节点序列：
  ```
  [前端操作] toggleMapping 调用 start_mapping/stop_mapping (F005, F019)
    -> 后端校验 endpoint 并构造 AddressInfo (F011)
    -> 后端选择目标协议或 fallback (F012)
    -> 后端创建并启动 source，设置 _running/_sources (F013)
    -> 后端 push_log 反向通知前端 (F018)
    -> 前端 mounted/status/log 同步可见状态 (F006)
    -> stop_mapping/_cleanup 停止 source 并清空状态 (F014, F015)
  ```
- 流转载体：endpoint config、`_running`、`_sources`、日志事件
- 触发条件：用户点击“开始映射”或“停止映射”
- 终止条件：用户停止映射、source 启动失败、窗口进程退出
- 设计意图：让 UI 成为控制面，Python 后端成为 source 生命周期的单一执行者

### 环 B：多协议 relay 会话环
- 类型：协议转发环 + 长连接会话环
- 重要性：主环
- 证据：F030, F033, F034, F080, F081, F083, F084, F085, F087, F088, F089, F093, F095
- 节点序列：
  ```
  [客户端连接] 某个 source 接受 VXI-11/HiSLIP/SOCKET 会话
    -> source 使用 target_factory 创建同会话 target client (F033, F034)
    -> target client 打开目标仪器连接 (F080, F085, F089)
    -> source 将客户端 bytes 写入 target (F083, F088, F095)
    -> 对查询型消息读取 target response (F084, F088, F095)
    -> source 将 response 回写客户端，直到会话关闭
  ```
- 流转载体：SCPI/VISA 原始 bytes、每会话 target client、source server 线程/session
- 触发条件：外部仪器客户端连接本地映射端口并发送命令
- 终止条件：客户端断开、source stop、target 异常或进程退出
- 设计意图：把客户端看到的本地 VISA endpoint 映射到目标仪器，同时允许源/目标协议不同

### 环 C：VXI-11 link / RPC 生命周期环
- 类型：协议生命周期环
- 重要性：核心支撑环
- 证据：F040, F041, F042, F043, F044, F045, F046, F047, F048, F070, F071, F072, F073, F074
- 节点序列：
  ```
  [VXI-11 client] create_link RPC (F070, F071)
    -> RPC handler 动态路由到 create_link handler (F048)
    -> server registry 创建 device 实例并登记 link id (F040, F041, F042)
    -> 后续 write/read RPC 通过 link id 与 DeviceLock 调用 device hook (F043, F044)
    -> destroy_link 禁用 SRQ、销毁 interrupt channel、释放 lock、删除 link (F045, F072)
  ```
- 流转载体：link id、device instance、DeviceLock、core/abort server 共享 registry
- 触发条件：VXI-11 客户端打开仪器资源
- 终止条件：客户端 destroy_link/close、连接断开或 server close
- 设计意图：用 link id 隔离每个 VXI-11 会话，并把协议 RPC 映射到可继承的 device hook

### 环 D：SRQ 异步通知环
- 类型：异步事件环
- 重要性：辅助环
- 证据：F061, F062, F075, F076, F077, F113
- 节点序列：
  ```
  [客户端启用 SRQ] enable_srq_handler 注册本地 callback 与 handle (F075)
    -> 服务端 device_enable_srq 保存 handle/enable 状态 (F062)
    -> device 事件触发 signal_srq (F061, F113)
    -> interrupt RPC 到达 IntrHandler.handle_30 (F076)
    -> IntrServer registry 根据 handle 调用原客户端 callback (F077)
  ```
- 流转载体：SRQ handle、`srq_enabled`、`srq_active`、IntrServer registry
- 触发条件：客户端注册 SRQ callback 且设备调用 `signal_srq()`
- 终止条件：客户端 disable_srq_handler/close、destroy_intr_chan、server 关闭
- 设计意图：在主读写 RPC 之外提供异步服务请求通知

## 待确认环（证据不足或存在 ⚠️）

### 候选环 X：VXI-11 remote/local 控制路径
- 怀疑存在原因：F903 显示 `handle_16()` 进入 remote handler 后调用未定义的 `lock.is_open`。
- 缺失证据：`DeviceLock` 未发现 `is_open`，无法确认该路径可运行。
- 建议人工确认：执行 remote/local 相关客户端测试，或修复为现有 `DeviceLock` API。

### 候选环 Y：完整 HiSLIP 控制/锁/SRQ 环
- 怀疑存在原因：HiSLIP 协议包含 async lock、status query、remote/local 等消息。
- 缺失证据：F904 明确说明当前实现仅覆盖常见 SCPI relay，多个高级语义未完整实现。
- 建议人工确认：若需要仪器级锁、TLS、SRQ 或 device clear 语义，先扩展协议测试。

## 环之间的关系
- 环 A 是控制面主环，负责启动/停止环 B。
- 环 B 是数据面主环，其中 VXI-11 source 复用环 C。
- 环 C 是 VXI-11 协议支撑环，可独立用于库/示例服务端，也可嵌入环 B。
- 环 D 是环 C 的异步辅助环，不参与普通 write/read 数据面。

## 阶段 3 自检
- [x] 每个正文环都有 ≥3 个 finding 证据
- [x] 已扫描入口反查、状态字段、共享资源、错误处理、生命周期 5 种方法
- [x] 证据不足或不确定候选已移入“待确认”
- [x] 结论为多环：控制面环 + 数据面环 + VXI-11 生命周期环 + SRQ 辅助环
