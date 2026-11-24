import re

from .model import Issue, norm

MONEY = re.compile(
    r"\d[\d\s]{2,}\s*(?:руб|₽|р\b)|(?:оклад|зарплат|доход|оплат)\w*\D{0,25}\d{4,}", re.I
)
EMPLOYMENT_HINT = re.compile(
    r"занятост|полн\w+ (?:рабоч|день|ставк)|неполн|частичн|совместител|стажиров|ставк", re.I
)
SCHEDULE_HINT = re.compile(
    r"график|смен|\b\d\s*/\s*\d\b|\d{1,2}[:.]\d{2}|понедельник|пятниц|выходн|вахт"
    r"|рабоч\w+ (?:день|недел)",
    re.I,
)
CODE_IN_TITLE = re.compile(r"\b\d{3,}\S*")
YEARS = re.compile(r"(?:не менее|минимум|от)\s+(\d+)\s+(?:лет|года|год)\b", re.I)
SOFT = re.compile(r"желател|приветству|плюсом|предпочтительн", re.I)
EXPERIENCE_FIELDS = ("requirement.qualification", "requirements", "duty", "qualification")


def _only_region(address, region):
    def clean(text):
        text = re.sub(r"[^\w\s]", " ", norm(text))
        return " ".join(w for w in text.split() if w not in ("россия", "область", "обл"))

    return bool(region) and clean(address) == clean(region)


def check(v):
    issues = []
    f = v.fields

    if v.salary_min == 0 and v.salary_max == 0 and not MONEY.search(v.text_except("salary")):
        issues.append(
            Issue(
                "оплата",
                "salary_min",
                "",
                "Размер оплаты не указан ни в полях, ни в описании.",
                "Указать оклад или диапазон в рублях, а если часть дохода переменная, "
                "пояснить, из чего она складывается.",
                "rule",
            )
        )
    elif 0 < v.salary_max < v.salary_min:
        issues.append(
            Issue(
                "оплата",
                "salary_min",
                str(v.salary_min),
                "Нижняя граница оплаты больше верхней.",
                "Проверить и исправить границы оплаты.",
                "rule",
                {"field": "salary_max", "quote": str(v.salary_max)},
            )
        )

    if "employment" not in f and not EMPLOYMENT_HINT.search(v.text_except("salary")):
        issues.append(
            Issue(
                "тип занятости",
                "employment",
                "",
                "Тип занятости не указан.",
                "Уточнить, какая занятость предлагается: полная или неполная, "
                "постоянная или временная.",
                "rule",
            )
        )

    has_schedule = any(k in f for k in ("schedule", "scheduleTypeComment", "shift"))
    if not has_schedule and not SCHEDULE_HINT.search(v.text_except("salary")):
        issues.append(
            Issue(
                "график",
                "schedule",
                "",
                "График работы не указан.",
                "Указать дни недели, часы работы и режим (например, пятидневка, сменный график).",
                "rule",
            )
        )

    place = f.get("addresses.address.location", "")
    if not place:
        issues.append(
            Issue(
                "место работы",
                "addresses.address.location",
                "",
                "Место работы не указано.",
                "Указать населённый пункт и адрес, где соискателю предстоит работать.",
                "rule",
            )
        )
    elif _only_region(place, v.region):
        issues.append(
            Issue(
                "место работы",
                "addresses.address.location",
                place,
                "Место работы указано только на уровне региона.",
                "Уточнить населённый пункт и адрес рабочего места.",
                "rule",
            )
        )

    title = f.get("job-name", "")
    code = CODE_IN_TITLE.search(title)
    if code:
        issues.append(
            Issue(
                "название",
                "job-name",
                title,
                f"В названии должности есть код «{code.group(0)}», который ничего не говорит соискателю.",
                "Заменить код понятным названием должности.",
                "rule",
            )
        )

    if v.experience == 0:
        for key in EXPERIENCE_FIELDS:
            text = f.get(key, "")
            hit = next(
                (m for m in YEARS.finditer(text) if not SOFT.search(text[max(0, m.start() - 40) : m.end() + 40])),
                None,
            )
            if hit:
                issues.append(
                    Issue(
                        "требования",
                        "requirement.experience",
                        "0",
                        f"В поле опыта указано 0 лет, а в тексте требуется «{hit.group(0)}».",
                        "Уточнить, какой стаж действительно нужен, и привести поля в соответствие.",
                        "rule",
                        {"field": key, "quote": hit.group(0)},
                    )
                )
                break

    return issues
