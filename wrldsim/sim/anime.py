import json
import threading
import time
import urllib.error
import urllib.request

from .eclipse import KEY_ENV, LANG_RULE, _http_error_text, api_key

SEARCH_RESULTS = 6
MAX_TOKENS = 3800
TIMEOUT_SEC = 150
TITLE_MAX = 80

RESEARCH_PROMPT = """Ты исследователь аниме, манги и ранобэ для текстовой игры. Игрок ввёл название произведения (на любом языке, возможно с ошибками или сокращённо). Найди его в интернете с помощью веб-поиска, определи, о каком произведении идёт речь, и собери карточку мира, по которой потом можно честно играть в этом мире.

Опирайся на найденные страницы (вики фанатов, Wikipedia, MyAnimeList, AniList, Shikimori и подобные), не выдумывай то, чего в произведении нет. Если вариантов несколько (сиквелы, ремейки), выбери самое известное и скажи об этом в summary. Если не нашёл ничего достоверного, верни {"found": false, "suggestions": ["название 1", "название 2"]}.

Отвечай ТОЛЬКО JSON-объектом, без пояснений вокруг:
{"found": true, "title": "оригинальное или международное название", "title_ru": "название по-русски", "kind": "аниме|манга|ранобэ|игра",
 "year": число или null, "genres": ["жанр", ...],
 "summary": "о чём произведение, 3-5 предложений, без финальных спойлеров",
 "setting": "где и когда происходит действие (мир, эпоха, страны, города)",
 "world_rules": "как устроен мир: система силы или магии, технологии, главные законы и ограничения, 4-7 предложений",
 "tone": "атмосфера и тон (юмор, драма, жестокость, романтика) в одну-две фразы",
 "factions": [{"name": "организация, клан, страна", "desc": "кто они и чего хотят"}],
 "characters": [{"name": "имя", "role": "кто это", "desc": "характер, способности, роль в сюжете, без спойлеров", "age": число или null, "gender": "М|Ж|иное|null"}],
 "locations": [{"name": "место", "desc": "что это"}],
 "starts": [{"label": "точка старта (арка, момент канона)", "note": "ситуация в этот момент: что происходит, кто рядом, что на кону"}]}

Нужно: 3-6 фракций, 6-10 персонажей (главные и значимые), 4-8 мест, 3-5 точек старта по порядку канона (первая - самое начало истории). Имена, названия мест и организаций пиши так, как их принято называть по-русски (в транскрипции или как в русском переводе), в скобках можно оригинал. Без откровенного 18+ контента."""

CLEAN_TEXT = {"summary": 800, "setting": 400, "world_rules": 900, "tone": 240}


def _s(value, limit):
    return " ".join(str(value or "").split())[:limit]


def _list(value, keys, limits, cap):
    out = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str):
            item = {keys[0]: item}
        if not isinstance(item, dict):
            continue
        row = {k: _s(item.get(k), lim) for k, lim in zip(keys, limits)}
        if row[keys[0]] and row[keys[0]].lower() not in (r[keys[0]].lower() for r in out):
            out.append(row)
    return out[:cap]


def clean_card(data):
    if not isinstance(data, dict):
        raise ValueError("ECLIPSE Prime вернул непонятный ответ.")
    if not data.get("found", True) or not data.get("title"):
        sug = [_s(x, 60) for x in (data.get("suggestions") or []) if str(x).strip()][:4]
        raise ValueError("Не нашёл такое аниме." + (" Может быть: " + "; ".join(sug) + "." if sug else ""))
    card = {"title": _s(data.get("title"), TITLE_MAX), "title_ru": _s(data.get("title_ru"), TITLE_MAX),
            "kind": _s(data.get("kind") or "аниме", 20),
            "genres": [_s(g, 24) for g in (data.get("genres") or []) if str(g).strip()][:5]}
    try:
        card["year"] = int(data["year"]) if data.get("year") else None
    except (TypeError, ValueError):
        card["year"] = None
    for key, limit in CLEAN_TEXT.items():
        card[key] = _s(data.get(key), limit)
    card["factions"] = _list(data.get("factions"), ("name", "desc"), (60, 200), 6)
    card["locations"] = _list(data.get("locations"), ("name", "desc"), (60, 160), 8)
    chars = _list(data.get("characters"), ("name", "role", "desc"), (60, 90, 260), 10)
    raw = data.get("characters") if isinstance(data.get("characters"), list) else []
    for row in chars:
        src = next((c for c in raw if isinstance(c, dict) and _s(c.get("name"), 60) == row["name"]), {})
        try:
            row["age"] = int(src["age"]) if src.get("age") else None
        except (TypeError, ValueError):
            row["age"] = None
        row["gender"] = _s(src.get("gender"), 8) if src.get("gender") else ""
    card["characters"] = chars
    starts = _list(data.get("starts"), ("label", "note"), (70, 260), 5)
    card["starts"] = starts or [{"label": "Начало истории", "note": "Канонический старт: история только начинается."}]
    if not card["summary"]:
        raise ValueError("Нашёл название, но не смог собрать описание мира. Попробуйте ещё раз.")
    return card


