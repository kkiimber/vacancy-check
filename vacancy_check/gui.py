import json
import os
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from . import settings
from .analyze import analyze, write_report
from .cli import build_ai
from .llm import AIError
from .source import SourceError, fetch, load_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BG = "#f4f4f1"
CARD = "#ffffff"
LINE = "#dcdcd6"
TEXT = "#222222"
MUTED = "#666666"
GREEN = "#2f6f5e"
GREEN_DARK = "#265b4d"
GREEN_PALE = "#eef5f2"
AMBER = "#8a5a00"
BLUE = "#1f56a3"
WARN = "#fff3d6"

MODES = {
    "GigaChat": "gigachat",
    "Записанные ответы": "replay",
    "Без ИИ, только правила": "none",
}


def plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Отчёт по вакансиям")
        self.geometry("1000x780")
        self.minsize(760, 560)
        self.configure(bg=BG)
        self.option_add("*Font", ("Segoe UI", 10))

        self.data = None
        self.file = ""
        self.running = False
        self.events = queue.Queue()

        self.source = tk.StringVar(value="file")
        self.mode = tk.StringVar(value="GigaChat")
        self.limit = tk.StringVar(value="200")
        self.status = tk.StringVar(value="")
        self.query = tk.StringVar()
        self.topic = tk.StringVar(value="Все темы")
        self.origin = tk.StringVar(value="Любой источник")
        self.only = tk.BooleanVar(value=True)

        self.build()
        for var in (self.query, self.topic, self.origin, self.only):
            var.trace_add("write", lambda *_: self.render())

    def label(self, parent, **kw):
        kw.setdefault("bg", parent["bg"])
        kw.setdefault("fg", TEXT)
        return tk.Label(parent, **kw)

    def button(self, parent, text, command, primary=False):
        if primary:
            return tk.Button(parent, text=text, command=command, bg=GREEN, fg="white",
                             activebackground=GREEN_DARK, activeforeground="white",
                             relief="flat", padx=14, pady=5, cursor="hand2")
        return tk.Button(parent, text=text, command=command, bg=CARD, fg=TEXT,
                         activebackground=BG, relief="solid", bd=1, padx=12, pady=4,
                         cursor="hand2")

    def build(self):
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=14)

        self.label(body, text="Отчёт по вакансиям", font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(0, 10))

        panel = tk.Frame(body, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        panel.pack(fill="x", pady=(0, 14))
        inner = tk.Frame(panel, bg=CARD)
        inner.pack(fill="x", padx=14, pady=12)

        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x")
        tk.Radiobutton(row, text="Файл с вакансиями", variable=self.source, value="file",
                       bg=CARD, activebackground=CARD, selectcolor=CARD).pack(side="left")
        self.button(row, "Выбрать файл", self.pick_file).pack(side="left", padx=8)
        self.file_label = self.label(row, text="не выбран", fg=MUTED)
        self.file_label.pack(side="left")
        tk.Radiobutton(row, text="API региона 39", variable=self.source, value="api",
                       bg=CARD, activebackground=CARD, selectcolor=CARD).pack(side="right")

        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(10, 0))
        self.label(row, text="ИИ").pack(side="left")
        ttk.Combobox(row, textvariable=self.mode, values=list(MODES), state="readonly",
                     width=24).pack(side="left", padx=(6, 16))
        self.label(row, text="Максимум вакансий").pack(side="left")
        tk.Spinbox(row, from_=1, to=1000, textvariable=self.limit, width=6,
                   relief="solid", bd=1).pack(side="left", padx=(6, 0))
        self.button(row, "Открыть готовый отчёт", self.open_report).pack(side="right")
        self.start_button = self.button(row, "Создать отчёт", self.start, primary=True)
        self.start_button.pack(side="right", padx=8)

        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(10, 0))
        self.bar = ttk.Progressbar(row, mode="determinate")
        self.bar.pack(side="left", fill="x", expand=True)
        self.label(row, textvariable=self.status, fg=MUTED).pack(side="left", padx=(10, 0))

        self.summary = self.label(body, text="", font=("Segoe UI", 12, "bold"))
        self.summary.pack(anchor="w")
        self.meta = self.label(body, text="", fg=MUTED)
        self.meta.pack(anchor="w", pady=(0, 6))
        self.failed = self.label(body, text="", bg=WARN, anchor="w", padx=10, pady=5)

        tools = self.tools = tk.Frame(body, bg=BG)
        tools.pack(fill="x", pady=(0, 8))
        tk.Entry(tools, textvariable=self.query, width=24, relief="solid", bd=1).pack(side="left", ipady=3)
        self.topic_box = ttk.Combobox(tools, textvariable=self.topic, state="readonly", width=18,
                                      values=["Все темы"])
        self.topic_box.pack(side="left", padx=8)
        ttk.Combobox(tools, textvariable=self.origin, state="readonly", width=16,
                     values=["Любой источник", "Правила", "ИИ"]).pack(side="left")
        tk.Checkbutton(tools, text="только с замечаниями", variable=self.only, bg=BG,
                       activebackground=BG).pack(side="left", padx=12)

        frame = tk.Frame(body, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, wrap="word", bg=CARD, fg=TEXT, relief="flat", padx=16, pady=8,
                            cursor="arrow", state="disabled", spacing1=2, spacing3=2)
        scroll = ttk.Scrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.tags()

    def tags(self):
        t = self.text
        t.tag_configure("vac", font=("Segoe UI", 11, "bold"), background="#ecece7", spacing1=14, spacing3=6, lmargin1=0, lmargin2=0)
        t.tag_configure("count", font=("Segoe UI", 10), foreground=MUTED)
        t.tag_configure("link", foreground=BLUE, underline=True)
        t.tag_configure("topic", font=("Segoe UI", 10, "bold"), spacing1=10)
        t.tag_configure("rule", foreground=AMBER)
        t.tag_configure("llm", foreground=BLUE)
        t.tag_configure("field", font=("Consolas", 9), foreground="#777777", lmargin1=18, lmargin2=18, spacing1=4, spacing3=0)
        t.tag_configure("quote", lmargin1=18, lmargin2=18, spacing3=2)
        t.tag_configure("none", foreground="#777777", font=("Segoe UI", 10, "italic"))
        t.tag_configure("problem", spacing1=4)
        t.tag_configure("rec", background=GREEN_PALE, lmargin1=8, lmargin2=8, spacing1=4, spacing3=6)
        t.tag_configure("recbold", font=("Segoe UI", 10, "bold"), foreground=GREEN_DARK)
        t.tag_configure("empty", foreground=MUTED)
        t.tag_bind("link", "<Enter>", lambda e: t.config(cursor="hand2"))
        t.tag_bind("link", "<Leave>", lambda e: t.config(cursor="arrow"))

    def pick_file(self):
        path = filedialog.askopenfilename(
            title="Файл с вакансиями", filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if path:
            self.file = path
            self.file_label.config(text=os.path.basename(path))
            self.source.set("file")

    def open_report(self):
        path = filedialog.askopenfilename(
            title="Готовый отчёт", initialdir=os.path.join(ROOT, "reports"),
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, ValueError):
            messagebox.showerror("Ошибка", "Файл не читается как JSON.")
            return
        if not isinstance(data, dict) or not isinstance(data.get("vacancies"), list):
            messagebox.showerror("Ошибка", "В файле нет списка vacancies, это не отчёт сервиса.")
            return
        self.show(data)

    def start(self):
        if self.running:
            return
        use_file = self.source.get() == "file"
        if use_file and not self.file:
            messagebox.showinfo("Источник", "Выберите файл с вакансиями.")
            return
        try:
            limit = max(1, int(self.limit.get()))
        except ValueError:
            messagebox.showinfo("Максимум", "Максимум вакансий должен быть числом.")
            return

        cfg = settings.load(os.path.join(ROOT, "config.toml"))
        cfg["ai"] = MODES[self.mode.get()]
        cfg["max_vacancies"] = limit
        recording = os.path.join(ROOT, "examples", "ai_recording.json")
        if cfg["ai"] == "replay":
            cfg["cache"] = recording if os.path.exists(recording) else cfg["cache"]
        cfg["out"] = os.path.join(ROOT, "reports", "check.json" if use_file else "latest.json")

        self.running = True
        self.start_button.config(state="disabled")
        self.bar.config(value=0, mode="indeterminate")
        self.bar.start(12)
        self.status.set("Запуск")
        threading.Thread(target=self.work, args=(cfg, self.file if use_file else None), daemon=True).start()
        self.after(100, self.poll)

    def work(self, cfg, path):
        try:
            provider, cache, ai_on = build_ai(cfg)
        except AIError as err:
            self.events.put(("error", f"ИИ не настроен: {err}\n\nВыберите режим «Без ИИ, только правила» или задайте ключ в файле .env."))
            return
        try:
            if path:
                items = load_file(path)[: cfg["max_vacancies"]]
                origin = path
            else:
                items = fetch(cfg["url"], cfg["page_size"], cfg["max_vacancies"], cfg["timeout"])
                origin = cfg["url"]
        except (SourceError, OSError, ValueError) as err:
            kept = " Последний отчёт оставлен без изменений." if os.path.exists(cfg["out"]) else ""
            self.events.put(("error", f"Не удалось получить вакансии: {err}.{kept}"))
            return
        try:
            report = analyze(items, provider, cache, ai_on, origin,
                             progress=lambda done, total: self.events.put(("progress", done, total)))
            if cache:
                cache.save()
            write_report(cfg["out"], report)
        except Exception as err:
            self.events.put(("error", f"Сбой при анализе: {err}"))
            return
        self.events.put(("done", report, cfg["out"]))

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, done, total = event
                    self.bar.stop()
                    self.bar.config(mode="determinate", maximum=total, value=done)
                    self.status.set(f"{done} из {total}")
                else:
                    self.finish(event)
        except queue.Empty:
            pass
        if self.running:
            self.after(100, self.poll)

    def finish(self, event):
        self.running = False
        self.bar.stop()
        self.start_button.config(state="normal")
        if event[0] == "error":
            self.bar.config(mode="determinate", value=0)
            self.status.set("Ошибка")
            messagebox.showerror("Ошибка", event[1])
            return
        _, report, out = event
        self.bar.config(mode="determinate", value=self.bar["maximum"])
        self.status.set(f"Отчёт сохранён: {os.path.relpath(out, ROOT)}")
        self.show(report)

    def show(self, data):
        self.data = data
        topics = sorted({i["topic"] for v in data["vacancies"] for i in v["issues"]})
        self.topic_box.config(values=["Все темы"] + topics)
        self.topic.set("Все темы")
        self.render()

    def render(self):
        if not self.data:
            return
        vacancies = self.data["vacancies"]
        issues = [i for v in vacancies for i in v["issues"]]
        by_rule = sum(1 for i in issues if i["origin"] == "rule")
        with_issues = sum(1 for v in vacancies if v["issues"])
        self.summary.config(text=(
            f"Вакансий: {len(vacancies)}, с замечаниями: {with_issues}, замечаний: {len(issues)} "
            f"(правила {by_rule}, ИИ {len(issues) - by_rule})"))

        ai = self.data.get("ai") or {}
        meta = [self.data.get("generated_at", "").replace("T", " ")[:19], self.data.get("source", "")]
        meta.append(f"{ai.get('provider')}, {ai.get('model')}" if ai.get("enabled") and ai.get("model") else
                    "записанные ответы" if ai.get("enabled") else "без ИИ")
        self.meta.config(text=" | ".join(m for m in meta if m))

        failed = ai.get("failed") or []
        if failed:
            self.failed.config(text=f"ИИ не ответил по вакансиям: {len(failed)}. По ним только замечания правил.")
            self.failed.pack(fill="x", pady=(0, 8), before=self.tools)
        else:
            self.failed.pack_forget()

        q = self.query.get().strip().lower()
        topic = "" if self.topic.get() == "Все темы" else self.topic.get()
        origin = {"Правила": "rule", "ИИ": "llm"}.get(self.origin.get(), "")
        filtering = bool(topic or origin or q)

        t = self.text
        t.config(state="normal")
        t.delete("1.0", "end")
        shown = 0
        for v in vacancies:
            kept = [i for i in v["issues"] if (not topic or i["topic"] == topic) and (not origin or i["origin"] == origin)]
            if q and q not in (v["id"] + json.dumps(kept, ensure_ascii=False)).lower():
                continue
            if (self.only.get() or filtering) and not kept:
                continue
            shown += 1
            n = len(kept)
            count = f"{n} {plural(n, 'замечание', 'замечания', 'замечаний')}" if n else "замечаний нет"
            if v.get("url"):
                t.insert("end", v["id"], ("vac", "link", "u" + str(shown)))
                url = v["url"]
                t.tag_bind("u" + str(shown), "<Button-1>", lambda e, u=url: webbrowser.open(u))
            else:
                t.insert("end", v["id"], ("vac",))
            t.insert("end", f"   {count}\n", ("vac", "count"))
            for i in kept:
                self.issue(i)
        if not shown:
            t.insert("end", "\nНичего не найдено", ("empty",))
        t.config(state="disabled")
        t.yview_moveto(0)

    def issue(self, i):
        t = self.text
        t.insert("end", i["topic"].capitalize(), ("topic",))
        t.insert("end", "   правило\n" if i["origin"] == "rule" else "   ИИ\n", ("topic", i["origin"]))
        self.quote(i["field"], i["quote"])
        if i.get("conflicts_with"):
            self.quote(i["conflicts_with"]["field"], i["conflicts_with"]["quote"])
        t.insert("end", i["problem"] + "\n", ("problem",))
        t.insert("end", "Уточнить: ", ("rec", "recbold"))
        t.insert("end", i["recommendation"] + "\n", ("rec",))

    def quote(self, field, quote):
        self.text.insert("end", field + "\n", ("field",))
        if quote:
            self.text.insert("end", quote + "\n", ("quote",))
        else:
            self.text.insert("end", "пропуск, цитаты нет\n", ("quote", "none"))


def main():
    os.chdir(ROOT)
    settings.load_dotenv()
    App().mainloop()


if __name__ == "__main__":
    main()
