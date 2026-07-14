# PoE2 单机六角色自动跟随 技术方案详细

> [← 返回概要](./poe2-six-follow-overview-2026-07-13.md)

## 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-07-13 | v1.0 | 初版，覆盖全部已实现模块与 OpenSpec 契约 |

---

## 模块设计

### Config Loader — 配置加载与校验

- **职责**：从 YAML 文件加载队伍配置，解析为强类型 dataclass，执行约束校验
- **输入**：配置文件路径（如 `config/party-six-follow.yaml`）
- **输出**：`PartyConfig` dataclass（含 LeaderConfig、FollowerConfig[]、SamplingConfig、RuntimeConfig）
- **核心逻辑**：
  1. `yaml.safe_load()` 加载原始字典
  2. 递归解析为嵌套 dataclass 实例
  3. 校验 follower 数量（必须 ≥ 5 且 ≤ 10）、role_id 唯一性、tick 间隔合理范围（20-500ms）
  4. 校验不通过抛 `ValueError` 阻止后续流程
- **异常处理**：文件缺失 → `FileNotFoundError` 提示；YAML 格式错误 → 指出具体行号
- **与其他模块交互**：被 `Poe2FollowApp` 在启动时调用，结果是所有其他模块的数据输入源

### Window Registry — 窗口发现与绑定

- **职责**：扫描系统窗口列表，按标题匹配 PoE2 客户端窗口，建立 1+5 窗口绑定关系
- **输入**：`PartyConfig` 中的 `leader.windowTitle` 和 `followers[].windowTitle`
- **输出**：6 个 `WindowBinding` 对象（含 handle、resolution、status）
- **核心逻辑**：
  1. 调用平台特定 API 枚举顶层窗口（Windows: `win32gui.EnumWindows`；macOS: 返回空列表 stub）
  2. 标题子串匹配，按配置顺序分配 leader（索引 0）和 followers（索引 1-5）
  3. 获取窗口句柄和分辨率
  4. 标记 status 为 `ready`/`missing`/`mismatch`
- **异常处理**：找不到窗口 → `status='missing'`，记录日志不抛异常；字符串匹配歧义 → 记录 warning
- **与其他模块交互**：绑定结果写入 `PartyRuntimeState` 中，供所有模块查询窗口句柄

### Party State — 全局状态机

- **职责**：维护系统的唯一全局状态，管理四态转换（idle → running → regroup → safe_pause），仲裁所有降级和恢复决策
- **输入**：各模块的状态变更请求（`transition_to`、`request_regroup`、`fail_regroup`、`record_drift` 等）
- **输出**：当前全局模式 `RunMode`，`activeFollowers` / `pausedFollowers` 集合
- **核心逻辑**：
  1. `transition_to(target)` — 检查目标模式是否合法（如不可从 idle 直接到 regroup）
  2. `request_regroup()` — 标记进入 regroup 模式，计数器 +1；超过 3 次 → `fail_regroup()` → safe_pause
  3. `record_drift(role_id)` — 记录单 follower 漂移；超 `max_drift_ticks` → request_regroup
  4. `clear_drift(role_id)` — 漂移恢复后清零
  5. `is_degraded()` — 所有 follower 都有异常时的兜底判断
- **异常处理**：非法状态转换 → 记录错误日志，拒绝执行，保持上一状态
- **与其他模块交互**：所有模块通过此单例读写全局状态，TickBus 在 `running` 模式下负责分发

### Tick Bus — 采样广播总线

- **职责**：以固定间隔驱动采样→分发循环，是系统节拍器
- **输入**：`LeaderSampler` 注册为采样源；`FollowerExecutor` 注册为消费者
- **输出**：每个 tick 将 `LeaderSample` 分发给 5 个 follower 回调，同时更新 `missed_ticks` 计数器
- **核心逻辑**：
  1. `asyncio.sleep(tick_ms/1000)` 维持固定 tick 频率
  2. 调用 `sampler.sample()` 获取当前 `LeaderSample`
  3. 若采样有效 → 重置 missed_ticks；若无效 → missed_ticks += 1
  4. 通过 `asyncio.gather(*[cb(sample) for cb in followers], return_exceptions=True)` 并行分发给所有 follower
