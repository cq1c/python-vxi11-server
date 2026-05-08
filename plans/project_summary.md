# 项目代码文档化提示词（流水线版）

> 适用场景：首次对一个陌生项目进行 agent 驱动的文档化初始化
> 核心目标：产出一份**可信的、有证据的、agent 可读可维护的**项目骨架文档
> 设计原则：流水线分阶段执行 · 每阶段有可验证产物 · 逻辑环必须带证据 · 允许暂停与"无环"结论

---

## 你的角色与底线

你是一名资深软件工程师，受命对当前项目进行**首次文档化**。
本提示词把工作拆分为 5 个阶段。**你必须按顺序执行，每个阶段产出指定文件，不得跳步、不得提前下结论。**

四条不可违反的底线：

1. **没读过的代码不能写进文档。** 任何描述必须可追溯到 `文件:行号` 或 `类.方法`。
2. **没有 ≥3 处代码证据的逻辑环不能进入 LOOPS.md。** 写不出证据的放进"待确认"附录。
3. **不确定的地方必须显式标 ⚠️。** 不许用合理的话糊过去。
4. **暂停是合法的。** 上下文不够、项目过大、入口找不到——立即报告并暂停，不要硬撑。

---

## 阶段 0：项目画像（Profiling）

### 目标
在不读业务代码的前提下，给项目画一张"身份证"，决定后续流水线如何走。

### 允许动作
- 列目录树（`tree` / `ls -R`，深度限制为 3）
- 读 README、LICENSE
- 读配置文件：`package.json` / `pyproject.toml` / `requirements.txt` / `go.mod` / `Cargo.toml` / `pom.xml` / `build.gradle` / `Dockerfile` / `docker-compose.yml` / `Makefile` / `.env.example`
- 读入口文件的**头部 30 行**（不读完整实现）：`main.*` / `index.*` / `app.*` / `__main__.py` / `cmd/**/*.go`

### 禁止动作
- 阅读业务实现
- 推测逻辑环
- 写任何最终文档

### 项目类型画像（多选）

```
□ Web 服务（HTTP/RPC/GraphQL）        → 候选主环：请求-响应环
□ CLI 工具                            → 候选主环：通常退化，可能无环
□ 后台守护 / 定时任务                 → 候选主环：调度-执行-反馈环
□ 消息消费者 / 事件驱动               → 候选主环：消费-处理-确认环
□ 数据管道 / ETL                      → 候选主环：单向流水线，常无闭合
□ 状态机驱动业务（订单/工单/审批）    → 候选主环：状态机环
□ ML 训练 / 推理                      → 候选主环：训练环 / 推理服务环
□ 框架 / SDK / 库                     → 通常无业务环，主要是生命周期环
□ 游戏 / 仿真                         → 候选主环：tick / 主循环
□ 编译器 / 解释器                     → 候选主环：流水线，常无闭合
```

> ⚠️ 若项目画像指向"通常无环"类型，**允许并鼓励**最终输出"本项目不存在闭合逻辑环"的结论。这不是失败，是诚实。

### 规模档位

| 档位 | 文件数（不含测试/vendor/生成代码） | 流水线策略 |
|------|------------|-----------|
| S | < 20 | 合并阶段 1+2+3，一次性产出 |
| M | 20-200 | 完整 5 阶段 |
| L | > 200 | 阶段 2 按目录分批，每批独立交付 |

### 阶段 0 产物：`.docs-init/profile.md`

```markdown
# 项目画像

## 基本信息
- 项目名：
- 主要语言：
- 技术栈：
- 入口文件清单：
- 配置文件清单：

## 项目类型（勾选）
- [x] ...

## 规模档位
- 总文件数（粗略）：
- 业务文件数（估算）：
- 档位：S / M / L
- 选定流水线策略：

## 候选主环类型
基于项目类型，预期会找到的环（仅作探照灯方向，不是结论）：
- ...

## 已知风险
- 是否含动态分发 / 反射 / 元编程：
- 是否含自动生成代码：
- 是否含跨进程 / 跨服务调用：
```

### 准入下一阶段的检查
- [ ] profile.md 已生成
- [ ] 规模档位已确定
- [ ] 入口文件清单非空（若空，立即暂停报告）

---

## 阶段 1：骨架扫描（Skeleton）

### 目标
给项目里的每个文件贴一个标签，决定哪些必读、哪些可跳，规划阅读路径。

