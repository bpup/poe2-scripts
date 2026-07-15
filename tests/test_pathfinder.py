"""Unit tests for Pathfinder — A* navigation and WASD conversion.

These tests are platform-independent (no Win32 APIs) and run on any OS.
"""

import unittest

from src.core.pathfinder import Pathfinder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_grid(w: int, h: int):
    """Return an all-walkable grid of size w×h."""
    return [[0] * w for _ in range(h)]


# ---------------------------------------------------------------------------
# Vector-based navigation (no terrain grid)
# ---------------------------------------------------------------------------

class PathfinderVectorTests(unittest.TestCase):
    def setUp(self):
        self.pf = Pathfinder()

    def test_has_no_grid(self):
        self.assertFalse(self.pf.has_grid)

    def test_north(self):
        # North = increasing y in game coordinates (y grows northward)
        keys = self.pf.to_wasd(0.0, 0.0, 0.0, 10.0)
        self.assertIn("w", keys)

    def test_south(self):
        # South = decreasing y
        keys = self.pf.to_wasd(0.0, 10.0, 0.0, 0.0)
        self.assertIn("s", keys)

    def test_east(self):
        keys = self.pf.to_wasd(0.0, 0.0, 10.0, 0.0)
        self.assertIn("d", keys)

    def test_west(self):
        keys = self.pf.to_wasd(10.0, 0.0, 0.0, 0.0)
        self.assertIn("a", keys)

    def test_diagonal_northeast(self):
        # Northeast = +x, +y
        keys = self.pf.to_wasd(0.0, 0.0, 10.0, 10.0)
        self.assertIn("w", keys)
        self.assertIn("d", keys)

    def test_diagonal_southwest(self):
        # Southwest = -x, -y
        keys = self.pf.to_wasd(10.0, 10.0, 0.0, 0.0)
        self.assertIn("s", keys)
        self.assertIn("a", keys)

    def test_same_position_returns_empty(self):
        self.assertEqual(self.pf.to_wasd(5.0, 5.0, 5.0, 5.0), set())

    def test_very_close_target_returns_empty(self):
        # Displacement < 0.01 threshold → no movement
        self.assertEqual(self.pf.to_wasd(5.0, 5.0, 5.005, 5.005), set())


# ---------------------------------------------------------------------------
# Grid-based A* pathfinding
# ---------------------------------------------------------------------------

class PathfinderGridTests(unittest.TestCase):
    def test_has_grid(self):
        pf = Pathfinder(grid=_open_grid(5, 5), cell_size=1.0)
        self.assertTrue(pf.has_grid)

    def test_find_path_straight_east(self):
        pf = Pathfinder(grid=_open_grid(10, 10), cell_size=1.0)
        path = pf.find_path(0.0, 0.0, 9.0, 0.0)
        self.assertGreater(len(path), 1)
        self.assertEqual(path[0], (0, 0))
        self.assertEqual(path[-1], (9, 0))

    def test_find_path_diagonal(self):
        pf = Pathfinder(grid=_open_grid(10, 10), cell_size=1.0)
        path = pf.find_path(0.0, 0.0, 9.0, 9.0)
        self.assertGreater(len(path), 1)
        self.assertEqual(path[-1], (9, 9))

    def test_find_path_blocked_goal_returns_empty(self):
        grid = _open_grid(10, 10)
        grid[5][5] = 1          # block the destination cell
        pf = Pathfinder(grid=grid, cell_size=1.0)
        path = pf.find_path(0.0, 0.0, 5.0, 5.0)
        self.assertEqual(path, [])

    def test_find_path_out_of_bounds_returns_empty(self):
        pf = Pathfinder(grid=_open_grid(10, 10), cell_size=1.0)
        path = pf.find_path(0.0, 0.0, 20.0, 20.0)
        self.assertEqual(path, [])

    def test_find_path_same_start_and_goal(self):
        pf = Pathfinder(grid=_open_grid(10, 10), cell_size=1.0)
        path = pf.find_path(0.0, 0.0, 0.0, 0.0)
        self.assertEqual(len(path), 1)
        self.assertEqual(path[0], (0, 0))

    def test_find_path_routes_around_wall(self):
        grid = _open_grid(10, 10)
        # Vertical wall at x=5, rows 0–7; gap at rows 8–9
        for y in range(8):
            grid[y][5] = 1
        pf = Pathfinder(grid=grid, cell_size=1.0)
        path = pf.find_path(0.0, 0.0, 9.0, 0.0)
        self.assertGreater(len(path), 0)
        self.assertEqual(path[-1], (9, 0))
        # Path must not pass through the wall
        wall_cells = {(5, y) for y in range(8)}
        for cell in path:
            self.assertNotIn(cell, wall_cells)

    def test_to_wasd_with_grid_moves_east(self):
        pf = Pathfinder(grid=_open_grid(20, 20), cell_size=1.0)
        keys = pf.to_wasd(1.0, 1.0, 15.0, 1.0)
        self.assertIn("d", keys)

    def test_to_wasd_with_grid_at_goal_returns_empty(self):
        pf = Pathfinder(grid=_open_grid(20, 20), cell_size=1.0)
        # Start == goal → path has 1 node → empty keys
        keys = pf.to_wasd(5.0, 5.0, 5.0, 5.0)
        self.assertEqual(keys, set())

    def test_cell_size_scaling(self):
        # With cell_size=10, world coord 50 maps to grid cell 5
        pf = Pathfinder(grid=_open_grid(10, 10), cell_size=10.0)
        path = pf.find_path(0.0, 0.0, 90.0, 0.0)
        self.assertGreater(len(path), 1)
        self.assertEqual(path[-1], (9, 0))


if __name__ == "__main__":
    unittest.main()
