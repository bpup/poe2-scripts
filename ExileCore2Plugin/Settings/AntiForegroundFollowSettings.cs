using ExileCore2.Shared.Attributes;
using ExileCore2.Shared.Interfaces;
using ExileCore2.Shared.Nodes;

namespace AutoFollow.Settings;

/// <summary>
/// Plugin settings — all hot-reloadable from the ImGui overlay.
/// Editor never loses focus on ANY window (no foreground check).
/// </summary>
public class AntiForegroundFollowSettings : ISettings
{
    // ── General ─────────────────────────────────────────────────────────
    public ToggleNode Enable { get; set; } = new ToggleNode(true);

    [Menu("Leader", "Party member name your followers should track")]
    public TextNode LeaderName { get; set; } = new TextNode("");

    // ── Follow Behavior ─────────────────────────────────────────────────
    [Menu("Follow Distance", "Max grid units from leader before moving", 18, 200)]
    public RangeNode<float> FollowDistance { get; set; } = new RangeNode<float>(35f, 5f, 120f);

    [Menu("Stop Distance", "How close to get before releasing input", 10, 100)]
    public RangeNode<float> StopDistance { get; set; } = new RangeNode<float>(8f, 2f, 30f);

    [Menu("Click Radius", "Random offset added to click target to look human", 0, 20)]
    public RangeNode<float> ClickJitter { get; set; } = new RangeNode<float>(5f, 0f, 20f);

    [Menu("Update Interval (ms)", "How often to recalculate the follow target", 50, 500)]
    public RangeNode<int> UpdateIntervalMs { get; set; } = new RangeNode<int>(200, 50, 500);

    // ── Combat ──────────────────────────────────────────────────────────
    [Menu("Attack Nearby", "Use skill when enemies are in range")]
    public ToggleNode AttackNearby { get; set; } = new ToggleNode(true);

    [Menu("Attack Range", "World units — enemies closer than this trigger attack", 10, 120)]
    public RangeNode<float> AttackRange { get; set; } = new RangeNode<float>(60f, 10f, 120f);

    [Menu("Attack Skill Key", "Keyboard key for your main attack skill")]
    public HotkeyNodeV2 AttackSkillKey { get; set; } = new HotkeyNodeV2(System.Windows.Forms.Keys.Q);

    [Menu("Attack Interval (ms)", "Min time between skill uses", 200, 3000)]
    public RangeNode<int> AttackIntervalMs { get; set; } = new RangeNode<int>(800, 200, 3000);

    // ── Flask ───────────────────────────────────────────────────────────
    [Menu("Auto Flask", "Use life/mana flasks when low")]
    public ToggleNode AutoFlask { get; set; } = new ToggleNode(true);

    [Menu("Life Flask Threshold (%)", 10, 90)]
    public RangeNode<float> LifeFlaskThreshold { get; set; } = new RangeNode<float>(50f, 10f, 90f);

    [Menu("Mana Flask Threshold (%)", 10, 90)]
    public RangeNode<float> ManaFlaskThreshold { get; set; } = new RangeNode<float>(30f, 10f, 90f);

    // ── Area Transition ─────────────────────────────────────────────────
    [Menu("Auto Enter Portal", "Click portals/area transitions near leader")]
    public ToggleNode AutoPortal { get; set; } = new ToggleNode(true);

    [Menu("Portal Detection Radius", 10, 200)]
    public RangeNode<float> PortalRadius { get; set; } = new RangeNode<float>(100f, 10f, 200f);

    // ── Debug ───────────────────────────────────────────────────────────
    [Menu("Show Debug Overlay", "Draw follow target, distances on screen")]
    public ToggleNode ShowDebug { get; set; } = new ToggleNode(false);
}
