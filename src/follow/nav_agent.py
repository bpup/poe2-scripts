from __future__ import annotations

import math
import queue
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from src.common.logger import get_logger
from src.core.behavior_randomizer import jitter, jitter_up, maybe, position_jitter, reseed
from src.core.input_injector import InputInjector
from src.core.memory_reader import EntityPosition, GameProcess, HealthData, MemoryReader, TerrainData
from src.core.pathfinder import Pathfinder
from src.core.window_registry import WindowRegistry
from src.core.window_registry import WindowStatus as WinStatus

logger = get_logger(__name__)

TICK_INTERVAL = 0.05
STUCK_THRESHOLD = 5.0
STUCK_STEPS = 5
UNSTUCK_VECTORS = [
    (1.0, 0.0),
    (-1.0, 0.0),
    (0.0, -1.0),
    (0.0, 1.0),
]

_FORMATION_DIAMOND = [(0, -1), (1, 0), (-1, 0), (-1, -2), (1, -2)]
_FORMATION_LINE = [(0, -1), (0, -2), (0, -3), (0, -4), (0, -5)]
_FORMATION_V = [(-1, -1), (1, -1), (-2, -2), (2, -2), (-3, -3)]

_FM = {
    "diamond": _FORMATION_DIAMOND,
    "line": _FORMATION_LINE,
    "v": _FORMATION_V,
}


