def number(x, digits=1):
    return f"{x:,.{digits}f}".replace(",", " ").replace(".", ",")


def people(n):
    if n >= 1e9:
        return f"{number(n / 1e9, 2)} млрд"
    if n >= 1e6:
        return f"{number(n / 1e6, 1)} млн"
    if n >= 1e3:
        return f"{number(n / 1e3, 0)} тыс."
    return number(n, 0)


_CURRENCY = ["$", ""]


def set_currency(prefix="$", suffix=""):
    _CURRENCY[0], _CURRENCY[1] = prefix, suffix


def usd(n, currency=None):
    if n >= 1e12:
        body = f"{number(n / 1e12, 2)} трлн"
    elif n >= 1e9:
        body = f"{number(n / 1e9, 1)} млрд"
    elif n >= 1e6:
        body = f"{number(n / 1e6, 0)} млн"
    else:
        body = number(n, 0)
    prefix, suffix = currency or _CURRENCY
    return f"{prefix}{body}{suffix}"


MONTHS_GEN_RU = ["января", "февраля", "марта", "апреля", "мая", "июня",
                 "июля", "августа", "сентября", "октября", "ноября", "декабря"]


MONTHS_SHORT_RU = ["янв.", "фев.", "мар.", "апр.", "мая", "июн.",
                   "июл.", "авг.", "сен.", "окт.", "ноя.", "дек."]


def date_ru(d):
    return f"{d.day} {MONTHS_GEN_RU[d.month - 1]} {d.year}"


def game_year(d, offset=0):
    year = d.year - offset
    return year if year > 0 else year - 1


def game_date_ru(d, offset=0, suffix=False, clock=True):
    year = game_year(d, offset)
    era = f"{-year} г. до н. э." if year < 0 else f"{year} г." if suffix else str(year)
    text = f"{d.day} {MONTHS_GEN_RU[d.month - 1]} {era}"
    return f"{text}, {d:%H:%M}" if clock else text


def game_short_ru(d, clock=True):
    text = f"{d.day} {MONTHS_SHORT_RU[d.month - 1]}"
    return f"{text} {d:%H:%M}" if clock else text


def plural(n, one, few, many):
    n = int(abs(n))
    if 11 <= n % 100 <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(n % 10, many)


def days(n):
    return f"{int(n)} {plural(n, 'день', 'дня', 'дней')}"


MIN_DAY = 1440
SPAN_UNITS = [("век", "века", "веков", 36500 * MIN_DAY),
              ("год", "года", "лет", 365 * MIN_DAY),
              ("месяц", "месяца", "месяцев", 30 * MIN_DAY),
              ("день", "дня", "дней", MIN_DAY),
              ("час", "часа", "часов", 60),
              ("минута", "минуты", "минут", 1)]


def span_ru(minutes):
    parts, rest = [], int(minutes)
    for one, few, many, size in SPAN_UNITS:
        n, rest = divmod(rest, size)
        if n:
            parts.append(f"{n} {plural(n, one, few, many)}")
    return " ".join(parts) or "0 минут"


CONTINENTS_RU = {
    "Asia": "Азия",
    "Europe": "Европа",
    "Africa": "Африка",
    "North America": "Северная Америка",
    "South America": "Южная Америка",
    "Oceania": "Океания",
    "Antarctica": "Антарктида",
    "Seven seas (open ocean)": "Открытый океан",
}

REGION_KINDS_RU = {
    "State": "Штат",
    "Province": "Провинция",
    "Region": "Регион",
    "Oblast": "Область",
    "Republic": "Республика",
    "Autonomous Republic": "Автономная республика",
    "Autonomous Okrug": "Автономный округ",
    "Autonomous Oblast": "Автономная область",
    "Autonomous Region": "Автономный район",
    "Krai": "Край",
    "Federal City": "Город федерального значения",
    "Federal District": "Федеральный округ",
    "Municipality": "Муниципалитет",
    "Prefecture": "Префектура",
    "Metropolis": "Столичная префектура",
    "Department": "Департамент",
    "Metropolitan Department": "Департамент",
    "County": "Графство",
    "District": "Округ",
    "Territory": "Территория",
    "Union Territory": "Союзная территория",
    "Special Municipality": "Особый муниципалитет",
    "Special Administrative Region": "Особый административный район",
}
