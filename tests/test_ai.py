import json

from tests.conftest import FakeProvider
from vacancy_check import ai_step
from vacancy_check.analyze import analyze
from vacancy_check.llm import AIError
from vacancy_check.normalize import normalize

REMOTE = {
    "topic": "место работы",
    "field": "duty",
    "quote": "Работа полностью дистанционная из любого города",
    "problem": "В обязанностях сказано про удалённую работу, а в требованиях про офис.",
    "recommendation": "Уточнить, работа удалённая или нужно приходить в офис каждый день.",
    "conflicts_with": {
        "field": "requirement.qualification",
        "quote": "Обязательное ежедневное присутствие в офисе в Калининграде",
    },
}


def test_real_quotes_survive(sample_items):
    provider = FakeProvider({"DEMO-39-004": [REMOTE]})
    report = analyze(sample_items, provider)
    issues = {v["id"]: v["issues"] for v in report["vacancies"]}["DEMO-39-004"]
    assert len(issues) == 1
    assert issues[0]["origin"] == "llm"
    assert issues[0]["conflicts_with"]["field"] == "requirement.qualification"


def test_invented_quote_is_dropped(sample_items):
    fake = dict(REMOTE, quote="Бесплатные обеды для всех сотрудников")
    report = analyze(sample_items, FakeProvider({"DEMO-39-004": [fake]}))
    issues = {v["id"]: v["issues"] for v in report["vacancies"]}["DEMO-39-004"]
    assert issues == []


def test_invented_second_quote_is_dropped(sample_items):
    fake = dict(REMOTE, conflicts_with={"field": "duty", "quote": "Выдумка про отпуск"})
    report = analyze(sample_items, FakeProvider({"DEMO-39-004": [fake]}))
    assert report["vacancies"][3]["issues"] == []


def test_unknown_topic_is_dropped(sample_items):
    fake = dict(REMOTE, topic="отпуск")
    report = analyze(sample_items, FakeProvider({"DEMO-39-004": [fake]}))
    assert report["vacancies"][3]["issues"] == []


def test_model_does_not_repeat_rule_issue(sample_items):
    dup = {
        "topic": "оплата",
        "field": "salary_min",
        "quote": "",
        "problem": "Оплата не указана вообще нигде в вакансии.",
        "recommendation": "Указать размер оплаты труда в рублях.",
    }
    report = analyze(sample_items, FakeProvider({"DEMO-39-002": [dup]}))
    issues = report["vacancies"][1]["issues"]
    assert [i["origin"] for i in issues] == ["rule"]


def test_cache_replay_without_provider(sample_items, tmp_path):
    path = str(tmp_path / "ai.json")
    cache = ai_step.Cache(path)
    provider = FakeProvider({"DEMO-39-004": [REMOTE]})
    first = analyze(sample_items, provider, cache)
    cache.save()
    assert provider.calls == 10

    replay = analyze(sample_items, None, ai_step.Cache(path, readonly=True))
    assert replay["ai"]["failed"] == []
    assert [v["issues"] for v in replay["vacancies"]] == [v["issues"] for v in first["vacancies"]]


def test_replay_miss_is_reported_not_fatal(sample_items, tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({}))
    report = analyze(sample_items, None, ai_step.Cache(str(path), readonly=True))
    assert len(report["ai"]["failed"]) == 10
    assert report["vacancies"][1]["issues"][0]["origin"] == "rule"


class BrokenProvider:
    name = "broken"
    model = "m"

    def complete(self, system, user, schema):
        raise AIError("квота исчерпана")


def test_provider_failure_keeps_rule_issues(sample_items):
    report = analyze(sample_items, BrokenProvider())
    assert len(report["ai"]["failed"]) == 10
    assert report["vacancies"][2]["issues"][0]["topic"] == "требования"


def test_parse_handles_code_fence():
    raw = '```json\n{"issues": []}\n```'
    assert ai_step.parse(raw) == {"topics": [], "issues": []}


def test_label_instead_of_explanation_is_dropped(sample_items):
    vague = dict(REMOTE, problem="неоднозначность")
    report = analyze(sample_items, FakeProvider({"DEMO-39-004": [vague]}))
    assert report["vacancies"][3]["issues"] == []


def test_issue_on_topic_marked_clear_is_dropped(sample_items):
    v = normalize(sample_items[3])
    parsed = {"topics": [{"topic": "место работы", "status": "понятно", "note": ""}], "issues": [REMOTE]}
    assert ai_step.validate(v, parsed, []) == []
    parsed["topics"][0]["status"] = "противоречие"
    assert len(ai_step.validate(v, parsed, [])) == 1


def test_same_vacancy_twice_gives_one_result(sample_items):
    report = analyze(sample_items + sample_items[:3])
    ids = [v["id"] for v in report["vacancies"]]
    assert len(ids) == len(set(ids)) == 10


def test_prompt_contains_all_fields_and_known_issues(sample_items):
    from vacancy_check.rules import check

    v = normalize(sample_items[1])
    system, user = ai_step.build_prompt(v, check(v))
    assert "[schedule] Гибкий график" in user
    assert "salary_min: 0" in user
    assert "Уже найдено" in user


def test_claim_of_missing_info_is_dropped_when_field_is_filled(sample_items):
    v = normalize(sample_items[5])
    claim = {
        "topic": "оплата",
        "field": "salary_max",
        "quote": "",
        "problem": "Отсутствует информация о максимальной зарплате.",
        "recommendation": "Добавить информацию о верхней границе зарплаты.",
    }
    assert ai_step.validate(v, {"topics": [], "issues": [claim]}, []) == []


def test_claim_of_missing_info_stays_when_field_is_empty():
    v = normalize({"id": "x", "job-name": "Продавец", "salary_min": 0, "salary_max": 0})
    claim = {
        "topic": "график",
        "field": "schedule",
        "quote": "",
        "problem": "График работы нигде не указан в вакансии.",
        "recommendation": "Указать дни и часы работы сотрудника.",
    }
    assert len(ai_step.validate(v, {"topics": [], "issues": [claim]}, [])) == 1


def test_same_contradiction_reported_twice_is_kept_once(sample_items):
    v = normalize(sample_items[3])
    mirror = {
        "topic": "требования",
        "field": "requirement.qualification",
        "quote": "Обязательное ежедневное присутствие в офисе в Калининграде к 09:00.",
        "problem": "Требования спорят с обязанностями про дистанционный формат работы.",
        "recommendation": "Уточнить у работодателя, дистанционная это работа или офисная.",
        "conflicts_with": {"field": "duty", "quote": "Работа полностью дистанционная из любого города."},
    }
    first = dict(REMOTE, conflicts_with={
        "field": "requirement.qualification",
        "quote": "Обязательное ежедневное присутствие в офисе в Калининграде к 09:00",
    })
    parsed = {"topics": [], "issues": [first, mirror]}
    assert len(ai_step.validate(v, parsed, [])) == 1


def test_progress_is_reported_per_vacancy(sample_items):
    seen = []
    analyze(sample_items, None, None, False, progress=lambda done, total: seen.append((done, total)))
    assert seen[0] == (1, 10)
    assert seen[-1] == (10, 10)
