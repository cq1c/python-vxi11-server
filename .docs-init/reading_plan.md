# 阅读计划

## 必读（entry / route / state-def）
- `app.py`
- `view/src/main.ts`
- `view/src/App.vue`
- `vxi11_server/__init__.py`
- `vxi11_server/instrument_server.py`
- `vxi11_server/instrument_device.py`
- `vxi11_server/rpc.py`
- `vxi11_server/transports/base.py`
- `vxi11_server/transports/factory.py`
- `vxi11_server/transports/__init__.py`

共 10 个文件。

## 必读（core-biz）
- `vxi11_server/vxi11.py`
- `vxi11_server/transports/vxi11_relay.py`
- `vxi11_server/transports/hislip.py`
- `vxi11_server/transports/socket_relay.py`
- `vxi11_server/portmap_server.py`

共 5 个文件。

## 抽样阅读（support / infra / examples）
- 抽样比例：约 35%
- 已读代表文件：
  - `view/package.json`
  - `view/vite.config.ts`
  - `scripts/build_pyinstaller.py`
  - `demo_servers/time-device.py`
  - `demo_servers/unittest-device.py`
  - `demo_servers/srq-device.py`
  - `demo_clients/unittest-client.py`

## 跳过（说明原因）
- `view/node_modules/`：三方依赖
- `__pycache__/`：Python 生成缓存
- `view/auto-imports.d.ts`、`view/components.d.ts`：前端自动生成类型声明
- Vue 默认脚手架组件与图标：不参与映射生命周期或协议转发环
- 其余 demo clients：用于人工/外部库兼容验证，不作为项目主环证据来源

## 预估覆盖率
- 必读 + 抽样 / 总业务文件数 ≈ 22 / 42，按文件数约 52%
- 若按核心实现行数估算，已覆盖 `app.py`、`vxi11_server/` 与 `view/src/App.vue` 的主要业务路径，覆盖率约 85%
- 文件数覆盖率低于 60% 的原因：仓库包含 Vue 默认脚手架、demo client、生成类型声明等低业务密度文件；阶段 4 会在盲点中说明

## 阶段 1 自检
- [x] 每个非跳过文件都有标签
- [x] reading_plan.md 给出了预估覆盖率
- [x] 覆盖率 < 60% 的取舍理由已说明
