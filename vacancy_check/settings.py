import os
import tomllib

DEFAULTS = {
    "url": "http://opendata.trudvsem.ru/api/v1/vacancies/region/39",
    "page_size": 100,
    "max_vacancies": 200,
    "timeout": 30,
    "out": "reports/latest.json",
    "ai": "gigachat",
    "model": None,
    "cache": ".cache/ai.json",
}


def load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def load(path="config.toml"):
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path, "rb") as f:
            cfg.update(tomllib.load(f))
    return cfg
