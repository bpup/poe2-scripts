# PoE2 Auto-Follow

PoE 2 多开跟随工具 — 地形感知寻路、实体躲避、自动编队跟随、血量监控、卡住自救、进程自动恢复。

## 功能

- **内存坐标读取** — AOB 扫描定位 `GameStates` 全局指针，沿偏移链读取 Leader 和每个 Follower 的世界坐标（X, Y, Z）
- **地形感知寻路** — 读取 AreaInstance 的可通行网格（~1200×N 格，约 10.87 单位/格），A* 寻路自动绕行障碍物
- **实体碰撞躲避** — 遍历 `AwakeEntities`（红黑树），400 单位半径内的怪物产生斥力场，避免撞怪
- **生命值监控** — 读取 Life 组件的 `VitalStruct`（当前/最大/比率），Leader 和 Follower 血量实时显示在 GUI
- **编队跟随** — 5 个 Follower 按 Diamond / Line / V 型编队保持在 Leader 指定偏移位置
- **卡住自救（4 级递增）** — 静止检测 → 跳跃（SPACE）→ 位移技能（Q）→ 反向逃离（8 ticks）→ 冷却恢复
- **进程自动恢复** — 游戏崩溃/重启后自动重新扫描 PID 并重连，无需手动重启工具
- **WASD 键注入** — 通过 `PostMessage(WM_KEYDOWN/UP)` 向每个窗口注入按键，无需前台焦点
- **实时 GUI 监控** — tkinter 界面：Leader 信息栏（位置 + 血量）+ Follower 状态表（位置、编队目标、血量、卡住等级、当前按键）+ 嵌入式日志面板
- **CI 打包为 EXE** — GitHub Actions 在 Windows 上通过 PyInstaller 构建，产物 `poe2-follow.exe`，开箱即用

## 原理

### 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│  NavGui (tkinter)                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ Leader 信息  │  │ Follower 状态│  │  日志面板    │           │
│  │ HP: 1234/2500│  │ 位置/血量/键 │  │              │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│         ▲                 ▲                                        │
│         │   status_queue  │                                        │
│  ┌──────┴─────────────────┴───────────────────────────────────┐  │
│  │  NavAgent (后台线程)                                        │  │
│  │  ┌─────────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │  │
│  │  │ MemoryReader│  │Pathfinder│  │Input     │  │Process  │ │  │
│  │  │ • 坐标      │  │ • A*网格 │  │ Injector │  │Recovery │ │  │
│  │  │ • 地形网格  │  │ • 绕障碍 │  │          │  │         │ │  │
│  │  │ • 实体列表  │  └──────────┘  └──────────┘  └─────────┘ │  │
│  │  │ • 生命值    │                                            │  │
│  │  └──────┬──────┘                                            │  │
│  └─────────┼──────────────────────────────────────────────────┘  │
│            │ ReadProcessMemory   + PostMessage                    │
│      ┌─────▼─────┐              ┌──────┬──────┐                  │
│      │ PoE2.exe  │              │PoE2  │PoE2  │                  │
│      │ (Leader)  │              │Foll1 │Foll2 │ ...              │
│      └───────────┘              └──────┴──────┘                  │
└──────────────────────────────────────────────────────────────────┘
```

### 1. 内存坐标读取（MemoryReader）

通过 Win32 API `ReadProcessMemory` 读取 PoE2 进程内存，用多层指针链解析玩家坐标。

**AOB 扫描入口**：程序启动时不会假设固定的内存地址，而是通过字节模式扫描整个游戏模块：

```
48 39 2D ?? ?? ?? ?? 0F 85 16 01 00 00
 │  │  │  └── 4-byte 位移            └── jnz 指令（唯一性）
 │  │  └── [rip+rel32] 寻址
 │  └── cmp（比较指令）
 └── REX.W 前缀（64位操作）
```

这是一条 `cmp [rip+rel32], rbp` 指令，在匹配地址上计算 `match_addr + 7 + int32(displacement)` 得到 `GameStates` 全局指针。

**坐标偏移链**：拿到 `GameStates` 后，沿多层指针链逐级解引用：

```
GameStates → InGameState(+0x08)
           → AreaInstance(+0x290)
           ├── LocalPlayer(+0x5B8)              → Entity
           ├── AwakeEntities(+0x6D8)            → std::map<uint, Entity*>  (红黑树)
           └── TerrainMetadata(+0x8B8)          → 可通行网格

Entity → EntityDetails(+0x08)
       └── ComponentLookUp(+0x28)
           ├── "Render" → RenderComponent
           │   └── WorldPosition(+0x138)        → (X, Y, Z) float
           └── "Life"  → LifeComponent
               ├── Health(+0x1B0)               → VitalStruct
               │   ├── Current(+0x30)           → int32
               │   └── Maximum(+0x2C)           → int32
               └── Mana(+0x208), ES(+0x248)