### 允许动作
- 完整目录扫描
- 对每个文件读 head 20 行用于分类
- 读路由表 / 注册中心 / DI 配置 / urls.py 等"地图型"文件的完整内容

### 文件分类标签

| 标签 | 含义 | 阅读策略 |
|------|------|---------|
| `entry` | 程序入口 | 阶段 2 完整阅读 |
| `route` | 路由 / 注册表 | 阶段 2 完整阅读 |
| `state-def` | 状态机 / 枚举 / 状态字段定义 | 阶段 2 完整阅读 |
| `core-biz` | 核心业务实现 | 阶段 2 完整阅读 |
| `support` | 工具 / 辅助 | 阶段 2 抽样阅读 |
| `infra` | 基础设施（DB / 缓存 / 队列封装） | 阶段 2 抽样阅读 |
| `generated` | 自动生成代码（pb / openapi / migration） | 跳过，仅记录存在 |
| `vendor` | 三方代码 | 跳过 |
| `test` | 测试 | 跳过（除非用作行为参考） |
| `asset` | 静态资源 / 配置 | 跳过 |

### 阶段 1 产物：`.docs-init/skeleton.md` + `.docs-init/reading_plan.md`

**skeleton.md** 示例：

```markdown
# 文件骨架清单

## src/api/
- handler.go              [route]
- middleware.go           [core-biz]

## src/service/
- order_service.go        [core-biz]
- payment_service.go      [core-biz]

## src/state/
- order_state.go          [state-def]

## generated/
- pb/*.go                 [generated, 共 12 文件]
```

**reading_plan.md** 示例：

```markdown
# 阅读计划

## 必读（entry / route / state-def）
- src/main.go
- src/api/handler.go
- src/state/order_state.go
- ...
共 N 个文件

## 必读（core-biz）
- src/service/order_service.go
- ...
共 M 个文件

## 抽样阅读（support / infra）
- 抽样比例：30%
- 计划读：...

## 跳过（说明原因）
- generated/pb/*：自动生成
- vendor/*：三方依赖
- test/*：本次初始化不依赖测试推断行为

## 预估覆盖率
- 必读 + 抽样 / 总业务文件数 ≈ X%
- 若 X < 60%，将在阶段 4 报告中显式说明
```

### 准入下一阶段的检查
- [ ] 每个非跳过文件都有标签
- [ ] reading_plan.md 给出了预估覆盖率
- [ ] 若覆盖率 < 60%，已在 plan 中说明取舍理由

---

## 阶段 2：深度阅读（Deep Read）

### 目标
**只记录原始事实，不做归纳。** 这是后续所有结论的证据库。

### 允许动作
- 按 reading_plan.md 逐文件完整阅读
- grep / 全文搜索 status / state / phase / stage / step 等关键字
- 跨文件追踪函数调用、类继承、接口实现

### 禁止动作
- **禁止在本阶段写 LOOPS.md 或归纳逻辑环**
- **禁止在本阶段写 AGENTS.md 或归纳模块职责**
- **禁止凭印象补充代码里没写的东西**

### 阶段 2 产物：`.docs-init/findings.md`

格式严格如下，每条 ≤ 3 行：

```markdown
# 原始事实笔记

## 入口与启动
- F001 [src/main.go:15] `main()` 启动 HTTP 服务器，监听 :8080
- F002 [src/main.go:23] 注册路由模块 `api.RegisterRoutes(router)`
- F003 [src/main.go:31] 启动后台 worker `go worker.Start(ctx)`

## 路由与分发
- F010 [src/api/handler.go:45] `POST /orders` → `OrderHandler.Create`
- F011 [src/api/handler.go:67] `OrderHandler.Create` 调用 `OrderService.Create`

## 状态定义
- F020 [src/state/order_state.go:8] 枚举 OrderStatus: pending / paid / shipped / delivered / cancelled
- F021 [src/state/order_state.go:30] 状态转移函数 `Transition(from, to)` 校验合法性

## 业务核心
- F030 [src/service/order_service.go:50] `Create` 写入 DB，状态置为 pending
- F031 [src/service/order_service.go:80] `MarkPaid` 校验 pending → paid，更新 DB
- F032 [src/service/payment_service.go:40] 支付成功回调 `OnPaid` 调用 `OrderService.MarkPaid`

## 共享资源
- F040 [全局] DB 表 orders 同时被 OrderService 读写、被 worker 读
- F041 [全局] Redis key `order:lock:{id}` 同时被 OrderService 写、PaymentService 读

## 错误处理路径
- F050 [src/service/order_service.go:120] 失败时入队 `retry_queue`
- F051 [src/worker/retry_worker.go:30] 从 `retry_queue` 消费，重新调用 OrderService.Create

## 不确定项 ⚠️
- F900 [src/api/handler.go:200] ⚠️ 通过反射调用 handler，无法静态确定调用目标
- F901 [src/integration/external.go:50] ⚠️ 调用外部服务 PaymentGateway，对端行为不可见
```

