"""UI mockup — non-functional wireframe for design review.

Run: python mockup.py
Shows 2 screens: Launcher → Main Dashboard
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# ── Color palette ────────────────────────────────────────────
BG_DARK = "#1a1a2e"
BG_PANEL = "#16213e"
BG_CARD = "#0f3460"
ACCENT = "#e94560"
ACCENT2 = "#00d2ff"
TEXT = "#e0e0e0"
TEXT_DIM = "#888888"
GREEN = "#4ade80"
YELLOW = "#fbbf24"
ORANGE = "#f97316"
WHITE = "#ffffff"

FONT_TITLE = ("Segoe UI", 13, "bold")
FONT_HEADER = ("Segoe UI", 11, "bold")
FONT_BODY = ("Segoe UI", 10)
FONT_MONO = ("Consolas", 9)
FONT_SMALL = ("Segoe UI", 8)


def make_screen1() -> tk.Tk:
    """Screen 1: Multi-Launcher."""
    root = tk.Tk()
    root.title("PoE2 Multi-Launcher  —  UI Mockup")
    root.geometry("600x520")
    root.configure(bg=BG_DARK)
    root.resizable(False, False)

    # ── Header ────────────────────────────────────────────────
    header = tk.Frame(root, bg=BG_PANEL, padx=20, pady=12)
    header.pack(fill="x")
    tk.Label(header, text="🔧  PoE2  Multi-Launcher", font=FONT_TITLE,
             fg=WHITE, bg=BG_PANEL).pack(side="left")
    tk.Label(header, text="Step 1 / 2", font=FONT_SMALL,
             fg=TEXT_DIM, bg=BG_PANEL).pack(side="right", pady=4)

    # ── Account cards ─────────────────────────────────────────
    section = tk.Frame(root, bg=BG_DARK, padx=20, pady=16)
    section.pack(fill="both", expand=True)

    tk.Label(section, text="Accounts", font=FONT_HEADER,
             fg=TEXT, bg=BG_DARK, anchor="w").pack(fill="x")

    desc = tk.Label(section,
        text="Each account launches 1 PoE2 window (local co-op = 2 characters).\n"
             "One physical controller + one virtual gamepad per window.",
        font=FONT_BODY, fg=TEXT_DIM, bg=BG_DARK, anchor="w", justify="left")
    desc.pack(fill="x", pady=(4, 12))

    accounts = [
        ("Account A", "Main account", "physical gamepad", True),
        ("Account B", "Alt account", "virtual gamepad", True),
        ("Account C", "Not active", "—", False),
    ]

    for name, desc_text, controller, enabled in accounts:
        card = tk.Frame(section, bg=BG_CARD if enabled else "#1a1a2e",
                        padx=14, pady=10, relief="solid",
                        bd=1 if enabled else 0)
        card.pack(fill="x", pady=(0, 8))

        left = tk.Frame(card, bg=card["bg"])
        left.pack(side="left")

        status_color = GREEN if enabled else TEXT_DIM
        status_text = "● Active" if enabled else "○ Disabled"

        tk.Label(left, text=f"{name}  —  {desc_text}", font=FONT_BODY,
                 fg=WHITE if enabled else TEXT_DIM, bg=card["bg"]).pack(anchor="w")
        tk.Label(left, text=f"{status_text}    Controller: {controller}",
                 font=FONT_SMALL, fg=status_color, bg=card["bg"]).pack(anchor="w")

        # Launch / Config buttons
        right = tk.Frame(card, bg=card["bg"])
        right.pack(side="right")
        if enabled:
            btn_style = {"font": FONT_SMALL, "padx": 10, "pady": 3}
            tk.Button(right, text="Configure", **btn_style,
                      bg="#2d2d5e", fg=TEXT, bd=0).pack(side="left", padx=3)
            tk.Button(right, text="Launch", **btn_style,
                      bg=ACCENT, fg=WHITE, bd=0).pack(side="left", padx=3)

    # ── Add account button ────────────────────────────────────
    add_btn = tk.Frame(section, bg=BG_DARK)
    add_btn.pack(fill="x", pady=(4, 16))
    tk.Button(add_btn, text="+  Add Account", font=FONT_BODY,
              bg=BG_PANEL, fg=ACCENT2, bd=0, padx=14, pady=4).pack(side="left")

    # ── Bottom bar ────────────────────────────────────────────
    bottom = tk.Frame(section, bg=BG_DARK)
    bottom.pack(side="bottom", fill="x")

    tk.Label(bottom, text="Status:  All accounts ready", font=FONT_SMALL,
             fg=GREEN, bg=BG_DARK).pack(side="left")

    ttk.Separator(section, orient="horizontal").pack(fill="x", pady=12)

    tk.Button(bottom, text="Launch All & Continue  →", font=FONT_HEADER,
              bg=ACCENT, fg=WHITE, bd=0, padx=24, pady=10,
              command=root.destroy).pack(side="right")

    return root


def make_screen2() -> tk.Tk:
    """Screen 2: Main Dashboard (Follow Control)."""
    root = tk.Tk()
    root.title("PoE2 Auto-Follow  —  Dashboard  —  UI Mockup")
    root.geometry("1150x720")
    root.configure(bg=BG_DARK)
    root.minsize(900, 600)

    # ── Top bar ───────────────────────────────────────────────
    topbar = tk.Frame(root, bg=BG_PANEL, padx=16, pady=8)
    topbar.pack(fill="x")

    tk.Label(topbar, text="🎮  PoE2 Auto-Follow", font=FONT_TITLE,
             fg=WHITE, bg=BG_PANEL).pack(side="left")

    status_frame = tk.Frame(topbar, bg=BG_PANEL)
    status_frame.pack(side="right")

    for label, color in [("● Running", GREEN), ("Leader PID: 1234", TEXT_DIM),
                          ("Followers: 3/3", GREEN)]:
        tk.Label(status_frame, text=label, font=FONT_SMALL,
                 fg=color, bg=BG_PANEL).pack(side="left", padx=6)

    # ── Main content (left panel + right panel) ───────────────
    main = tk.Frame(root, bg=BG_DARK)
    main.pack(fill="both", expand=True, padx=8, pady=8)

    # ── LEFT PANEL: Character list ────────────────────────────
    left_panel = tk.Frame(main, bg=BG_PANEL, padx=12, pady=12, width=420)
    left_panel.pack(side="left", fill="y", padx=(0, 8))
    left_panel.pack_propagate(False)

    tk.Label(left_panel, text="Characters", font=FONT_HEADER,
             fg=WHITE, bg=BG_PANEL).pack(anchor="w")

    # Account A
    _section_label(left_panel, "Account A  (PID 1234)")

    _char_card(left_panel, "P1", "Monk_Lee", "Monk · Lv.85", "Leader",
               "Leader — physical controller", GREEN, ACCENT)
    _char_card(left_panel, "P2", "Ranger_Kai", "Ranger · Lv.82", "Follower",
               "Follower — VGamepad #1", GREEN, ACCENT2)

    tk.Frame(left_panel, bg=BG_PANEL, height=6).pack()

    # Account B
    _section_label(left_panel, "Account B  (PID 5678)")

    _char_card(left_panel, "P1", "Witch_Zara", "Witch · Lv.80", "Follower",
               "Follower — VGamepad #2", GREEN, YELLOW)
    _char_card(left_panel, "P2", "Warrior_Thor", "Warrior · Lv.78", "Follower",
               "Follower — VGamepad #3", GREEN, YELLOW)

    # ── RIGHT PANEL: Map + Controls ───────────────────────────
    right_panel = tk.Frame(main, bg=BG_PANEL, padx=12, pady=12)
    right_panel.pack(side="left", fill="both", expand=True)

    # Tab bar
    tabs = tk.Frame(right_panel, bg=BG_PANEL)
    tabs.pack(fill="x", pady=(0, 8))
    for text, active in [("Big Map", True), ("Detail View", False), ("Settings", False)]:
        bg = BG_CARD if active else BG_PANEL
        fg = ACCENT2 if active else TEXT_DIM
        tk.Label(tabs, text=text, font=FONT_BODY if active else FONT_SMALL,
                 fg=fg, bg=bg, padx=14, pady=4).pack(side="left", padx=(0, 2))

    # Map canvas placeholder
    map_frame = tk.Frame(right_panel, bg="#0a0a1a", height=300)
    map_frame.pack(fill="both", expand=True, pady=(0, 8))
    map_frame.pack_propagate(False)

    canvas = tk.Canvas(map_frame, bg="#0a0a1a", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    # Draw fake terrain grid
    w, h = 600, 300
    for x in range(0, w, 20):
        for y in range(0, h, 20):
            color = "#1a2a4a" if (x // 20 + y // 20) % 3 != 0 else "#0d1b33"
            canvas.create_rectangle(x, y, x + 20, y + 20, fill=color, outline="#0f2847")

    # Legend
    canvas.create_oval(300, 140, 308, 148, fill=ACCENT, outline="")
    canvas.create_text(316, 144, text="Leader", fill=TEXT, font=FONT_SMALL, anchor="w")

    for i, color in enumerate([GREEN, YELLOW, ORANGE]):
        cx = 440 + i * 100
        canvas.create_oval(cx, 140, cx + 8, 148, fill=color, outline="")
        canvas.create_text(cx + 14, 144, text=f"Follower {i + 1}",
                          fill=TEXT, font=FONT_SMALL, anchor="w")

    # Formation zone indicator
    canvas.create_rectangle(260, 110, 340, 130, outline=ACCENT2, dash=(3, 3))
    canvas.create_text(300, 120, text="Diamond Formation", fill=ACCENT2, font=FONT_SMALL)

    # ── Follower status table ─────────────────────────────────
    tk.Label(right_panel, text="Follower Status", font=FONT_HEADER,
             fg=WHITE, bg=BG_PANEL).pack(anchor="w", pady=(4, 4))

    table = ttk.Treeview(right_panel,
        columns=("char", "slot", "account", "role", "position", "status", "controller"),
        show="headings", height=4)

    table.heading("char", text="Character")
    table.heading("slot", text="Slot")
    table.heading("account", text="Account")
    table.heading("role", text="Role")
    table.heading("position", text="Position")
    table.heading("status", text="Status")
    table.heading("controller", text="Controller")

    for col in ("slot", "account", "role"):
        table.column(col, width=70)
    table.column("char", width=130)
    table.column("position", width=140)
    table.column("status", width=80)
    table.column("controller", width=130)

    table.pack(fill="x")

    rows = [
        ("Ranger_Kai", "P2", "A", "Follower 1", "(1523, 842, 10)", "Following", "VGamepad #1"),
        ("Witch_Zara", "P1", "B", "Follower 2", "(1547, 830, 10)", "Stuck ⚠", "VGamepad #2"),
        ("Warrior_Thor", "P2", "B", "Follower 3", "(1510, 858, 10)", "Following", "VGamepad #3"),
    ]
    for r in rows:
        table.insert("", "end", values=r)

    # ── Bottom control bar ────────────────────────────────────
    ctrl_bar = tk.Frame(right_panel, bg=BG_PANEL)
    ctrl_bar.pack(fill="x", pady=(8, 0))

    # Formation selector
    tk.Label(ctrl_bar, text="Formation:", font=FONT_SMALL,
             fg=TEXT_DIM, bg=BG_PANEL).pack(side="left", padx=(0, 4))
    fm_combo = ttk.Combobox(ctrl_bar, values=["Diamond", "Line", "V", "Free"],
                            width=10, state="readonly")
    fm_combo.set("Diamond")
    fm_combo.pack(side="left", padx=(0, 12))

    tk.Label(ctrl_bar, text="Spacing:", font=FONT_SMALL,
             fg=TEXT_DIM, bg=BG_PANEL).pack(side="left", padx=(0, 4))
    ttk.Scale(ctrl_bar, from_=20, to=100, value=35,
              length=80).pack(side="left", padx=(0, 16))
    tk.Label(ctrl_bar, text="35", font=FONT_SMALL,
             fg=WHITE, bg=BG_PANEL).pack(side="left", padx=(0, 12))

    # Zoom controls
    tk.Label(ctrl_bar, text="Map:", font=FONT_SMALL,
             fg=TEXT_DIM, bg=BG_PANEL).pack(side="left", padx=(0, 4))
    for text in ["−", "100%", "+"]:
        tk.Button(ctrl_bar, text=text, font=FONT_SMALL, padx=8,
                  bg=BG_CARD, fg=TEXT, bd=0).pack(side="left", padx=1)

    # Start/Stop
    ctrl_right = tk.Frame(ctrl_bar, bg=BG_PANEL)
    ctrl_right.pack(side="right")

    tk.Button(ctrl_right, text="⏸  Pause", font=FONT_BODY, padx=14, pady=4,
              bg="#7c3a00", fg=WHITE, bd=0).pack(side="right", padx=3)
    tk.Button(ctrl_right, text="⏹  Stop", font=FONT_BODY, padx=14, pady=4,
              bg=ACCENT, fg=WHITE, bd=0).pack(side="right", padx=3)
    tk.Button(ctrl_right, text="▶  Start Follow", font=FONT_BODY, padx=14, pady=4,
              bg="#1a6b3a", fg=WHITE, bd=0).pack(side="right", padx=3)

    # ── Log area (bottom strip) ───────────────────────────────
    log_frame = tk.Frame(root, bg="#0d0d1a", height=100)
    log_frame.pack(fill="x", side="bottom")
    log_frame.pack_propagate(False)

    tk.Label(log_frame, text="  Log", font=FONT_SMALL, fg=TEXT_DIM,
             bg="#0d0d1a", anchor="w").pack(fill="x")
    log_text = tk.Text(log_frame, bg="#0d0d1a", fg=TEXT_DIM, font=FONT_MONO,
                       height=4, bd=0, padx=8, pady=4)
    log_text.pack(fill="both", expand=True)
    log_text.insert("1.0",
        "[14:32:01] INFO     NavAgent started: 1 leader, 3 followers.\n"
        "[14:32:01] INFO     VGamepad #1 → Account A P2 (Ranger_Kai)\n"
        "[14:32:02] INFO     VGamepad #2 → Account B P1 (Witch_Zara)\n"
        "[14:32:02] INFO     VGamepad #3 → Account B P2 (Warrior_Thor)\n"
        "[14:32:05] WARNING  Follower 2 (Witch_Zara) stuck — initiating anti-stuck level 1 (jump)\n"
    )
    log_text.config(state="disabled")

    return root


def _section_label(parent, text):
    """Section header in left panel."""
    f = tk.Frame(parent, bg=BG_PANEL, pady=4)
    f.pack(fill="x", pady=(10, 2))
    tk.Label(f, text=text, font=FONT_SMALL, fg=ACCENT2, bg=BG_PANEL).pack(anchor="w")


def _char_card(parent, slot, name, class_lvl, role, controller_desc,
               status_color, accent_color):
    """A character card in the left panel."""
    card = tk.Frame(parent, bg=BG_CARD, padx=10, pady=8)
    card.pack(fill="x", pady=(0, 4))

    # Left side
    left = tk.Frame(card, bg=BG_CARD)
    left.pack(side="left")

    tk.Label(left, text=f"[{slot}]  {name}", font=FONT_BODY,
             fg=WHITE, bg=BG_CARD).pack(anchor="w")
    tk.Label(left, text=class_lvl, font=FONT_SMALL,
             fg=TEXT_DIM, bg=BG_CARD).pack(anchor="w")

    # Role badge
    badge = tk.Frame(card, bg=accent_color, padx=8, pady=2)
    badge.pack(side="right")
    tk.Label(badge, text=role, font=FONT_SMALL,
             fg=BG_DARK, bg=accent_color).pack()

    # Controller info
    tk.Label(card, text=controller_desc, font=FONT_SMALL,
             fg=TEXT_DIM, bg=BG_CARD).pack(side="right", padx=6)

    # Status dot
    tk.Label(card, text="●", font=("", 8), fg=status_color,
             bg=BG_CARD).pack(side="right", padx=(0, 2))


if __name__ == "__main__":
    root = make_screen1()
    root.mainloop()
    root2 = make_screen2()
    root2.mainloop()
