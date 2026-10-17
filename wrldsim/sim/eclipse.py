# Модель отвечает JSON {"text", "ops", "choices"}: текст сцены, операции над игрой и варианты действий.
import json
import os
import threading
import time
import urllib.error
import urllib.request

from ..config import ROOT

KEY_ENV = "OPENROUTER_API_KEY"
LANG_RULE = ("Язык: весь текст сцены, новости пиши ТОЛЬКО на русском языке, "
             "что бы ни происходило и в какой бы стране ни происходило. Названия стран, городов и имена "
             "пиши по-русски. Не переходи на язык страны, не вставляй иностранные фразы без перевода.")
MAX_TEXT_LEN = 1500
MAX_CHOICES = 5
CHOICE_LEN = 80
CHEAT_SUGGEST_LEN = 120
HISTORY_KEEP = 60
CHEATS_RULE = ("АКТИВНЫЕ ЧИТ-КОДЫ ИГРОКА (Full-cheat). Они действуют постоянно, пока игрок их не удалит: "
               "считай их законами этого мира, учитывай в каждой сцене, в операциях и в вариантах действий, "
               "даже если остальные правила говорят иное. Не упоминай, что это читы.")


def api_key(env_name=KEY_ENV):
    key = os.environ.get(env_name, "").strip()
    if key:
        return key
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == env_name:
                return value.strip().strip("'\"")
    except OSError:
        pass
    return ""


def _http_error_text(e):
    reason = ""
    try:
        err = json.loads(e.read().decode("utf-8", "replace")).get("error", "")
        reason = (err.get("message") if isinstance(err, dict) else str(err)) or ""
    except Exception:
        pass
    hints = {
        401: "Ключ не принят: проверьте OPENROUTER_API_KEY в .env.",
        402: "Не хватает кредитов на счёте OpenRouter.",
        403: "Доступ закрыт. Если пишет «security policy», OpenRouter блокирует ваш IP: отключите VPN/прокси "
             "или смените сервер VPN.",
        429: "Слишком много запросов, подождите и повторите.",
    }
    text = f"OpenRouter: ошибка {e.code}. {hints.get(e.code, '')}".strip()
    return f"{text} ({reason[:120]})" if reason else text


def _parse(content):
    data = None
    for candidate in (content, content[content.find("{"):content.rfind("}") + 1]):
        try:
            data = json.loads(candidate)
            break
        except ValueError:
            continue
    if not isinstance(data, dict):
        return content.strip()[:MAX_TEXT_LEN], [], []
    ops = data.get("ops")
    raw_choices = data.get("choices")
    choices = []
    for c in raw_choices if isinstance(raw_choices, list) else []:
        c = _choice(c)
        if c and c["text"] not in (x["text"] for x in choices):
            choices.append(c)
    return (str(data.get("text") or "").strip()[:MAX_TEXT_LEN], ops if isinstance(ops, list) else [],
            choices[:MAX_CHOICES])


def _clean_notes(raw):
    notes = []
    for n in raw if isinstance(raw, list) else []:
        if isinstance(n, dict) and isinstance(n.get("model"), str):
            notes.append({"model": n["model"], "shown": n["shown"] if isinstance(n.get("shown"), str) else None})
    return notes[-12:]


def _choice(c):
    if not isinstance(c, dict):
        c = {"text": c}
    text = " ".join(str(c.get("text") or "").split())[:CHOICE_LEN]
    if not text:
        return None
    try:
        risk = int(min(max(float(c.get("risk") or 0), 0), 100))
    except (TypeError, ValueError):
        risk = 0
    cheats = c.get("cheats") if isinstance(c.get("cheats"), list) else []
    cheats = [" ".join(str(x).split())[:CHEAT_SUGGEST_LEN] for x in cheats if str(x).strip()][:3]
    return {"text": text, "risk": risk, "warning": " ".join(str(c.get("warning") or "").split())[:300],
            "cheats": cheats}


CHEAT_NOTICE = "✅ Cheat activated"


