from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class CharacterConfig:
    """A single character within an account window.

    slot: 0 = P1 (keyboard), 1 = P2 (gamepad)
    role: "leader" (manual control, no injection) or "follower"
    input_method: auto-inferred from slot if empty ("keyboard" | "gamepad")
    """
    slot: int
    role: str
    input_method: str = ""


@dataclass
class AccountConfig:
    """One PoE2 window with 1-2 characters in local co-op.

    id: unique account identifier ("main", "alt", ...)
    window_title: substring to match for HWND detection
    characters: 1-2 CharacterConfig entries (slot 0 required)
    """
    id: str
    window_title: str
    characters: List[CharacterConfig] = field(default_factory=list)


@dataclass
class SamplingConfig:
    tick_ms: int = 50
    turn_threshold: float = 15.0


@dataclass
class RuntimeConfig:
    max_follower_lag_ms: int = 200
    max_drift_ticks: int = 10
    regroup_cooldown_ms: int = 3000
    pause_on_resolution_mismatch: bool = True


@dataclass
class PartyConfig:
    accounts: List[AccountConfig] = field(default_factory=list)
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    nav: Optional[Dict[str, Any]] = None


def _parse_aob_pattern(raw: dict) -> dict:
    hex_str: str = raw.get("bytes", "")
    parts = hex_str.strip().split()
    pattern: List[int] = []
    mask: List[int] = []
    for p in parts:
        if p in ("?", "??"):
            pattern.append(0)
            mask.append(0)
        else:
            pattern.append(int(p, 16))
            mask.append(0xFF)
    return {
        "bytes": bytes(pattern),
        "mask": bytes(mask),
        "disp_offset": int(raw.get("disp_offset", 3)),
        "instr_len": int(raw.get("instr_len", 7)),
    }


def _default_input_method(slot: int, role: str) -> str:
    if role == "leader":
        return "none"
    if slot == 0:
        return "keyboard"
    return "gamepad"


def load_config(path: str) -> PartyConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw:
        raise ValueError("Config file is empty.")

    # ── accounts ──
    accounts_raw = raw.get("accounts", [])
    if not isinstance(accounts_raw, list):
        raise ValueError("'accounts' must be a list.")
    if not accounts_raw:
        raise ValueError("At least one account is required.")

    seen_acct_ids: set = set()
    accounts: list[AccountConfig] = []
    for a_raw in accounts_raw:
        a_id = a_raw.get("id")
        if not a_id or not isinstance(a_id, str):
            raise ValueError("Each account must have a non-empty 'id'.")
        if a_id in seen_acct_ids:
            raise ValueError(f"Duplicate account id: {a_id}")
        seen_acct_ids.add(a_id)

        window_title = a_raw.get("window_title", "Path of Exile 2")

        chars_raw = a_raw.get("characters", [])
        if not isinstance(chars_raw, list):
            raise ValueError(f"account.{a_id}.characters must be a list.")
        if len(chars_raw) < 1:
            raise ValueError(f"account.{a_id} must have at least 1 character.")
        if len(chars_raw) > 2:
            raise ValueError(f"account.{a_id} has {len(chars_raw)} characters — max 2 for local co-op.")

        seen_slots: set = set()
        characters: list[CharacterConfig] = []
        for c_raw in chars_raw:
            slot = c_raw.get("slot")
            if slot not in (0, 1):
                raise ValueError(f"account.{a_id} character slot must be 0 or 1, got {slot}.")
            if slot in seen_slots:
                raise ValueError(f"account.{a_id} duplicate character slot {slot}.")
            seen_slots.add(slot)

            role = c_raw.get("role")
            if role not in ("leader", "follower"):
                raise ValueError(
                    f"account.{a_id} slot {slot} role must be 'leader' or 'follower', got {role!r}."
                )

            input_method = c_raw.get("input_method", "")
            if input_method not in ("", "keyboard", "gamepad", "none"):
                raise ValueError(
                    f"account.{a_id} slot {slot} invalid input_method {input_method!r}."
                    f" Must be keyboard, gamepad, none, or omit for auto."
                )
            if not input_method:
                input_method = _default_input_method(slot, role)

            characters.append(CharacterConfig(slot=slot, role=role, input_method=input_method))

        accounts.append(AccountConfig(id=a_id, window_title=window_title, characters=characters))

    # ── leader validation ──
    leader_slots = [
        (acct.id, ch.slot) for acct in accounts for ch in acct.characters if ch.role == "leader"
    ]
    if not leader_slots:
        raise ValueError("No leader assigned — exactly one character must have role 'leader'.")
    if len(leader_slots) > 1:
        ids = ", ".join(f"{aid}:{slot}" for aid, slot in leader_slots)
        raise ValueError(f"Multiple leaders assigned: {ids}. Exactly one leader required.")

    # ── sampling ──
    sampling_raw = raw.get("sampling", {})
    sampling = SamplingConfig(
        tick_ms=int(sampling_raw.get("tick_ms", 50)),
        turn_threshold=float(sampling_raw.get("turn_threshold", 15)),
    )
    if sampling.tick_ms <= 0:
        raise ValueError("sampling.tick_ms must be > 0.")

    # ── runtime ──
    runtime_raw = raw.get("runtime", {})
    runtime = RuntimeConfig(
        max_follower_lag_ms=int(runtime_raw.get("max_follower_lag_ms", 200)),
        max_drift_ticks=int(runtime_raw.get("max_drift_ticks", 10)),
        regroup_cooldown_ms=int(runtime_raw.get("regroup_cooldown_ms", 3000)),
        pause_on_resolution_mismatch=bool(
            runtime_raw.get("pause_on_resolution_mismatch", True)
        ),
    )

    # ── nav (PoE2 offsets) ──
    nav: Optional[Dict[str, Any]] = None
    nav_raw = raw.get("nav")
    if nav_raw:
        aob_raw = nav_raw.get("aob", {})
        aob: Dict[str, dict] = {}
        for name in aob_raw:
            aob[name] = _parse_aob_pattern(aob_raw[name])

        behavior = nav_raw.get("behavior", {})
        nav = {
            "aob": aob,
            "offsets": nav_raw.get("offsets", {}),
            "world_to_grid_ratio": float(nav_raw.get("world_to_grid_ratio", 10.8696)),
            "render_component_name": nav_raw.get("render_component_name", "Render"),
            "player_component_name": nav_raw.get("player_component_name", "Player"),
            "player_component": nav_raw.get("player_component", {}),
            "entity_path": nav_raw.get("entity_path", {}),
            "portal": nav_raw.get("portal", {}),
            "flask": nav_raw.get("flask", {}),
            "auto_loot": nav_raw.get("auto_loot", {}),
            "death": nav_raw.get("death", {}),
            "behavior": {
                "formation": behavior.get("formation", {}),
                "anti_stuck": behavior.get("anti_stuck", {}),
            },
        }

    return PartyConfig(
        accounts=accounts,
        sampling=sampling,
        runtime=runtime,
        nav=nav,
    )
