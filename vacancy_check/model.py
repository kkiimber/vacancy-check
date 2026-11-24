import re
from dataclasses import dataclass, asdict

TOPICS = (
    "название",
    "обязанности",
    "требования",
    "оплата",
    "график",
    "место работы",
    "тип занятости",
)


def norm(text):
    text = text.replace("ё", "е").replace("Ё", "Е")
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass
class Vacancy:
    id: str
    url: str | None
    region: str
    fields: dict
    salary_min: int
    salary_max: int
    experience: int | None

    def text_except(self, *skip):
        return "\n".join(t for k, t in self.fields.items() if k not in skip)

    def locate(self, quote, hint=None):
        q = norm(quote)
        if not q:
            return None
        if hint in self.fields and q in norm(self.fields[hint]):
            return hint
        for key, text in self.fields.items():
            if q in norm(text):
                return key
        return None


@dataclass
class Issue:
    topic: str
    field: str
    quote: str
    problem: str
    recommendation: str
    origin: str
    conflicts_with: dict | None = None

    def as_dict(self):
        data = asdict(self)
        if not data["conflicts_with"]:
            del data["conflicts_with"]
        return data
