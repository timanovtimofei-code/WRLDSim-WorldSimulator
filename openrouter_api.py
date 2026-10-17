"""Готовый клиент OpenRouter для модели deepseek/deepseek-v4-flash.

Без сторонних библиотек (только стандартная Python). Ключ берётся из переменной
окружения OPENROUTER_API_KEY.

Использование в коде:
    from openrouter_api import ask
    reply = ask("Привет!")
    reply = ask([{"role": "system", "content": "..."}, {"role": "user", "content": "..."}])

Проверка из консоли:
    python openrouter_api.py "Скажи привет"
"""
import json
import os
import sys
import urllib.error
import urllib.request

URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "deepseek/deepseek-v4-flash"
KEY_ENV = "OPENROUTER_API_KEY"
TIMEOUT_SEC = 60

# Системный промпт - prompt.txt рядом с этим файлом; нет файла - запрос без промпта.
PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.txt")


def load_prompt():
    try:
        with open(PROMPT_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def ask(messages, *, system=None, json_mode=False, reasoning=False, temperature=1.0, max_tokens=800, full=False):
    """Отправляет запрос. messages - строка или список {"role", "content"}.

    system - необязательный системный промпт (строка). Свой промпт удобно держать
    в отдельном файле: ask("текст", system=open("prompt.txt", encoding="utf-8").read())

    Возвращает текст ответа (или весь JSON-ответ, если full=True).
    Бросает RuntimeError с понятным текстом при любой ошибке.
    """
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(f"Не задана переменная окружения {KEY_ENV}.")
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    system = system or load_prompt()
    if system:
        messages = [{"role": "system", "content": system}] + list(messages)
    body = {"model": MODEL, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if reasoning:
        body["reasoning"] = {"enabled": True}
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"OpenRouter ответил ошибкой {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"OpenRouter недоступен (сеть или таймаут): {e}") from e
    except ValueError as e:
        raise RuntimeError("OpenRouter вернул не JSON.") from e
    if full:
        return data
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Неожиданный формат ответа: {json.dumps(data, ensure_ascii=False)[:500]}") from e


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) or "Ответь одним словом: работает?"
    try:
        result = ask(prompt, full=True)
    except RuntimeError as err:
        print("ОШИБКА:", err)
        sys.exit(1)
    print("Модель:", result.get("model"))
    print("Ответ:", result["choices"][0]["message"].get("content"))
    print("Токены:", result.get("usage"))
