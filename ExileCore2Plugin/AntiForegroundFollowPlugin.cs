using ExileCore2;
using ExileCore2.PoEMemory.Components;
using ExileCore2.Shared.Enums;
using ImGuiNET;
using AutoFollow.Core;
using AutoFollow.Settings;

namespace AutoFollow;

public class AntiForegroundFollowPlugin : BaseSettingsPlugin<AntiForegroundFollowSettings>
{
    private FollowCore? _followCore;
    private IntPtr _windowHandle = IntPtr.Zero;
    private bool _pluginReady;

    public override bool Initialise()
    {
        Name = "AutoFollow (No Foreground)";

        // Resolve window handle from the game process
        var gameProcess = GameController?.Window?.Handle;
        _windowHandle = gameProcess ?? IntPtr.Zero;

        if (_windowHandle == IntPtr.Zero)
        {
            LogError("Could not find PoE2 window handle. Is the game running?", 5);
            return false;
        }

        // Auto-initialize leader name from party if left blank
        if (string.IsNullOrWhiteSpace(Settings.LeaderName))
        {
            var playerName = GameController?.Game?.IngameState?.Data?.LocalPlayer
                ?.GetComponent<Player>()?.PlayerName;
            if (!string.IsNullOrEmpty(playerName))
            {
                Settings.LeaderName.Value = playerName;
                LogMsg($"Auto-detected local player '{playerName}' as potential leader. "
                     + $"Change in settings if you are a follower.", 5f);
            }
        }

        _followCore = new FollowCore(GameController, Settings);
        _pluginReady = true;

        LogMsg("AutoFollow initialized. "
             + "Work on background windows. F12 to toggle overlay.", 5f);

        return true;
    }

    public override void Render()
    {
        if (!_pluginReady) return;
        if (_followCore == null) return;

        if (!Settings.Enable)
        {
            ImGui.TextDisabled("Plugin disabled — toggle Enable in settings.");
            return;
        }

        if (_windowHandle == IntPtr.Zero)
        {
            _windowHandle = GameController?.Window?.Handle ?? IntPtr.Zero;
            if (_windowHandle == IntPtr.Zero)
            {
                ImGui.TextColored(new System.Numerics.Vector4(1, 0.3f, 0.3f, 1),
                    "No window handle. Reload plugin.");
                return;
            }
        }

        // -- Status display ----------------------------------------------
        var state = _followCore.State;
        var stateColor = state switch
        {
            FollowState.Following => new System.Numerics.Vector4(0.3f, 1, 0.3f, 1),
            FollowState.Attacking => new System.Numerics.Vector4(1, 0.6f, 0.2f, 1),
            FollowState.Idle => new System.Numerics.Vector4(0.5f, 0.5f, 0.5f, 1),
            FollowState.EnteringPortal => new System.Numerics.Vector4(0.3f, 0.5f, 1, 1),
            FollowState.Dead => new System.Numerics.Vector4(1, 0.2f, 0.2f, 1),
            _ => new System.Numerics.Vector4(1, 1, 1, 1),
        };

        ImGui.Text("State: ");
        ImGui.SameLine();
        ImGui.TextColored(stateColor, state.ToString());

        if (_followCore.LeaderFound)
        {
            ImGui.Text($"Leader: {Settings.LeaderName.Value}");
            var player = GameController?.Game?.IngameState?.Data?.LocalPlayer;
            if (player != null)
            {
                var dist = SharpDX.Vector2.Distance(player.Pos, _followCore.LastLeaderPos);
                ImGui.Text($"Distance: {dist:F0} units");
            }
        }
        else
        {
            ImGui.TextColored(new System.Numerics.Vector4(1, 0.5f, 0, 1),
                $"Searching for leader: '{Settings.LeaderName.Value}'...");
        }

        // -- Debug overlay in game world ---------------------------------
        if (Settings.ShowDebug && _followCore.LeaderFound)
        {
            var camera = GameController?.Game?.IngameState?.Camera;
            if (camera != null)
            {
                var screenPos = camera.WorldToScreen(_followCore.LastLeaderPos);
                if (screenPos != SharpDX.Vector2.Zero)
                {
                    var drawList = ImGui.GetBackgroundDrawList();
                    var leaderScreen = new System.Numerics.Vector2(screenPos.X, screenPos.Y);
                    drawList.AddCircleFilled(leaderScreen, 8f,
                        ImGui.ColorConvertFloat4ToU32(
                            new System.Numerics.Vector4(0, 1, 0, 0.8f)));
                    drawList.AddText(leaderScreen + new System.Numerics.Vector2(10, -20),
                        ImGui.ColorConvertFloat4ToU32(
                            new System.Numerics.Vector4(0, 1, 0, 1)),
                        Settings.LeaderName.Value);
                }
            }
        }
    }

    public override void Tick()
    {
        if (!_pluginReady) return;
        if (_followCore == null) return;
        if (!Settings.Enable) return;
        if (_windowHandle == IntPtr.Zero) return;

        _followCore.Tick(_windowHandle);
    }
}