- **异常处理**：单个 follower 异常不阻断其他；漏采反馈给 RegroupController 做评估
- **与其他模块交互**：持有 LeaderSampler 和 FollowerExecutor 引用，是数据流的中枢管道

### Leader Sampler — 主控输入采样

- **职责**：监听主控玩家键盘输入（WASD），计算归一化移动向量，分类事件类型，生成 `LeaderSample`
- **输入**：pynput 全局键盘 hook（无焦点依赖）
- **输出**：每 tick 生成一个 `LeaderSample`
- **核心逻辑**：
  1. pynput `Listener(on_press, on_release)` 维护当前按键集合 `{w, a, s, d, ...}`
  2. 按键集合 → 归一化向量（w=上, s=下, a=左, d=右，对角线组合如 w+a=左上，向量 {-0.707, -0.707}）
  3. 向量与上一帧比较：零→非零 = `move`；非零→零 = `stop`；方向角度差超 `turn_threshold` = `turn`
  4. heading 通过 `atan2(y, x)` 计算（0-359 度）
  5. 事件打包为 `LeaderSample(tickId, capturedAt, movementVector, isMoving, heading, event, source='keyboard')`
- **异常处理**：监听线程异常 → 标记为无效采样，TickBus 累积 missed_ticks
- **与其他模块交互**：被 TickBus 的 tick 循环调用的 `sample()` 方法

### Follower Executor — 跟随指令执行

- **职责**：将 `LeaderSample` 转换为 `FollowerCommand`，通过键盘注入驱动每个 follower 窗口
- **输入**：`LeaderSample` + `WindowBinding`（窗口句柄）
- **输出**：`FollowerCommand` 对比当前按键状态后执行差量按键注入
- **核心逻辑**：
  1. `vector_to_keys(movementVector)` — 将归一化向量映射为 WASD 按键组合（x>0.25=d, x<-0.25=a, y>0.25=s, y<-0.25=w，阈值 0.25 过滤微动噪声）
  2. `_diff_and_apply(role_id, desired_keys)` — 对比当前已按下的键，只对新键执行 press、对不再需要的键执行 release
  3. `emergency_stop(role_id)` — 释放该 follower 所有按键（safe_pause 时调用）
- **异常处理**：按键注入失败 → 标记该 follower 为异常；紧急停在任何状态下都能调用
- **与其他模块交互**：注册到 TickBus 作为 follower 回调；受 PartyState 模式约束（仅 running 模式执行动作）

### Regroup Controller — 失步检测与恢复

- **职责**：评估系统健康状态，检测失步触发 regroup 恢复流程
- **输入**：TickBus 的 `missed_ticks`、PartyState 中各 follower 的漂移状态
- **输出**：状态变更请求（regroup、safe_pause）、恢复尝试的 FollowerCommand 序列
- **核心逻辑**：
  1. `evaluate()` — 每个监控周期（约 500ms）检查：missed_ticks ≥ 3 → safe_pause；missed_ticks ≥ 2 → 记录 warning；检查各 follower 漂移
  2. `_try_regroup(role_id)` — 发起 regroup 流程，attempt 计数器 +1，超过阈值（3 次）→ fail_regroup → safe_pause
  3. `_handle_regroup_phase()` — 暂停该 follower → 等待 5 秒 grace period → 从最后已知 leader 状态重新下发移动指令 → 验证漂移是否恢复
- **异常处理**：grace period 内 follower 句柄丢失 → 直接 safe_pause
- **与其他模块交互**：作为 monitor 循环的一部分在 `Poe2FollowApp.run()` 中运行，读写 PartyState

### App Entry — CLI 编排入口