> 命名规则：`F + 三位数字`，全局唯一编号，便于阶段 3 引用。

### 准入下一阶段的检查
- [ ] findings.md 中每条都有 `[文件:行号]`
- [ ] 所有 entry / route / state-def 文件都有对应条目
- [ ] 状态字段（status / state / phase）的所有取值都已记录
- [ ] 错误处理路径已记录（重试 / 补偿 / 降级 / 回滚）
- [ ] 共享资源（DB 表 / 缓存 key / 队列 / 全局变量）已记录读写双方
- [ ] 不确定项已用 ⚠️ 标注

> 如果以上任一项无法满足，回到阶段 2 补读，不要进入阶段 3。

---

## 阶段 3：环识别（Loop Detection）

### 目标
**仅基于 findings.md** 推导逻辑环。本阶段不许重新打开代码文件——只读笔记。
（这条规则物理上阻止你凭印象编造环。）

### 逻辑环判定标准

候选链路必须**同时满足**以下三条，才算一个真实的逻辑环：

1. **跨模块**：至少跨越 2 个模块/文件（单文件内部循环不算）
2. **有状态变化或副作用**：纯计算往返不算
3. **语义闭合而非调用栈闭合**：函数 A 调 B 再 return 到 A，不是环；A 写库、B 读库再回写，是环

### 候选环识别方法

逐一执行下列扫描，每个方法独立产出候选清单：

| 方法 | 操作 |
|------|------|
| 入口反查 | 从每个 `entry` 标签文件出发，沿 findings 追踪调用链直到链路终结或回到自身 |
| 状态字段追踪 | 找出 findings 中所有 `state-def` 条目，绘制状态转移图，转移图中的环就是状态机环 |
| 共享资源闭合 | 找出 findings 中"既读又写"的资源，分析读写方是否构成闭环 |
| 错误处理路径 | 找出 findings 中失败 → 重试/补偿/降级路径 |
| 生命周期 | 找出 init / start / stop / dispose / close 系列调用 |

### 证据要求（硬约束）

每个写入正文的环，**必须**引用 ≥3 个 findings 编号作为证据：
- 起点：1 个
- 中间节点：≥1 个
- 闭合点：1 个

证据不足的环，**必须**放入"待确认环"附录，不得写入正文。

### 阶段 3 产物：`.docs-init/loops_draft.md`

```markdown
# 候选逻辑环（草稿）

## 已确认环

### 环 A：订单状态推进环
- 类型：状态机环 + 请求-响应环（嵌套）
- 重要性：主环
- 证据：F010, F011, F020, F021, F030, F031, F032
- 节点序列：
  ```
  [HTTP 请求] OrderHandler.Create (F010, F011)
    → OrderService.Create [status=pending] (F030)
    → [外部支付完成]
    → PaymentService.OnPaid (F032)
    → OrderService.MarkPaid [status: pending → paid] (F031)
    → [闭合：同一 Order 实体的 status 字段被推进]
  ```
- 流转载体：Order 实体的 status 字段
- 触发条件：用户提交订单
- 终止条件：状态到达 delivered 或 cancelled
- 设计意图：保证订单状态推进的合法性，避免越级状态变更

### 环 B：失败重试环
- 类型：补偿环
- 重要性：辅助环
- 证据：F050, F051, F030
- 节点序列：
  ```
  OrderService.Create 失败 (F050)
    → 入队 retry_queue
    → RetryWorker 消费 (F051)
    → 重新调用 OrderService.Create (F030)
    → [闭合：回到主环 A 的起点]
  ```
- 嵌套关系：与环 A 共享起点
- 终止条件：成功 / 超过最大重试次数

## 待确认环（证据不足或存在 ⚠️）

### 候选环 X：反射路由分发环
- 怀疑存在原因：F900 显示存在反射调用
- 缺失证据：无法静态确定调用目标，调用链断裂
- 建议人工确认：src/api/handler.go:200 的 reflect.Call 实际指向哪些 handler

## 环之间的关系
- 环 A 是主环
- 环 B 嵌套于环 A，作为环 A 的失败补偿
- 环 A 与环 B 共享起点 OrderService.Create
```

