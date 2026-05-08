# 文件骨架清单

## 根目录
- `README.md` [support]
- `.gitignore` [asset]
- `app.py` [entry, core-biz]
- `automation_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg` [asset]
- `test.py` [test]

## plans/
- `project_summary.md` [support]

## scripts/
- `build_pyinstaller.py` [infra]

## demo_servers/
- `time-device.py` [entry, test]
- `unittest-device.py` [entry, test]
- `srq-device.py` [entry, test]

## demo_clients/
- `time_client.py` [test]
- `locked_time_client.py` [test]
- `srq-client.py` [test]
- `unittest-client.py` [test]
- `unittest-rs-client.py` [test]

## vxi11_server/
- `__init__.py` [route]
- `instrument_device.py` [core-biz, state-def]
- `instrument_server.py` [entry, route, core-biz]
- `portmap_server.py` [infra]
- `rpc.py` [infra, route]
- `vxi11.py` [core-biz, infra]

## vxi11_server/transports/
- `__init__.py` [route]
- `base.py` [state-def, support]
- `factory.py` [route]
- `vxi11_relay.py` [core-biz]
- `hislip.py` [core-biz]
- `socket_relay.py` [core-biz]

## view/
- `README.md` [support]
- `package.json` [infra]
- `pnpm-lock.yaml` [generated]
- `vite.config.ts` [infra]
- `tsconfig.json` / `tsconfig.app.json` / `tsconfig.node.json` [infra]
- `eslint.config.ts` / `.oxfmtrc.json` / `.oxlintrc.json` / `.editorconfig` [infra]
- `.gitattributes` / `.gitignore` / `.vscode/*` [asset]
- `auto-imports.d.ts` / `components.d.ts` [generated]
- `env.d.ts` [support]
- `index.html` [asset]
- `public/favicon.ico` [asset]

## view/src/
- `main.ts` [entry]
- `App.vue` [core-biz]
- `router/index.ts` [route, support]
- `stores/counter.ts` [support]
- `views/HomeView.vue` / `views/AboutView.vue` [support]
- `components/*.vue` [support]
- `components/icons/*.vue` [asset]
- `assets/base.css` / `assets/main.css` / `assets/logo.svg` [asset]

## 跳过组
- `.git/` [vendor]
- `view/node_modules/` [vendor]
- `__pycache__/`、`scripts/__pycache__/`、`vxi11_server/**/__pycache__/` [generated]

## 阶段 1 自检
- [x] 每个非跳过文件都有标签
- [x] 生成阅读计划
- [x] 跳过文件已说明原因
