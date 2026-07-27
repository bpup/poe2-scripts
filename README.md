# PoE2 Auto-Follow

PoE 2 多账号本地双人跟随工具 — 地形感知寻路、实体躲避、自动编队跟随、虚拟手柄 P2 操控、卡住自救、进程自动恢复。

## 功能

- **多账号支持** — 支持 2~3 个 PoE2 窗口，每个窗口本地双人（P1 键鼠 + P2 手柄），共 4~6 个角色同时跟随
- **虚拟手柄 P2 操控** — 通过 ViGEmBus 虚拟 Xbox 360 手柄操控每个窗口的 P2（slot 1），无需物理手柄
- **内存坐标读取** — AOB 扫描定位 `GameStates` 全局指针，沿偏移链读取 Leader 和每个 Follower 的世界坐标（X, Y, Z）；通过 `AwakeEntities` 检索 P2 坐标
- **地形感知寻路** — 读取 AreaInstance 的可通行网格（~1200×N 格，约 10.87 单位/格），A* 寻路自动绕行障碍物
- **实体碰撞躲避** — 遍历 `AwakeEntities`（红黑树），400 单位半径内的怪物产生斥力场，避免撞怪
- **生命值监控** — 读取 Life 组件的 `VitalStruct`（当前/最大/比率），Leader 和 Follower 血量实时显示在 GUI
- **编队跟随** — 所有 Follower 按 Diamond / Line / V 型编队保持在 Leader 指定偏移位置
- **卡住自救（4 级递增）** — 静止检测 → 跳跃（手柄 A / 键盘 SPACE）→ 位移技能（手柄 X / 键盘 Q）→ 反向逃离（8 ticks）→ 冷却恢复
- **进程自动恢复** — 游戏崩溃/重启后自动重新扫描 PID 并重连，无需手动重启工具
- **双通道输入注入** — P1 通过 `PostMessage(WM_KEYDOWN/UP)` 注入键盘；P2 通过 ViGEmBus 虚拟手柄注入摇杆和按键
- **多实例启动器** — 通过 mutex 解除实现多开，自动管理桌面环境（关闭 Process Hacker、暂停 Wallpaper Engine）
- **实时 GUI 监控** — tkinter 界面：Leader 信息栏（位置 + 血量）+ Follower 状态表（账号、槽位、角色、位置、血量、卡住等级、当前输入）+ 嵌入式日志面板

## 原理