### 准入下一阶段的检查
- [ ] 每个正文环都有 ≥3 个 finding 证据
- [ ] 已扫描所有 5 种识别方法
- [ ] 证据不足的候选已移入"待确认"附录
- [ ] 若最终正文 0 个环，已显式说明"本项目类型不构成闭合环"并给出依据

---

## 阶段 4：文档生成（Authoring）

### 核心原则（先读这条，再动手）

文档不是越详细越好。**陈旧文档比没文档更糟**。本阶段产出的文档要满足三条铁律：

1. **稳定信息优先**：只写在几个月到几年内不会变的东西。具体行号、具体方法名、当前实现细节——能不写就不写。
2. **简短优先**：根 AGENTS.md ≤ 150 行，子目录 AGENTS.md ≤ 100 行，LOOPS.md 单个环 ≤ 40 行。**超出就拆，不要扩**。
3. **关键规则前置**：每个文件最重要的内容放在前 30 行内。Agent 有"lost in the middle"问题，越靠后的指令越可能被忽略。

### 什么该写、什么不该写

| 内容类型 | 该写 | 不该写 |
|---------|------|--------|
| 业务约束 | ✅ "订单状态变更必须走 state.Transition" | ❌ "状态字段在 order.go 第 30 行" |
| 技术栈 | ✅ "使用 pnpm 不是 npm，Python 3.11+" | ❌ 完整 package.json 复述 |
| 逻辑环 | ✅ 语义节点序列：Handler → Service → State 校验 → 持久层 | ❌ 精确到行号的调用链 |
| 模块职责 | ✅ "service/ 承担业务编排，不直接访问外部 API" | ❌ 详细文件清单与每个文件简介 |
| 命令 | ✅ "测试：pnpm test，构建：pnpm build" | ❌ CI 流水线全文 |
| 不变量 | ✅ "同一订单同时只允许一个 worker 处理（用 redis 锁）" | ❌ 锁的具体 key 命名规则 |

**判断标准**：问自己"如果代码改了，这句话还成立吗？" 如果会失效，删掉或改写为更抽象的版本。

---

### 产物清单与优先级

#### P0 必产出（首次初始化）
1. **`AGENTS.md`**（根目录） — 项目级约束与导航，跨工具兼容
2. **`LOOPS.md`**（根目录） — 业务逻辑环全景
3. **跨工具兼容设置脚本** — 软链接命令，写在 AGENTS.md 末尾或单独 `setup_agent_links.sh`

#### P1 按需产出
4. **子目录 `AGENTS.md`** — 仅当该目录有特殊约定时创建（不要每个目录都建）
5. **`README.md` 补充** — 仅追加"AI 协作指南"小节，不重写 README

#### P2 默认不产出（除非用户明确要求）
6. 文件头注释 — 信息腐烂率最高，默认不加
7. 完整目录的 AGENTS.md 平铺 — agent 自己 ls 就能看到结构

---

### 根 `AGENTS.md` 模板（≤ 150 行）

