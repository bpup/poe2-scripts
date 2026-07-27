"""NavAgent: the core auto-follow engine for multi-account local co-op.

Orchestrates:
  1. Memory reading — leader position (P1), follower positions (P1+P2 via
     awake entity scan), terrain grids, health data
  2. Pathfinding — A* over AreaInstance walkable grid → WASD direction
  3. Formation — maintains diamond/line/V offset relative to leader
  4. Entity avoidance — repulsion field from nearby awake monsters
  5. Dual-channel input — PostMessage keyboard for P1 + ViGEmBus virtual
     gamepad for P2 (per-account, per-slot routing)
  6. Anti-stuck — 4-level escalation: jump → skill → reverse escape → cooldown
  7. Process recovery — auto-reconnect on PoE2 crash/restart

Architecture:
    PartyConfig → [Player] × N accounts × 2 slots
        ├── role=leader    → read-only (manual control)
        ├── slot=0,P1      → keyboard injection
        └── slot=1,P2      → virtual gamepad injection (VGamepadManager)

Runs on a background thread; communicates with NavGui via status_queue.
"""

from __future__ import annotations

import math
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from src.common.config_loader import PartyConfig
from src.common.logger import get_logger
from src.core.behavior_randomizer import jitter, jitter_up, maybe, position_jitter, reseed
from src.core.input_injector import InputInjector
from src.core.memory_reader import (
    CharacterInfo,
    EntityPosition,
    GameProcess,
    HealthData,
    MemoryReader,
    TerrainData,
)
from src.core.pathfinder import Pathfinder
from src.core.vgamepad_controller import VGamepadManager
from src.core.window_registry import WindowRegistry

logger = get_logger(__name__)

TICK_INTERVAL = 0.05
STUCK_THRESHOLD = 5.0
STUCK_STEPS = 5
_CONFIG_RELOAD_INTERVAL = 50  # ticks between config hot-reload checks (~2.5 s)
UNSTUCK_VECTORS = [
    (1.0, 0.0),
    (-1.0, 0.0),
    (0.0, -1.0),
    (0.0, 1.0),
]

_KEY_TO_BTN: Dict[str, str] = {
    "SPACE": "A", "Q": "X", "LMB": "A",
    "1": "LB", "2": "RB", "3": "DPAD_UP", "4": "DPAD_DOWN", "5": "DPAD_LEFT",
}

_FM_DIAMOND = [(0, -1), (1, 0), (-1, 0), (-1, -2), (1, -2)]
_FM_LINE = [(0, -1), (0, -2), (0, -3), (0, -4), (0, -5)]
_FM_V = [(-1, -1), (1, -1), (-2, -2), (2, -2), (-3, -3)]

_FM = {"diamond": _FM_DIAMOND, "line": _FM_LINE, "v": _FM_V}


@dataclass
class Player:
    """Runtime state for one character in the follow system.

    key: unique id like "main:0" (account_id + ":" + slot)
    account_id: owning account ("main", "alt")
    slot: 0 = P1 keyboard, 1 = P2 gamepad
    role: "leader" (manual) or "follower" (auto-controlled)
    input_method: "keyboard", "gamepad", or "none" (leader)
    pid / hwnd: Win32 process ID and window handle
    char_info: last known character name/class/level
    last_pos: previous world position (for stuck detection)
    stuck_counter/level/reverse_remaining: anti-stuck state machine
    """
    key: str
    account_id: str
    slot: int
    role: str
    input_method: str
    pid: int
    hwnd: int
    char_info: Optional[CharacterInfo] = None
    last_pos: Optional[EntityPosition] = None
    stuck_counter: int = 0
    stuck_level: int = 0
    reverse_remaining: int = 0
    last_flask: float = 0.0
    last_click: float = 0.0
    dead: bool = False


