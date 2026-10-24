"""球団・球場の材料で共用する、公式照合済みの収容人数。"""
import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "data/venue_capacities.json"
CAPACITIES = json.loads(SOURCE.read_text(encoding="utf-8"))["venues"]


def apply_capacity(venue):
    """APIの元データを壊さず、照合済みの球場だけ人数を統一する。"""
    record = CAPACITIES.get(venue.get("name"))
    if record is None:
        return venue
    return {**venue, "fieldInfo": {**(venue.get("fieldInfo") or {}),
                                   "capacity": record["capacity"]}}


def capacity_note(name):
    return CAPACITIES.get(name, {}).get("display_note", "")
