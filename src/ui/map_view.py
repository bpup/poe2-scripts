from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional, Tuple

from src.core.memory_reader import EntityPosition, TerrainData

# ── display constants ──────────────────────────────────────────

CELL_PX = 3          # pixels per grid cell at zoom=1
PLAYER_RADIUS = 5    # radius in pixels for leader/followers
FOLLOWER_COLORS = ["#4FC3F7", "#81C784", "#FFB74D", "#CE93D8", "#F06292"]

MIN_ZOOM = 0.25
MAX_ZOOM = 4.0


class MapView(ttk.Frame):
    """Scrollable minimap showing terrain grid + player positions (no fog).

    Accepts terrain data and leader/follower positions via ``update_data()``.
    The canvas auto-scrolls to keep the leader centered.
    """

    def __init__(self, parent: tk.Widget, **kwargs: Any) -> None:
        super().__init__(parent, **kwargs)
        self._terrain: Optional[TerrainData] = None
        self._leader_pos: Optional[EntityPosition] = None
        self._follower_positions: List[Tuple[float, float, str]] = []
        self._zoom: float = 1.0
        self._drag_start: Optional[Tuple[int, int]] = None

        self._build_ui()

    def _build_ui(self) -> None:
        self._h_scroll = ttk.Scrollbar(self, orient=tk.HORIZONTAL)
        self._v_scroll = ttk.Scrollbar(self, orient=tk.VERTICAL)

        self._canvas = tk.Canvas(
            self,
            width=600,
            height=500,
            bg="#1a1a2e",
            xscrollcommand=self._h_scroll.set,
            yscrollcommand=self._v_scroll.set,
            highlightthickness=0,
        )
        self._h_scroll.configure(command=self._canvas.xview)
        self._v_scroll.configure(command=self._canvas.yview)

        self._canvas.grid(row=0, column=0, sticky=tk.NSEW)
        self._v_scroll.grid(row=0, column=1, sticky=tk.NS)
        self._h_scroll.grid(row=1, column=0, sticky=tk.EW)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # zoom controls
        zoom_frame = ttk.Frame(self)
        zoom_frame.grid(row=0, column=0, sticky=tk.NE, padx=4, pady=4)
        ttk.Button(zoom_frame, text="+", width=3, command=self._zoom_in).pack(side=tk.LEFT, padx=1)
        ttk.Button(zoom_frame, text="-", width=3, command=self._zoom_out).pack(side=tk.LEFT, padx=1)
        self._zoom_label = ttk.Label(zoom_frame, text="1.0x", font=("", 8))
        self._zoom_label.pack(side=tk.LEFT, padx=4)

        # bind mouse wheel for zoom
        self._canvas.bind("<MouseWheel>", self._on_mousewheel, add=True)
        self._canvas.bind("<Button-4>", self._on_mousewheel_linux_up, add=True)
        self._canvas.bind("<Button-5>", self._on_mousewheel_linux_down, add=True)

        # bind pan
        self._canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self._canvas.bind("<B2-Motion>", self._on_pan_move)

        self._img_id: Optional[int] = None

    def update_data(
        self,
        terrain: Optional[TerrainData] = None,
        leader_pos: Optional[EntityPosition] = None,
        follower_positions: Optional[List[Tuple[float, float, str]]] = None,
    ) -> None:
        if terrain is not None:
            self._terrain = terrain
        if leader_pos is not None:
            self._leader_pos = leader_pos
        if follower_positions is not None:
            self._follower_positions = follower_positions
        self._redraw()

    def set_zoom(self, z: float) -> None:
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, z))
        self._zoom_label.configure(text=f"{self._zoom:.1f}x")
        self._redraw()

    def _zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.5)

    def _zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.5)

    def _on_mousewheel(self, event: Any) -> None:
        if event.delta > 0:
            self.set_zoom(self._zoom * 1.2)
        else:
            self.set_zoom(self._zoom / 1.2)

    def _on_mousewheel_linux_up(self, event: Any) -> None:
        self.set_zoom(self._zoom * 1.2)

    def _on_mousewheel_linux_down(self, event: Any) -> None:
        self.set_zoom(self._zoom / 1.2)

    def _on_pan_start(self, event: Any) -> None:
        self._drag_start = (event.x, event.y)

    def _on_pan_move(self, event: Any) -> None:
        if self._drag_start is None:
            return
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        self._canvas.xview_scroll(-dx, tk.UNITS)
        self._canvas.yview_scroll(-dy, tk.UNITS)
        self._drag_start = (event.x, event.y)

    def _redraw(self) -> None:
        self._canvas.delete("all")

        terrain = self._terrain
        zoom = self._zoom
        cp = CELL_PX * zoom

        if terrain and terrain.grid and terrain.cells_per_row > 0:
            w = int(terrain.cells_per_row * cp)
            h = int(terrain.num_rows * cp)
            self._canvas.configure(scrollregion=(0, 0, w, h))

            img = tk.PhotoImage(width=w, height=h)
            color_map: Dict[int, str] = {}
            rows = terrain.grid
            cells_per_row = terrain.cells_per_row

            # Build flat pixel data for PhotoImage (format: "{r} {g} {b} ")
            pixel_data = ""
            for row_idx, row in enumerate(rows):
                if row_idx >= terrain.num_rows:
                    break
                for col_idx in range(cells_per_row):
                    val = row[col_idx] if col_idx < len(row) else 1
                    if val == 0:
                        pixel_data += "30 30 60 "  # walkable (dark blue)
                    else:
                        pixel_data += "10 10 25 "   # blocked (near black)
            img.put(pixel_data, to=(0, 0, w, h))

            self._img_id = self._canvas.create_image(0, 0, anchor=tk.NW, image=img)
            self._canvas.image = img  # prevent garbage collection

            # Draw grid lines at low zoom
            if zoom >= 1.5:
                for x in range(0, w + 1, max(1, int(50 * cp))):
                    self._canvas.create_line(x, 0, x, h, fill="#2a2a4a", width=1)
                for y in range(0, h + 1, max(1, int(50 * cp))):
                    self._canvas.create_line(0, y, w, y, fill="#2a2a4a", width=1)
        else:
            self._canvas.configure(scrollregion=(0, 0, 600, 500))
            self._canvas.create_text(
                300, 250, text="No terrain data yet — start following to load map.",
                fill="#555577", font=("", 11),
            )
            self._img_id = None
            return

        leader = self._leader_pos
        if leader is not None:
            lx = int(leader.x / terrain.cell_size * cp) if terrain else 0
            ly = int(leader.y / terrain.cell_size * cp) if terrain else 0
            pr = PLAYER_RADIUS + 2
            # glow
            self._canvas.create_oval(
                lx - pr - 2, ly - pr - 2, lx + pr + 2, ly + pr + 2,
                fill="#ff444444", outline="",
            )
            # leader dot
            self._canvas.create_oval(
                lx - pr, ly - pr, lx + pr, ly + pr,
                fill="#FF4444", outline="#FFFFFF", width=2,
            )
            self._canvas.create_text(lx, ly - pr - 8, text="Leader", fill="#FFFFFF", font=("", 8, "bold"))

            # auto-center on leader
            cw = self._canvas.winfo_width() or 600
            ch = self._canvas.winfo_height() or 500
            sx = max(0, lx - cw // 2)
            sy = max(0, ly - ch // 2)
            self._canvas.xview_moveto(sx / max(1, w))
            self._canvas.yview_moveto(sy / max(1, h))

        # Draw followers
        for i, (fx, fy, label) in enumerate(self._follower_positions):
            fx_px = int(fx / terrain.cell_size * cp) if terrain else 0
            fy_px = int(fy / terrain.cell_size * cp) if terrain else 0
            color = FOLLOWER_COLORS[i % len(FOLLOWER_COLORS)]
            pr = PLAYER_RADIUS
            # glow
            self._canvas.create_oval(
                fx_px - pr - 2, fy_px - pr - 2, fx_px + pr + 2, fy_px + pr + 2,
                fill=f"{color}44", outline="",
            )
            self._canvas.create_oval(
                fx_px - pr, fy_px - pr, fx_px + pr, fy_px + pr,
                fill=color, outline="#FFFFFF", width=1,
            )
            if label:
                self._canvas.create_text(fx_px, fy_px - pr - 6, text=label, fill=color, font=("", 7))
