from __future__ import annotations

import heapq
import math
from typing import List, Optional, Set, Tuple

from src.common.logger import get_logger

logger = get_logger(__name__)

WASD_DIRECTIONS: Dict[Tuple[int, int], str] = {
    (0, -1): "w",
    (0, 1): "s",
    (-1, 0): "a",
    (1, 0): "d",
    (-1, -1): "wa",
    (1, -1): "wd",
    (-1, 1): "as",
    (1, 1): "sd",
}


def _direction_to_wasd(dx: float, dy: float, threshold: float = 0.01) -> Set[str]:
    keys: Set[str] = set()
    if dx > threshold:
        keys.add("d")
    elif dx < -threshold:
        keys.add("a")
    if dy < -threshold:
        keys.add("w")
    elif dy > threshold:
        keys.add("s")
    return keys


class Pathfinder:
    def __init__(self, grid: Optional[List[List[int]]] = None, cell_size: float = 1.0) -> None:
        self._grid = grid
        self._cell_size = cell_size
        self._height = len(grid) if grid else 0
        self._width = len(grid[0]) if grid and self._height > 0 else 0

    @property
    def has_grid(self) -> bool:
        return self._grid is not None

    def find_path(
        self,
        start_x: float,
        start_y: float,
        goal_x: float,
        goal_y: float,
    ) -> List[Tuple[int, int]]:
        if self._grid is None:
            return []

        sx = int(start_x / self._cell_size)
        sy = int(start_y / self._cell_size)
        gx = int(goal_x / self._cell_size)
        gy = int(goal_y / self._cell_size)

        if not self._in_bounds(sx, sy) or not self._in_bounds(gx, gy):
            return []
        if not self._is_walkable(gx, gy):
            return []

        return self._astar(sx, sy, gx, gy)

    def to_wasd(
        self,
        start_x: float,
        start_y: float,
        goal_x: float,
        goal_y: float,
    ) -> Set[str]:
        if self._grid is not None:
            path = self.find_path(start_x, start_y, goal_x, goal_y)
            if len(path) > 1:
                nx, ny = path[1]
                dx = nx - int(start_x / self._cell_size)
                dy = ny - int(start_y / self._cell_size)
                if dx == 0 and dy == 0 and len(path) > 2:
                    nx, ny = path[2]
                    dx = nx - int(start_x / self._cell_size)
                    dy = ny - int(start_y / self._cell_size)
                return self._cardinal_to_wasd(dx, dy)
            elif len(path) == 1:
                return set()

        return self._vector_to_wasd(start_x, start_y, goal_x, goal_y)

    def _astar(self, sx: int, sy: int, gx: int, gy: int) -> List[Tuple[int, int]]:
        def h(x: int, y: int) -> float:
            return abs(x - gx) + abs(y - gy)

        open_set: List[Tuple[float, int, int, int, int]] = [(h(sx, sy), sx, sy, -1, -1)]
        came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}
        cost_so_far: Dict[Tuple[int, int], float] = {(sx, sy): 0.0}

        max_iterations = self._width * self._height * 2

        while open_set and max_iterations > 0:
            max_iterations -= 1
            _, cx, cy, px, py = heapq.heappop(open_set)

            if (cx, cy) in came_from:
                continue

            came_from[(cx, cy)] = (px, py)

            if cx == gx and cy == gy:
                path: List[Tuple[int, int]] = []
                cur: Tuple[int, int] = (gx, gy)
                for _ in range(max_iterations):
                    path.append(cur)
                    if cur == (sx, sy):
                        break
                    cur = came_from[cur]
                path.reverse()
                return path

            neighbors = [(0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)]
            for dx, dy in neighbors:
                nx, ny = cx + dx, cy + dy
                if not self._in_bounds(nx, ny) or not self._is_walkable(nx, ny):
                    continue
                diagonal = abs(dx) == 1 and abs(dy) == 1
                move_cost = 1.414 if diagonal else 1.0
                new_cost = cost_so_far.get((cx, cy), float("inf")) + move_cost
                if new_cost < cost_so_far.get((nx, ny), float("inf")):
                    cost_so_far[(nx, ny)] = new_cost
                    heapq.heappush(open_set, (new_cost + h(nx, ny), nx, ny, cx, cy))

        return []

    def _vector_to_wasd(self, sx: float, sy: float, gx: float, gy: float) -> Set[str]:
        dx = gx - sx
        dy = sy - gy
        dist_sq = dx * dx + dy * dy
        if dist_sq < 0.01:
            return set()
        return _direction_to_wasd(dx, dy)

    @staticmethod
    def _cardinal_to_wasd(dx: int, dy: int) -> Set[str]:
        if dx == 0 and dy == 0:
            return set()
        result: Set[str] = set()
        if dx > 0:
            result.add("d")
        elif dx < 0:
            result.add("a")
        if dy > 0:
            result.add("s")
        elif dy < 0:
            result.add("w")
        return result

    def _in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self._width and 0 <= y < self._height

    def _is_walkable(self, x: int, y: int) -> bool:
        if self._grid is None:
            return True
        return self._grid[y][x] == 0
