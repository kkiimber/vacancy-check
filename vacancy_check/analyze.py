import json
import os
import tempfile
from datetime import datetime, timezone

from . import ai_step, rules
from .llm import AIError
from .normalize import normalize


def analyze(raw_items, provider=None, cache=None, ai_enabled=True, origin="", progress=None):
    unique = {}
    for raw in raw_items:
        unique.setdefault(str(raw["id"]), raw)

    results, failed = [], []
    for done, (vac_id, raw) in enumerate(unique.items(), 1):
        v = normalize(raw)
        issues = rules.check(v)
        if ai_enabled:
            try:
                issues += ai_step.review(v, issues, provider, cache)
            except (AIError, ValueError) as err:
                failed.append({"id": vac_id, "error": str(err)})
        results.append({"id": v.id, "url": v.url, "issues": [i.as_dict() for i in issues]})
        if progress:
            progress(done, len(unique))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": origin,
        "ai": {
            "enabled": ai_enabled,
            "provider": getattr(provider, "name", "replay" if ai_enabled else None),
            "model": getattr(provider, "model", None),
            "failed": failed,
        },
        "vacancies": results,
    }


def write_report(path, report):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