class NavAgent:
    def __init__(
        self,
        nav_config: dict,
        leader_hwnd: int,
        follower_hwnds: List[int],
        status_queue: Optional[queue.Queue[dict]] = None,
    ) -> None:
        self._reader = MemoryReader(nav_config)
        self._injector = InputInjector()
        self._pathfinder = Pathfinder()
        self._registry = WindowRegistry()

        self._terrain_loaded = False
        self._nearby_entities: Dict[int, List[EntityPosition]] = {}

        self._leader_hwnd = leader_hwnd
        self._follower_hwnds = follower_hwnds
        self._status_queue = status_queue

        self._leader_pid: Optional[int] = None
        self._follower_pids: Dict[int, int] = {}
        self._follower_indices: Dict[int, int] = {}

        self._held_keys: Dict[int, Set[str]] = {}
        self._last_positions: Dict[int, EntityPosition] = {}
        self._cur_leader_pos: Optional[EntityPosition] = None

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

        self._portal_position: Optional[Tuple[float, float]] = None
        self._portal_last_seen: float = 0.0
        self._follower_entered_portal: Set[int] = set()
        self._follower_last_click: Dict[int, float] = {}

        flask_cfg = nav_config.get("flask", {})
        self._flask_enabled = flask_cfg.get("enabled", True)
        self._flask_hp_threshold = float(flask_cfg.get("hp_threshold", 0.50))
        self._flask_mana_threshold = float(flask_cfg.get("mana_threshold", 0.30))
        self._flask_cooldown = float(flask_cfg.get("flask_cooldown", 0.5))
        self._flask_keys: List[str] = flask_cfg.get("flask_keys", ["1", "2", "3", "4", "5"])
        self._last_flask: Dict[int, float] = {}

        loot_cfg = nav_config.get("auto_loot", {})
        self._loot_enabled = loot_cfg.get("enabled", True)
        self._loot_keywords: List[str] = loot_cfg.get("entity_path_keywords", ["Metadata/Items"])
        self._loot_pickup_radius = float(loot_cfg.get("pickup_radius", 8.0))
        self._loot_click_delay = float(loot_cfg.get("click_delay", 0.3))

        self._death_enabled = nav_config.get("death", {}).get("enabled", True)
        self._follower_dead: Set[int] = set()

        self._stuck_counters: Dict[int, int] = {}
        self._stuck_levels: Dict[int, int] = {}
        self._reverse_remaining: Dict[int, int] = {}
        self._consecutive_failures: int = 0
        self._max_consecutive_failures: int = 30

        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._resolve_pids()
        self._build_follower_indices()

        reseed()

        self._portal_position = None
        self._follower_entered_portal.clear()
        self._follower_last_click.clear()
        self._last_flask.clear()
        self._follower_dead.clear()

        if self._leader_pid is None:
            logger.error("Leader PID not found.")
            self._running = False
            return
        if not self._follower_pids:
            logger.error("No follower PIDs found.")
            self._running = False
            return

        logger.info(
            "NavAgent started: leader PID=%d, %d followers.",
            self._leader_pid,
            len(self._follower_pids),
        )

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
        leader_proc = self._reader.open_process(self._leader_pid)
        if leader_proc is None:
            self._handle_read_failure()
            return

        result = self._reader.read_local_player_position(leader_proc)
        if result is None:
            self._handle_read_failure()
            return
        self._consecutive_failures = 0
        leader_pos, leader_entity = result

        leader_health: Optional[HealthData] = None
        if leader_entity:
            leader_health = self._reader.read_health(leader_proc, leader_entity)

        self._cur_leader_pos = leader_pos

        if not self._terrain_loaded:
            self._load_terrain(leader_proc)

        self._load_entities(leader_proc)
        self._detect_portal(leader_proc, leader_pos)

        self._emit_leader(leader_pos, leader_health)

        follower_data: List[dict] = []
        for hwnd, pid in self._follower_pids.items():
            proc = self._reader.open_process(pid)
            if proc is None:
                continue

            result_f = self._reader.read_local_player_position(proc)
            if result_f is None:
                continue
            follower_pos, follower_entity = result_f

            follower_health: Optional[HealthData] = None
            if follower_entity:
                follower_health = self._reader.read_health(proc, follower_entity)

            if self._handle_death(hwnd, follower_health):
                continue

            if follower_health is not None:
                self._handle_flask(hwnd, follower_health)

            self._handle_loot(hwnd, proc, follower_pos)

            portal_active = self._portal_position is not None
            if portal_active and hwnd not in self._follower_entered_portal:
                formation_target = self._portal_position
                self._handle_portal_entry(hwnd, follower_pos)
            else:
                formation_target = self._apply_formation_offset(
                    hwnd, leader_pos.x, leader_pos.y
                )

            wasd = self._compute_wasd(
                hwnd, formation_target, follower_pos, leader_pos
            )
            self._apply_keys(hwnd, wasd)

            idx = self._follower_indices.get(hwnd, 0)
            follower_data.append({
                "hwnd": hwnd,
                "pid": pid,
                "index": idx,
                "pos": follower_pos,
                "fmt_target": formation_target,
                "stuck_level": self._stuck_levels.get(hwnd, 0),
                "stuck_counter": self._stuck_counters.get(hwnd, 0),
                "reverse_remaining": self._reverse_remaining.get(hwnd, 0),
                "wasd": "".join(sorted(wasd)) if wasd else "",
                "health": follower_health,
            })

        if follower_data:
            self._emit_status("followers", follower_data)

    def _compute_wasd(
        self,
        hwnd: int,
        target: Tuple[float, float],
        follower: EntityPosition,
        leader: EntityPosition,
    ) -> Set[str]:
        anti_stuck = self._check_anti_stuck(hwnd, follower, leader, target)
        if anti_stuck is not None:
            return anti_stuck

        tx, ty = target[0], target[1]

        avoid_dx, avoid_dy = 0.0, 0.0
        min_dist = 100.0
        for _, ent in self._nearby_entities.items():
            edx = follower.x - ent.x
            edy = follower.y - ent.y
            edist = (edx * edx + edy * edy) ** 0.5
            if 0 < edist < min_dist:
                strength = (min_dist - edist) / min_dist
                avoid_dx += (edx / edist) * strength * 150.0
                avoid_dy += (edy / edist) * strength * 150.0

        dx = (tx + avoid_dx) - follower.x
        dy = follower.y - (ty + avoid_dy)
        dist = (dx * dx + dy * dy) ** 0.5

        if dist < 1.0:
            return set()

        return self._pathfinder.to_wasd(
            follower.x, follower.y, tx + avoid_dx, ty + avoid_dy,
        )

    def _apply_keys(self, hwnd: int, desired: Set[str]) -> None:
        current = self._held_keys.get(hwnd, set())
        to_release = current - desired
        to_press = desired - current

        for key in to_release:
            self._injector.release(hwnd, key)
        for key in to_press:
            self._injector.press(hwnd, key)

        self._held_keys[hwnd] = desired

    def _load_terrain(self, leader_proc: GameProcess) -> None:
        terrain: Optional[TerrainData] = self._reader.read_terrain_grid(leader_proc)
        if terrain is None:
            return

        self._pathfinder = Pathfinder(grid=terrain.grid, cell_size=terrain.cell_size)
        self._terrain_loaded = True
        logger.info(
            "Terrain grid loaded: %dx%d (%d walkable cells).",
            terrain.cells_per_row,
            terrain.num_rows,
            sum(1 for row in terrain.grid for c in row if c == 0),
        )

    def _load_entities(self, leader_proc: GameProcess) -> None:
        raw = self._reader.read_awake_entities(leader_proc)
        if not raw:
            return

        self._nearby_entities.clear()
        leader_pos = self._cur_leader_pos
        if leader_pos is None:
            return

        threat_radius = 400.0
        for entity_addr, ex, ey, ez in raw:
            dist = math.hypot(ex - leader_pos.x, ey - leader_pos.y)
            if dist < threat_radius:
                self._nearby_entities[entity_addr] = EntityPosition(ex, ey, ez)

    def _handle_flask(self, hwnd: int, health: HealthData) -> None:
        if not self._flask_enabled:
            return

        if health.ratio >= jitter(self._flask_hp_threshold, 0.15):
            return

        now = time.monotonic()
        if now - self._last_flask.get(hwnd, 0.0) < jitter(self._flask_cooldown, 0.35):
            return

        if maybe(0.10):
            return

        self._last_flask[hwnd] = now

        for key in self._flask_keys:
            self._injector.press(hwnd, key)
            self._injector.release(hwnd, key)
        logger.debug("Flask used on HWND=%d (HP=%d/%d)", hwnd, health.current, health.maximum)

    def _handle_death(self, hwnd: int, health: Optional[HealthData]) -> bool:
        if not self._death_enabled:
            return False

        if health is None or health.current == 0:
            if hwnd not in self._follower_dead:
                self._follower_dead.add(hwnd)
                self._injector.release_all(hwnd, self._held_keys.get(hwnd, set()))
                self._held_keys.pop(hwnd, None)
                logger.warning("Follower HWND=%d dead — waiting for respawn.", hwnd)
            return True

        if hwnd in self._follower_dead:
            self._follower_dead.discard(hwnd)
            logger.info("Follower HWND=%d respawned (HP=%d/%d).", hwnd, health.current, health.maximum)
        return False

    def _handle_loot(
        self, hwnd: int, proc: GameProcess, follower_pos: EntityPosition,
    ) -> None:
        if not self._loot_enabled:
            return

        entities = self._reader.read_awake_entities_with_paths(
            proc, path_keywords=self._loot_keywords,
        )
        if not entities:
            return

        for _, ex, ey, _, _ in entities:
            dist = math.hypot(follower_pos.x - ex, follower_pos.y - ey)
            if dist < self._loot_pickup_radius:
                now = time.monotonic()
                delay = jitter_up(self._loot_click_delay, 0.40)
                if now - self._follower_last_click.get(hwnd, 0.0) >= delay:
                    self._injector.click(hwnd)
                    self._follower_last_click[hwnd] = now
                    logger.debug("Loot pickup on HWND=%d at (%.1f,%.1f)", hwnd, ex, ey)
                break

    def _detect_portal(self, leader_proc: GameProcess, leader_pos: EntityPosition) -> None:
        if not self._portal_enabled:
            return
        if self._portal_position is not None:
            if not self._follower_entered_portal or len(self._follower_entered_portal) < len(self._follower_pids):
                return
            self._portal_position = None
            self._follower_entered_portal.clear()
            logger.info("Portal cleared — all followers entered.")
            return

        entities = self._reader.read_awake_entities_with_paths(
            leader_proc, path_keywords=self._portal_keywords,
        )
        if not entities:
            return

        best_dist = float("inf")
        best_pos = None
        for entity_addr, ex, ey, ez, path in entities:
            dist = math.hypot(ex - leader_pos.x, ey - leader_pos.y)
            if dist < self._portal_detection_radius and dist < best_dist:
                best_dist = dist
                best_pos = (ex, ey)

        if best_pos is not None:
            self._portal_position = best_pos
            self._follower_entered_portal.clear()
            self._follower_last_click.clear()
            logger.info(
                "Portal detected near Leader at (%.1f, %.1f) — %d follower(s) will enter.",
                best_pos[0], best_pos[1], len(self._follower_pids),
            )
            self._emit_state("Portal detected — followers entering...")

    def _handle_portal_entry(
        self, hwnd: int, follower_pos: EntityPosition,
    ) -> None:
        if self._portal_position is None:
            return
        if hwnd in self._follower_entered_portal:
            return

        px, py = self._portal_position
        dist = math.hypot(follower_pos.x - px, follower_pos.y - py)

        if dist < self._portal_interact_radius:
            now = time.monotonic()
            last = self._follower_last_click.get(hwnd, 0.0)
            delay = jitter(self._portal_click_delay, 0.25)
            if now - last >= delay:
                if self._portal_interact_key == "LMB":
                    self._injector.click(hwnd)
                else:
                    self._injector.press(hwnd, self._portal_interact_key)
                    self._injector.release(hwnd, self._portal_interact_key)
                self._follower_last_click[hwnd] = now
                logger.info("Follower HWND=%d clicked portal at (%.1f, %.1f).", hwnd, px, py)
            self._follower_entered_portal.add(hwnd)

    def _resolve_pids(self) -> None:
        all_pids = self._reader.find_poe2_processes()
        hwnd_to_pid: Dict[int, int] = {}

        for pid in all_pids:
            for hwnd in [self._leader_hwnd] + self._follower_hwnds:
                if hwnd in hwnd_to_pid:
                    continue
                try:
                    import win32process

                    _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                    if found_pid == pid:
                        hwnd_to_pid[hwnd] = pid
                        break
                except Exception:
                    pass

        self._leader_pid = hwnd_to_pid.get(self._leader_hwnd)
        for hwnd in self._follower_hwnds:
            if hwnd in hwnd_to_pid:
                self._follower_pids[hwnd] = hwnd_to_pid[hwnd]
            else:
                logger.warning("No PoE2 process found for HWND %d.", hwnd)

    def _handle_read_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._max_consecutive_failures:
            logger.warning(
                "Leader read failed %d consecutive ticks — attempting process recovery.",
                self._consecutive_failures,
            )
            self._recover_processes()
            self._consecutive_failures = 0

    def _recover_processes(self) -> None:
        self._reader.close_all()
        self._reader.reset_caches()
        self._leader_pid = None
        self._follower_pids.clear()
        self._follower_indices.clear()
        self._cur_leader_pos = None
        self._terrain_loaded = False
        self._portal_position = None
        self._follower_entered_portal.clear()
        self._follower_last_click.clear()
        self._last_flask.clear()
        self._follower_dead.clear()

        self._resolve_pids()
        self._build_follower_indices()

        if self._leader_pid is not None and self._follower_pids:
            logger.info(
                "Process recovery OK: leader PID=%d, %d followers.",
                self._leader_pid,
                len(self._follower_pids),
            )
            self._emit_state("Reconnected.")
        else:
            logger.error("Process recovery failed — no PoE2 processes found.")
            self._emit_state("Recovery failed — waiting for PoE2 processes...")

    def _build_follower_indices(self) -> None:
        for index, hwnd in enumerate(self._follower_hwnds):
            if hwnd in self._follower_pids:
                self._follower_indices[hwnd] = index

    def _apply_formation_offset(
        self, hwnd: int, leader_x: float, leader_y: float
    ) -> Tuple[float, float]:
        index = self._follower_indices.get(hwnd, 0)
        fm_type = self._formation.get("type", "diamond")
        offsets = _FM.get(fm_type, _FORMATION_DIAMOND)
        if index >= len(offsets):
            index = 0
        ox, oy = offsets[index]
        spacing = float(self._formation.get("spacing", 35.0))
        tx = leader_x + ox * spacing
        ty = leader_y + oy * spacing
        return position_jitter(tx, ty, 4.0)

    def _check_anti_stuck(
        self,
        hwnd: int,
        follower: EntityPosition,
        leader: EntityPosition,
        target: Tuple[float, float],
    ) -> Optional[Set[str]]:
        if not self._anti_stuck.get("enabled", True):
            return None

        prev = self._last_positions.get(hwnd)
        if prev is None:
            self._last_positions[hwnd] = follower
            return None

        threshold = jitter(float(self._anti_stuck.get("distance_threshold", 2.0)), 0.15)
        dx = follower.x - prev.x
        dy = follower.y - prev.y
        moved = (dx * dx + dy * dy) ** 0.5
        self._last_positions[hwnd] = follower

        if moved > threshold:
            self._stuck_counters[hwnd] = 0
            self._stuck_levels[hwnd] = 0
            self._reverse_remaining[hwnd] = 0
            return None

        self._stuck_counters[hwnd] = self._stuck_counters.get(hwnd, 0) + 1
        stuck_ticks = self._anti_stuck.get("stuck_ticks", 10)

        if self._stuck_counters[hwnd] < stuck_ticks:
            return None

        level = self._stuck_levels.get(hwnd, 0)

        if level == 0:
            self._stuck_levels[hwnd] = 1
            self._stuck_counters[hwnd] = 0
            jump_key = self._anti_stuck.get("jump_key", "SPACE")
            return {jump_key}

        if level == 1:
            self._stuck_levels[hwnd] = 2
            self._stuck_counters[hwnd] = 0
            skill_key = self._anti_stuck.get("skill_key", "Q")
            return {skill_key}

        if level == 2:
            self._stuck_levels[hwnd] = 3
            self._stuck_counters[hwnd] = 0
            self._reverse_remaining[hwnd] = self._anti_stuck.get(
                "reverse_duration_ticks", 8
            )

        rev = self._reverse_remaining.get(hwnd, 0)
        if rev > 0:
            self._reverse_remaining[hwnd] = rev - 1
            rx = follower.x * 2 - target[0]
            ry = follower.y * 2 - target[1]
            return self._pathfinder.to_wasd(follower.x, follower.y, rx, ry)

        cooldown = self._anti_stuck.get("reverse_cooldown_ticks", 30)
        if self._stuck_counters[hwnd] > cooldown:
            self._stuck_counters[hwnd] = 0
            self._stuck_levels[hwnd] = 0
        return None

    def _emergency_stop(self) -> None:
        for hwnd in list(self._held_keys.keys()):
            self._injector.release_all(hwnd, self._held_keys.get(hwnd, set()))
        self._held_keys.clear()
        logger.warning("NavAgent emergency stop — all keys released.")

    def _emit_status(self, msg_type: str, data: Any = None) -> None:
        if self._status_queue is None:
            return
        try:
            self._status_queue.put_nowait({"type": msg_type, "data": data} if data is not None else {"type": msg_type})
        except queue.Full:
            pass

    def _emit_state(self, text: str) -> None:
        if self._status_queue is None:
            return
        try:
            self._status_queue.put_nowait({"type": "state", "text": text})
        except queue.Full:
            pass

    def _emit_leader(self, pos: EntityPosition, health: Optional[HealthData] = None) -> None:
        if self._status_queue is None:
            return
        try:
            msg: dict = {"type": "leader", "pos": pos}
            if health is not None:
                msg["health"] = health
            self._status_queue.put_nowait(msg)
        except queue.Full:
            pass
