from .model import Vacancy


def flat(value):
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "; ".join(t for t in map(flat, value) if t)
    if isinstance(value, dict):
        return "; ".join(t for t in map(flat, value.values()) if t)
    return ""


def to_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def normalize(raw):
    req = raw.get("requirement")
    if not isinstance(req, dict):
        req = {}
    addresses = (raw.get("addresses") or {}).get("address") or []
    places = [a.get("location", "") for a in addresses if isinstance(a, dict)]
    region = raw.get("region") or {}

    fields = {
        "job-name": raw.get("job-name"),
        "salary": raw.get("salary"),
        "employment": raw.get("employment"),
        "schedule": raw.get("schedule"),
        "scheduleTypeComment": raw.get("scheduleTypeComment"),
        "shift": raw.get("shift"),
        "duty": raw.get("duty"),
        "requirements": raw.get("requirements"),
        "requirement.qualification": req.get("qualification"),
        "qualification": raw.get("qualification"),
        "requirement.education": req.get("education"),
        "conditions": raw.get("conditions"),
        "benefit": raw.get("benefit"),
        "term": raw.get("term"),
        "addresses.address.location": places,
    }
    fields = {key: text for key, value in fields.items() if (text := flat(value))}

    experience = req.get("experience")
    return Vacancy(
        id=str(raw["id"]),
        url=raw.get("vac_url") or None,
        region=flat(region.get("name")) if isinstance(region, dict) else "",
        fields=fields,
        salary_min=to_int(raw.get("salary_min")),
        salary_max=to_int(raw.get("salary_max")),
        experience=None if experience in (None, "") else to_int(experience),
    )
