# Слоты сохранений: saves/<режим>_<номер>.json = {"meta", "game", "eclipse"}; у каждого героя свой слот.
import json
import os
from datetime import datetime

from .. import config


def slot_path(mode_id, slot):
    return config.SAVES_DIR / f"{mode_id}_{slot}.json"


def read_meta(mode_id, slots):
    result = {}
    for slot in range(1, slots + 1):
        try:
            with open(slot_path(mode_id, slot), encoding="utf-8") as f:
                result[slot] = json.load(f)["meta"]
        except (OSError, ValueError, KeyError):
            result[slot] = None
    return result


def save(mode_id, slot, game_state, meta, eclipse=None):
    config.SAVES_DIR.mkdir(exist_ok=True)
    path = slot_path(mode_id, slot)
    tmp = path.with_suffix(".tmp")
    meta = {**meta, "mode_id": mode_id, "saved_at": datetime.now().isoformat(timespec="seconds")}
    data = {"meta": meta, "game": game_state}
    if eclipse is not None:
        data["eclipse"] = eclipse
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load(mode_id, slot):
    with open(slot_path(mode_id, slot), encoding="utf-8") as f:
        return json.load(f)


def delete(mode_id, slot):
    path = slot_path(mode_id, slot)
    existed = path.exists()
    path.unlink(missing_ok=True)
    path.with_suffix(".tmp").unlink(missing_ok=True)
    return existed


def read_raw(mode_id, slot):
    try:
        return slot_path(mode_id, slot).read_bytes()
    except OSError:
        return None


def restore_raw(mode_id, slot, raw):
    path = slot_path(mode_id, slot)
    if raw is None:
        path.unlink(missing_ok=True)
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)


def slot_for(mode_id, slots, save_id):
    meta = read_meta(mode_id, slots)
    for slot, m in meta.items():
        if m and m.get("save_id") == save_id:
            return slot
    return next((s for s, m in meta.items() if m is None), None)


def latest_mode():
    if not config.SAVES_DIR.exists():
        return None
    files = list(config.SAVES_DIR.glob("*_*.json"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime).stem.rsplit("_", 1)[0]


def any_saves():
    return config.SAVES_DIR.exists() and any(config.SAVES_DIR.glob("*_*.json"))
