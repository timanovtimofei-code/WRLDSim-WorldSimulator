from pathlib import Path

import sys

# В собранном exe данные, сейвы и .env лежат рядом с ним, а не во временной папке.
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"
FLAGS_DIR = DATA_DIR / "flags"

WORLD_CACHE = CACHE_DIR / "world.pkl"
MODES_FILE = DATA_DIR / "modes.json"
COUNTRIES_FILE = DATA_DIR / "countries.json"
ARCADE_FILE = DATA_DIR / "arcade.json"
REALISM_FILE = DATA_DIR / "realism.json"
ROLES_FILE = DATA_DIR / "roles.json"
SAVES_DIR = ROOT / "saves"

TITLE = "WrldSim"
WINDOW_SIZE = (1600, 900)
MIN_WINDOW_SIZE = (800, 520)
FPS = 120
IDLE_AFTER = 1.5
IDLE_FPS = 15
