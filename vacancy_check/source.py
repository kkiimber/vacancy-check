import json
import time

import requests


class SourceError(Exception):
    pass


def extract(data):
    try:
        items = data["results"]["vacancies"]
    except (KeyError, TypeError):
        raise SourceError("в ответе нет results.vacancies")
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        vac = item.get("vacancy", item)
        if isinstance(vac, dict) and vac.get("id"):
            out.append(vac)
    return out


def load_file(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as err:
        raise SourceError(f"не удалось прочитать {path}: {err}")
    return extract(data)


def _get(http, url, params, timeout, retries):
    last = None
    for attempt in range(retries):
        try:
            resp = http.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            body = resp.json()
        except (requests.RequestException, ValueError) as err:
            last = err
            if attempt + 1 < retries:
                time.sleep(2**attempt)
            continue
        if str(body.get("status", "200")) != "200":
            raise SourceError(f"API вернуло статус {body.get('status')}")
        return body
    raise SourceError(f"API недоступно: {last}")


def fetch(url, page_size=100, max_items=200, timeout=30, retries=3, http=None):
    http = http or requests
    found, seen = [], set()
    unit, page = 1, 0
    while len(found) < max_items:
        body = _get(http, url, {"offset": page * unit, "limit": page_size}, timeout, retries)
        batch = extract(body)
        fresh = [v for v in batch if v["id"] not in seen]
        if page > 0 and batch and len(fresh) * 2 < len(batch):
            if unit == 1 and page_size > 1:
                unit = page_size
                continue
            break
        for vac in fresh:
            seen.add(vac["id"])
            found.append(vac)
        try:
            total = int(body.get("meta", {}).get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        if len(batch) < page_size or (total and len(seen) >= total):
            break
        page += 1
    return found[:max_items]
