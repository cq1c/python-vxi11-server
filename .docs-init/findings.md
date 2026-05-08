# 原始事实笔记

## 入口与启动
- F001 [app.py:410] 模块级创建 `api = JsApi()`，供 pywebview 注入前端调用。
- F002 [app.py:413] `main()` 配置日志、解析视图 URL，并创建标题为 “VISA 设备映射工具” 的 webview 窗口。
- F003 [app.py:431] `main()` 读取 `VIEW_DEBUG` 后调用 `webview.start(debug=debug)` 启动桌面 UI 事件循环。
- F004 [view/src/main.ts:5] 前端创建 Vue 应用，注册 Element Plus 图标组件后挂载到 `#app`。
- F005 [view/src/App.vue:25] 前端 `PyApi` 类型声明暴露 `start_mapping`、`stop_mapping`、`get_status`、`get_default_endpoints`、`get_persisted_state`、`set_log_level`。
- F006 [view/src/App.vue:307] `onMounted` 安装 `window.__pushLog`，等待 pywebview bridge，然后同步后端状态与持久化配置。

## UI 配置与生命周期
- F010 [app.py:113] `default_endpoint_config()` 默认启用 VXI-11、HiSLIP、SOCKET，并填入 HiSLIP/SOCKET 默认端口。
- F011 [app.py:177] `_build_endpoint_addresses()` 将 UI endpoint config 转换为每个协议一个 `AddressInfo`，并校验 host/port/至少一个协议。
- F012 [app.py:218] `_pick_target_address()` 优先选择同协议目标；缺失时按 HiSLIP > VXI-11 > SOCKET 回退。
- F013 [app.py:327] `JsApi.start_mapping()` 持有锁，校验源/目标，持久化输入，按源协议创建 source 并启动。
- F014 [app.py:382] `JsApi.stop_mapping()` 持有锁，调用 `_cleanup()` 后写入停止日志。
- F015 [app.py:395] `_cleanup()` 遍历当前 source 调用 `stop()`，再清空 `_sources`、`_running`、source/target config。
- F016 [app.py:253] `_load_persisted()` 从 OS 临时目录 pickle 读取上次 source/target/log level；格式不符则返回空字典。
- F017 [app.py:266] `_save_persisted()` 将 source、target、log level 写回 pickle，写入失败被忽略。
- F018 [app.py:280] `push_log()` 按日志级别过滤消息，并通过 `window.evaluate_js` 调用前端 `window.__pushLog`。
- F019 [view/src/App.vue:268] `toggleMapping()` 根据 `running` 调用后端 `start_mapping()` 或 `stop_mapping()`，并更新按钮状态。
- F020 [view/src/App.vue:230] 前端也校验 host、至少一个协议、HiSLIP/SOCKET 端口范围。

## 协议抽象与分发
- F030 [vxi11_server/transports/base.py:12] `Transport` 枚举定义三种协议取值：`vxi11`、`hislip`、`socket`。
- F031 [vxi11_server/transports/base.py:48] `parse_address()` 支持 VXI-11、HiSLIP、raw SOCKET 三类 TCPIP VISA 资源字符串。
- F032 [vxi11_server/transports/base.py:106] `listen_host_for_source()` 对 loopback 保持 `127.0.0.1`，其他 host 绑定到所有 IPv4 接口。
- F033 [vxi11_server/transports/factory.py:20] `make_target()` 根据 `AddressInfo.transport` 创建 VXI-11、HiSLIP 或 SOCKET target client。
- F034 [vxi11_server/transports/factory.py:30] `make_source()` 根据 `AddressInfo.transport` 创建 VXI-11、HiSLIP 或 SOCKET source server。

## VXI-11 服务端与 RPC
- F040 [vxi11_server/instrument_server.py:140] `DeviceRegistry` 维护 device name 到 device class/lock 的注册表。
- F041 [vxi11_server/instrument_server.py:196] `Vxi11Server.link_create()` 通过 registry 创建 device 实例，生成 link id，并写入 link registry。
- F042 [vxi11_server/instrument_server.py:283] `Vxi11CoreHandler.handle_10()` 处理 create_link：创建 link、调用 `device_init()`，并可按请求加锁。
- F043 [vxi11_server/instrument_server.py:341] `handle_11()` 处理 device_write：校验 link、按 lock 包裹后调用 `device.device_write()`。
- F044 [vxi11_server/instrument_server.py:365] `handle_12()` 处理 device_read：校验 link、按 lock 包裹后调用 `device.device_read()`。
- F045 [vxi11_server/instrument_server.py:317] `handle_23()` 销毁 link 时禁用 SRQ、销毁 interrupt channel、释放 lock 并删除 link。
- F046 [vxi11_server/instrument_server.py:573] `InstrumentServer` 同时创建 abort server 与 core server，共享 device/link registry。
- F047 [vxi11_server/instrument_server.py:618] `InstrumentServer.listen()` 分别启动 abort/core 线程，并注册 core server 到 portmap。
- F048 [vxi11_server/rpc.py:660] `RPCRequestHandler.handle_call()` 根据 RPC proc 动态拼出 `handle_<proc>` 并 `getattr()` 调用。
- F049 [vxi11_server/rpc.py:719] `TCPServer.register()` 通过 portmapper 注册当前 RPC mapping；失败时记录 rpcbind 相关错误。
- F050 [vxi11_server/portmap_server.py:204] 内置 `PortMapServer` 支持 NULL、SET、UNSET、GETPORT、DUMP，并维护 `(prog, vers, prot) -> port` 映射。