### 整体架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│  NavGui (tkinter)                                                        │
│  ┌──────────────┐  ┌───────────────────────────────┐  ┌──────────────┐  │
│  │ Leader 信息  │  │ Follower 状态表                │  │  日志面板    │  │
│  │ HP: 1234/2500│  │ #│Account│Slot│Role│HP│Stuck  │  │              │  │
│  └──────────────┘  └───────────────────────────────┘  └──────────────┘  │
│         ▲                           ▲                                    │
│         │          status_queue     │                                    │
│  ┌──────┴───────────────────────────┴────────────────────────────────┐  │
│  │  NavAgent (后台线程)                                               │  │
│  │  ┌─────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────┐ │  │
│  │  │ MemoryReader│ │Pathfinder│ │Input     │ │VGamepad  │ │Proc  │ │  │
│  │  │ • 坐标      │ │ • A*网格 │ │ Injector │ │ Manager  │ │Recov │ │  │
│  │  │ • 地形网格  │ │ • 绕障碍 │ │(键盘 P1) │ │(手柄 P2) │ │      │ │  │
│  │  │ • 实体列表  │ └──────────┘ └──────────┘ └──────────┘ └──────┘ │  │
│  │  │ • 生命值    │                                                  │  │
│  │  └──────┬──────┘                                                  │  │
│  └─────────┼────────────────────────────────────────────────────────┘  │
│            │ RPM + PostMessage + ViGEmBus                                │
│     ═══════╪═══════════════════════════════════════════════════════════  │
│            │                                                             │
│  ┌─────────▼─────────┐  ┌─────────▼─────────┐                           │
│  │ 账号 main         │  │ 账号 alt          │                           │
│  │ ┌───────────────┐ │  │ ┌───────────────┐ │                           │
│  │ │ P1 (slot 0)   │ │  │ │ P1 (slot 0)   │ │                           │
│  │ │ 键盘 · Leader │ │  │ │ 键盘 · Follwer│ │                           │
│  │ ├───────────────┤ │  │ ├───────────────┤ │                           │
│  │ │ P2 (slot 1)   │ │  │ │ P2 (slot 1)   │ │                           │
│  │ │ 手柄 · Follwer│ │  │ │ 手柄 · Follwer│ │                           │
│  │ └───────────────┘ │  │ └───────────────┘ │                           │
│  │   PoE2.exe        │  │   PoE2.exe        │                           │
│  └───────────────────┘  └───────────────────┘                           │
└──────────────────────────────────────────────────────────────────────────┘
```

### 1. 玩家模型

每个角色由一个 `Player` 对象表示，通过 `{账号ID}:{槽位号}` 唯一标识（如 `main:0`、`alt:1`）：

| 属性 | 说明 |
|------|------|
| `key` | 唯一标识，如 `"main:0"` |
| `account_id` | 所属账号 ID（`main`、`alt`） |
| `slot` | 槽位号（0 = P1 键鼠，1 = P2 手柄） |
| `role` | `leader`（唯一）或 `follower` |
| `input_method` | `keyboard`（slot 0）、`gamepad`（slot 1）、`none`（leader） |
| `pid` | 进程 ID |
| `hwnd` | 窗口句柄 |

Leader 的 `input_method = none`（不注入输入，由玩家手动控制）；P1 跟随者用键盘注入；P2 跟随者用虚拟手柄注入。

### 2. 内存坐标读取（MemoryReader）

通过 Win32 API `ReadProcessMemory` 读取 PoE2 进程内存。

**AOB 扫描入口**：程序启动时通过字节模式扫描游戏模块定位 `GameStates` 全局指针：

```
48 39 2D ?? ?? ?? ?? 0F 85 16 01 00 00
 │  │  │  └── 4-byte 位移            └── jnz 指令（唯一性）
 │  │  └── [rip+rel32] 寻址
 │  └── cmp
 └── REX.W 前缀（64位操作）
```

**坐标偏移链**：

```
GameStates → InGameState(+0x08)
           → AreaInstance(+0x290)
           ├── LocalPlayer(+0x5B8)              → Entity（P1）
           ├── AwakeEntities(+0x6D8)            → std::map（红黑树）
           │   └── Entity → ComponentLookUp → PlayerComponent  → P2
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

**P1 读取**：`LocalPlayer` 直接指向当前窗口 P1 的 Entity。

**P2 读取**：遍历 `AwakeEntities`，检查每个 Entity 的 `ComponentLookUp` 是否包含 `PlayerComponent`，以此找到同一窗口下的 P2 坐标。

每次 tick（默认 50ms）读取 Leader 和所有 Follower 的坐标、血量、周边实体、地形网格。

### 2.1 地形感知寻路

从 `AreaInstance.TerrainMetadata` 读取可通行网格：

- `walkable_data`（+0xD0）→ `byte[]` 数组，每字节含 2 个格子（高/低 nibble）
- `bytes_per_row`（+0x130）→ 每行字节数（621），即 1242 格/行
- 世界/网格比例约 10.87 单位/格

非零 nibble = 障碍物，零 = 可通行。将网格注入 `Pathfinder`，A* 自动绕行。

### 2.2 实体碰撞躲避

遍历 `AwakeEntities`（MSVC `std::map` 红黑树），读取 Leader 周边 400 单位半径内实体的世界坐标。在 WASD 方向计算中叠加斥力场（100 单位范围，150× 强度），Follower 自动绕开密集怪物群。

### 3. 编队系统

每个 Follower 从编队模板中获取自己相对于 Leader 的位置偏移：