```

每次 tick（默认 50ms）读取 Leader 和所有 Follower 的坐标、血量、周边实体、地形网格。

### 1.1 地形感知寻路

从 `AreaInstance.TerrainMetadata` 读取可通行网格：

- `walkable_data`（+0xD0）→ `byte[]` 数组，每字节含 2 个格子（高/低 nibble）
- `bytes_per_row`（+0x130）→ 每行字节数（621），即 1242 格/行
- 世界/网格比例约 10.87 单位/格

非零 nibble = 障碍物，零 = 可通行。将网格注入 `Pathfinder`，A* 自动绕行。

### 1.2 实体碰撞躲避

遍历 `AwakeEntities`（MSVC `std::map` 红黑树结构，节点含 `_Left/_Parent/_Right` 指针 + value pair），读取 Leader 周边 400 单位半径内实体的世界坐标。在 WASD 方向计算中叠加斥力场（100 单位范围，150× 强度），Follower 自动绕开密集怪物群。

### 2. 编队系统

每个 Follower 从编队模板中获取自己相对于 Leader 的位置偏移：

| 编队类型 | 说明 | Follower 偏移（5 个位置） |
|---------|------|-------------------------|
| `diamond` | 菱形阵 | 正后方、右翼、左翼、后排左、后排右 |
| `line` | 一字长蛇 | 后方依次排开 5 格 |
| `v` | V 字阵 | 两翼展开 3 排 |

通过 `spacing` 参数控制位置间距（世界单位），在每次 tick 中计算 `formation_target = leader_pos + offset * spacing`。

### 3. 卡住自救（Anti-Stuck）

如果 Follower 连续 N 个 tick 移动距离低于阈值（默认 2.0 世界单位），判定为卡住，进入递增自救流程：

| 等级 | 触发条件 | 动作 |
|-----|---------|------|
| L0 | Normal | 正常跟随 |
| L1 | 静止 ≥ 10 ticks | 按 SPACE（跳跃脱困）|
| L2 | 跳跃后仍静止 | 按 Q（位移技能，如烈焰冲刺）|
| L3 | 技能后仍静止 | 反向逃离 8 ticks，然后进入 30 ticks 冷却 |

等级在 Follower 恢复移动时自动归零。冷却结束后若再次静止则从 L1 重新开始。

### 4. 进程自动恢复

当 Leader 或 Follower 游戏进程崩溃/重启时，连续 30 次 tick（约 1.5s）读取失败后触发自动恢复流程：

1. 关闭所有旧进程句柄，清空坐标/组件索引缓存
2. 重新扫描系统进程列表（`EnumProcesses`）
3. 按 HWND 重新匹配 Leader/Follower 的 PID（`GetWindowThreadProcessId`）
4. 重建 AOB 入口、ComponentLookUp 索引、地形网格
5. GUI 状态栏显示 "Reconnected." 或 "Recovery failed..."

无需手动重启工具，游戏重启后自动恢复跟随。

### 5. 按键注入（InputInjector）

通过 Win32 `PostMessage` 向目标窗口发送 `WM_KEYDOWN` / `WM_KEYUP` 消息：

- 不支持驱动级模拟键盘，走 Windows 消息队列
- 无需焦点切换 — 可同时向多个后台窗口注入
- 使用正确的 `lParam` 编码（scan code、previous state、transition bit）
- 每 tick 计算 delta（`desired_keys - current_keys`），精确释放和按下按键

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.10+
- PoE 2 客户端（Steam 或独立版）至少 2 个窗口
- 管理员权限（读取其他进程内存需要）

### 安装

```bash
git clone git@github.com:bpup/poe2-scripts.git
cd poe2-scripts

# 创建虚拟环境（推荐）
python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

### 配置

编辑 `config/nav-follow.yaml`：

```yaml
followers:
  - role_id: follower_1
    window_title: "Path of Exile 2"   # 窗口标题关键字

sampling:
  tick_ms: 50                          # 控制循环间隔（毫秒）

nav:
  behavior:
    formation:
      type: diamond                    # diamond | line | v
      spacing: 35.0                    # 编队间距（世界单位）
    anti_stuck:
      enabled: true
      distance_threshold: 2.0          # 判定卡住的移动距离
      stuck_ticks: 10                  # 卡住判定连续帧数
      jump_key: "SPACE"
      skill_key: "Q"
```

### 运行

```bash
python src/app.py
```

启动后弹出窗口选择对话框：列出所有标题含 "Path of Exile 2" 的窗口，选择一个 Leader、勾选需要跟随的 Follower，点击 OK 进入主界面。主 GUI 启动后点击 **Start** 开始跟随。

### 下载预编译 EXE

前往 [GitHub Releases](https://github.com/bpup/poe2-scripts/releases) 下载最新的 `poe2-follow.exe`，解压后直接运行（需将 `config/nav-follow.yaml` 放在同目录下）。

## 项目结构

```
poe2_scripts/
├── config/
│   └── nav-follow.yaml          # 配置文件（偏移、编队、防卡住）
├── src/
│   ├── app.py                   # 入口 — 启动 GUI
│   ├── common/
│   │   ├── config_loader.py     # YAML 配置解析 + 数据类
│   │   ├── gui_log_handler.py   # 日志→tkinter 桥接（Queue + ScrolledText）
│   │   └── logger.py            # 结构化日志
│   ├── core/
│   │   ├── input_injector.py    # Win32 PostMessage 按键注入
│   │   ├── memory_reader.py     # ReadProcessMemory + AOB + 偏移链 + 地形/实体/血量
│   │   ├── pathfinder.py        # A* 寻路 + 地形网格 + WASD 方向转换
│   │   └── window_registry.py   # 窗口扫描、绑定、健康检查
│   ├── follow/
│   │   └── nav_agent.py         # 主循环：坐标/血量读取→编队→寻路→避怪→按键→防卡→恢复
│   └── ui/
│       └── gui.py               # tkinter 界面（Leader 位置/血量、Follower 状态表、日志）
├── .github/workflows/
│   └── build.yml                # CI：Windows PyInstaller 打包 + Release 发布
├── pyinstaller.spec             # PyInstaller 打包配置
└── requirements.txt
```

## 致谢

内存偏移参考 [POE2Radar/Poe2Offsets.cs](https://github.com/POE2Radar/POE2Radar/blob/master/Framework/Offsets/Poe2Offsets.cs)。

## 免责声明

本项目仅用于学习和研究 Windows 进程内存读取技术。使用本工具可能违反 PoE 2 服务条款，请自行承担风险。
