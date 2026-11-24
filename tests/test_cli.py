import json

from tests.conftest import SAMPLE
from vacancy_check import cli, source


def run(tmp_path, *extra):
    out = tmp_path / "report.json"
    args = ["--file", SAMPLE, "--ai", "none", "--out", str(out), "--config", str(tmp_path / "no.toml")]
    return cli.main(args + list(extra)), out


def test_rerun_gives_same_content(tmp_path):
    code, out = run(tmp_path)
    assert code == 0
    first = json.loads(out.read_text(encoding="utf-8"))
    code, out = run(tmp_path)
    second = json.loads(out.read_text(encoding="utf-8"))
    assert first["vacancies"] == second["vacancies"]
    assert len(second["vacancies"]) == 10


def test_every_vacancy_has_id_url_and_issues(tmp_path):
    _, out = run(tmp_path)
    for item in json.loads(out.read_text(encoding="utf-8"))["vacancies"]:
        assert set(item) == {"id", "url", "issues"}
        assert isinstance(item["issues"], list)


def test_failed_source_keeps_last_report(tmp_path, monkeypatch, capsys):
    _, out = run(tmp_path)
    before = out.read_text(encoding="utf-8")

    def down(*args, **kwargs):
        raise source.SourceError("API недоступно")

    monkeypatch.setattr(cli, "fetch", down)
    code = cli.main(["--ai", "none", "--out", str(out), "--config", str(tmp_path / "no.toml")])
    assert code == 1
    assert out.read_text(encoding="utf-8") == before
    assert "Последний успешный отчёт" in capsys.readouterr().err


def test_max_vacancies_applies_to_file_mode(tmp_path):
    _, out = run(tmp_path, "--max", "4")
    assert len(json.loads(out.read_text(encoding="utf-8"))["vacancies"]) == 4


def test_missing_credentials_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GIGACHAT_CREDENTIALS", raising=False)
    out = tmp_path / "r.json"
    code = cli.main(
        ["--file", SAMPLE, "--ai", "gigachat", "--out", str(out), "--config", str(tmp_path / "no.toml")]
    )
    assert code == 2
    assert not out.exists()
    assert "GIGACHAT_CREDENTIALS" in capsys.readouterr().err
