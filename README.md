# PoE2 Auto-Follow

PoE 2 多账号自动跟随工具集 — 支持后台多窗口同时运行，无需窗口焦点。

## 两种跟随方案

| 方案 | 引擎 | 输入方式 | 优势 |
|------|------|---------|------|
| **ExileCore2 插件**（推荐） | C# / ExileCore2 | 后台鼠标点击 | 简单可靠，不需手柄，支持后台 |
| Python 独立版 | Python / Win32 RPM | WASD 键盘 + 虚拟手柄 | 地形寻路，实体避怪，v 型编队 |

## ExileCore2 插件（推荐）

基于 [Curvu/Copilot](https://github.com/Curvu/Copilot) 思路重写。去掉所有前台窗口检查，通过 `PostMessage` 在后台窗口模拟鼠标点击，利用游戏内置寻路自动跟随。

```
队长窗口 (手动操作)
   │
   ▼
PoE2 服务器 ──同步队员位置──→ Follower 窗口 1: ExileCore2 + AutoFollow
                             Follower 窗口 2: ExileCore2 + AutoFollow
```

### 功能

- **后台跟随** — 不需要窗口焦点，3 个 PoE2 窗口可同时运行
- **队长检测** — 通过角色名自动识别队长，读取其世界坐标
- **自动攻击** — 检测附近敌对实体，自动释放技能
- **自动血瓶/魔瓶** — HP/MP 低于阈值自动喝药
- **自动进门** — 检测附近传送门/区域入口自动点击
- **ImGui 覆盖层** — 实时状态、距离显示、队长位置标记

详细文档：[ExileCore2Plugin/README.md](ExileCore2Plugin/README.md)

### 系统要求

- Windows 10/11 x64
- .NET 8 SDK x64
- [ExileCore2](https://github.com/exCore2/ExileCore2) 已编译
- 2~3 个 PoE2 窗口（每个需独立账号）

### 编译

```powershell
cd ExileCore2Plugin
dotnet build -c Release
# 输出: bin/Release/net8.0-windows/AutoFollow.dll
```

将 `AutoFollow.dll` 放到 ExileCore2 的 `Plugins/` 目录，启动 Loader 选择 PoE2 进程 PID，F12 打开覆盖层配置。

### CI 自动构建

每次 push 到 main 分支自动编译。下载最新 DLL：[Actions](https://github.com/bpup/poe2-scripts/actions)

---

## 一键启动（PoE2 多窗口 + ExileCore2）

双击 `one-click.bat` 自动完成全部启动流程。

### 配置

编辑 `one-click-config.ps1`：

```powershell
$WINDOWS = 3               # PoE2 窗口数量
$POE2_PATH = ""            # PoE2.exe 路径（留空自动检测）
$EXILECORE2_DIR = "D:\ExileCore2"  # ExileCore2 目录（可选）
$LOGIN_WAIT = 90           # 每窗口登录等待秒数
```

### 启动流程

1. **Phase 1** — 关闭所有 PoE2 + Loader 进程
2. **Phase 2** — 依次启动 N 个 PoE2 窗口（自动解除 PoERunMutexB）
3. **Phase 3** — 为每个 follower 窗口复制 ExileCore2 目录并启动 Loader

### 手动解除互斥锁

如果一键启动失败，手动解除 PoERunMutexB：

```
handle64.exe -a -p <PoE2_PID>     # 找到 MutantEx 行
handle64.exe -c <handle_id> -p <PoE2_PID> -y
```

---

## Python 独立版

原有的内存读取 + A* 寻路 + 虚拟手柄方案，适合需要高级控制的场景。

### 环境要求

- Windows 10/11
- Python 3.10+
- ViGEmBus 驱动（[下载](https://github.com/nefarius/ViGEmBus/releases)）
- 管理员权限

### 安装

```bash
git clone git@github.com:bpup/poe2-scripts.git
cd poe2-scripts
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 配置

编辑 `config/nav-follow.yaml`：

```yaml
accounts:
  - id: main
    window_title: "Path of Exile 2"
    characters:
      - slot: 0    # P1 键盘
        role: leader
      - slot: 1    # P2 手柄
        role: follower
  - id: alt
    window_title: "Path of Exile 2"
    characters:
      - slot: 0
        role: follower
      - slot: 1
        role: follower

sampling:
  tick_ms: 50

nav:
  behavior:
    formation:
      type: diamond        # diamond | line | v
      spacing: 35.0
    anti_stuck:
      enabled: true
      distance_threshold: 2.0
      stuck_ticks: 10
      jump_key: "SPACE"
      skill_key: "Q"
```

### 运行

```bash
python src/app.py
# 或
python launcher.py    # 自动启动多窗口
```

---

## 项目结构

```
poe2_scripts/
├── one-click.bat                     # 一键启动入口（双击运行）
├── one-click-config.ps1              # 一键启动配置
│
├── scripts/
│   ├── one-click.ps1                 # 一键启动主脚本（3 阶段）
│   ├── launch-poe.ps1                # 交互式 PoE2 多窗口启动器
│   ├── setup.bat                     # 发布包安装脚本
│   └── build.ps1                     # ExileCore2 完整构建
│
├── ExileCore2Plugin/                 # ExileCore2 C# 插件（推荐方案）
│   ├── AutoFollow.csproj             # .NET 8 项目
│   ├── AntiForegroundFollowPlugin.cs # 插件入口
│   ├── Core/
│   │   ├── FollowCore.cs             # 跟随逻辑：队长检测、攻击、药水、传送门
│   │   └── BackgroundInput.cs        # 后台 PostMessage 输入注入
│   ├── Settings/
│   │   └── AntiForegroundFollowSettings.cs
│   └── README.md
│
├── src/                              # Python 独立版
│   ├── app.py                        # 入口 — 窗口选择 + GUI
│   ├── common/
│   │   ├── config_loader.py          # YAML 配置解析
│   │   ├── gui_log_handler.py        # 日志 → tkinter
│   │   └── logger.py                 # 结构化日志
│   ├── core/
│   │   ├── memory_reader.py          # RPM + AOB + 偏移链
│   │   ├── pathfinder.py             # A* 寻路 + 地形网格
│   │   ├── input_injector.py         # PostMessage 键盘注入
│   │   ├── vgamepad_controller.py    # ViGEmBus 虚拟手柄
│   │   └── window_registry.py        # 窗口扫描/绑定
│   ├── follow/
│   │   └── nav_agent.py              # 主循环：读取→编队→寻路→避怪→输入→防卡
│   └── ui/
│       └── gui.py                    # tkinter 监控界面
│
├── launcher.py                       # Python 多实例启动器
├── config/
│   └── nav-follow.yaml              # Python 版配置文件
│
├── .github/workflows/
│   └── build.yml                     # CI：编译 C# 插件 + 打包发布
│
├── requirements.txt
└── pyinstaller.spec
```

## 致谢

- ExileCore2 插件基于 [Curvu/Copilot](https://github.com/Curvu/Copilot)
- Python 版内存偏移参考 [POE2Radar/Poe2Offsets.cs](https://github.com/POE2Radar/POE2Radar/blob/master/Framework/Offsets/Poe2Offsets.cs)
- 虚拟手柄基于 [ViGEmBus](https://github.com/nefarius/ViGEmBus) 和 [vgamepad](https://github.com/yannbouteiller/vgamepad)

## 免责声明

本项目仅用于学习研究。使用可能违反 PoE 2 服务条款，请自行承担风险。
