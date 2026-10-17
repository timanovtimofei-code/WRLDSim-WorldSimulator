# Скачивает флаги стран с flagcdn.com в data/flags/<ISO2>.png: python tools/fetch_flags.py
# Эмодзи-флаги Windows не рисует (показывает буквы), поэтому флаги - картинки.
import pickle
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wrldsim import config  # noqa: E402

URL = "https://flagcdn.com/w160/{code}.png"


def main():
    with open(config.WORLD_CACHE, "rb") as f:
        countries = pickle.load(f)["countries"]
    config.FLAGS_DIR.mkdir(parents=True, exist_ok=True)

    got, missing = 0, []
    for c in countries:
        code = c["iso2"]
        if not code:
            missing.append(c["name"])
            continue
        dest = config.FLAGS_DIR / f"{code}.png"
        if dest.exists():
            got += 1
            continue
        req = urllib.request.Request(URL.format(code=code.lower()), headers={"User-Agent": "WrldSim/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                dest.write_bytes(resp.read())
            got += 1
        except urllib.error.URLError as e:
            missing.append(f"{c['name']} ({code}: {e})")

    print(f"Флагов: {got}. Без флага: {len(missing)}")
    for name in missing:
        print("  -", name)


if __name__ == "__main__":
    main()