- **职责**：加载配置、绑定窗口、启停 tick 循环和监控协程、处理优雅退出
- **输入**：命令行参数 `config_path`
- **输出**：启动日志、运行时状态摘要、退出码
- **核心逻辑**：
  1. `load_config(path)` → `PartyConfig`
  2. `bind_all_windows()` → 6 个 WindowBinding 写入 PartyState
  3. `async run()`：同时启动 `_tick_loop`（TickBus）和 `_monitor_loop`（HealthMonitor + RegroupController.evaluate）
  4. SIGINT/SIGTERM → 优雅关闭：释放所有 follower 按键 → 停止 tick → 记录退出日志
- **异常处理**：未捕获异常 → 记录 traceback → emergency_stop_all → exit(1)
- **与其他模块交互**：持有所有模块引用，是唯一的编排者

---

## 关键节点

### 节点 1：窗口绑定流程

- **触发条件**：`Poe2FollowApp.bind_all_windows()` 被调用
- **前置条件**：配置文件已成功加载，windowTitle 字段非空
- **执行逻辑**：
  1. 调用 `WindowRegistry.scan_windows(leader_title, follower_titles[])`
  2. 每个配置标题在窗口列表中做子串匹配
  3. 匹配成功 → 创建 `WindowBinding(status='ready')`，获取句柄和分辨率
  4. 匹配失败 → 创建 `WindowBinding(status='missing')`
  5. 所有 windowBinding 写入 `PartyState`
  6. `PartyState.all_bindings_ready()` 检查是否全部 `ready`
  7. 若有 `missing` → 打印未匹配的标题，等待人工修正，禁止进入 running
- **并发保护**：绑定为启动阶段的同步操作，不与其他协程竞争
- **出错处理**：API 调用失败 → 返回 `mismatch` 状态，记录详细错误信息

### 节点 2：Tick 循环主流程

- **触发条件**：PartyState 过渡到 `running` 后，TickBus 开始循环
- **前置条件**：LeaderSampler 和 5 个 FollowerExecutor 已注册到 TickBus
- **执行逻辑**：
  1. `sample = sampler.sample()` — 获取当前 tick 的主控采样
  2. 若 `sample is None` → `missed_ticks += 1`，跳过指令下发，等待下一 tick
  3. 若 `sample` 有效 → `missed_ticks = 0`，打包 `sample.tickId += 1`, `sample.capturedAt = time.time()`
  4. `asyncio.gather(...)` 并行调用所有 follower 回调（返回 `FollowerCommand`）
- **并发保护**：`asyncio.gather(return_exceptions=True)` 确保单个 follower 抛异常不中断其他
- **超时定义**：每个 follower 回调无显式超时，依赖 pynput 注入为同步瞬时操作

### 节点 3：按键差量注入

- **触发条件**：FollowerExecutor 收到 `LeaderSample`
- **前置条件**：目标窗口句柄有效，`window.status === 'ready'`
- **执行逻辑**：
  1. `desired = vector_to_keys(sample.movementVector)` → 例如 `{'w', 'd'}`（右上方向）
  2. `current = held_keys[role_id]` → 例如 `{'w'}`（当前只按着 w）
  3. `to_press = desired - current` → `{'d'}`
  4. `to_release = current - desired` → 空集
  5. 执行 `press(d)` — 通过 pynput `Controller` 发送到目标窗口
  6. 更新 `held_keys[role_id] = desired`
  7. 记录 `FollowerCommand(tickId, roleId, action='press', ...)`
- **并发保护**：每个 follower 有独立的 `held_keys` 字典，并行执行无锁冲突
- **出错处理**：window 句柄失效 → 写入 PartyState 标记该 follower 异常 → 本次 tick 跳过

### 节点 4：漂移检测与 regroup

- **触发条件**：RegroupController 在 monitor 循环中周期性评估（约 500ms 一次）
- **前置条件**：PartyState 处于 `running` 模式
- **执行逻辑**：
  1. 检查 `missed_ticks`：≥ 3 → 直接 `safe_pause`；≥ 2 → 记录 warning
  2. 遍历每个 `active_follower`：检查其 `drift_ticks` 是否超过 `max_drift_ticks`（默认 10）
  3. 未超过 → 继续监控
  4. 超过 → 记录 `excessively_drifting` → 从 `active_followers` 移除 → 加入 `paused_followers` → 调用 `_try_regroup(role_id)`
  5. `_try_regroup` 尝试 3 次：暂停 → grace period 5s → 重发移动指令 → 验证
  6. 3 次全部失败 → `fail_regroup` → `safe_pause`