class NavAgent:
    def __init__(
        self,
        config: PartyConfig,
        hwnds: List[int],
        status_queue: Optional[queue.Queue[dict]] = None,
        config_path: Optional[str] = None,
    ) -> None:
        nav_config = config.nav or {}
        self._reader = MemoryReader(nav_config)
        self._injector = InputInjector()
        self._vgamepad = VGamepadManager()
        self._pathfinder = Pathfinder()
        self._registry = WindowRegistry()

        self._terrain_loaded = False
        self._nearby_entities: Dict[int, List[EntityPosition]] = {}
        self._status_queue = status_queue

        self._players: Dict[str, Player] = {}
        self._leader_key: str = ""

        self._terrain_data: Optional[TerrainData] = None
        self._terrain_dirty: bool = False

        behavior = nav_config.get("behavior", {})
        self._formation = behavior.get("formation", {})
        self._anti_stuck = behavior.get("anti_stuck", {})

        portal_cfg = nav_config.get("portal", {})
        self._portal_enabled = portal_cfg.get("enabled", True)
        self._portal_keywords = portal_cfg.get("entity_path_keywords", ["portal"])
        self._portal_interact_radius = float(portal_cfg.get("interact_radius", 4.0))
        self._portal_detection_radius = float(portal_cfg.get("detection_radius", 100.0))
        self._portal_click_delay = float(portal_cfg.get("click_repeat_delay", 1.5))
        self._portal_interact_key = portal_cfg.get("interact_key", "LMB")

        flask_cfg = nav_config.get("flask", {})
        self._flask_enabled = flask_cfg.get("enabled", True)
        self._flask_hp_threshold = float(flask_cfg.get("hp_threshold", 0.50))
        self._flask_mana_threshold = float(flask_cfg.get("mana_threshold", 0.30))
        self._flask_cooldown = float(flask_cfg.get("flask_cooldown", 0.5))
        self._flask_keys: List[str] = flask_cfg.get("flask_keys", ["1", "2", "3", "4", "5"])

        loot_cfg = nav_config.get("auto_loot", {})
        self._loot_enabled = loot_cfg.get("enabled", True)
        self._loot_keywords: List[str] = loot_cfg.get("entity_path_keywords", ["Metadata/Items"])
        self._loot_pickup_radius = float(loot_cfg.get("pickup_radius", 8.0))
        self._loot_click_delay = float(loot_cfg.get("click_delay", 0.3))

        self._death_enabled = nav_config.get("death", {}).get("enabled", True)

        self._consecutive_failures: int = 0
        self._max_consecutive_failures: int = 30

        # Per-follower pause (set from GUI thread; GIL makes set ops safe)
        self._paused_keys: Set[str] = set()

        # Area transition detection — terrain reloads on area_instance pointer change
        self._last_area_ptr: Optional[int] = None

        # Config hot-reload
        self._config_path: Optional[str] = config_path
        self._config_mtime: float = 0.0
        self._reload_tick_counter: int = 0

        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._portal_position: Optional[Tuple[float, float]] = None
        self._portal_entered: Set[str] = set()

        self._follower_indices: Dict[str, int] = {}
        self._vgamepad_ids: Dict[str, int] = {}
        self._held_keys: Dict[str, Set[str]] = {}
        self._build_player_map(config, hwnds)

    # -- Player map construction -----------------------------------------

    def _build_player_map(self, config: PartyConfig, hwnds: List[int]) -> None:
        all_pids = self._reader.find_poe2_processes()
        if not all_pids:
            logger.warning("No PoE2 processes found.")
            return

        hwnd_pids: Dict[int, int] = {}
        for hwnd in hwnds:
            try:
                import win32process
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid in all_pids:
                    hwnd_pids[hwnd] = pid
            except Exception:
                pass

        sorted_pids = sorted(set(hwnd_pids.values()))
        pid_to_hwnd = {pid: hwnd for hwnd, pid in hwnd_pids.items()}

        for idx, (account, pid) in enumerate(zip(config.accounts, sorted_pids)):
            hwnd = pid_to_hwnd.get(pid, 0)
            for char in account.characters:
                pkey = f"{account.id}:{char.slot}"
                player = Player(
                    key=pkey, account_id=account.id, slot=char.slot,
                    role=char.role, input_method=char.input_method,
                    pid=pid, hwnd=hwnd,
                )
                self._players[pkey] = player
                if char.role == "leader":
                    self._leader_key = pkey

        if not self._leader_key:
            raise RuntimeError("No leader Player found in config.")

        follower_keys = [k for k, p in self._players.items() if p.role == "follower"]
        for idx, fkey in enumerate(follower_keys):
            self._follower_indices[fkey] = idx

        for player in self._players.values():
            if player.input_method == "gamepad" and player.pid != 0:
                cid = self._vgamepad.create()
                self._vgamepad_ids[player.key] = cid
                logger.info("VGamepad cid=%d for %s", cid, player.key)

    # -- Lifecycle -------------------------------------------------------

    def start(self) -> None:
        self._running = True
        reseed()

        self._portal_position = None
        self._portal_entered.clear()
        self._held_keys.clear()
        for p in self._players.values():
            p.last_click = 0.0
            p.last_flask = 0.0
            p.dead = False
            p.stuck_counter = 0
            p.stuck_level = 0
            p.reverse_remaining = 0
        self._last_area_ptr = None
        self._paused_keys: Set[str] = set()
        self._reload_tick_counter = 0
        if self._config_path:
            try:
                self._config_mtime = os.path.getmtime(self._config_path)
            except OSError:
                self._config_mtime = 0.0

        leader = self._players.get(self._leader_key)
        if leader is None or leader.pid == 0:
            logger.error("Leader PID not found.")
            self._running = False
            return

        followers = [p for p in self._players.values()
                     if p.role == "follower" and p.pid != 0]
        if not followers:
            logger.error("No follower PIDs found.")
            self._running = False
            return

        logger.info("NavAgent started: leader=%s, %d followers.",
                     self._leader_key, len(followers))
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._emit_state("Stopped.")
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._emergency_stop()
        self._reader.close_all()

    # -- Main loop -------------------------------------------------------

    def _run(self) -> None:
        try:
            while self._running:
                self._tick()
                time.sleep(jitter(TICK_INTERVAL, 0.25))
        except KeyboardInterrupt:
            logger.info("NavAgent interrupted.")
        finally:
            self._emergency_stop()
            self._reader.close_all()
            self._emit_state("Disconnected.")

    def _tick(self) -> None:
        leader = self._players.get(self._leader_key)
        if leader is None:
            return

        leader_proc = self._reader.open_process(leader.pid)
        if leader_proc is None:
            self._handle_read_failure()
            return

        result = self._reader.read_local_player_position(leader_proc)
        if result is None:
            self._handle_read_failure()
            return
        self._consecutive_failures = 0
        leader_pos, leader_entity, area_ptr = result

        # Detect area transitions — reset terrain grid and portal state
        if area_ptr and area_ptr != self._last_area_ptr:
            if self._last_area_ptr is not None:
                logger.info(
                    "Area transition detected (0x%X → 0x%X) — resetting terrain, portal and stuck state.",
                    self._last_area_ptr, area_ptr,
                )
                self._terrain_loaded = False
                self._pathfinder = Pathfinder()
                self._portal_position = None
                self._portal_entered.clear()
                for p in self._players.values():
                    p.last_click = 0.0
                    p.stuck_counter = 0
                    p.stuck_level = 0
                    p.reverse_remaining = 0
            self._last_area_ptr = area_ptr

        leader_health: Optional[HealthData] = None
        if leader_entity:
            leader_health = self._reader.read_health(leader_proc, leader_entity)

        leader.last_pos = leader_pos

        if leader.char_info is None and leader_entity:
            ci = self._reader.read_character_info(leader_proc, leader_entity)
            if ci is not None:
                leader.char_info = ci

        if not self._terrain_loaded:
            self._load_terrain(leader_proc)

        self._load_entities(leader_proc)
        self._detect_portal(leader_proc, leader_pos)
        self._emit_leader(leader, leader_health)

        follower_data: List[dict] = []
        for pkey, player in self._players.items():
            if player.role != "follower" or player.pid == 0:
                continue

            proc = self._reader.open_process(player.pid)
            if proc is None:
                continue

            result_f = self._read_follower_position(proc, player)
            if result_f is None:
                continue
            follower_pos, follower_entity, _ = result_f

            follower_health: Optional[HealthData] = None
            if follower_entity:
                follower_health = self._reader.read_health(proc, follower_entity)

            # If this follower is paused, release all held keys and skip automation
            if player.key in self._paused_keys:
                if player.key in self._held_keys:
                    self._injector.release_all(player.hwnd, self._held_keys[player.key])
                    del self._held_keys[player.key]
                follower_data.append({
                    "key": pkey, "pid": player.pid, "hwnd": player.hwnd,
                    "index": 0, "pos": follower_pos, "fmt_target": None,
                    "stuck_level": 0, "stuck_counter": 0,
                    "reverse_remaining": 0, "wasd": "",
                    "health": follower_health, "char_info": player.char_info,
                })
                continue

            if self._handle_death(player, follower_health):
                continue

            if follower_health is not None:
                self._handle_flask(player, follower_health)

            self._handle_loot(player, proc, follower_pos)

            portal_active = self._portal_position is not None
            if portal_active and pkey not in self._portal_entered:
                formation_target = self._portal_position
                self._handle_portal_entry(player, follower_pos)
            else:
                formation_target = self._apply_formation_offset(
                    pkey, leader_pos.x, leader_pos.y,
                )

            if player.char_info is None and follower_entity:
                ci = self._reader.read_character_info(proc, follower_entity)
                if ci is not None:
                    player.char_info = ci

            self._route_movement(player, formation_target, follower_pos, leader_pos)

            idx = self._follower_indices.get(pkey, 0)
            follower_data.append({
                "key": pkey, "pid": player.pid, "hwnd": player.hwnd,
                "index": idx, "pos": follower_pos, "fmt_target": formation_target,
                "stuck_level": player.stuck_level,
                "stuck_counter": player.stuck_counter,
                "reverse_remaining": player.reverse_remaining,
                "health": follower_health, "char_info": player.char_info,
            })

        if follower_data:
            self._emit_status("followers", follower_data)
        self._emit_map(leader_pos, follower_data)

        # Periodic config hot-reload check
        self._reload_tick_counter += 1
        if self._reload_tick_counter >= _CONFIG_RELOAD_INTERVAL:
            self._reload_tick_counter = 0
            self._maybe_reload_config()

    def _read_follower_position(
        self, proc: GameProcess, player: Player,
    ) -> Optional[Tuple[EntityPosition, Optional[int], Optional[int]]]:
        if player.slot == 0:
            result = self._reader.read_local_player_position(proc)
            if result is None:
                return None
            pos, entity, area_ptr = result
            return (pos, entity, area_ptr)
        all_players = self._reader.find_all_local_players(proc)
        if player.slot >= len(all_players):
            return None
        _, x, y, z = all_players[player.slot]
        return (EntityPosition(float(x), float(y), float(z)), None, None)

    # -- Movement routing ------------------------------------------------

    def _route_movement(
        self, player: Player, target: Tuple[float, float],
        follower: EntityPosition, leader: EntityPosition,
    ) -> None:
        wasd = self._compute_wasd(player, target, follower, leader)
        wasd = set(wasd) if isinstance(wasd, list) else wasd
        if player.input_method == "gamepad":
            self._vgamepad.move_wasd(self._cid(player), wasd)
        elif player.input_method == "keyboard":
            self._apply_keys_delta(player, wasd)

    def _cid(self, player: Player) -> int:
        return self._vgamepad_ids.get(player.key, -1)

    def _apply_keys_delta(self, player: Player, desired: Set[str]) -> None:
        current = self._held_keys.get(player.key, set())
        for key in current - desired:
            self._injector.release(player.hwnd, key)
        for key in desired - current:
            self._injector.press(player.hwnd, key)
        self._held_keys[player.key] = desired

    # -- WASD / anti-stuck / formation -----------------------------------

        # Periodic config hot-reload check
        self._reload_tick_counter += 1
        if self._reload_tick_counter >= _CONFIG_RELOAD_INTERVAL:
            self._reload_tick_counter = 0
            self._maybe_reload_config()

    def _compute_wasd(
        self, player: Player, target: Tuple[float, float],
        follower: EntityPosition, leader: EntityPosition,
    ) -> Set[str]:
        action = self._check_anti_stuck(player, follower, leader, target)
        if action is not None:
            return action

        tx, ty = target[0], target[1]

        avoid_dx, avoid_dy = 0.0, 0.0
        min_dist = 100.0
        for _, ent in self._nearby_entities.items():
            edx = follower.x - ent.x
            edy = follower.y - ent.y
            edist = math.hypot(edx, edy)
            if 0 < edist < min_dist:
                strength = (min_dist - edist) / min_dist
                avoid_dx += (edx / edist) * strength * 150.0
                avoid_dy += (edy / edist) * strength * 150.0

        dx = (tx + avoid_dx) - follower.x
        dy = follower.y - (ty + avoid_dy)
        if math.hypot(dx, dy) < 1.0:
            return set()

        return self._pathfinder.to_wasd(
            follower.x, follower.y, tx + avoid_dx, ty + avoid_dy,
        )

    def _check_anti_stuck(
        self, player: Player, follower: EntityPosition,
        leader: EntityPosition, target: Tuple[float, float],
    ) -> Optional[Set[str]]:
        if not self._anti_stuck.get("enabled", True):
            return None

        prev = player.last_pos
        if prev is None:
            player.last_pos = follower
            return None

        threshold = jitter(float(self._anti_stuck.get("distance_threshold", 2.0)), 0.15)
        moved = math.hypot(follower.x - prev.x, follower.y - prev.y)
        player.last_pos = follower

        if moved > threshold:
            player.stuck_counter = 0
            player.stuck_level = 0
            player.reverse_remaining = 0
            return None

        player.stuck_counter += 1
        stuck_ticks = self._anti_stuck.get("stuck_ticks", 10)
        if player.stuck_counter < stuck_ticks:
            return None

        level = player.stuck_level

        if level == 0:
            player.stuck_level = 1
            player.stuck_counter = 0
            key = self._anti_stuck.get("jump_key", "SPACE")
            return self._resolve_action(player, key)

        if level == 1:
            player.stuck_level = 2
            player.stuck_counter = 0
            key = self._anti_stuck.get("skill_key", "Q")
            return self._resolve_action(player, key)

        if level == 2:
            player.stuck_level = 3
            player.stuck_counter = 0
            player.reverse_remaining = self._anti_stuck.get("reverse_duration_ticks", 8)

        rev = player.reverse_remaining
        if rev > 0:
            player.reverse_remaining = rev - 1
            rx = follower.x * 2 - target[0]
            ry = follower.y * 2 - target[1]
            return self._pathfinder.to_wasd(follower.x, follower.y, rx, ry)

        cooldown = self._anti_stuck.get("reverse_cooldown_ticks", 30)
        if player.stuck_counter > cooldown:
            player.stuck_counter = 0
            player.stuck_level = 0
        return None

    def _resolve_action(self, player: Player, key: str) -> Set[str]:
        if player.input_method == "gamepad":
            btn = _KEY_TO_BTN.get(key, "A")
            self._vgamepad.press_button(self._cid(player), btn)
            self._vgamepad.release_button(self._cid(player), btn)
            return set()
        self._injector.press(player.hwnd, key)
        self._injector.release(player.hwnd, key)
        return set()

    def _apply_formation_offset(
        self, pkey: str, lx: float, ly: float,
    ) -> Tuple[float, float]:
        index = self._follower_indices.get(pkey, 0)
        fm_type = self._formation.get("type", "diamond")
        offsets = _FM.get(fm_type, _FM_DIAMOND)
        ox, oy = offsets[index % len(offsets)]
        spacing = float(self._formation.get("spacing", 35.0))
        return position_jitter(lx + ox * spacing, ly + oy * spacing, 4.0)

    # -- World state -----------------------------------------------------

    def _load_terrain(self, leader_proc: GameProcess) -> None:
        terrain = self._reader.read_terrain_grid(leader_proc)
        if terrain is None:
            return
        self._pathfinder = Pathfinder(grid=terrain.grid, cell_size=terrain.cell_size)
        self._terrain_data = terrain
        self._terrain_loaded = True
        self._terrain_dirty = True
        logger.info("Terrain: %dx%d, %d walkable",
                     terrain.cells_per_row, terrain.num_rows,
                     sum(1 for row in terrain.grid for c in row if c == 0))

    def _load_entities(self, leader_proc: GameProcess) -> None:
        raw = self._reader.read_awake_entities(leader_proc)
        if not raw:
            return
        self._nearby_entities.clear()
        leader = self._players.get(self._leader_key)
        if leader is None or leader.last_pos is None:
            return
        for entity_addr, ex, ey, ez in raw:
            if math.hypot(ex - leader.last_pos.x, ey - leader.last_pos.y) < 400.0:
                self._nearby_entities[entity_addr] = EntityPosition(ex, ey, ez)

    # -- Flask / death / loot / portal -----------------------------------

    def _handle_flask(self, player: Player, health: HealthData) -> None:
        if not self._flask_enabled or health.ratio >= jitter(self._flask_hp_threshold, 0.15):
            return
        now = time.monotonic()
        if now - player.last_flask < jitter(self._flask_cooldown, 0.35) or maybe(0.10):
            return
        player.last_flask = now

        if player.input_method == "gamepad":
            cid = self._cid(player)
            for key in self._flask_keys:
                btn = _KEY_TO_BTN.get(key)
                if btn:
                    self._vgamepad.press_button(cid, btn)
                    self._vgamepad.release_button(cid, btn)
        else:
            for key in self._flask_keys:
                self._injector.press(player.hwnd, key)
                self._injector.release(player.hwnd, key)

    def _handle_death(self, player: Player, health: Optional[HealthData]) -> bool:
        if not self._death_enabled:
            return False
        if health is None or health.current == 0:
            if not player.dead:
                player.dead = True
                logger.warning("Player %s dead.", player.key)
            return True
        if player.dead:
            player.dead = False
            logger.info("Player %s respawned.", player.key)
        return False

    def _handle_loot(
        self, player: Player, proc: GameProcess, fpos: EntityPosition,
    ) -> None:
        if not self._loot_enabled:
            return
        entities = self._reader.read_awake_entities_with_paths(
            proc, path_keywords=self._loot_keywords,
        )
        if not entities:
            return
        for _, ex, ey, _, _ in entities:
            if math.hypot(fpos.x - ex, fpos.y - ey) < self._loot_pickup_radius:
                now = time.monotonic()
                if now - player.last_click >= jitter_up(self._loot_click_delay, 0.40):
                    self._do_interact(player)
                    player.last_click = now
                break

    def _do_interact(self, player: Player) -> None:
        if player.input_method == "gamepad":
            self._vgamepad.press_button(self._cid(player), "A")
            self._vgamepad.release_button(self._cid(player), "A")
        else:
            self._injector.click(player.hwnd)

    def _detect_portal(self, leader_proc: GameProcess, leader_pos: EntityPosition) -> None:
        if not self._portal_enabled:
            return
        if self._portal_position is not None:
            nf = sum(1 for p in self._players.values()
                     if p.role == "follower" and p.pid != 0)
            if len(self._portal_entered) < nf:
                return
            self._portal_position = None
            self._portal_entered.clear()
            logger.info("Portal cleared — all followers entered.")
            return

        entities = self._reader.read_awake_entities_with_paths(
            leader_proc, path_keywords=self._portal_keywords,
        )
        if not entities:
            return

        best = None
        best_dist = float("inf")
        for _, ex, ey, _, _ in entities:
            d = math.hypot(ex - leader_pos.x, ey - leader_pos.y)
            if d < self._portal_detection_radius and d < best_dist:
                best_dist = d
                best = (ex, ey)

        if best:
            self._portal_position = best
            self._portal_entered.clear()
            for p in self._players.values():
                p.last_click = 0.0
            logger.info("Portal at (%.1f, %.1f)", best[0], best[1])
            self._emit_state("Portal detected — followers entering...")

    def _handle_portal_entry(self, player: Player, fpos: EntityPosition) -> None:
        if self._portal_position is None or player.key in self._portal_entered:
            return
        px, py = self._portal_position
        if math.hypot(fpos.x - px, fpos.y - py) < self._portal_interact_radius:
            now = time.monotonic()
            if now - player.last_click >= jitter(self._portal_click_delay, 0.25):
                self._do_interact(player)
                player.last_click = now
            self._portal_entered.add(player.key)

    # -- Process recovery ------------------------------------------------

    def _handle_read_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._max_consecutive_failures:
            logger.warning("Leader read failed %d ticks — recovering.",
                           self._consecutive_failures)
            self._recover_processes()
            self._consecutive_failures = 0

    def _recover_processes(self) -> None:
        self._reader.close_all()
        self._reader.reset_caches()
        for p in self._players.values():
            p.pid = 0
            p.char_info = None
            p.last_pos = None
        self._terrain_data = None
        self._terrain_dirty = False
        self._terrain_loaded = False
        self._last_area_ptr = None
        self._portal_position = None
        self._portal_entered.clear()

        all_pids = self._reader.find_poe2_processes()
        if not all_pids:
            self._emit_state("Recovery failed — no PoE2 processes.")
            return

        pids = sorted(set(all_pids))
        player_list = list(self._players.values())
        for i, pid in enumerate(pids):
            if i < len(player_list):
                player_list[i].pid = pid

        logger.info("Process recovery OK: %d pids.", len(pids))
        self._emit_state("Reconnected.")

    # -- Emergency stop / emit -------------------------------------------

    def set_paused(self, player_key: str, paused: bool) -> None:
        """Pause or resume automation for a single follower by player key.

        Thread-safe under CPython (GIL protects set mutations).
        """
        if paused:
            self._paused_keys.add(player_key)
            logger.info("Follower %s paused.", player_key)
        else:
            self._paused_keys.discard(player_key)
            logger.info("Follower %s resumed.", player_key)

    def _maybe_reload_config(self) -> None:
        """Re-read behavior config from disk if the file has changed."""
        if not self._config_path:
            return
        try:
            mtime = os.path.getmtime(self._config_path)
            if mtime <= self._config_mtime:
                return
            self._config_mtime = mtime
            from src.common.config_loader import load_config as _load_config  # lazy
            new_cfg = _load_config(self._config_path)
            if not new_cfg.nav:
                return
            nav = new_cfg.nav
            behavior = nav.get("behavior", {})
            self._formation = behavior.get("formation", self._formation)
            self._anti_stuck = behavior.get("anti_stuck", self._anti_stuck)
            flask_cfg = nav.get("flask", {})
            self._flask_enabled = flask_cfg.get("enabled", self._flask_enabled)
            self._flask_hp_threshold = float(flask_cfg.get("hp_threshold", self._flask_hp_threshold))
            self._flask_mana_threshold = float(flask_cfg.get("mana_threshold", self._flask_mana_threshold))
            self._flask_cooldown = float(flask_cfg.get("flask_cooldown", self._flask_cooldown))
            self._flask_keys = flask_cfg.get("flask_keys", self._flask_keys)
            loot_cfg = nav.get("auto_loot", {})
            self._loot_enabled = loot_cfg.get("enabled", self._loot_enabled)
            self._loot_pickup_radius = float(loot_cfg.get("pickup_radius", self._loot_pickup_radius))
            self._loot_click_delay = float(loot_cfg.get("click_delay", self._loot_click_delay))
            logger.info("Config hot-reloaded from %s.", self._config_path)
            self._emit_state("Config reloaded.")
        except Exception as exc:
            logger.warning("Config hot reload failed: %s", exc)

    def _emergency_stop(self) -> None:
        for pkey, keys in self._held_keys.items():
            player = self._players.get(pkey)
            if player and player.input_method == "keyboard":
                self._injector.release_all(player.hwnd, keys)
        self._held_keys.clear()
        self._vgamepad.close_all()
        logger.warning("NavAgent emergency stop.")

    def _emit_status(self, msg_type: str, data: Any = None) -> None:
        if self._status_queue is None:
            return
        try:
            payload = {"type": msg_type, "data": data} if data is not None else {"type": msg_type}
            self._status_queue.put_nowait(payload)
        except queue.Full:
            pass

    def _emit_state(self, text: str) -> None:
        if self._status_queue is None:
            return
        try:
            self._status_queue.put_nowait({"type": "state", "text": text})
        except queue.Full:
            pass

    def _emit_leader(self, leader: Player, health: Optional[HealthData] = None) -> None:
        if self._status_queue is None or leader.last_pos is None:
            return
        try:
            msg: dict = {"type": "leader", "pos": leader.last_pos}
            if health:
                msg["health"] = health
            if leader.char_info:
                msg["char_info"] = leader.char_info
            self._status_queue.put_nowait(msg)
        except queue.Full:
            pass

    def _emit_map(self, leader_pos: EntityPosition, follower_data: List[dict]) -> None:
        if self._status_queue is None:
            return
        try:
            terrain = None
            if self._terrain_dirty:
                terrain = self._terrain_data
                self._terrain_dirty = False
            flist: List[Tuple[float, float, str]] = []
            for fd in follower_data:
                pos = fd.get("pos")
                if pos:
                    ci = fd.get("char_info")
                    label = ci.name if ci and ci.name else f"F{fd.get('index','')}"
                    flist.append((pos.x, pos.y, label))
            self._status_queue.put_nowait({
                "type": "map",
                "data": {"terrain": terrain, "leader_pos": leader_pos, "followers": flist},
            })
        except queue.Full:
            pass
