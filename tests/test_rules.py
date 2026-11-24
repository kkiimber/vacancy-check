from vacancy_check.normalize import normalize
from vacancy_check.rules import check


def by_id(items):
    return {raw["id"]: check(normalize(raw)) for raw in items}


def test_clean_vacancies_have_no_rule_issues(sample_items):
    found = by_id(sample_items)
    for vac_id in ("DEMO-39-001", "DEMO-39-005", "DEMO-39-007", "DEMO-39-009"):
        assert found[vac_id] == []


def test_missing_salary(sample_items):
    issues = by_id(sample_items)["DEMO-39-002"]
    assert [(i.topic, i.quote) for i in issues] == [("оплата", "")]


def test_zero_upper_salary_is_not_an_error(sample_items):
    issues = by_id(sample_items)["DEMO-39-006"]
    assert all(i.topic != "оплата" for i in issues)


def test_experience_contradiction_has_both_values(sample_items):
    (issue,) = by_id(sample_items)["DEMO-39-003"]
    assert issue.quote == "0"
    assert issue.conflicts_with == {"field": "requirement.qualification", "quote": "не менее 5 лет"}


def test_region_only_address(sample_items):
    (issue,) = by_id(sample_items)["DEMO-39-006"]
    assert issue.topic == "место работы"
    assert issue.quote == "Калининградская область"


def test_structured_schedule_is_enough():
    raw = {
        "id": "x",
        "job-name": "Библиотекарь",
        "salary_min": 30000,
        "salary_max": 30000,
        "employment": "Полная занятость",
        "schedule": "Сменный график",
        "duty": "Работа с читателями.",
        "addresses": {"address": [{"location": "г. Гусев, ул. Новая, 1"}]},
        "region": {"name": "Калининградская область"},
    }
    assert check(normalize(raw)) == []


def test_missing_fields_are_reported():
    raw = {"id": "x", "job-name": "Продавец", "salary_min": 0, "salary_max": 0, "duty": "Торговля."}
    topics = {i.topic for i in check(normalize(raw))}
    assert topics == {"оплата", "тип занятости", "график", "место работы"}


def test_code_in_title():
    raw = {
        "id": "x",
        "job-name": "Кухонный рабочий 1311-р",
        "salary_min": 30000,
        "salary_max": 30000,
        "employment": "Полная занятость",
        "schedule": "Полный рабочий день",
        "addresses": {"address": [{"location": "г. Калининград, ул. Зелёная, 1"}]},
    }
    (issue,) = check(normalize(raw))
    assert issue.topic == "название" and issue.quote == "Кухонный рабочий 1311-р"
