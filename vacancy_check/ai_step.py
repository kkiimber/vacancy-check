import hashlib
import json
import os
import re

from .llm import AIError
from .model import TOPICS, Issue, norm

PROMPT_VERSION = "3"
MAX_ISSUES = 8
STATUSES = ("понятно", "пропуск", "неоднозначно", "противоречие")

SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "enum": list(TOPICS)},
                    "status": {"type": "string", "enum": list(STATUSES)},
                    "note": {"type": "string"},
                },
                "required": ["topic", "status", "note"],
            },
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "enum": list(TOPICS)},
                    "field": {"type": "string"},
                    "quote": {"type": "string"},
                    "problem": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "conflicts_with": {
                        "type": "object",
                        "properties": {"field": {"type": "string"}, "quote": {"type": "string"}},
                        "required": ["field", "quote"],
                    },
                },
                "required": ["topic", "field", "quote", "problem", "recommendation"],
            },
        },
    },
    "required": ["topics", "issues"],
}

SYSTEM = """Ты помогаешь редактору вакансий подготовить уточнения для работодателя. \
Соискатель должен из вакансии понять условия работы. Найди пропуски, неоднозначные \
формулировки и противоречия.

Шаг 1. Пройди по всем семи темам: название, обязанности, требования, оплата, график, \
место работы, тип занятости. Для каждой запиши в topics статус и короткую заметку, где в \
вакансии лежат сведения:
- «понятно»: конкретные сведения есть хотя бы в одном поле;
- «пропуск»: сведений нет нигде;
- «неоднозначно»: есть только общая или расплывчатая формулировка без конкретики;
- «противоречие»: два места в вакансии говорят разное.

Шаг 2. По каждой теме со статусом не «понятно» запиши замечание в issues.

Что считается проблемой:
- расплывчатые формулировки без конкретики: «гибкий график» или «сменный график» без дней, \
часов или схемы смен, «разные поручения», «другие задачи по необходимости», «условия \
обсуждаются на собеседовании», «достойная оплата». Если расписание названо в другом поле, \
это не пропуск, но тогда проверь, не спорят ли поля друг с другом;
- слишком общее название должности («Специалист», «Сотрудник») без указания профиля;
- противоречия: удалённая работа и обязательное присутствие в офисе; один график в одном \
поле и другой в другом; опыт не нужен, но требуется стаж; разные города или адреса; \
полная занятость и частичная;
- пропуск сведений, которые соискателю нужны.

Что проблемой не считается:
- сведение есть в структурном поле, даже если описание его не повторяет;
- населённый пункт без улицы, если ничто в вакансии не говорит о неясном формате работы;
- сведения лежат не в том поле, но понятны;
- короткое описание, из которого всё ясно;
- отсутствие верхней границы оплаты, когда указана нижняя («от 35000»);
- короткие или общие требования («ответственность», «знание офисных программ»): не проси \
дополнить их образованием или навыками. Исключение: формулировки вроде «опыт \
приветствуется» или «желательно», когда соискатель не поймёт, обязательно ли это.

Как писать замечание:
- problem: одно полное предложение о том, что именно непонятно соискателю. Одно слово \
вроде «неоднозначность» или «противоречие» не годится.
- recommendation: что уточнить у работодателя, начинай с глагола в неопределённой форме \
(«Уточнить, ...», «Указать, ...»), один конкретный вопрос.
- quote: дословная цитата из вакансии без изменений. Для пропуска quote пустая строка, а \
в field имя поля, где сведения должны быть.
- Для противоречия в quote и field дай первое значение, в conflicts_with второе, обе \
цитаты дословные.

Пример. Вакансия: [job-name] Курьер, [schedule] Гибкий график, [duty] Доставка заказов. \
Замечание: {"topic": "график", "field": "schedule", "quote": "Гибкий график", \
"problem": "Не сказано, в какие дни и часы нужно работать при гибком графике.", \
"recommendation": "Уточнить, какие дни и часы обязательны и как согласуется расписание."}

Не придумывай факты, цифры и названия, не делай выводов о нарушении закона. Нулевая \
оплата означает, что оплата не указана. Не повторяй замечания, уже найденные \
автоматическими проверками. Верни только JSON."""


