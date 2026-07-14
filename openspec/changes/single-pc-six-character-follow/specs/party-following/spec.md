# 单机六角色队伍跟随能力规格

## 1. Capability

- 名称：`party-following`
- 适用场景：单机运行 6 个角色实例，1 个角色由玩家主控，5 个角色通过自动化逻辑复现主控移动节奏。
- 变更类型：`new-capability`

## 2. Current Behavior

- 当前代码行为：
  - 当前仓库为空，没有任何主控采样、窗口管理、跟随执行或异常恢复行为。
  - 当前只有本次新增的 OpenSpec 文档，用于定义后续实现目标。
- 关联文件：
  - `/Users/liuchang/Desktop/project/poe2_scripts/openspec/changes/single-pc-six-character-follow/proposal.md`
  - `/Users/liuchang/Desktop/project/poe2_scripts/openspec/changes/single-pc-six-character-follow/api-contract.md`
  - `/Users/liuchang/Desktop/project/poe2_scripts/openspec/changes/single-pc-six-character-follow/implementation-delta.md`

## 3. Target Behavior

- 目标行为：
  - 系统启动后能绑定 1 个主控窗口和 5 个 follower 窗口。
  - 主控移动、停下和显著转向时，5 个 follower 在可配置的 tick 延迟内同步动作。
  - 任意 follower 失步、窗口失焦或采样中断时，系统会暂停危险动作并进入 regroup 或 safe pause。
- 差异摘要：
  - 从“完全无实现”变为“具备可执行的六角色跟随链路设计和验收标准”。

## 4. Requirements

- Requirement 1：
  - 系统必须显式区分 1 个 `leader` 和 5 个 `follower`，且所有窗口绑定结果都要进入统一状态对象管理。
- Requirement 2：
  - follower 的跟随动作必须由 `LeaderSample` 驱动，不能各自独立采样，以避免 5 条分叉时间线。
- Requirement 3：
  - 任意异常场景都必须先停输入，再决定 regroup 或人工接管，不能在未知状态下继续盲跟。

## 5. Acceptance

- 输入：
  - 6 个已启动的游戏窗口。
  - 1 份包含 leader 与 5 个 follower 的配置文件。
  - 系统支持的统一分辨率、窗口模式和键位布局。
- 触发：
  - 用户启动跟随系统，并成功绑定 6 个窗口。
  - 用户开始手动操控 leader 角色移动。
- 预期结果：
  - 5 个 follower 在允许延迟内复现 leader 的移动和停止节奏。
  - follower 延迟超阈值、失焦或失步时，系统输出明确状态并暂停自动输入。
  - leader 采样中断时，全队切换为 `safe_pause`，等待人工处理。

## 6. Edge Cases

- 边界条件：
  - 6 个窗口分辨率一致但性能不足，导致 tick 间隔抖动。
  - 主控只做短促点按而不是持续移动。
  - 个别 follower 因地形或碰撞造成短时路径偏离。
- 异常场景：
  - leader 窗口被最小化或句柄失效。
  - follower 窗口标题变更，导致绑定失败。
  - 输入采样线程卡死，连续多个 tick 没有有效事件。
- 降级策略：
  - 先进入 `regroup` 尝试短时恢复。
  - 恢复失败或 leader 采样中断时，升级到 `safe_pause`。
  - 所有降级动作都必须留下可追踪日志，便于后续调整跟随阈值。
