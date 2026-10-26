using ExileCore2;
using ExileCore2.PoEMemory.Components;
using ExileCore2.PoEMemory.MemoryObjects;
using ExileCore2.Shared.Enums;
using ExileCore2.Shared.Helpers;
using System.Numerics;
using System.Diagnostics;

namespace AutoFollow.Core;

public enum FollowState
{
    Idle,
    Following,
    Attacking,
    EnteringPortal,
    Dead,
}

public class FollowCore
{
    private readonly GameController _gameController;
    private readonly Settings.AntiForegroundFollowSettings _settings;
    private readonly Random _rand;

    private DateTime _lastFollowTick = DateTime.MinValue;
    private DateTime _lastAttackTick = DateTime.MinValue;
    private DateTime _lastFlaskTick = DateTime.MinValue;
    private DateTime _lastPortalClick = DateTime.MinValue;
    private DateTime _lastStateChange = DateTime.UtcNow;

    private FollowState _state = FollowState.Idle;
    private int _leaderEntityId = -1;
    private Vector3 _lastLeaderPos;

    public FollowState State => _state;
    public Vector3 LastLeaderPos => _lastLeaderPos;
    public bool LeaderFound => _leaderEntityId >= 0;

    public FollowCore(
        GameController gameController,
        Settings.AntiForegroundFollowSettings settings)
    {
        _gameController = gameController;
        _settings = settings;
        _rand = new Random();

        _lastStateChange = DateTime.UtcNow;
    }

    public void Tick(IntPtr windowHandle)
    {
        var player = _gameController?.Game?.IngameState?.Data?.LocalPlayer;
        var entity = player?.GetComponent<ExileCore2.PoEMemory.Components.Life>();
        if (player == null || entity == null)
        {
            SetState(FollowState.Idle);
            return;
        }

        var localLife = player.GetComponent<Life>();
        if (localLife != null && localLife.CurHP <= 0)
        {
            SetState(FollowState.Dead);
            return;
        }

        // -- Detect leader in party --------------------------------------
        var leaderEntity = FindLeader();

        if (leaderEntity == null)
        {
            SetState(FollowState.Idle);
            return;
        }

        _leaderEntityId = (int)leaderEntity.Id;
        _lastLeaderPos = leaderEntity.Pos;

        var playerPos = player.Pos;
        var leaderWorldPos = leaderEntity.Pos;
        var distToLeader = Vector3.Distance(playerPos, leaderWorldPos);

        // -- Flask check ------------------------------------------------
        HandleFlask(localLife, windowHandle);

        // -- Portal check -----------------------------------------------
        if (_settings.AutoPortal && TryEnterPortal(playerPos, leaderWorldPos, windowHandle))
        {
            SetState(FollowState.EnteringPortal);
            return;
        }

        // -- Attack check (skip if leader is too far — prioritize follow)
        if (_settings.AttackNearby && distToLeader < 200f)
        {
            var enemyInRange = FindNearestEnemy(playerPos, _settings.AttackRange);
            if (enemyInRange)
            {
                SetState(FollowState.Attacking);
                HandleAttack(windowHandle);
                return;
            }
        }

        // -- Follow logic -----------------------------------------------
        if (distToLeader <= _settings.StopDistance)
        {
            SetState(FollowState.Idle);
            return;
        }

        SetState(FollowState.Following);

        var now = DateTime.UtcNow;
        if ((now - _lastFollowTick).TotalMilliseconds < _settings.UpdateIntervalMs)
            return;

        _lastFollowTick = now;

        var followTarget = CalculateFollowTarget(playerPos, leaderWorldPos, distToLeader);
        BackgroundInput.ClickWorldPos(windowHandle, followTarget, _gameController);
    }