| 编队类型 | 说明 | Follower 偏移 |
|---------|------|--------------|
| `diamond` | 菱形阵 | 正后方、右翼、左翼、后排左、后排右 |
| `line` | 一字长蛇 | 后方依次排开 |
| `v` | V 字阵 | 两翼展开 |

通过 `spacing` 参数控制位置间距（世界单位），每次 tick 计算 `formation_target = leader_pos + offset * spacing`。

### 4. 卡住自救（Anti-Stuck）

Follower 连续 N 个 tick 移动距离低于阈值时判定为卡住，进入递增自救：

| 等级 | 触发条件 | 键盘动作 | 手柄动作 |
|-----|---------|---------|---------|
| L0 | Normal | 正常跟随 | 正常跟随 |
| L1 | 静止 ≥ 10 ticks | SPACE（跳跃） | A 键 |
| L2 | 跳跃后仍静止 | Q（位移技能） | X 键 |
| L3 | 技能后仍静止 | 反向逃离 8 ticks → 30 ticks 冷却 | 反向逃离 8 ticks → 30 ticks 冷却 |

等级在恢复移动时自动归零。

### 5. 进程自动恢复

Leader 或 Follower 进程崩溃/重启时，连续 30 次 tick（约 1.5s）读取失败后触发恢复：

1. 关闭所有旧进程句柄，清空坐标/组件索引缓存
2. 重新扫描系统进程列表（`EnumProcesses`）
3. 按 HWND 重新匹配各 Player 的 PID（`GetWindowThreadProcessId`）
4. 重建 AOB 入口、ComponentLookUp 索引、地形网格
5. GUI 状态栏显示 "Reconnected." 或 "Recovery failed..."

### 6. 双通道输入注入

| 通道 | 适用角色 | 技术 | 原理 |
|------|---------|------|------|
| 键盘 | P1（slot 0） | `PostMessage(WM_KEYDOWN/UP)` | 向目标窗口消息队列注入按键 |
| 手柄 | P2（slot 1） | ViGEmBus 虚拟 Xbox 360 | 创建设备节点，写入 XUSB 报告 |

键盘通道使用 delta 差分法：每 tick 计算 `desired_keys - current_keys`，精确释放和按下按键。手柄通道通过 `vgamepad` 库操控虚拟 Xbox 360 控制器，支持左摇杆（WASD 方向）+ 按钮映射。

**按钮映射**：

| 动作 | 键盘 | 虚拟手柄 |
|------|------|---------|
| 跳跃 | SPACE | A |
| 技能 | Q | X |
| 交互 | LMB | A |
| 使用 | — | B |
| 血瓶 1 | 1 | LB |
| 血瓶 2 | 2 | RB |
| 血瓶 3 | 3 | D-Pad ↑ |
| 血瓶 4 | 4 | D-Pad ↓ |
| 血瓶 5 | 5 | D-Pad ← |

### 7. 多实例启动器

`launcher.py` 通过 mutex 解除实现 PoE2 多开：