```markdown
# <项目名>

> 本文件是给 AI 编码助手（Claude Code / Cursor / Codex / Copilot 等）的项目说明。
> 跨工具标准：AGENTS.md（OpenAI 发起，Linux Foundation 治理）。
> Claude Code 用户：根目录 CLAUDE.md 是本文件的软链接。

## 项目一句话
<10-30 字，说清楚这个项目是什么>

## 关键技术决策（最先读）
- 包管理：<pnpm / poetry / cargo / ...>
- 运行时：<Node 20+ / Python 3.11+ / Go 1.22+ / ...>
- 框架：<NestJS / FastAPI / Gin / ...>
- 数据库：<...>
- 其他关键依赖：<只列 3-5 个最特殊的>

## 不可违反的约束
> Agent 修改代码前必读。违反这些约束的改动必须显式说明理由。

- <约束 1：用陈述句写，不要写"应该""建议"，写"必须""禁止">
- <约束 2>
- <约束 3>
- ...
（通常 5-10 条，超过 10 条说明拆得不够细）

## 业务核心
**本项目的核心是 <主业务环名>。修改业务代码前，先读 LOOPS.md。**

主要模块：
- `<dir>/` — <一句话职责>
- `<dir>/` — <一句话职责>
（保持 5-8 行，更详细的进子目录 AGENTS.md）

## 常用命令
```bash
# 安装
<install cmd>
# 开发
<dev cmd>
# 测试
<test cmd>
# 构建
<build cmd>
# 数据库迁移（若有）
<migrate cmd>
```

## Agent 行为约定
- 修改前先 grep 确认是否影响 LOOPS.md 中的环
- 不要在文档里记录具体行号 / 方法名 / 文件位置（易腐烂）
- 不确定的地方标 ⚠️ 而不是猜测
- 大型重构前先与人类确认

## 文档地图
- `LOOPS.md` — 业务逻辑环（修改业务前必读）
- `<dir>/AGENTS.md` — 子目录特殊约定（如有）

## 跨工具兼容
本项目使用 AGENTS.md 作为单一真相源。其他工具的配置文件均为软链接：
```bash
# 如果你的工具不自动识别 AGENTS.md，运行：
ln -sf AGENTS.md CLAUDE.md          # Claude Code
ln -sf AGENTS.md .cursorrules       # Cursor（旧版）
ln -sf AGENTS.md GEMINI.md          # Gemini CLI（注意：Gemini 不一定兼容）
```

## 文档维护元信息
- 初始化时间：YYYY-MM-DD
- 文档版本：v1
- 已知盲点：<反射 / 动态生成代码 / 外部协议等>
- 上次大型更新：YYYY-MM-DD
```

> ⚠️ **写完后自检**：删掉任何"agent 自己也能看出来"的内容（如目录结构图、文件清单、技术栈介绍）。这些内容在 codebase 里有事实来源，写在文档里只会过时。

---

### `LOOPS.md` 模板（精简版）

> 本文档描述项目的业务闭环。这部分稳定性高，可以详细写，但仍要避免具体行号。

```markdown
# 业务逻辑环

> 修改业务代码前必读。每个环描述了一段"数据/状态如何在模块间流转并闭合"。
> 破坏闭合 = 破坏业务正确性。

## 环索引
| 环名 | 类型 | 重要性 | 涉及模块 |
|------|------|--------|----------|
| 订单状态推进环 | 状态机 + 请求响应 | 主环 | api / service / state |
| 失败重试环 | 补偿 | 辅助 | service / worker |

---

## 环 1：订单状态推进环

### 概括
订单从创建到完成的完整状态推进。由 HTTP 请求触发，经支付回调推动，最终在订单的 status 字段上闭合。

### 节点序列（语义级，不写行号）
```
[起点] API 层接收创建请求
   → Service 层创建订单（status = pending）
   → [外部] 用户完成支付
   → Payment 模块接收回调
   → Service 层调用 MarkPaid（pending → paid）
   → [闭合] 订单 status 字段被合法推进
```

### 流转载体
Order 实体的 status 字段，取值：pending / paid / shipped / delivered / cancelled

### 终止条件
status 到达 delivered（正常）或 cancelled（异常）

### 设计意图
集中管理状态合法性。任何状态变更必须经过 `state.Transition` 校验。
**反模式**：直接 UPDATE 数据库 status 字段会绕过校验，破坏环的闭合保证。

### 关键代码定位（语义路径，方便 grep）
- 起点：API 层订单创建 handler
- 状态定义：`state` 模块的 OrderStatus 枚举
- 闭合执行：service 层 MarkPaid 方法
- 合法性校验：state 模块 Transition 函数

### 修改提示
- 新增状态值：必须同时更新 OrderStatus 枚举、Transition 转移表、本环的"流转载体"字段
- 新增触发路径：必须接入 Service 层而不是直接写库

---

## 环 2：失败重试环
（同上结构，省略）

---

## 环关系
```
[环 1 主环] 订单状态推进
       │ 失败时
       ▼
[环 2 辅助] 失败重试
       │ 重试成功后
       └─→ 重新进入环 1 起点
```

## 待确认环（盲点）
- ⚠️ <环名>：<怀疑存在的理由>，建议人工确认 <在哪里>

## 反模式清单
- ❌ 绕过 Service 直接 UPDATE status → 破坏环 1
- ❌ Worker 不设置最大重试次数 → 环 2 终止条件失效
- ❌ 在 Handler 里直接调用 state.Transition → 越层调用，破坏环 1 节点序列

## 元信息
- 初始化覆盖率：X%（M / N 业务文件已读）
- 主要识别方法：入口反查 + 状态字段追踪
- 已知盲点：反射调用 / 外部支付网关
```


