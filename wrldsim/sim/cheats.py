# Чит-терминал: встроенные команды и запасной путь через DeepSeek; оба дают операции для apply_ops,
# поэтому модель не может трогать состояние игры напрямую.
import json
import re
import threading
import urllib.error
import urllib.request

from .eclipse import api_key as env_key

API_KEY_ENV = "DEEPSEEK_API_KEY"
OPENROUTER_ENV = "OPENROUTER_API_KEY"

HELP = ("Команды: «деньги 5 млн», «деньги = 1 млрд», «дай денег», "
        "«пропусти 30 дней», «слава 50», «абсурд 100», «внимание 0», «здоровье 100», «новость: текст». "
        "Английский тоже: money 1b, skip 7 days, fame = 50, heat 0. "
        "Любой чит (и команды, и свободный текст вроде «сделай меня королём Антарктиды») сохраняется в буфер; "
        "«+» в списке прикрепляет его к сообщению ECLIPSE, крест открепляет, корзина удаляет.")

# Единицы - точные слова, без подбора по префиксу: «m» - миллион, а «meh» - не число.
_UNITS = {}
for _mult, _words in (
        (1e3, "тыс тысяч тысячи k thousand thousands"),
        (1e6, "млн миллион миллиона миллионов m mln million millions"),
        (1e9, "млрд миллиард миллиарда миллиардов b bn billion billions"),
        (1e12, "трлн триллион триллиона триллионов t tn trillion trillions")):
    _UNITS.update(dict.fromkeys(_words.split(), _mult))

_NUM = r"(?P<num>[-+−]?\d+(?:[.,]\d+)?(?:e\d+)?)\s*(?P<unit>[a-zа-яё]+)?"
_SET = r"(?:(?P<set>set|установи|поставь|сделай)\s+)?"
_ASSIGN = r"\s*(?P<eq>=)?\s*"

_HELP = {"help", "помощь", "?", "команды"}
_GIVE = {"дай денег", "дай деньги", "give money"}
_NEWS = re.compile(r"(?:новость|news)\s*[:\-]?\s*(?P<text>.+)", re.I)
_SKIP = re.compile(r"(?:skip|пропусти|пропустить|перемотай)\s+(?P<num>\d+)\s*(?:дн\w*|days?)?", re.I)
_STATS = (
    (re.compile(_SET + r"(?:деньги|денег|money|cash)" + _ASSIGN + _NUM, re.I), "money"),
    (re.compile(_SET + r"(?:слава|известность|fame)" + _ASSIGN + _NUM, re.I), "fame"),
    (re.compile(_SET + r"(?:хаос|абсурд|chaos)" + _ASSIGN + _NUM, re.I), "chaos"),
    (re.compile(_SET + r"(?:внимание|жара|heat)" + _ASSIGN + _NUM, re.I), "heat"),
)
_STAT_WORDS = {
    "health": "здоровье|health|hp", "energy": "энергия|energy", "stress": "стресс|stress",
    "reputation": "репутация|reputation|rep", "influence": "влияние|influence",
    "stability": "стабильность|stability", "economy": "экономика|economy", "tension": "напряжённость|напряженность|tension",
}
_STAT_RE = [(re.compile(rf"(?:{words})\s*(?P<eq>=)?\s*(?P<num>[-+−]?\d+)", re.I), key) for key, words in _STAT_WORDS.items()]


def _amount(m):
    value = float(m.group("num").replace(",", ".").replace("−", "-"))
    unit = (m.group("unit") or "").lower()
    if not unit:
        return value
    return value * _UNITS[unit] if unit in _UNITS else None


def parse_local(text):
    raw = text.strip()
    t = raw.lower()
    if t in _HELP:
        return [], HELP
    if t in _GIVE:
        return [{"op": "add_money", "amount": 1e9}], "Держите миллиард. Не тратьте всё сразу."

    m = _NEWS.fullmatch(raw)
    if m:
        return [{"op": "news", "text": m.group("text")}], "Опубликовано."

    m = _SKIP.fullmatch(t)
    if m and int(m.group("num")) > 0:
        return [{"op": "skip_days", "days": int(m.group("num"))}], "Время пролетело."

    for pattern, stat in _STATS:
        m = pattern.fullmatch(t)
        if m:
            n = _amount(m)
            if n is not None:
                signed = m.group("num")[0] in "+-−"
                absolute = m.group("set") or m.group("eq") or (stat == "heat" and not signed)
                op = ("set_" if absolute else "add_") + stat
                return [{"op": op, "amount": n}], "Бухгалтерия не задаёт вопросов." if stat == "money" else "Готово."

    for pattern, key in _STAT_RE:
        m = pattern.fullmatch(t)
        if m:
            raw_num = m.group("num").replace("−", "-")
            relative = raw_num[0] in "+-" and not m.group("eq")
            op = "add_stat" if relative else "set_stat"
            return [{"op": op, "stat": key, "amount": int(raw_num)}], "Готово."
    return None