- **并发保护**：monitor 循环和 tick 循环通过 PartyState 的原子属性读取
- **出错处理**：grace period 内发现句柄丢失 → 直接升级为 `safe_pause`

### 节点 5：优雅退出

- **触发条件**：SIGINT (Ctrl+C) / SIGTERM
- **前置条件**：任何运行模式下均可触发
- **执行逻辑**：
  1. 捕获信号 → 设置 `shutdown_event`
  2. `emergency_stop_all()` — 遍历所有 6 个角色，释放所有已按下的按键
  3. 停止 `keyboard_listener`
  4. 取消 tick 和 monitor 协程
  5. 记录退出日志（tick 总数、异常统计）
  6. `exit(0)` 正常退出
- **并发保护**：`shutdown_event` 为 `asyncio.Event`，tick 循环每帧检查并退出
- **出错处理**：强杀（SIGKILL）无法优雅退出，但不造成破坏（按键注入是瞬时的，不会残留按住状态）

---

## 接口对接

### LeaderSample — 主控采样 → TickBus

- **调用时机**：每个 tick（默认 50ms），由 TickBus 调用 `sampler.sample()`
- **请求参数**（无显式参数，采样自内部键盘状态）：
  ```python
  # LeaderSample
  @dataclass
  class LeaderSample:
      tick_id: int           # 递增序号
      captured_at: float     # time.time() 毫秒精度
      movement_vector: tuple  # (x: float, y: float) 归一化后范围 [-1, 1]
      is_moving: bool
      heading: int           # 0-359 度
      event: str             # 'move' | 'stop' | 'turn' | 'teleport'
      source: str            # 'keyboard' | 'mouse' | 'hybrid'
  ```
- **响应处理**：
  - 有效 → TickBus 重置 missed_ticks，分发到所有 follower
  - `None`（采样线程异常）→ TickBus missed_ticks += 1，本次不分发
  - 连续 2 tick 为 None → RegroupController 记录 warning
  - 连续 3 tick 为 None → RegroupController 触发 safe_pause
- **降级策略**：采样中断不丢弃已建立的按键状态，safe_pause 时 `emergency_stop_all()` 释放所有残留按键

### FollowerCommand — TickBus → FollowerExecutor

- **调用时机**：每个 follower 在收到 LeaderSample 后同步生成
- **响应结构**：
  ```python
  @dataclass
  class FollowerCommand:
      tick_id: int
      role_id: str
      action: str            # 'press' | 'release' | 'tap' | 'hold' | 'pause' | 'regroup'
      movement_vector: tuple
      hold_ms: int           # 按住时长 (ms)，tap/hold 动作时有效
      reason: str            # 指令来源说明
  ```
- **响应处理**：
  - `action='press'/'release'` → 执行差量注入
  - `action='pause'` → 紧急停止该 follower
  - `action='regroup'` → 跳过正常执行，记录 regroup 尝试
- **降级策略**：follower 延迟超过 `maxFollowerLagMs` → 发送 `pause` 而不是堆积旧命令

### WindowBinding — WindowRegistry → PartyState

- **调用时机**：启动阶段 `bind_all_windows()`
- **响应结构**：
  ```python
  @dataclass
  class WindowBinding:
      role_id: str
      role_type: str         # 'leader' | 'follower'
      window_title: str
      handle: str            # 窗口句柄（Win32 API 返回的 int 转 str）
      resolution: tuple      # (width, height)
      scale: float           # 默认 1.0
      status: str            # 'ready' | 'missing' | 'mismatch'
  ```