    private Entity? FindLeader()
    {
        var party = _gameController?.Game?.IngameState?.Data?.LocalPlayer?.GetComponent<Player>();
        if (party == null) return null;

        var entities = _gameController?.Entities;
        if (entities == null) return null;

        var leaderName = _settings.LeaderName.Value;
        if (string.IsNullOrWhiteSpace(leaderName)) return null;

        foreach (var entity in entities)
        {
            if (entity == null) continue;

            var playerComp = entity.GetComponent<Player>();
            if (playerComp == null) continue;

            if (string.Equals(playerComp.PlayerName, leaderName,
                StringComparison.OrdinalIgnoreCase))
            {
                // Also check if entity is alive
                var life = entity.GetComponent<Life>();
                if (life == null || life.CurHP > 0)
                    return entity;
            }
        }

        return null;
    }

    private bool FindNearestEnemy(Vector3 playerPos, float range)
    {
        var entities = _gameController?.Entities;
        if (entities == null) return false;

        foreach (var entity in entities)
        {
            if (entity == null || !entity.IsHostile) continue;
            if (!entity.IsAlive) continue;

            var dist = Vector3.Distance(playerPos, entity.Pos);
            if (dist <= range) return true;
        }

        return false;
    }

    private Vector3 CalculateFollowTarget(Vector3 playerPos, Vector3 leaderPos, float dist)
    {
        var dir = Vector3.Normalize(leaderPos - playerPos);
        var targetDist = dist - _settings.StopDistance * 0.5f;
        var target = playerPos + dir * targetDist;

        // Add human-like jitter
        var jitter = _settings.ClickJitter;
        if (jitter > 0)
        {
            var angle = (float)(_rand.NextDouble() * Math.PI * 2);
            var offset = (float)(_rand.NextDouble() * jitter);
            target.X += (float)Math.Cos(angle) * offset;
            target.Y += (float)Math.Sin(angle) * offset;
        }

        return target;
    }

    private void HandleFlask(Life? life, IntPtr hwnd)
    {
        if (!_settings.AutoFlask) return;

        var now = DateTime.UtcNow;
        if ((now - _lastFlaskTick).TotalMilliseconds < 500) return;

        if (life == null) return;

        var hpRatio = life.HPPercentage / 100f;
        var manaRatio = life.MPPercentage / 100f;

        if (hpRatio < _settings.LifeFlaskThreshold / 100f)
        {
            BackgroundInput.SendKey(hwnd, System.Windows.Forms.Keys.D1);
            _lastFlaskTick = now;
        }
        else if (manaRatio < _settings.ManaFlaskThreshold / 100f)
        {
            BackgroundInput.SendKey(hwnd, System.Windows.Forms.Keys.D2);
            _lastFlaskTick = now;
        }
    }

    private void HandleAttack(IntPtr hwnd)
    {
        var now = DateTime.UtcNow;
        if ((now - _lastAttackTick).TotalMilliseconds < _settings.AttackIntervalMs)
            return;

        _lastAttackTick = now;
        BackgroundInput.SendKey(hwnd, _settings.AttackSkillKey.Value.Key);
    }

    private bool TryEnterPortal(Vector3 playerPos, Vector3 leaderPos, IntPtr hwnd)
    {
        // Detect nearby area transition objects near the leader
        var entities = _gameController?.Entities;
        if (entities == null) return false;

        foreach (var entity in entities)
        {
            if (entity == null || !entity.IsTargetable) continue;

            var path = entity.Path?.ToLowerInvariant() ?? "";
            var isPortal = path.Contains("townportal") ||
                           path.Contains("areatransition") ||
                           path.Contains("portal");

            if (!isPortal) continue;

            var distToPortal = Vector3.Distance(playerPos, entity.Pos);
            if (distToPortal > _settings.PortalRadius) continue;

            var now = DateTime.UtcNow;
            if ((now - _lastPortalClick).TotalMilliseconds < 1500) return false;

            _lastPortalClick = now;

            BackgroundInput.ClickWorldPos(hwnd, entity.Pos, _gameController);
            return true;
        }

        return false;
    }

    private void SetState(FollowState newState)
    {
        if (_state != newState)
        {
            _state = newState;
            _lastStateChange = DateTime.UtcNow;
        }
    }
}