def card_name(card):
    ru, orig = card.get("title_ru"), card.get("title")
    return f"{ru} ({orig})" if ru and orig and ru.lower() != orig.lower() else (ru or orig or "Аниме")


def card_prompt(card, hero=None, start=None):
    lines = [f"МИР ИГРЫ: {card_name(card)} ({card.get('kind', 'аниме')}{', ' + str(card['year']) + ' г.' if card.get('year') else ''}).",
             f"Жанры: {', '.join(card.get('genres') or [])}." if card.get("genres") else "",
             f"О мире: {card.get('summary', '')}", f"Место и время: {card.get('setting', '')}",
             f"Правила мира: {card.get('world_rules', '')}", f"Тон: {card.get('tone', '')}"]
    if card.get("factions"):
        lines.append("Фракции: " + "; ".join(f"{f['name']} - {f['desc']}" for f in card["factions"]))
    if card.get("characters"):
        lines.append("Известные персонажи: " + "; ".join(
            f"{c['name']} ({c['role']}): {c['desc']}" for c in card["characters"]))
    if card.get("locations"):
        lines.append("Места: " + "; ".join(f"{p['name']} - {p['desc']}" for p in card["locations"]))
    if start:
        lines.append(f"ТОЧКА СТАРТА: {start['label']}. {start['note']}")
    if hero:
        lines.append(f"ГЕРОЙ ИГРОКА: {hero.get('name', '')} - {hero.get('role', '')}"
                     + (f", {hero['age']} лет" if hero.get("age") else "")
                     + (". Это персонаж канона: играй его в характере, остальные относятся к нему так, как в оригинале."
                        if hero.get("canon") else ". Это собственный персонаж игрока, который попал в этот мир."))
    return "\n".join(x for x in lines if x)


class AnimeResearch:
    def __init__(self, cfg, query):
        self.cfg = cfg
        self.query = " ".join(str(query).split())[:120]
        self.card = None
        self.error = None
        self.done = False
        self.started = time.monotonic()
        self.sources = []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.card = self._call()
        except RuntimeError as e:
            self.error = str(e)
        except ValueError as e:
            self.error = str(e)
        except Exception as e:
            self.error = f"Сбой поиска: {type(e).__name__}"
        self.done = True

    def _call(self):
        key = api_key(self.cfg.get("key_env", KEY_ENV))
        if not key:
            raise RuntimeError(f"Нет ключа. Задайте {KEY_ENV} в системе или в файле .env рядом с игрой.")
        system = RESEARCH_PROMPT + "\n\n" + LANG_RULE
        body = {"model": self.cfg["model"],
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": f"Название от игрока: «{self.query}»"}],
                "plugins": [{"id": "web", "max_results": SEARCH_RESULTS}],
                "reasoning": {"enabled": False}, "temperature": 0.3, "max_tokens": MAX_TOKENS}
        try:
            data = self._post(body, key)
        except urllib.error.HTTPError as e:
            if e.code not in (400, 404, 422):
                raise RuntimeError(_http_error_text(e)) from e
            # веб-плагин не принят: повторяем без интернета, по памяти модели
            body.pop("plugins")
            body["messages"][0]["content"] += ("\n\nИнтернет сейчас недоступен: опирайся на свои знания об этом "
                                              "произведении и ничего не выдумывай.")
            self.offline = True
            try:
                data = self._post(body, key)
            except urllib.error.HTTPError as e2:
                raise RuntimeError(_http_error_text(e2)) from e2
        try:
            message = data["choices"][0]["message"]
            raw = message.get("content") or ""
            for ann in message.get("annotations") or []:
                url = (ann.get("url_citation") or {}).get("url")
                if url and url not in self.sources:
                    self.sources.append(url)
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise RuntimeError("OpenRouter вернул непонятный ответ.") from e
        parsed = None
        for candidate in (raw, raw[raw.find("{"):raw.rfind("}") + 1]):
            try:
                parsed = json.loads(candidate)
                break
            except ValueError:
                continue
        if parsed is None:
            raise RuntimeError("Не удалось разобрать ответ ECLIPSE Prime. Попробуйте ещё раз.")
        card = clean_card(parsed)
        card["sources"] = self.sources[:4]
        card["offline"] = bool(getattr(self, "offline", False))
        return card

    def _post(self, body, key):
        req = urllib.request.Request(self.cfg["url"], data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                return json.load(resp)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError("OpenRouter недоступен (сеть или таймаут). Поиск в интернете занимает до пары минут.") from e
        except ValueError as e:
            raise RuntimeError("OpenRouter вернул непонятный ответ.") from e
