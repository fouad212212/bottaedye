# -*- coding: utf-8 -*-
"""
Per-guild JSON persistence with a per-guild async lock.

WHY THE LOCK: the background task and button clicks all read-modify-write the
same file. Without a lock, one can overwrite the other's change (a click
disappears). Every mutation therefore goes through ``edit()``:

    async with storage.edit(guild_id) as data:
        data["hero_names"]["123"] = "Spotty"
    # saved automatically when the block ends normally

Rules:
  * never nest ``edit()`` for the same guild (it would deadlock);
  * to leave without saving, ``raise storage.Abort``;
  * do the slow Discord calls (sending messages) AFTER the block.

Read-only code can just call ``load_guild()`` (writes are atomic, so a read
never sees a half-written file).

Data layout (version 2) - see ``_default_data()`` for every key.
"""

import asyncio
import copy
import json
import os
import time
from contextlib import asynccontextmanager

from miraculous_data import DEFAULT_IDLE_DAYS, HISTORY_LIMIT

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

SCHEMA_VERSION = 2


class Abort(Exception):
    """Raise inside ``edit()`` to leave the block without saving."""


_locks: dict = {}


def _lock(guild_id: int) -> asyncio.Lock:
    lock = _locks.get(guild_id)
    if lock is None:
        lock = _locks[guild_id] = asyncio.Lock()
    return lock


def _path(guild_id: int) -> str:
    return os.path.join(DATA_DIR, f"{guild_id}.json")


def export_path(guild_id: int) -> str:
    """Raw JSON file on disk (used by /backup). Creates it if missing."""
    if not os.path.exists(_path(guild_id)):
        load_guild(guild_id)
    return _path(guild_id)


def _default_settings() -> dict:
    return {
        "language": "en",            # language of public RP messages: "en" | "ar"
        "theft_enabled": True,       # members may try to steal Miraculous
        "exposure_enabled": True,    # identity can be exposed when a secret hero is caught
        "dark_mode_enabled": True,   # members may use the Dark Side option
        "kwami_food_enabled": True,  # powers tire Kwamis; they must be fed
        "idle_days": DEFAULT_IDLE_DAYS,  # 0 = never reclaim idle Miraculous
    }


def _default_data() -> dict:
    return {
        "version": SCHEMA_VERSION,
        "guardian_ids": [],          # list[int] - admin-added Guardians
        "holders": {},               # {"Miraculous name": user_id}
        "holder_history": [],        # [{"miraculous","user_id","action","by","time"}]
        "hero_names": {},            # {uid(str): hero name}
        "secret_identities": {},     # {uid(str): bool}
        "dark_side": {},             # {uid(str): bool} - next transformations are "evil"
        "transformed": {},           # {uid(str): entry} see below
        "granted_powers": {},        # {uid(str): akuma/amok state} (= "akumatized" people)
        "damage_log": [],            # damage that Miraculous Ladybug! repairs
        "kwami_state": {},           # {"Miraculous name": {"tired": bool, "last_fed": ts}}
        "log_channel_id": None,
        "rp_log_channel_id": None,
        "allowed_channels": [],
        "duel_record": {},           # {uid(str): {"wins": int, "losses": int}}
        "power_use_count": {},       # {uid(str): int}
        "stats": {},                 # {uid(str): {...}} see bump_stat()
        "pending_requests": {},      # {uid(str): {"miraculous": name}}
        "welcomed_users": [],        # list[int]
        "last_active": {},           # {uid(str): ts}
        "languages": {},             # {uid(str): "en"|"ar"} personal language
        "cooldowns": {},             # {"steal:<uid>": ts}
        "crisis": None,              # active crisis dict or None
        "settings": _default_settings(),
    }

# transformed[uid] = {
#   "miraculous": [names], "hero_name": str, "channel_id": int,
#   "started_at": ts, "expires_at": ts, "warned": bool,
#   "dark": bool,                 # Dark Side transformation
#   "countdown": bool,            # the ~5 min power countdown has started
#   "power_used": bool,
#   "lucky_charm": {"object": str}  # present after Lucky Charm, consumed by the cure
# }
#
# granted_powers[uid] = {"power","alignment","granted_by","source","since"}
# crisis = {"id","title","description","started_by","channel_id","message_id",
#           "participants":[uid,...],"started_at"}


