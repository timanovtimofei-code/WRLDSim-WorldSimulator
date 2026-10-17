import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from ..config import CACHE_DIR
from ..ui import format as fmt
from .eclipse import _http_error_text, api_key

CATEGORIES = ["Недвижимость", "Транспорт", "Бизнес", "Электроника", "Роскошь", "Охрана", "Услуги", "Чёрный рынок"]
ITEMS_PER_PAGE = 12
NAME_LEN = 60
DESC_LEN = 220
SELL_SHARE = 0.6
INVENTORY_MAX = 200
IMG_DIR = CACHE_DIR / "shop_img"
PEXELS_ENV = "PEXELS_API_KEY"
USER_AGENT = "WrldSim/0.1 (game; shop images)"

SYSTEM = (
    "Ты - каталог магазина в игре-симуляторе жизни. По состоянию игры (страна, дата, герой, деньги) "
    "и запросу игрока придумай товары, которые реально можно купить в этой стране в эту эпоху. "
    "Цена - число в ДОЛЛАРАХ США по курсу, НЕ в рублях и не в местной валюте (пример: квартира в Москве "
    "около 300000, хороший автомобиль 30000-100000). Разброс цен широкий: от доступного герою до явно "
    "недоступного. Ответ строго JSON без пояснений: "
    '{"items": [{"name": "название по-русски", "price": число, "description": "1-2 предложения по-русски: '
    'что это и чем полезно в жизни героя", "image_query": "2-3 простых английских слова о том, как товар выглядит, без '
    'названий городов, стран и брендов (пример: luxury apartment interior, sports car, bodyguard)"}]}. '
    f"Ровно {ITEMS_PER_PAGE} товаров, без повторов.")

SYSTEM_ERA = (
    "Ты - каталог магазина в игре-симуляторе жизни. По состоянию игры (государство, дата, эпоха, герой, деньги) "
    "и запросу игрока придумай товары, которые реально можно было купить или заказать в этом государстве в "
    "этот год. Никаких анахронизмов: только то, что существовало тогда и там. Цена - число в игровой денежной "
    "единице (условные монеты эпохи; в описаниях называй их так, как указано в поле «монеты» состояния игры), "
    "соразмерное деньгам героя и ценам того времени. Разброс цен широкий: от доступного герою до явно "
    "недоступного. Ответ строго JSON без пояснений: "
    '{"items": [{"name": "название по-русски", "price": число, "description": "1-2 предложения по-русски: '
    'что это и чем полезно в жизни героя", "image_query": "2-3 простых английских слова о том, как товар выглядит '
    '(можно replica, antique, museum), без названий городов, стран и брендов (пример: bronze sword, wooden ship, '
    'silk cloth)"}]}. '
    f"Ровно {ITEMS_PER_PAGE} товаров, без повторов.")


def _clean_items(raw):
    data = None
    for candidate in (raw, raw[raw.find("{"):raw.rfind("}") + 1]):
        try:
            data = json.loads(candidate)
            break
        except ValueError:
            continue
    items = []
    for it in (data or {}).get("items", []) if isinstance(data, dict) else []:
        if not isinstance(it, dict):
            continue
        name = " ".join(str(it.get("name") or "").split())[:NAME_LEN]
        try:
            price = float(it.get("price"))
        except (TypeError, ValueError):
            continue
        if not name or not (price > 0) or price > 1e13 or name in (x["name"] for x in items):
            continue
        items.append({"name": name, "price": round(price, 2),
                      "description": " ".join(str(it.get("description") or "").split())[:DESC_LEN],
                      "image_query": " ".join(str(it.get("image_query") or name).split())[:60]})
    return items[:ITEMS_PER_PAGE]


