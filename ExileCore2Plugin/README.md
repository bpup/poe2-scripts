# AutoFollow — Background-Window ExileCore2 Plugin

基于 [Curvu/Copilot](https://github.com/Curvu/Copilot) 思路重写的自动跟随 ExileCore2 插件。**核心改动：去掉所有前台窗口检查，支持后台多窗口同时运行。**

## 原理

```
队长窗口 (手动操作)
   │
   ▼
PoE2 服务器 ──同步队员位置──→ 跟随窗口 1: ExileCore2 + AutoFollow
                             跟随窗口 2: ExileCore2 + AutoFollow
                             跟随窗口 3: ExileCore2 + AutoFollow
```

每个跟随窗口：
1. 通过 `PostMessage` 在自己的游戏窗口上模拟鼠标点击
2. 游戏内置寻路系统自动导航到点击位置
3. 不需要前景窗口，不需要 SetCursorPos，不需要 SendInput

## 系统要求

- Windows 10/11 x64
- .NET 8 SDK x64 ([下载](https://dotnet.microsoft.com/download/dotnet/8.0))
- [ExileCore2](https://github.com/exCore2/ExileCore2) 已编译（Loader 目录在 ExileCore2 同级）
- DirectX Runtime + VC 2015 Redistributable
- 3 个 PoE2 窗口（每个需要独立账号 + 解除 PoERunMutexB）

## 编译

```powershell
cd ExileCore2Plugin
dotnet build -c Release
```

输出: `ExileCore2Plugin/bin/Release/net8.0-windows/AutoFollow.dll`

## 安装

1. 将 `AutoFollow.dll` 放到 ExileCore2 的 `Plugins/` 目录
2. 启动 ExileCore2 Loader → 选择对应的 PoE2 进程 PID
3. 按 F12 打开 ExileCore2 覆盖层 → 配置 AutoFollow

## 配置（每个跟随窗口独立配置）

在 ImGui 覆盖层中设置：

### 必备
| 设置 | 说明 |
|------|------|
| **Leader Name** | 队长角色名（英文字符） |
| **Enable** | 开关跟随 |

### 跟随行为
| 设置 | 默认值 | 说明 |
|------|--------|------|
| Follow Distance | 35 | 离队长多远开始移动（格子单位） |
| Stop Distance | 8 | 移动到多近停下 |
| Click Jitter | 5 | 鼠标点击随机偏移（防检测） |
| Update Interval | 200ms | 多久刷新一次跟随目标 |

### 战斗
| 设置 | 默认值 |
|------|--------|
| Attack Nearby | ON |
| Attack Range | 60 |
| Attack Skill Key | Q |
| Attack Interval | 800ms |

### 药水
| 设置 | 默认值 |
|------|--------|
| Auto Flask | ON |
| Life阈值 | 50% |
| Mana阈值 | 30% |

### 传送门
| 设置 | 默认值 |
|------|--------|
| Auto Enter Portal | ON |

### 配置持久化
- 每个 ExileCore2 实例的配置独立存储
- 恢复插件时自动读取 `LeaderName` 最后设置的值

## 使用步骤

### 启动前

1. 关闭所有 PoE2 窗口
2. 准备 3 个独立账号（每个账号 2 角色，共 6 角色）

### 启动 3 个 PoE2 窗口

```powershell
# 1. 正常启动 PoE2 #1 → 登账号1 → 选队长角色
# 2. 正常（或通过 CloseHandle 启动 PoE2 #2）→ 登账号2 → 选跟随角色
# 3. 正常（或通过 CloseHandle 启动 PoE2 #3）→ 登账号3 → 选跟随角色
```

> 多窗口需解除 PoERunMutexB 互斥锁。方法：Process Explorer → 选择 PoE2 进程 → 找 `\BaseNamedObjects\PoERunMutexB` → CloseHandle

### 启动 ExileCore2

```powershell
# 每个窗口独立运行一个 Loader
# Loader 启动时选择对应 PoE2 进程的 PID
# 按 F12 → 打开 AutoFollow 面板 → 设置 LeaderName
```

### 配置跟随

每个跟随窗口（窗口 2、窗口 3 的 ExileCore2）：
1. F12 → 找到 AutoFollow 面板
2. 设置 `LeaderName` 为队长的角色名
3. Enable = ON
4. 队长移动时，跟随角色自动通过鼠标点击路径跟随

### 窗口管理技巧

- 使用 Windows 虚拟桌面（Win+Tab）分隔窗口
- 或使用 [Multi-Account Launcher](https://www.ownedcore.com/forums/mmo/path-of-exile/poe-bots-programs/1106895-multi-account-launcher-path-of-exile-1-2-run-dozens-of-windows-one-pc.html) 管理多窗口布局

## 已知限制

1. **鼠标点击式跟随**：通过屏幕点击触发游戏内置寻路，不是 WASD 键控移动。点击速度受 `UpdateInterval` 限制。
2. **WASD 不支持后台**：PoE2 使用 DirectInput 读取键盘状态，PostMessage 的 WM_KEYDOWN 对 WASD 无效（但技能键有效）。
3. **无跨窗口 IPC**：每个窗口独立运行，通过 PoE2 服务器同步队员位置。
4. **仅测试过 Standalone/Steam 版**：Epic/Kakao 版未测试。

## 风险提示

- 自动跟随属于最低风险的自动化类型（移动 + 点击 ≈ 人类行为）
- ExileCore2 框架本身多年无确认封号报告
- 但任何自动化都有封号风险，建议用非大号账号
- 不要在死亡后自动出图（Copilot 有因这个行为被封的案例）

## 项目结构

```
ExileCore2Plugin/
├── AutoFollow.csproj                     # .NET 8 项目文件
├── AntiForegroundFollowPlugin.cs         # 插件入口（继承 BaseSettingsPlugin）
├── Core/
│   ├── FollowCore.cs                     # 跟随逻辑：队长检测、寻路、攻击、药水
│   └── BackgroundInput.cs                # 后台 PostMessage 输入注入
├── Settings/
│   └── AntiForegroundFollowSettings.cs   # 所有可热重载设置
└── README.md
```

## License

MIT — 基于 Curvu/Copilot 的思路，独立重写。