- **响应处理**：
  - `ready` → 写入 PartyState，窗口可用
  - `missing` → 写入 PartyState 但禁止进入 running
  - `mismatch` → 根据配置 `pauseOnResolutionMismatch` 决定是否阻止 running
- **降级策略**：任意 follower 的 `status !== 'ready'` → 不允许进入 running；leader 窗口丢失 → 立即 safe_pause

### PartyRuntimeState — 全局状态同步

- **调用时机**：所有模块在状态变更时读写
- **响应结构**：
  ```python
  @dataclass
  class PartyRuntimeState:
      mode: RunMode              # IDLE | RUNNING | REGROUP | SAFE_PAUSE
      leader_role_id: str
      active_followers: list[str]
      paused_followers: list[str]
      last_healthy_tick_id: int
      last_error: Optional[str]
  ```
- **响应处理**：
  - 所有模块在修改运行行为前查询 `mode`
  - 只有 `RUNNING` 模式下 TickBus 才分发采样
  - `SAFE_PAUSE` 下 FollowerExecutor 拒绝所有非 `emergency_stop` 的指令
- **降级策略**：状态变更都是原子操作，不存在"部分进入某状态"的中间态

---

## 交互设计

### Tick 循环内的完整数据流

| 阶段 | 模块 | 操作 | 输入 | 输出 |
|------|------|------|------|------|
| 1. 采样 | LeaderSampler | `sample()` | pynput 键盘状态 | `LeaderSample` 或 `None` |
| 2. 分发 | TickBus | `gather(followers)` | `LeaderSample` | 等待所有 follower 回调 |
| 3. 向量转换 | FollowerExecutor | `vector_to_keys()` | `movementVector` | `set[str]` 目标按键集 |
| 4. 差量计算 | FollowerExecutor | `_diff_and_apply()` | 目标按键集 vs 当前按键集 | `press()` / `release()` 调用 |
| 5. 指令记录 | FollowerExecutor | 日志 | `FollowerCommand` | debug 日志 |
| 6. 监控评估 | RegroupController | `evaluate()` | missed_ticks, drift_ticks | 状态变更请求 |

### 异常场景下的交互流程

| 异常 | 检测者 | 动作 1 | 动作 2 | 恢复条件 |
|------|--------|--------|--------|---------|
| Leader 采样中断 ≥3 tick | TickBus → RegroupController | `transition_to(SAFE_PAUSE)` | emergency_stop_all() | 人工确认后重置为 idle |
| 单 follower 漂移 10 tick | PartyState → RegroupController | `request_regroup(role_id)` | _try_regroup (max 3 次) | 漂移 clears 且按键状态同步 |
| regroup 3 次失败 | RegroupController | `fail_regroup()` | `transition_to(SAFE_PAUSE)` | 人工确认后重置 |
| 窗口句柄失效 | HealthMonitor → PartyState | 标记该 binding 为 missing | leader 失效 → safe_pause；follower 失效 → pause 该 follower | 窗口恢复后重新绑定 |
| 分辨率不一致 | WindowRegistry | 标记 `status='mismatch'` | 若 `pauseOnResolutionMismatch=true` → 禁止进入 running | 调整窗口分辨率 |

### 用户可感知的状态与反馈

| 状态 | 控制台输出 | 对按键注入的影响 |
|------|-----------|-----------------|
| idle | `[INFO] 6 windows bound. Ready to start.` | 无注入 |
| running | `[INFO] Follow started.` 周期性 debug 日志 | 正常注入 |
| regroup | `[WARN] Follower X drifting, regroup attempt N/3` | 仅暂停该 follower |
| safe_pause | `[ERROR] Safe pause engaged. All input stopped.` | 全部注入停止 |

---

## 数据结构

### 核心 dataclass 定义（来源：OpenSpec api-contract.md）

