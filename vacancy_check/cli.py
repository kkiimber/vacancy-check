import argparse
import os
import sys

from . import settings
from .ai_step import Cache
from .analyze import analyze, write_report
from .llm import AIError, make_provider
from .source import SourceError, fetch, load_file


def parse_args(argv):
    p = argparse.ArgumentParser(prog="vacancy_check", description="Отчёт о прозрачности вакансий")
    p.add_argument("--file", help="проверочный режим: локальный JSON в формате ответа API")
    p.add_argument("--url", help="адрес API региона")
    p.add_argument("--max", type=int, dest="max_vacancies", help="максимум вакансий")
    p.add_argument("--page-size", type=int, help="размер страницы API")
    p.add_argument("--out", help="куда сохранить отчёт")
    p.add_argument(
        "--ai",
        choices=["gigachat", "openai", "replay", "none"],
        help="gigachat и openai ходят к модели, replay берёт записанные ответы, none без ИИ",
    )
    p.add_argument("--model", help="имя модели")
    p.add_argument("--cache", help="файл с кешем ответов модели")
    p.add_argument("--config", default="config.toml")
    return p.parse_args(argv)


def build_ai(cfg):
    kind = cfg["ai"]
    if kind == "none":
        return None, None, False
    if kind == "replay":
        path = cfg["cache"]
        if not os.path.exists(path):
            raise AIError(f"нет файла с записью ответов: {path}")
        return None, Cache(path, readonly=True), True
    provider = make_provider(kind, os.environ, cfg.get("model"))
    return provider, Cache(cfg["cache"]), True


def main(argv=None):
    args = parse_args(argv)
    settings.load_dotenv()
    cfg = settings.load(args.config)
    for key in ("url", "max_vacancies", "page_size", "out", "ai", "model", "cache"):
        value = getattr(args, key, None)
        if value is not None:
            cfg[key] = value

    try:
        provider, cache, ai_on = build_ai(cfg)
    except AIError as err:
        print(f"Ошибка ИИ: {err}", file=sys.stderr)
        print("Запустите с --ai none, чтобы получить отчёт без ИИ.", file=sys.stderr)
        return 2

    try:
        if args.file:
            items = load_file(args.file)[: cfg["max_vacancies"]]
            origin = args.file
        else:
            items = fetch(cfg["url"], cfg["page_size"], cfg["max_vacancies"], cfg["timeout"])
            origin = cfg["url"]
    except SourceError as err:
        print(f"Ошибка источника: {err}", file=sys.stderr)
        if os.path.exists(cfg["out"]):
            print(f"Последний успешный отчёт оставлен без изменений: {cfg['out']}", file=sys.stderr)
        return 1

    report = analyze(items, provider, cache, ai_on, origin)
    if cache:
        cache.save()
    write_report(cfg["out"], report)

    total = sum(len(v["issues"]) for v in report["vacancies"])
    print(f"Вакансий: {len(report['vacancies'])}, замечаний: {total}, отчёт: {cfg['out']}")
    failed = report["ai"]["failed"]
    if failed:
        print(f"ИИ не обработал вакансий: {len(failed)} (первая ошибка: {failed[0]['error']})")
    return 0