class CatalogRequest:
    def __init__(self, cfg, summary, category, query=""):
        self.cfg = cfg
        self.done = False
        self.error = None
        self.items = []
        self.category, self.query = category, query
        topic = f"Поиск игрока: «{query}»" if query else f"Категория: {category}"
        self._system = SYSTEM_ERA if summary.get("монеты") else SYSTEM
        self._user = f"Состояние игры: {json.dumps(summary, ensure_ascii=False)}\n{topic}"
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.items = self._call()
            if not self.items:
                self.error = "Модель не прислала товаров. Нажмите «Обновить»."
        except RuntimeError as e:
            self.error = str(e)
        except Exception as e:
            self.error = f"Сбой запроса: {type(e).__name__}"
        self.done = True

    def _call(self):
        key = api_key(self.cfg.get("key_env", "OPENROUTER_API_KEY"))
        if not key:
            raise RuntimeError("Нет ключа OPENROUTER_API_KEY: магазину нужен ИИ для каталога.")
        body = {"model": self.cfg["model"], "reasoning": {"enabled": False}, "temperature": 0.9,
                "max_tokens": 2500, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": self._system}, {"role": "user", "content": self._user}]}
        req = urllib.request.Request(self.cfg["url"], data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.cfg["timeout_sec"]) as resp:
                raw = json.load(resp)["choices"][0]["message"]["content"] or ""
        except urllib.error.HTTPError as e:
            raise RuntimeError(_http_error_text(e)) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError("OpenRouter недоступен (сеть или таймаут).") from e
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise RuntimeError("OpenRouter вернул непонятный ответ.") from e
        return _clean_items(raw)


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def _find_pexels(query, key):
    data = _get_json("https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "per_page": 1, "orientation": "landscape"}), {"Authorization": key})
    photos = data.get("photos") or []
    return photos[0]["src"]["medium"] if photos else None


def _find_openverse(query):
    data = _get_json("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": query, "page_size": 3, "mature": "false"}))
    for r in data.get("results") or []:
        if r.get("thumbnail") or r.get("url"):
            return r.get("thumbnail") or r["url"]
    return None


def _find_commons(query):
    data = _get_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 3,
        "gsrsearch": f"filetype:bitmap {query}", "prop": "imageinfo", "iiprop": "url|mime", "iiurlwidth": 400}))
    pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") in ("image/jpeg", "image/png") and info.get("thumburl"):
            return info["thumburl"]
    return None


class ImageFetcher:
    def __init__(self):
        self._state = {}
        self._lock = threading.Lock()
        self._sem = threading.Semaphore(4)

    @staticmethod
    def _file(query):
        return IMG_DIR / (hashlib.sha1(query.lower().encode("utf-8")).hexdigest()[:20] + ".img")

    def path(self, query):
        if not query:
            return None
        with self._lock:
            st = self._state.get(query)
            if st is None:
                f = self._file(query)
                if f.exists():
                    self._state[query] = st = (str(f) if f.stat().st_size else "missing")
                else:
                    self._state[query] = st = "loading"
                    threading.Thread(target=self._load, args=(query,), daemon=True).start()
        return None if st in ("loading", "missing") else st

    def _load(self, query):
        f = self._file(query)
        result = "missing"
        with self._sem:
            try:
                key = api_key(PEXELS_ENV)
                url = _find_pexels(query, key) if key else None
                for find in (() if url else (_find_openverse, _find_commons)):
                    try:
                        url = find(query)
                    except Exception:
                        url = None
                    if url:
                        break
                if url:
                    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        data = resp.read(4_000_000)
                    IMG_DIR.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(data)
                    result = str(f)
            except Exception:
                # Сеть или сервис недоступны: в этот запуск не повторяем и на диск ничего не пишем.
                pass
        with self._lock:
            self._state[query] = result


def inventory(state):
    return state.setdefault("inventory", [])


def buy(game, item, price):
    if game.s["money"] < price:
        return False
    game.s["money"] -= price
    inv = inventory(game.s)
    inv.append({"name": item["name"], "price": price, "description": item.get("description", ""),
                "image_query": item.get("image_query", ""), "minute": game.s["minute"]})
    del inv[:-INVENTORY_MAX]
    game.log(f"Покупка: {item['name']} за {fmt.usd(price)}.", "minus")
    return True


def sell(game, index):
    inv = inventory(game.s)
    if not 0 <= index < len(inv):
        return None
    item = inv.pop(index)
    gain = round(item["price"] * SELL_SHARE, 2)
    game._add_money(gain)
    game.log(f"Продано: {item['name']} за {fmt.usd(gain)}.", "plus")
    return gain