```python
# --- config_loader.py ---
@dataclass
class LeaderConfig:
    role_id: str
    window_title: str

@dataclass
class FollowerConfig:
    role_id: str
    window_title: str

@dataclass
class SamplingConfig:
    tick_ms: int              # 默认 50
    turn_threshold: int       # 默认 45（度）

@dataclass
class RuntimeConfig:
    max_follower_lag_ms: int  # 默认 200
    max_drift_ticks: int      # 默认 10
    regroup_cooldown_ms: int  # 默认 3000
    pause_on_resolution_mismatch: bool  # 默认 True

@dataclass
class PartyConfig:
    leader: LeaderConfig
    followers: list[FollowerConfig]
    sampling: SamplingConfig
    runtime: RuntimeConfig

# --- tick_bus.py ---
@dataclass
class LeaderSample:
    tick_id: int
    captured_at: float
    movement_vector: tuple     # (x, y)，归一化 float
    is_moving: bool
    heading: int               # 0-359
    event: str                 # 'move'|'stop'|'turn'|'teleport'
    source: str                # 'keyboard'|'mouse'|'hybrid'

# --- follower_executor.py ---
@dataclass
class FollowerCommand:
    tick_id: int
    role_id: str
    action: str                # 'press'|'release'|'tap'|'hold'|'pause'|'regroup'
    movement_vector: tuple
    hold_ms: int               # 按住时长，tap/hold 动作时有效
    reason: str                # 指令来源说明

# --- party_state.py ---
class RunMode(Enum):
    IDLE = "idle"
    RUNNING = "running"
    REGROUP = "regroup"
    SAFE_PAUSE = "safe_pause"

class WindowStatus(Enum):
    READY = "ready"
    MISSING = "missing"
    MISMATCH = "mismatch"

@dataclass
class WindowBinding:
    role_id: str
    role_type: str             # 'leader'|'follower'
    window_title: str
    handle: str
    resolution: tuple          # (width, height)
    scale: float
    status: WindowStatus
```

### 前端内部扩展（来源：已实现代码）

```python
# leader_sampler.py — 内部状态
class LeaderSampler:
    _pressed_keys: set[str]     # 当前按下的按键 {'w', 'd'}
    _prev_vector: tuple         # 上一帧的移动向量
    _prev_event: str            # 上一帧的事件类型

# follower_executor.py — 内部状态
class FollowerExecutor:
    _held_keys: dict[str, set[str]]  # role_id → 当前已按下的按键集
    _controllers: dict[str, pynput.keyboard.Controller]

# regroup_controller.py — 内部状态
class RegroupController:
    _attempts: dict[str, int]   # role_id → regroup 尝试次数
    _grace_until: dict[str, float]  # role_id → grace period 结束时间
```

---

## 测试设计

### 可测试点清单

| 场景 | 前置条件 | 操作 | 预期结果 | 优先级 |
|------|---------|------|---------|--------|
| 配置加载正常 | party-six-follow.yaml 格式正确 | `load_config(path)` | 返回 PartyConfig，5 followers | P0 |
| 配置校验-不够5个 follower | followers 数组长度=3 | `load_config(path)` | 抛出 ValueError | P0 |
| 配置校验-role_id重复 | 2个 follower 使用相同 role_id | `load_config(path)` | 抛出 ValueError | P0 |
| 状态机 idle→running | 6窗口全部 ready | `transition_to(RUNNING)` | mode 变为 RUNNING | P0 |
| 状态机 running→regroup | 单 follower 漂移超限 | `request_regroup(role_id)` | mode 变为 REGROUP，attempt=1 | P0 |
| 状态机 regroup→safe_pause | 3次 regroup 失败 | 连续 `fail_regroup()` | mode 变为 SAFE_PAUSE | P0 |
| 非法状态转换 | idle 状态 | `transition_to(REGROUP)` | 拒绝，记录 error 日志 | P0 |
| 向量→按键映射 | 向量 (-0.7, -0.7) | `vector_to_keys((-0.7, -0.7))` | 返回 `{'w', 'a'}` | P1 |
| 差量按键注入 | 当前按着 `{'w'}`，目标 `{'w','d'}` | `_diff_and_apply(...)` | press(d)，不重复press(w) | P1 |
| 停止事件检测 | 上一帧有移动向量，当前帧 (0,0) | 事件分类 | event='stop' | P1 |
| 转向事件检测 | 上一帧 heading=0，当前帧 heading=90 | 事件分类（阈值45°） | event='turn' | P1 |
| 微小方向变化不触发 turn | heading delta=30 < threshold=45 | 事件分类 | event='move' | P1 |
| tick 总线漏采≥3 → safe_pause | 连续3 tick 采样=None | `evaluate()` | 触发 safe_pause | P1 |
| tick 总线漏采≥2 → warning | 连续2 tick 采样=None | `evaluate()` | 记录 WARNING 不触发降级 | P1 |
| 单 follower 漂移 10 tick → regroup | drift_ticks 累积=10 | `evaluate()` | 触发 request_regroup | P1 |
| regroup 3次失败 → safe_pause | attempt=3 | `fail_regroup()` | mode=SAFE_PAUSE | P1 |
| emergency_stop_all | normal state | `emergency_stop_all()` | 所有6角色按键 release | P1 |
| 优雅退出 SIGINT | 系统 running | Ctrl+C | emergency_stop_all → exit(0) | P1 |
| macOS stub 不崩溃 | 非 Windows | `scan_windows(...)` | 返回空列表，不抛异常 | P2 |
| 配置文件缺失 | path 不存在 | `load_config(path)` | FileNotFoundError | P2 |
| tick 间隔处理 | tick_ms=50 | 100个 tick 计时 | 实际 5000ms ± 250ms (5%) | P2 |