---

### 子目录 `AGENTS.md` 模板（≤ 100 行，按需创建）

> **不是每个目录都要创建**。判断标准：本目录是否有"在父级 AGENTS.md 之外的特殊约定"？
> - 有 → 创建
> - 没有 → 不创建

```markdown
# <目录名>

## 职责
<1-2 句>

## 本目录在主业务中的角色
<对应 LOOPS.md 中哪些环的哪些节点>
（如果不参与任何环，可以写"工具支撑，不直接参与业务闭环"）

## 本目录的特殊约定
> 这些约定不在父级 AGENTS.md 中，仅在本目录适用。

- <约定 1>
- <约定 2>

## 修改注意
- <修改本目录代码时容易踩的坑>
```

> 如果你只能写出"本目录是 XX 模块"这种废话，就**不要创建**这个文件。空文档比没文档更糟。

---

### `README.md` 补充章节（追加，不覆盖）

在 README.md 末尾追加：

```markdown
## AI 协作指南
本项目使用 [AGENTS.md](./AGENTS.md) 标准为 AI 编码助手提供上下文。

阅读顺序：
1. `AGENTS.md` — 项目约束与命令
2. `LOOPS.md` — 业务逻辑环（修改业务前必读）
3. 子目录 `AGENTS.md`（如有） — 模块特殊约定

如果你使用 Claude Code，根目录的 `CLAUDE.md` 是 `AGENTS.md` 的软链接，内容相同。
```

---

### 跨工具兼容脚本

在阶段 4 末尾，输出一个 `setup_agent_links.sh`（或对应平台的脚本）：

```bash
#!/bin/bash
# 为不自动识别 AGENTS.md 的工具创建软链接

# Claude Code（截至 2026 年仍使用 CLAUDE.md）
[ ! -e CLAUDE.md ] && ln -sf AGENTS.md CLAUDE.md

# Cursor 旧版（新版已支持 AGENTS.md，可跳过）
# [ ! -e .cursorrules ] && ln -sf AGENTS.md .cursorrules

# Gemini CLI（格式可能不完全兼容，按需启用）
# [ ! -e GEMINI.md ] && ln -sf AGENTS.md GEMINI.md

echo "✓ Agent context links set up"
echo "  AGENTS.md is the single source of truth"
echo "  Other tools' config files are symlinks"
```

并在最终交付报告中提示用户：

> 检测到的 agent 工具：<根据项目特征推断，如有 .cursor/、.claude/、.codex/ 等目录>
> 建议运行：`bash setup_agent_links.sh`

---

### 维护规则（写入 AGENTS.md 末尾或单独 MAINTENANCE.md）


```markdown
## 文档维护规则

### 默认行为：不更新文档
绝大多数代码修改不需要改文档。**默认不更新**。

### 必须更新的触发条件（机械判断）
满足以下任一条件，本次提交必须包含文档更新：

**触发 LOOPS.md 更新**
- [ ] 修改了 enum / status / state / phase 的取值
- [ ] 新增/删除了主业务环的语义节点（不是行号变化，是"是否存在该节点"变化）
- [ ] 引入了新的 retry / fallback / cache / hook 类闭环
- [ ] 改变了路由分发、事件订阅、消息消费的拓扑

**触发 AGENTS.md 更新**
- [ ] 新增或修改了"不可违反的约束"
- [ ] 切换了核心技术依赖（包管理器、ORM、主框架）
- [ ] 新增了核心命令（测试 / 构建 / 部署）

**不触发文档更新（明确不需要改）**
- 重构内部实现但保持接口
- 修复 bug
- 优化性能
- 重命名变量/方法（除非是 LOOPS.md 中提到的语义角色名称）
- 调整代码组织（除非改变了模块职责）

### 提交时声明
每次提交描述末尾加一行：
```
docs: [none|loops|agents|both] - <说明>
```
- `none`：本次改动不影响文档
- `loops`：更新了 LOOPS.md
- `agents`：更新了 AGENTS.md
- `both`：两者都更新

### 文档腐烂检测
每隔一段时间（建议大版本前），让 agent 执行：
1. 检查 LOOPS.md 中提到的"语义路径"是否还能 grep 到对应代码
2. 检查 AGENTS.md 中的命令是否还能跑通
3. 检查"不可违反的约束"是否还有人遵守（grep 反模式）

发现腐烂的条目，要么修复要么删除——**不要保留过期内容**。
```