1. 关闭可能干扰的桌面工具（Process Hacker、Wallpaper Engine）
2. 通过 `NtQuerySystemInformation` 枚举所有进程句柄，找到并关闭 PoE2 命名 mutex
3. 通过 Steam URL（`steam://rungameid/2694490`）或独立 exe 启动指定数量的实例
4. 配置每个实例的窗口标题和分辨率（通过 NVIDIA ProfileInspector）

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.10+
- PoE 2 客户端（Steam 或独立版）至少 2 个窗口
- ViGEmBus 驱动（[下载安装](https://github.com/nefarius/ViGEmBus/releases)）— 虚拟手柄支持
- 管理员权限（读取其他进程内存、操控虚拟手柄需要）

### 安装

```bash
git clone git@github.com:bpup/poe2-scripts.git
cd poe2-scripts

# 创建虚拟环境（推荐）
python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

### 游戏内设置

每个 PoE2 窗口中，P2 需要使用手柄操作。在游戏设置中将 P2 输入设备设为手柄：

1. 打开 PoE2 → 设置 → 输入
2. P2 玩家 → 输入设备 → **手柄**
3. 确保每个窗口的 P2 都已正确配置

### 配置

编辑 `config/nav-follow.yaml`：

```yaml
accounts:
  - id: main                          # 账号 ID（唯一）
    window_title: "Path of Exile 2"   # 窗口标题关键字
    characters:
      - slot: 0                       # P1（键鼠）
        role: leader                  # 唯一的 leader
      - slot: 1                       # P2（手柄）
        role: follower                # 跟随者
  - id: alt
    window_title: "Path of Exile 2"
    characters:
      - slot: 0
        role: follower
      - slot: 1
        role: follower

sampling:
  tick_ms: 50                         # 控制循环间隔（毫秒）

nav:
  behavior:
    formation:
      type: diamond                   # diamond | line | v
      spacing: 35.0                   # 编队间距（世界单位）
    anti_stuck:
      enabled: true
      distance_threshold: 2.0         # 判定卡住的移动距离
      stuck_ticks: 10                 # 卡住判定连续帧数
      jump_key: "SPACE"
      skill_key: "Q"
```

**配置说明**：
- 必须有且仅有一个 `role: leader`
- 每个账号 1~2 个角色（`slot: 0` 必需，`slot: 1` 可选）
- `slot: 0` → P1 键鼠操控；`slot: 1` → P2 虚拟手柄操控
- 账号数量 2~3 个

### 运行

```bash
python src/app.py
```

启动后：
1. 弹出窗口选择对话框 — 为每个账号选择对应的 PoE2 窗口
2. GUI 显示账号与槽位信息
3. 点击 **Start** 开始跟随

### 多开启动

```bash
python launcher.py
```

按 `config/nav-follow.yaml` 中的账号数量自动启动对应数量的 PoE2 实例。

## 项目结构

```
poe2_scripts/
├── config/
│   └── nav-follow.yaml              # 配置文件（账号、角色、偏移、编队、防卡）
├── src/
│   ├── app.py                       # 入口 — 窗口选择 + 启动 GUI
│   ├── common/
│   │   ├── config_loader.py         # YAML 配置解析 + Player/Account 数据类
│   │   ├── gui_log_handler.py       # 日志→tkinter 桥接（Queue + ScrolledText）
│   │   └── logger.py                # 结构化日志
│   ├── core/
│   │   ├── input_injector.py        # Win32 PostMessage 键盘注入
│   │   ├── memory_reader.py         # RPM + AOB + 偏移链 + 地形/实体/血量/P2 检测
│   │   ├── pathfinder.py            # A* 寻路 + 地形网格 + WASD 方向转换
│   │   ├── vgamepad_controller.py   # ViGEmBus 虚拟 Xbox 360 手柄管理器
│   │   └── window_registry.py       # 窗口扫描、绑定、健康检查
│   ├── follow/
│   │   └── nav_agent.py             # 主循环：坐标/血量读取→编队→寻路→避怪→按键/手柄→防卡→恢复
│   └── ui/
│       └── gui.py                   # tkinter 界面（账号/槽位选择、Leader/Follower 状态、日志）
├── launcher.py                      # 多实例启动器（mutex 解除 + Steam 启动）
├── .github/workflows/
│   └── build.yml                    # CI：Windows PyInstaller 打包 + Release 发布
├── pyinstaller.spec                 # PyInstaller 打包配置
└── requirements.txt
```

## 致谢

内存偏移参考 [POE2Radar/Poe2Offsets.cs](https://github.com/POE2Radar/POE2Radar/blob/master/Framework/Offsets/Poe2Offsets.cs)。

虚拟手柄基于 [ViGEmBus](https://github.com/nefarius/ViGEmBus) 驱动和 [vgamepad](https://github.com/yannbouteiller/vgamepad) Python 库。

## 免责声明

本项目仅用于学习和研究 Windows 进程内存读取技术。使用本工具可能违反 PoE 2 服务条款，请自行承担风险。