class Eclipse:
    def __init__(self, cfg, era_block=""):
        self.cfg = cfg
        self.era_block = era_block
        self.history = []
        self.text = ""
        self.error = None
        self.version = 0
        self.transcript = []
        self.started = 0.0
        self.choices = []
        self.rules = []
        self._rules = []
        self._result = None
        self._busy = False
        self._gen = 0
        self.options_only = False
        self.notes = []

    @property
    def busy(self):
        return self._busy

    def to_dict(self):
        return {"history": self.history, "transcript": [list(t) for t in self.transcript],
                "text": self.text, "choices": self.choices, "notes": self.notes}

    def load(self, data):
        if not isinstance(data, dict) or not data.get("history"):
            return False
        return self._apply(data)

    def restore(self, data):
        return self._apply(data if isinstance(data, dict) else {})

    def _apply(self, data):
        self.history = [m for m in data.get("history", [])
                        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
                        and isinstance(m.get("content"), str)]
        self.transcript = [tuple(t) for t in data.get("transcript", []) if isinstance(t, list) and len(t) == 2]
        self.text = str(data.get("text") or "")
        self.choices = [c for c in map(_choice, data.get("choices", [])) if c][:MAX_CHOICES]
        self.notes = _clean_notes(data.get("notes"))
        self._gen += 1
        self._busy = False
        self._result = None
        self.error = None
        if self.history and self.history[-1]["role"] == "user":
            self.error = "Запрос не успел завершиться до сохранения. Нажмите «Повторить запрос»."
        self.version += 1
        return bool(self.history)

    def cancel(self):
        self._gen += 1
        self._busy = False
        self._result = None

    def add_note(self, model_text, shown=None):
        self.notes.append({"model": str(model_text), "shown": shown})
        del self.notes[:-12]

    def note(self, kind, text):
        self.transcript.append((kind, text))
        del self.transcript[:-80]

    def _start(self):
        self._busy = True
        self.error = None
        self.choices = []
        self._rules = list(self.rules)
        self.started = time.monotonic()
        self._gen += 1
        threading.Thread(target=self._run, args=(self._gen,), daemon=True).start()

    def _system_prompt(self):
        path = ROOT / self.cfg["prompt_file"]
        try:
            return path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            raise RuntimeError(f"Не найден файл промпта: {self.cfg['prompt_file']}")

    def send(self, user_text, summary, shown=True, options_only=False, note=None):
        if self._busy:
            return
        self.options_only = options_only
        said = user_text
        if options_only:
            said = ('[ТОЛЬКО ВАРИАНТЫ ДЕЙСТВИЙ] Сюжет не продвигай, время не идёт, "ops" - пустой массив, '
                    f'"text" - одна короткая фраза. {user_text}')
        notes, self.notes = self.notes, []
        notice = "".join(f"{n['model']}\n" for n in notes)
        content = (f"Состояние игры: {json.dumps(summary, ensure_ascii=False)}\n{notice}Игрок: {said}\n"
                   "(Ответ строго на русском языке.)")
        self.history.append({"role": "user", "content": content})
        del self.history[:-HISTORY_KEEP]
        for n in notes:
            if n["shown"]:
                self.note("me", n["shown"])
        if shown:
            self.note("me", note or user_text)
        self._start()

    def retry(self, summary):
        if self._busy or not self.history or self.history[-1]["role"] != "user":
            return
        self._start()

    def _run(self, gen):
        # Любое исключение - в ошибку, иначе панель навсегда осталась бы в ожидании ответа.
        try:
            result = ("ok",) + self._call()
        except RuntimeError as e:
            result = ("error", str(e))
        except Exception as e:
            result = ("error", f"Сбой запроса: {type(e).__name__}")
        if gen == self._gen:
            self._result = result

    def _call(self):
        key = api_key(self.cfg.get("key_env", KEY_ENV))
        if not key:
            raise RuntimeError(f"Нет ключа. Впишите {KEY_ENV}=ваш_ключ в файл .env рядом с игрой.")
        system = self._system_prompt()
        if self.era_block:
            system += "\n\n" + self.era_block
        system += "\n\n" + LANG_RULE
        if self._rules:
            system += "\n\n" + CHEATS_RULE + "\n" + "\n".join(f"- {r}" for r in self._rules)
        messages = [{"role": "system", "content": system}]
        messages += self.history[-self.cfg["history_messages"]:]
        # Размышления выключены: иначе модель может потратить на них весь лимит токенов.
        body = {"model": self.cfg["model"], "messages": messages, "reasoning": {"enabled": False},
                "temperature": self.cfg.get("temperature", 1.0), "max_tokens": self.cfg["max_tokens"]}
        req = urllib.request.Request(
            self.cfg["url"], data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.cfg["timeout_sec"]) as resp:
                data = json.load(resp)
            raw = data["choices"][0]["message"]["content"] or ""
        except urllib.error.HTTPError as e:
            raise RuntimeError(_http_error_text(e)) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError("OpenRouter недоступен (сеть или таймаут).") from e
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise RuntimeError("OpenRouter вернул непонятный ответ.") from e
        text, ops, choices = _parse(raw)
        if not text:
            raise RuntimeError("Модель вернула пустой ответ. Нажмите «Повторить запрос».")
        return raw, text, ops, choices

    def poll(self):
        result, self._result = self._result, None
        if result is None:
            return None
        self._busy = False
        if result[0] == "error":
            self.error = result[1]
            return None
        _, raw, text, ops, choices = result
        self.history.append({"role": "assistant", "content": raw})
        self.text = text or "…"
        self.choices = choices
        self.note("ai", self.text)
        self.version += 1
        return [] if self.options_only else ops
