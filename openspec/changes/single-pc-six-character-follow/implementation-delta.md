# 单机六角色跟随自动化实现差异

## 1. 扫描结论

- 扫描路径：`/Users/liuchang/Desktop/project/poe2_scripts`
- `git status --short` 结果：当前目录不是 git 仓库，返回 `fatal: not a git repository (or any of the parent directories): .git`
- 目录扫描结果：`ls -la` 仅显示 `.` 与 `..`，未发现任何代码、配置、脚本、资源或文档文件。
- 关键词搜索结果：当前目录无可搜索文件，因此不存在“跟随 / follow / leader / party / role”相关既有逻辑。

## 2. 变更类型判断

- 结论：`new-capability`
- 说明：当前没有任何实现基线；本次 OpenSpec 不是对现有能力的改造，而是为未来脚本落地提供第一版实现地图。

## 3. 模块级变化矩阵

| 类别 | 当前命中 | 本次判断 | 建议落地点 | 说明 |
| --- | --- | --- | --- | --- |
| 页面 / 容器 | 无 | 新增 | `src/app.py`、`src/ui/status_panel.py` | 该项目更适合使用 CLI 入口，可选增加状态面板 |
| 状态管理 | 无 | 新增 | `src/core/party_state.py`、`src/core/tick_bus.py` | 管理全局运行态、角色绑定和 tick 分发 |
| 接口 / 桥接 | 无 | 新增 | `src/core/window_registry.py`、`src/follow/leader_sampler.py`、`src/follow/follower_executor.py` | 承接窗口绑定、输入采样和跟随命令下发 |
| 组件 / 公共能力 | 无 | 新增 | `src/common/logger.py`、`src/common/config_loader.py` | 提供日志、配置和公共校验 |
| 配置 | 无 | 新增 | `config/party-six-follow.yaml` | 固化 1 主控 5 跟随的运行参数 |
| 文档 | 无 | 新增 | `openspec/changes/single-pc-six-character-follow/*` | 当前已新增 OpenSpec 文档 |

## 4. 复用与不改范围

- 复用路径：当前无现成代码可复用。
- 不改范围：
  - 不把战斗、技能释放、自动拾取写进第一阶段跟随链路。
  - 不在没有验证的情况下引入内存读写、封包监听或驱动级注入能力。
  - 不假定后续一定存在 Web UI；默认优先保证 CLI 和日志链路可工作。

## 5. 接口字段不确定时的适配策略

- 窗口绑定字段不确定时，以 `WindowBinding` 作为唯一标准对象，对不同底层库做适配层转换。
- 主控采样若暂时拿不到真实角色坐标，第一阶段允许退化为“输入事件采样 + tick 对齐”，但必须把退化事实保留在日志里。
- follower 执行若暂时无法获得回执，默认按“提交成功但未确认”处理，并将恢复策略前置到 `regroup_controller`。

## 6. 后续最小改动路径

1. 在 `src/app.py` 建立可运行入口，并从 `config/party-six-follow.yaml` 读取 6 角色配置。
2. 在 `src/core/window_registry.py` 完成 6 个窗口的发现、绑定和健康检查。
3. 在 `src/follow/leader_sampler.py` 与 `src/follow/follower_executor.py` 打通“主控移动 -> follower 同步移动”的最小闭环。
4. 在 `src/follow/regroup_controller.py` 补全失步、失焦、分辨率不一致的暂停与恢复流程。
5. 完成后，再回写本 OpenSpec，把“待建文件”更新为“已实现文件”。