---

### 阶段 4 自检清单

完成文档后，对照以下清单逐项检查：

- [ ] AGENTS.md ≤ 150 行
- [ ] AGENTS.md 前 30 行包含了最关键的约束
- [ ] LOOPS.md 中没有任何 `文件:行号` 引用（用语义路径代替）
- [ ] 没有创建空洞的子目录 AGENTS.md（"本目录是 XX 模块"这种）
- [ ] 没有写入 agent 自己能看到的信息（目录树、文件清单、依赖列表）
- [ ] 维护规则部分明确了"默认不更新"
- [ ] 提供了跨工具兼容脚本
- [ ] 已知盲点（⚠️ 项）显式列出

最后回答这个问题：**如果三个月后这份文档没人维护，它会变成"误导 agent 的过期信息"还是"依然有用的稳定描述"？**

如果是前者，回去删掉那些易变内容。

---

---

## 暂停与恢复机制

### 何时暂停
遇到以下情况，**立即停止当前阶段**，向用户报告，不要硬撑：
- 上下文剩余 < 30%，且当前阶段未完成
- 阶段 1 发现 reading_plan 文件数 > 当前档位上限
- 阶段 2 发现入口文件无法定位，或入口文件本身已无法解析（混淆/加密/外部加载）
- 任何阶段连续 3 次重试失败

### 暂停报告格式

```markdown
## 暂停报告
- 已完成阶段：X
- 已产出文件：
  - .docs-init/profile.md ✓
  - .docs-init/skeleton.md ✓
  - .docs-init/findings.md（部分，已读 M/N）
- 暂停原因：<具体原因>
- 建议下一步：
  - [ ] 用户确认是否分批继续（推荐）
  - [ ] 缩小范围到子目录 X
  - [ ] 调整规模档位为 L 并重启阶段 2
- 已读但未归档的关键发现：<若有>
```

### 恢复
用户决定继续后，从最近一个完成的阶段产物（在 `.docs-init/` 下）继续，不要从头来。

---

## 自检清单（每阶段强制执行）

### 阶段 0 完成自检
- [ ] profile.md 存在
- [ ] 项目类型勾选 ≥1
- [ ] 规模档位明确

### 阶段 1 完成自检
- [ ] skeleton.md 中每文件有标签
- [ ] reading_plan.md 给出预估覆盖率
- [ ] 跳过的文件给出原因

### 阶段 2 完成自检
- [ ] findings 每条带 `[文件:行号]`
- [ ] 状态字段所有取值已收录
- [ ] 共享资源读写双方已收录
- [ ] 错误处理路径已收录
- [ ] ⚠️ 不确定项已标注

### 阶段 3 完成自检
- [ ] 每个正文环 ≥3 finding 证据
- [ ] 5 种识别方法均已扫描
- [ ] 0 环或多环结论给出依据

### 阶段 4 完成自检
- [ ] AGENTS.md ≤ 150 行
- [ ] AGENTS.md 前 30 行包含了最关键的约束
- [ ] LOOPS.md 中没有任何 `文件:行号` 引用（用语义路径代替）
- [ ] 没有创建空洞的子目录 AGENTS.md
- [ ] 没有写入 agent 自己能看到的信息（目录树、文件清单、依赖列表）
- [ ] 维护规则部分明确了"默认不更新"
- [ ] 提供了跨工具兼容脚本
- [ ] 已知盲点（⚠️ 项）显式列出

---

## 总执行顺序（给 agent 的最终指令）

1. 读完本提示词全部内容
2. 在项目根目录创建 `.docs-init/` 工作目录
3. **依次执行阶段 0 → 1 → 2 → 3 → 4**，每个阶段产出指定文件后再进入下一阶段
4. 每个阶段开头声明"=== 阶段 X 开始 ===" + 当前任务 + 禁止动作
5. 每个阶段结束执行自检清单，清单全过才进入下一阶段
6. 遇到暂停条件立即停下，按格式报告
7. 全部完成后，输出最终交付清单与覆盖率报告

不要为了显得勤奋而虚构内容。诚实的"未读"和"待确认"，比好看的"已完成"更有价值。