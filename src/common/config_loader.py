"""Configuration loader for PoE2 multi-client auto-follow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class LeaderConfig:
    """Leader (main) role configuration."""

    role_id: str


@dataclass
class FollowerConfig:
    """Follower role configuration."""

    role_id: str
    window_title: str


@dataclass
class SamplingConfig:
    """Input sampling parameters."""

    tick_ms: int = 50
    turn_threshold: float = 15.0


@dataclass
class RuntimeConfig:
    """Runtime behaviour parameters."""

    max_follower_lag_ms: int = 200
    max_drift_ticks: int = 10
    regroup_cooldown_ms: int = 3000
    pause_on_resolution_mismatch: bool = True


@dataclass
class PartyConfig:
    """Complete party configuration for a follow session."""

    leader: LeaderConfig
    followers: List[FollowerConfig] = field(default_factory=list)
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    nav: Optional[Dict[str, Any]] = None


def _parse_aob_pattern(raw: dict) -> dict:
    hex_str: str = raw.get("bytes", "")
    parts = hex_str.strip().split()
    pattern: List[int] = []  # -1 = wildcard
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


def load_config(path: str) -> PartyConfig:
    """Load and validate party configuration from a YAML file.

    Args:
        path: Filesystem path to the YAML configuration file.

    Returns:
        A validated PartyConfig instance.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If required fields are missing or invalid.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw:
        raise ValueError("Config file is empty.")

    # --- leader ---
    leader_raw = raw.get("leader")
    if not leader_raw:
        raise ValueError("Missing 'leader' section in config.")
    role_id = leader_raw.get("role_id")
    if not role_id or not isinstance(role_id, str):
        raise ValueError("leader.role_id must be a non-empty string.")
    leader = LeaderConfig(role_id=role_id)

    # --- followers ---
    followers_raw = raw.get("followers", [])
    if not isinstance(followers_raw, list):
        raise ValueError("'followers' must be a list.")
    if len(followers_raw) < 1 or len(followers_raw) > 5:
        raise ValueError(f"Expected 1-5 followers, got {len(followers_raw)}.")

    seen_ids: set = set()
    followers: list[FollowerConfig] = []
    for i, f_raw in enumerate(followers_raw):
        f_role = f_raw.get("role_id")
        if not f_role or not isinstance(f_role, str):
            raise ValueError(f"follower[{i}].role_id must be a non-empty string.")
        if f_role in seen_ids:
            raise ValueError(f"Duplicate follower role_id: {f_role}")
        seen_ids.add(f_role)

        f_title = f_raw.get("window_title", "Path of Exile 2")
        followers.append(FollowerConfig(role_id=f_role, window_title=f_title))

    # --- sampling ---
    sampling_raw = raw.get("sampling", {})
    sampling = SamplingConfig(
        tick_ms=int(sampling_raw.get("tick_ms", 50)),
        turn_threshold=float(sampling_raw.get("turn_threshold", 15)),
    )
    if sampling.tick_ms <= 0:
        raise ValueError("sampling.tick_ms must be > 0.")

    # --- runtime ---
    runtime_raw = raw.get("runtime", {})
    runtime = RuntimeConfig(
        max_follower_lag_ms=int(runtime_raw.get("max_follower_lag_ms", 200)),
        max_drift_ticks=int(runtime_raw.get("max_drift_ticks", 10)),
        regroup_cooldown_ms=int(runtime_raw.get("regroup_cooldown_ms", 3000)),
        pause_on_resolution_mismatch=bool(
            runtime_raw.get("pause_on_resolution_mismatch", True)
        ),
    )

    # --- nav (PoE2 offsets) ---
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
            "world_to_grid_ratio": float(
                nav_raw.get("world_to_grid_ratio", 10.8696)
            ),
            "render_component_name": nav_raw.get("render_component_name", "Render"),
            "behavior": {
                "formation": behavior.get("formation", {}),
                "anti_stuck": behavior.get("anti_stuck", {}),
            },
        }

    return PartyConfig(
        leader=leader,
        followers=followers,
        sampling=sampling,
        runtime=runtime,
        nav=nav,
    )
