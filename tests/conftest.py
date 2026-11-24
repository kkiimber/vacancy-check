import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "examples", "sample_vacancies.json")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in (
        "GIGACHAT_CREDENTIALS",
        "GIGACHAT_CA_BUNDLE",
        "GIGACHAT_INSECURE",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def sample_items():
    from vacancy_check.source import load_file

    return load_file(SAMPLE)


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status
        self.text = json.dumps(body, ensure_ascii=False)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code}")


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, answers):
        self.answers = answers
        self.calls = 0

    def complete(self, system, user, schema):
        self.calls += 1
        vac_id = user.split("\n", 1)[0].split()[-1]
        return json.dumps({"issues": self.answers.get(vac_id, [])}, ensure_ascii=False)