## InstrumentDevice 行为
- F060 [vxi11_server/instrument_device.py:47] `InstrumentDevice.__init__()` 保存 device name、lock，并初始化 interrupt/SRQ 相关字段。
- F061 [vxi11_server/instrument_device.py:106] `signal_srq()` 在 SRQ 已启用且 interrupt client 存在时置 `srq_active=True` 并发送 interrupt RPC。
- F062 [vxi11_server/instrument_device.py:221] `device_enable_srq()` 根据 enable 设置 `srq_handle` 与 `srq_enabled`。
- F063 [vxi11_server/instrument_device.py:261] `DefaultInstrumentDevice.device_init()` 初始化 IDN 元组与 `result`。
- F064 [vxi11_server/instrument_device.py:266] `DefaultInstrumentDevice.device_write()` 处理 `*IDN?`、`*DEVICE_LIST?`，否则返回 `invalid`。
- F065 [vxi11_server/instrument_device.py:291] `DefaultInstrumentDevice.device_read()` 将 `result` 编码成 ASCII bytes 返回。

## VXI-11 客户端
- F070 [vxi11_server/vxi11.py:415] `CoreClient` 将 create_link、device_write、device_read 等 VXI-11 调用封装为 RPC `make_call()`。
- F071 [vxi11_server/vxi11.py:716] `Device.open()` 创建 `CoreClient`，调用 create_link，保存 link、abort port 与最大接收大小。
- F072 [vxi11_server/vxi11.py:740] `Device.close()` 禁用 SRQ handler、destroy_link、关闭 client 并清空 link/client。
- F073 [vxi11_server/vxi11.py:766] `Device.write_raw()` 必要时 open，按 `max_recv_size` 分块调用 `client.device_write()`。
- F074 [vxi11_server/vxi11.py:804] `Device.read_raw()` 循环调用 `client.device_read()` 直到 reason 包含 RX_END/RX_CHR 或达到请求长度。
- F075 [vxi11_server/vxi11.py:945] `enable_srq_handler()` 创建本地 interrupt server，注册 handle，并调用远端 create_intr_chan/device_enable_srq。
- F076 [vxi11_server/vxi11.py:531] `IntrHandler.handle_30()` 收到 SRQ RPC 后按 handle 查表并调用注册设备的 `srq_callback()`。
- F077 [vxi11_server/vxi11.py:562] `IntrServer` 使用类变量保存全局 interrupt server 与 SRQ handle registry。

## Relay 实现
- F080 [vxi11_server/transports/vxi11_relay.py:36] `Vxi11TargetClient` 使用 `_vxi11.Instrument` 连接上游 VXI-11 仪器并转发 raw read/write。
- F081 [vxi11_server/transports/vxi11_relay.py:98] `Vxi11SourceServer.start()` 启动 portmap 与 `InstrumentServer`，并注册 relay device class。
- F082 [vxi11_server/transports/vxi11_relay.py:170] `_build_relay_device()` 动态创建 `InstrumentDevice` 子类，`device_init()` 中打开 target client。
- F083 [vxi11_server/transports/vxi11_relay.py:192] relay device 的 `device_write()` 转发 bytes 到 target，异常时返回 VXI-11 IO_ERROR。
- F084 [vxi11_server/transports/vxi11_relay.py:204] relay device 的 `device_read()` 从 target 读取 bytes 并按 pending 状态返回 VXI-11 read reason。
- F085 [vxi11_server/transports/socket_relay.py:34] `SocketTargetClient` 建立 raw TCP 连接；`write_raw()` 保证写入以 LF 结束。
- F086 [vxi11_server/transports/socket_relay.py:76] `SocketTargetClient.read_raw()` 维护 pending response buffer，并支持按 max_size 分段返回。
- F087 [vxi11_server/transports/socket_relay.py:186] `SocketSourceServer` 每个 TCP client 创建一个 target session，并按行处理收到的 SCPI 消息。
- F088 [vxi11_server/transports/socket_relay.py:262] `_handle_message()` 总是 write；只有消息包含 `?` 时才 read target response 并回写 client。
- F089 [vxi11_server/transports/hislip.py:127] `HislipTargetClient.open()` 建立 sync/async 双连接并完成 Initialize/AsyncInitialize/MaximumMessageSize 握手。
- F090 [vxi11_server/transports/hislip.py:221] `HislipTargetClient.write_raw()` 将 payload 分块为 DATA/DATA_END，message id 每次递增 2。
- F091 [vxi11_server/transports/hislip.py:247] `HislipTargetClient.read_raw()` 累积 DATA/DATA_END payload，遇到 Error/FatalError 抛异常。
- F092 [vxi11_server/transports/hislip.py:279] `_SessionRegistry` 维护 sync session id 到 `_HislipSession` 的配对关系。
- F093 [vxi11_server/transports/hislip.py:358] `_HislipSession.run_sync()` 等待 async channel，打开 target client，然后循环处理 DATA/DATA_END。
- F094 [vxi11_server/transports/hislip.py:408] `_HislipSession.run_async()` 响应 max size、lock、device clear、status query、remote/local 等 async 消息。
- F095 [vxi11_server/transports/hislip.py:465] `_handle_request()` 转发消息到 target；只有包含 `?` 时读取 response 并 `_send_data()`。
- F096 [vxi11_server/transports/hislip.py:548] `HislipSourceServer` 根据首个 HiSLIP message 区分 sync initialize 与 async initialize。