def build_prompt(v, known):
    lines = [f"Вакансия {v.id}"]
    lines += [f"[{key}] {text}" for key, text in v.fields.items()]
    lines.append(f"salary_min: {v.salary_min}")
    lines.append(f"salary_max: {v.salary_max}")
    if v.experience is not None:
        lines.append(f"requirement.experience (лет): {v.experience}")
    if known:
        lines.append("")
        lines.append("Уже найдено автоматическими проверками:")
        lines += [f"- {i.topic}, поле {i.field}: {i.problem}" for i in known]
    return SYSTEM, "\n".join(lines)


class Cache:
    def __init__(self, path, readonly=False):
        self.path = path
        self.readonly = readonly
        self.data = {}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)
        self.dirty = False

    def get(self, key):
        return self.data.get(key)

    def put(self, key, value):
        if self.readonly:
            return
        self.data[key] = value
        self.dirty = True

    def save(self):
        if not (self.path and self.dirty):
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1, sort_keys=True)
        self.dirty = False


def cache_key(system, user):
    raw = json.dumps([PROMPT_VERSION, system, user], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse(raw):
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\s*|\s*```$", "", text)
    data = json.loads(text)
    if isinstance(data, list):
        data = {"issues": data}
    if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
        raise ValueError("нет списка issues")
    topics = data.get("topics")
    return {"topics": topics if isinstance(topics, list) else [], "issues": data["issues"]}


PRESENT_IN = {
    "название": ("job-name",),
    "обязанности": ("duty",),
    "требования": ("requirements", "requirement.qualification", "qualification", "requirement.education"),
    "график": ("schedule", "scheduleTypeComment", "shift"),
    "место работы": ("addresses.address.location",),
    "тип занятости": ("employment",),
}


def has_data(v, topic):
    if topic == "оплата":
        return v.salary_min > 0 or v.salary_max > 0 or "salary" in v.fields
    return any(key in v.fields for key in PRESENT_IN[topic])


def _key(text):
    return norm(text).strip(" .,;:")


def validate(v, parsed, known):
    clear = {
        t.get("topic")
        for t in parsed["topics"]
        if isinstance(t, dict) and t.get("status") == "понятно"
    }
    taken = {(i.topic, i.field) for i in known}
    taken_topics = {i.topic for i in known}
    seen_pairs = set()
    out = []
    for item in parsed["issues"]:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic", "")).strip()
        field = str(item.get("field", "")).strip()
        quote = str(item.get("quote", "")).strip()
        problem = str(item.get("problem", "")).strip()
        advice = str(item.get("recommendation", "")).strip()
        if topic not in TOPICS or topic in clear:
            continue
        if len(problem.split()) < 5 or len(advice.split()) < 4:
            continue
        if not quote and has_data(v, topic):
            continue
        if quote:
            found = v.locate(quote, field)
            if not found:
                continue
            field = found
        elif not field:
            continue
        other = item.get("conflicts_with")
        conflict = None
        if isinstance(other, dict) and str(other.get("quote", "")).strip():
            oq = str(other["quote"]).strip()
            of = v.locate(oq, str(other.get("field", "")))
            if not of:
                continue
            conflict = {"field": of, "quote": oq}
        if (topic, field) in taken or (topic in taken_topics and not quote):
            continue
        pair = frozenset(
            [(field, _key(quote))] + ([(conflict["field"], _key(conflict["quote"]))] if conflict else [])
        )
        if quote and pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        taken.add((topic, field))
        out.append(Issue(topic, field, quote, problem, advice, "llm", conflict))
        if len(out) == MAX_ISSUES:
            break
    return out


def _ask(provider, system, user):
    for _ in range(2):
        raw = provider.complete(system, user, SCHEMA)
        try:
            parse(raw)
            return raw
        except (ValueError, AttributeError):
            user += "\n\nВерни только JSON по схеме, без пояснений."
    raise AIError("модель не вернула корректный JSON")


def review(v, known, provider, cache=None):
    system, user = build_prompt(v, known)
    key = cache_key(system, user)
    raw = cache.get(key) if cache else None
    if raw is None:
        if provider is None:
            raise AIError("в записи нет ответа для этой вакансии")
        raw = _ask(provider, system, user)
        if cache:
            cache.put(key, raw)
    return validate(v, parse(raw), known)