### 回归影响范围

- **直接影响**：
  - `src/core/party_state.py` — 状态机转换逻辑，任何相关修改影响全局
  - `src/common/config_loader.py` — 配置校验边界条件，影响所有模块启动
- **间接影响**：
  - `src/follow/follower_executor.py` — 修改按键注入逻辑影响所有 5 个 follower 的跟随精度
  - `src/follow/leader_sampler.py` — 采样逻辑变更影响事件分类准确性
- **不影响**：
  - `src/common/logger.py` — 纯基础设施，内部逻辑变更不影响业务模块

### Mock 策略

| 模块 | Mock 场景 | Mock 数据 |
|------|---------|---------|
| WindowRegistry | 非 Windows 环境 | stub 返回空列表，所有 binding status='ready'（模拟） |
| LeaderSampler | 不需要键盘硬件 | 注入预设按键集合 → 验证 sample() 输出 |
| FollowerExecutor | 不需要真实 PoE2 窗口 | stub pynput Controller，验证 `press/release` 调用序列 |
| 窗口健康检查 | 模拟句柄失效 | `check_health()` 返回 `MISSING`，验证降级流程 |
| 网络/IO | 本系统为纯本机，无网络依赖 | 不需要网络 mock |

---

## 文件布局

```
poe2_scripts/
├── config/
│   └── party-six-follow.yaml          # 队伍配置
├── src/
│   ├── app.py                         # CLI 入口
│   ├── common/
│   │   ├── __init__.py
│   │   ├── logger.py                  # 日志基础设施
│   │   └── config_loader.py           # 配置加载+校验
│   ├── core/
│   │   ├── __init__.py
│   │   ├── party_state.py             # 全局状态机
│   │   ├── tick_bus.py                # tick 总线
│   │   └── window_registry.py         # 窗口发现/绑定
│   └── follow/
│       ├── __init__.py
│       ├── leader_sampler.py          # 主控输入采样
│       ├── follower_executor.py       # 跟随指令执行
│       └── regroup_controller.py      # 失步检测与恢复
├── openspec/
│   └── changes/
│       └── single-pc-six-character-follow/
│           ├── proposal.md
│           ├── tasks.md
│           ├── api-contract.md
│           ├── implementation-delta.md
│           └── specs/
│               └── party-following/
│                   └── spec.md
├── docs/
│   └── architecture/
│       └── poe2-follow/
│           ├── README.md
│           ├── poe2-six-follow-overview-2026-07-13.md
│           └── poe2-six-follow-detail-2026-07-13.md
└── requirements.txt
```