## 示例与测试参考
- F110 [demo_servers/time-device.py:28] `TimeDevice` 继承 `InstrumentDevice`，仅重写 `device_read()` 返回当前 UTC 时间。
- F111 [demo_servers/unittest-device.py:21] `InstrumentRemote` 通过 `device_write()` 保存 `*IDN?` 结果，`device_read()` 返回该结果。
- F112 [demo_clients/unittest-client.py:62] unittest 覆盖同一 device 的独占锁冲突：第二个 `lock_on_open=True` open 应抛 “Device locked by another link”。
- F113 [demo_servers/srq-device.py:19] `SRQTestDevice` 通过 `SRQTIMER` 命令启动 Timer，随后调用 `signal_srq()`。

## 错误处理路径
- F120 [app.py:368] `start_mapping()` 任一 source 启动失败时记录错误，停止已启动 source，并重置运行状态。
- F121 [vxi11_server/transports/vxi11_relay.py:140] `Vxi11SourceServer.stop()` 对 `server.close()` 失败提供 bounded shutdown fallback。
- F122 [vxi11_server/portmap_server.py:55] `PortMapServer.stop()` 通过 coroutine shutdown，超时/异常记录 warning 后继续清理 event loop。
- F123 [vxi11_server/transports/hislip.py:401] HiSLIP sync loop 对连接关闭记录 INFO，对其他异常记录 ERROR，最后关闭 session。
- F124 [vxi11_server/transports/socket_relay.py:267] SOCKET source write/read/sendall 异常均记录错误并返回当前处理流程。

## 共享资源
- F130 [app.py:240] `JsApi` 维护 `_sources`、`_running`、source/target config，并使用 `threading.Lock()` 保护 start/stop。
- F131 [vxi11_server/instrument_server.py:582] `InstrumentServer` 创建共享 `_device_registry` 与 `_link_registry` 供 core/abort server 使用。
- F132 [vxi11_server/portmap_server.py:28] `PortMapServer` 用 `mappings` 字典保存 portmap 映射，TCP/UDP handler 都读写它。
- F133 [vxi11_server/transports/hislip.py:282] `_SessionRegistry` 使用 lock/condition 保护 session id 与 session 字典。

## 不确定项 ⚠️
- F900 [vxi11_server/rpc.py:660] ⚠️ RPC proc 到 handler 的目标通过动态 `getattr()` 决定，静态分析需手动对照所有 `handle_*` 方法。
- F901 [app.py:72] ⚠️ `app.py` monkey patch `vxi11_server.rpc.TCPServer.register_pmap/unregister`，对原始库行为有全局影响。
- F902 [app.py:77] ⚠️ `VIEW_URL`、PyInstaller `_MEIPASS`、本地 `view/dist`、Vite dev server 都可决定前端来源，运行形态会改变调试路径。
- F903 [vxi11_server/instrument_server.py:453] ⚠️ `handle_16()` 调用 `self.device.lock.is_open(...)`，但本次阅读的 `DeviceLock` 未定义 `is_open` 方法。
- F904 [vxi11_server/transports/hislip.py:17] ⚠️ HiSLIP 明确未实现 locking、async device clear、SRQ、trigger、TLS/credentials、remote/local 的完整语义。

## 阶段 2 自检
- [x] findings 每条带 `[文件:行号]`
- [x] 状态字段/枚举取值已收录：Transport、log level、running/SRQ/link/session 状态
- [x] 共享资源读写双方已收录
- [x] 错误处理路径已收录
- [x] 不确定项已用 ⚠️ 标注
