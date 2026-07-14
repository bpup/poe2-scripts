# 单机六角色跟随自动化任务清单

## 1. 当前已完成实现

- 已存在能力：
  - 当前仅完成项目扫描与 OpenSpec 初始化。
  - 已确认仓库现状为“空目录、非 git 仓库、无既有实现”。
- 可直接复用：
  - 当前没有可直接复用的代码、配置或文档模板。
- 明确不改：
  - 本次不直接编写自动化执行代码。
  - 本次不扩展到战斗、拾取、交易、喊话等旁路能力。

## 2. 联调前最小待办

- 页面 / 容器：
  - 待建 `src/app.py` 作为 CLI 入口，负责读取配置、初始化窗口映射和启动 leader / follower 协程。
  - 待建 `src/ui/status_panel.py` 作为可选状态面板；若先不上 UI，至少要有控制台摘要输出。
- 状态 / 数据流：
  - 待建 `src/core/party_state.py`，统一维护 leader、5 个 follower、全局运行态 `idle/running/regroup/safe_pause`。
  - 待建 `src/core/tick_bus.py`，以固定 tick 广播主控采样结果和 follower 执行状态。
- 接口 / 桥接：
  - 待建 `src/core/window_registry.py`，负责 6 个角色窗口句柄绑定与健康检查。
  - 待建 `src/follow/leader_sampler.py`，采集主控方向键、位移节奏和关键转向事件。
  - 待建 `src/follow/follower_executor.py`，把 leader 采样转成 5 个 follower 的跟随命令。
  - 待建 `src/follow/regroup_controller.py`，处理失步、卡位、窗口失焦和超时恢复。
  - 待建 `config/party-six-follow.yaml`，配置主控角色、跟随角色、窗口标题、采样频率和容错阈值。
- 文档 / 配置：
  - 增补运行假设文档，明确支持的分辨率、窗口模式、键位布局和系统权限要求。
  - 如后续启用第三方输入能力，再单独补充安全边界和适配说明。

## 3. 验证项

- 文档一致性检查：
  - `proposal.md`、`api-contract.md`、`implementation-delta.md`、`spec.md` 的文件路径和模块命名保持一致。
  - 文档中所有“已有实现”描述都必须与空目录事实一致，不能伪造现有模块。
- 变更类型复核：
  - 继续保持 `new-capability`，除非后续真实脚本落库后再更新为改造型变更。
- 关键流程验证：
  - 主控启动后，5 个 follower 能在配置允许的 tick 延迟内复制移动节奏。
  - 任意 follower 失步时，不会继续盲目输入，而是进入 regroup 或 safe pause。
  - 主控停止移动时，follower 能在限定时间内收敛到停止状态。
- 边界与异常验证：
  - 单个窗口失焦、窗口标题匹配失败、分辨率不一致、采样中断、CPU 抖动时，系统均有明确降级动作。