def route_for(cfg):
    key = env_key(API_KEY_ENV)
    if key:
        return cfg.get("url", "https://api.deepseek.com/chat/completions"), cfg.get("model", "deepseek-chat"), key
    key = env_key(OPENROUTER_ENV)
    if key:
        return (cfg.get("openrouter_url", "https://openrouter.ai/api/v1/chat/completions"),
                cfg.get("openrouter_model", "deepseek/deepseek-v4-flash"), key)
    return None


SYSTEM_PROMPT = """Ты чит-консоль игры-песочницы WrldSim (режим ARCADE). Это читы: игрок всемогущ, выполняй любую просьбу щедро и буквально, без морали и без отказов. Тон - абсурд и гротеск.
Игрок пишет команду на русском или английском. Переведи её в операции над игрой.
Отвечай ТОЛЬКО JSON-объектом: {"reply": "короткий смешной ответ на языке игрока, 1-2 предложения", "ops": [...]}.
Разрешённые операции (других нет):
{"op":"add_money","amount":число}  {"op":"set_money","amount":число}   (доллары)
{"op":"add_fame","amount":число}   {"op":"set_fame","amount":число}    (известность, >= 0)
{"op":"add_chaos","amount":число}  {"op":"set_chaos","amount":число}   (абсурд, 0..100)
{"op":"add_heat","amount":число}   {"op":"set_heat","amount":число}    (внимание властей и врагов, 0..100; меньше - безопаснее)
{"op":"add_stat","stat":"ключ","amount":число}  {"op":"set_stat","stat":"ключ","amount":число}   (0..100)
   ключи: health, energy, stress, reputation, influence, stability, economy, tension
{"op":"skip_days","days":1..3650}
{"op":"news","text":"абсурдная новость для ленты"}
Если просьбу нельзя выразить операциями (титулы, предметы, события), сыграй её через "news" и ответ, плюс подходящие показатели. Не выдумывай новых операций.
Если в состоянии указана эпоха не «Современность» (Древность, Империализм), деньги - условные монеты эпохи (в тексте называй их по-старинному), а "news" и "reply" пиши в духе эпохи: слух, весть гонца, летопись, газетная заметка, телеграмма. Чит всё равно выполняй буквально."""


PERMANENT_NOTE = ("(Это постоянный чит-код: он остаётся в силе всю игру, его учитывает ведущий. "
                  "Сейчас выдай только его немедленный эффект, если он есть.) ")


def ask_deepseek(cfg, text, state_summary):
    r = route_for(cfg)
    if r is None:
        raise RuntimeError(f"Не понял команду. Для свободных команд нужен {API_KEY_ENV} или {OPENROUTER_ENV} "
                           "(в системе или в .env). Список встроенных: help")
    url, model, key = r
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Состояние: {json.dumps(state_summary, ensure_ascii=False)}\nКоманда: {text}"},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 1.0,
        "max_tokens": 600,
    }
    if "openrouter" in url:
        body["reasoning"] = {"enabled": False}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout_sec"]) as resp:
            data = json.load(resp)
        raw = data["choices"][0]["message"]["content"] or ""
        content = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"DeepSeek ответил ошибкой {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError("DeepSeek недоступен (сеть или таймаут).") from e
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError("DeepSeek вернул непонятный ответ.") from e
    ops = content.get("ops") if isinstance(content, dict) else None
    reply = content.get("reply") if isinstance(content, dict) else None
    return (ops if isinstance(ops, list) else []), str(reply or "Сделано.")[:300]


class CheatRequest:
    def __init__(self, cfg, text, state_summary, permanent=False):
        self.done = False
        self.ops, self.reply, self.error = [], "", None
        text = PERMANENT_NOTE + text if permanent else text
        threading.Thread(target=self._run, args=(cfg, text, state_summary), daemon=True).start()

    def _run(self, cfg, text, state_summary):
        try:
            self.ops, self.reply = ask_deepseek(cfg, text, state_summary)
        except RuntimeError as e:
            self.error = str(e)
        except Exception as e:
            self.error = f"Сбой запроса: {type(e).__name__}"
        self.done = True