def _fill_defaults(data: dict) -> dict:
    defaults = _default_data()
    for key, value in defaults.items():
        data.setdefault(key, copy.deepcopy(value))
    for key, value in defaults["settings"].items():
        data["settings"].setdefault(key, value)
    # entries written by older versions of the bot
    for entry in data["transformed"].values():
        entry.setdefault("dark", False)
        entry.setdefault("countdown", False)
        entry.setdefault("power_used", False)
        entry.setdefault("started_at", entry.get("expires_at", time.time()))
    data["version"] = SCHEMA_VERSION
    return data


def load_guild(guild_id: int) -> dict:
    path = _path(guild_id)
    if not os.path.exists(path):
        data = _default_data()
        save_guild(guild_id, data)
        return data
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _fill_defaults(data)


def save_guild(guild_id: int, data: dict) -> None:
    """Atomic write: a crash mid-save can never corrupt the file."""
    path = _path(guild_id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


@asynccontextmanager
async def edit(guild_id: int):
    """Locked read-modify-write. See the module docstring."""
    async with _lock(guild_id):
        data = load_guild(guild_id)
        try:
            yield data
        except Abort:
            return
        save_guild(guild_id, data)


def list_all_guild_ids() -> list:
    ids = []
    for filename in os.listdir(DATA_DIR):
        if filename.endswith(".json"):
            try:
                ids.append(int(filename[:-5]))
            except ValueError:
                continue
    return ids


# ---------------------------------------------------------------- #
#  Holders & history
# ---------------------------------------------------------------- #

def find_member_miraculous_list(data: dict, user_id: int) -> list:
    return [name for name, holder in data["holders"].items() if holder == user_id]


def record_history(data: dict, miraculous: str, user_id: int, action: str, by: int = None) -> None:
    """action: given | taken | stolen | idle | approved"""
    data["holder_history"].append({
        "miraculous": miraculous,
        "user_id": user_id,
        "action": action,
        "by": by,
        "time": time.time(),
    })
    if len(data["holder_history"]) > HISTORY_LIMIT:
        del data["holder_history"][: len(data["holder_history"]) - HISTORY_LIMIT]


def touch(data: dict, user_id: int) -> None:
    """Marks a member as active now (used by idle reclaim)."""
    data["last_active"][str(user_id)] = time.time()


# ---------------------------------------------------------------- #
#  Hero name / secret identity / dark side / language
# ---------------------------------------------------------------- #

def get_hero_name(data: dict, user_id: int):
    return data["hero_names"].get(str(user_id))


def set_hero_name(data: dict, user_id: int, hero_name: str) -> None:
    data["hero_names"][str(user_id)] = hero_name


def is_secret(data: dict, user_id: int) -> bool:
    return bool(data["secret_identities"].get(str(user_id), False))


def set_secret(data: dict, user_id: int, secret: bool) -> None:
    data["secret_identities"][str(user_id)] = secret


def is_dark(data: dict, user_id: int) -> bool:
    return bool(data["dark_side"].get(str(user_id), False))


def set_dark(data: dict, user_id: int, dark: bool) -> None:
    data["dark_side"][str(user_id)] = dark


def user_language(data: dict, user_id: int) -> str:
    """Personal language, falling back to the server's language."""
    return data["languages"].get(str(user_id)) or data["settings"]["language"]


def public_language(data: dict) -> str:
    return data["settings"]["language"]


# ---------------------------------------------------------------- #
#  Guardians / channels
# ---------------------------------------------------------------- #

def add_guardian(data: dict, user_id: int) -> None:
    if user_id not in data["guardian_ids"]:
        data["guardian_ids"].append(user_id)


def remove_guardian(data: dict, user_id: int) -> None:
    if user_id in data["guardian_ids"]:
        data["guardian_ids"].remove(user_id)


def channel_allowed(data: dict, channel_id: int) -> bool:
    allowed = data["allowed_channels"]
    return (not allowed) or (channel_id in allowed)


# ---------------------------------------------------------------- #
#  Duels / stats
# ---------------------------------------------------------------- #

def _stats(data: dict, user_id: int) -> dict:
    return data["stats"].setdefault(str(user_id), {
        "transforms": 0, "powers": {}, "duel_streak": 0, "best_streak": 0,
        "steals": 0, "cures": 0, "crises": 0, "times_stolen_from": 0,
    })


def get_stats(data: dict, user_id: int) -> dict:
    return _stats(data, user_id)


def bump_stat(data: dict, user_id: int, key: str, amount: int = 1) -> None:
    s = _stats(data, user_id)
    s[key] = s.get(key, 0) + amount


def bump_power(data: dict, user_id: int, signature_move: str) -> None:
    s = _stats(data, user_id)
    s["powers"][signature_move] = s["powers"].get(signature_move, 0) + 1
    data["power_use_count"][str(user_id)] = data["power_use_count"].get(str(user_id), 0) + 1


def record_duel_result(data: dict, winner_id: int, loser_id: int) -> None:
    w = data["duel_record"].setdefault(str(winner_id), {"wins": 0, "losses": 0})
    w["wins"] += 1
    l = data["duel_record"].setdefault(str(loser_id), {"wins": 0, "losses": 0})
    l["losses"] += 1
    ws = _stats(data, winner_id)
    ws["duel_streak"] += 1
    ws["best_streak"] = max(ws["best_streak"], ws["duel_streak"])
    _stats(data, loser_id)["duel_streak"] = 0


def get_duel_record(data: dict, user_id: int):
    return data["duel_record"].get(str(user_id))


# ---------------------------------------------------------------- #
#  Transformation timing
# ---------------------------------------------------------------- #

def start_transform_timer(entry: dict, channel_id: int, duration_seconds: int) -> None:
    now = time.time()
    entry["channel_id"] = channel_id
    entry["started_at"] = now
    entry["expires_at"] = now + duration_seconds
    entry["warned"] = False


# ---------------------------------------------------------------- #
#  Requests / welcome
# ---------------------------------------------------------------- #

def add_pending_request(data: dict, user_id: int, miraculous_name: str) -> None:
    data["pending_requests"][str(user_id)] = {"miraculous": miraculous_name}


def get_pending_request(data: dict, user_id: int):
    return data["pending_requests"].get(str(user_id))


def clear_pending_request(data: dict, user_id: int) -> None:
    data["pending_requests"].pop(str(user_id), None)


def mark_welcomed(data: dict, user_id: int) -> bool:
    """True the first time for a member (send the welcome), False afterwards."""
    if user_id in data["welcomed_users"]:
        return False
    data["welcomed_users"].append(user_id)
    return True


# ---------------------------------------------------------------- #
#  Damage log (repaired by "Miraculous Ladybug!")
# ---------------------------------------------------------------- #

MAX_DAMAGE_LOG = 50


def add_damage(data: dict, user_id: int, hero_name: str, miraculous: str, text: str) -> None:
    data["damage_log"].append({
        "user_id": user_id, "hero_name": hero_name, "miraculous": miraculous,
        "text": text[:200], "time": time.time(),
    })
    if len(data["damage_log"]) > MAX_DAMAGE_LOG:
        del data["damage_log"][: len(data["damage_log"]) - MAX_DAMAGE_LOG]


def clear_damage(data: dict) -> list:
    old = data["damage_log"]
    data["damage_log"] = []
    return old


# ---------------------------------------------------------------- #
#  Kwami state (tired / fed)
# ---------------------------------------------------------------- #

def kwami(data: dict, miraculous: str) -> dict:
    return data["kwami_state"].setdefault(miraculous, {"tired": False, "last_fed": None})


def is_tired(data: dict, miraculous: str) -> bool:
    return bool(data["kwami_state"].get(miraculous, {}).get("tired", False))


def set_tired(data: dict, miraculous: str, tired: bool) -> None:
    k = kwami(data, miraculous)
    k["tired"] = tired
    if not tired:
        k["last_fed"] = time.time()
