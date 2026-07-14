# 单机六角色跟随自动化内部契约

## 1. 当前项目接口现状

- 当前仓库没有任何现有接口、桥接、服务调用或自动化引擎封装。
- 本文定义的是后续实现建议采用的“内部契约”，用于约束模块间数据交换，而不是宣称这些接口已经存在。

## 2. 角色与窗口绑定契约

### `WindowBinding`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `roleId` | `string` | 角色唯一标识，建议使用配置中的逻辑名称 |
| `roleType` | `'leader' | 'follower'` | 主控或跟随角色 |
| `windowTitle` | `string` | 用于匹配客户端窗口的标题或标题片段 |
| `handle` | `string` | 绑定后的窗口句柄字符串 |
| `resolution` | `{ width: number, height: number }` | 当前窗口分辨率 |
| `scale` | `number` | 缩放比，默认 `1` |
| `status` | `'ready' | 'missing' | 'mismatch'` | 绑定状态 |

### 兜底策略

- 任意 follower 的 `status !== 'ready'` 时，不允许进入 `running`。
- 若 leader 窗口丢失绑定，系统立即切换到 `safe_pause`。

## 3. 主控采样契约

### `LeaderSample`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `tickId` | `number` | 递增采样序号 |
| `capturedAt` | `number` | 采样时间戳，毫秒 |
| `movementVector` | `{ x: number, y: number }` | 归一化移动向量 |
| `isMoving` | `boolean` | 主控是否处于位移状态 |
| `heading` | `number` | 面向角度，取值范围 `0-359` |
| `event` | `'move' | 'stop' | 'turn' | 'teleport'` | 关键动作事件 |
| `source` | `'keyboard' | 'mouse' | 'hybrid'` | 输入来源 |

### 兜底策略

- 若 2 个连续 tick 未采到有效 `LeaderSample`，系统状态改为 `safe_pause`。
- `teleport` 事件不做盲跟，统一交给 regroup 流程。

## 4. 跟随指令契约

### `FollowerCommand`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `tickId` | `number` | 对应的 leader tick |
| `roleId` | `string` | follower 标识 |
| `action` | `'press' | 'release' | 'tap' | 'hold' | 'pause' | 'regroup'` | 执行动作 |
| `movementVector` | `{ x: number, y: number }` | 目标移动方向 |
| `holdMs` | `number` | 按住时长 |
| `reason` | `string` | 指令来源说明 |

### 兜底策略

- 任意 `FollowerCommand` 在执行前必须校验窗口仍处于 `ready`。
- 如果 follower 延迟超过 `maxFollowerLagMs`，应发送 `pause` 而不是继续堆积旧命令。

## 5. 运行状态契约

### `PartyRuntimeState`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `mode` | `'idle' | 'running' | 'regroup' | 'safe_pause'` | 全局运行态 |
| `leaderRoleId` | `string` | 当前主控角色 |
| `activeFollowers` | `string[]` | 当前正常跟随中的角色 |
| `pausedFollowers` | `string[]` | 已暂停的 follower |
| `lastHealthyTickId` | `number` | 最近一次全队健康的 tick |
| `lastError` | `string | null` | 最近一次错误摘要 |

### 兜底策略

- `safe_pause` 是全局强制态，进入后必须停止所有自动输入。
- `regroup` 只允许短时恢复尝试；连续失败后强制升级到 `safe_pause`。

## 6. 建议新增配置字段

### `config/party-six-follow.yaml`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `leader.roleId` | `string` | 主控角色 |
| `followers[].roleId` | `string` | 5 个 follower 标识 |
| `followers[].windowTitle` | `string` | 对应窗口标题 |
| `sampling.tickMs` | `number` | leader 采样周期 |
| `sampling.turnThreshold` | `number` | 转向事件触发阈值 |
| `runtime.maxFollowerLagMs` | `number` | follower 最大容忍延迟 |
| `runtime.maxDriftTicks` | `number` | 最大连续失步 tick 数 |
| `runtime.regroupCooldownMs` | `number` | regroup 冷却时间 |
| `runtime.pauseOnResolutionMismatch` | `boolean` | 分辨率不一致时是否强制暂停 |

## 7. 最小改动路径

- 第一步：先实现 `WindowBinding` 与 `PartyRuntimeState`，确保 6 个窗口可稳定绑定并被统一管理。
- 第二步：再实现 `LeaderSample -> FollowerCommand` 的最小链路，只覆盖移动和停止两个事件。
- 第三步：最后补 `regroup` 与 `safe_pause`，让系统在异常时有明确恢复路径。
