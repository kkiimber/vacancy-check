import pytest
import requests

from tests.conftest import FakeResponse
from vacancy_check import source


def vacancy(n):
    return {"vacancy": {"id": f"v{n}"}}


class PagedApi:
    """Эмулирует API: offset считается либо страницами, либо записями."""

    def __init__(self, total, by_records):
        self.total = total
        self.by_records = by_records
        self.requests = []

    def get(self, url, params, timeout):
        self.requests.append(dict(params))
        limit, offset = params["limit"], params["offset"]
        start = offset if self.by_records else offset * limit
        chunk = [vacancy(n) for n in range(start, min(start + limit, self.total))]
        return FakeResponse(
            {"status": "200", "meta": {"total": str(self.total)}, "results": {"vacancies": chunk}}
        )


@pytest.mark.parametrize("by_records", [False, True])
def test_pagination_in_both_offset_modes(by_records):
    api = PagedApi(total=250, by_records=by_records)
    items = source.fetch("http://x", page_size=100, max_items=1000, http=api)
    assert [v["id"] for v in items] == [f"v{n}" for n in range(250)]


def test_max_items_limit():
    api = PagedApi(total=250, by_records=False)
    assert len(source.fetch("http://x", page_size=100, max_items=120, http=api)) == 120


class DownApi:
    def get(self, url, params, timeout):
        raise requests.ConnectionError("нет сети")


def test_unavailable_api_raises(monkeypatch):
    monkeypatch.setattr(source.time, "sleep", lambda s: None)
    with pytest.raises(source.SourceError):
        source.fetch("http://x", http=DownApi())


def test_string_meta_values_are_fine():
    api = PagedApi(total=5, by_records=False)
    assert len(source.fetch("http://x", page_size=100, max_items=10, http=api)) == 5
