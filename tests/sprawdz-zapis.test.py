#!/usr/bin/env python3
"""Test kontroli zapisu `sprawdz-zapis.py`. Uruchomienie:

    python3 tests/sprawdz-zapis.test.py

Działa na tymczasowym repo git (bez zapisu do prawdziwego sejfu). Każdy przypadek negatywny ma
przypadek kontrolny, który przechodzi.
"""

import contextlib
import importlib.util
import io
import subprocess
import tempfile
from pathlib import Path

MODUL = Path(__file__).resolve().parent.parent / "tools" / "sprawdz-zapis.py"
spec = importlib.util.spec_from_file_location("sz", MODUL)
sz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sz)

bledy = []


def sprawdz(opis, warunek, szczegol=""):
    if warunek:
        print(f"  ✓ {opis}")
    else:
        print(f"  ✗ {opis} {szczegol}")
        bledy.append(opis)


def git(repo, *a):
    subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)


def zapisz(repo, sciezka, tresc):
    p = Path(repo) / sciezka
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tresc, encoding="utf-8")


def uruchom(repo):
    with contextlib.redirect_stdout(io.StringIO()) as wyj:
        kod = sz.main(["--sejf", repo, "--bez-indeksow"])
    return kod, wyj.getvalue()


def nowe_repo(t):
    git(t, "init", "-q")
    git(t, "config", "user.email", "test@example.invalid")
    git(t, "config", "user.name", "test")
    git(t, "config", "core.hooksPath", "/dev/null")
    zapisz(t, "produkt/raw/zrodlo.md", "oryginał\n")
    zapisz(t, "produkt/wiki/strona.md", "# Strona\n\n[[druga]]\n")
    zapisz(t, "produkt/wiki/druga.md", "# Druga\n\n[[strona]]\n")
    zapisz(t, "log.md", "## [2026-10-20] lint | claude-code | a | b\n")
    git(t, "add", "-A")
    git(t, "commit", "-q", "-m", "start")


with tempfile.TemporaryDirectory() as t:
    nowe_repo(t)
    print("1. Kontrola: zwykły zapis przechodzi")
    zapisz(t, "produkt/wiki/strona.md", "# Strona\n\nNowa teza. [[druga]]\n")
    zapisz(t, "produkt/raw/nowe-zrodlo.md", "nowe\n")
    zapisz(t, "log.md", "## [2026-10-20] lint | claude-code | a | b\n## [2026-10-20] ingest | claude-code | c | d\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("dopisane źródło, zmieniona strona, dopisany log = kod 0", kod == 0, wyj)

    print("2. raw/ tylko dodawane")
    zapisz(t, "produkt/raw/zrodlo.md", "zmieniony oryginał\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("zmiana istniejącego pliku w raw/ = kod 1", kod == 1 and "raw/ zmieniony (M)" in wyj, wyj)
    git(t, "checkout", "HEAD", "--", "produkt/raw/zrodlo.md")
    git(t, "rm", "-q", "--cached", "produkt/raw/zrodlo.md")
    kod, wyj = uruchom(t)
    sprawdz("usunięcie pliku z raw/ = kod 1", kod == 1 and "raw/ zmieniony (D)" in wyj, wyj)
    git(t, "add", "-A")
    kod, _ = uruchom(t)
    sprawdz("po przywróceniu raw/ = kod 0 (kontrola)", kod == 0)

    print("3. log.md tylko dopisywany")
    zapisz(t, "log.md", "## [2026-10-20] ingest | claude-code | c | d\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("usunięta linia logu = kod 1", kod == 1 and "log.md" in wyj, wyj)
    zapisz(t, "log.md", "## [2026-10-20] lint | claude-code | a | b\n## [2026-10-20] ingest | claude-code | c | d\n")
    git(t, "add", "-A")

    print("4. Martwe linki i ścieżki")
    zapisz(t, "produkt/wiki/trzecia.md", "# Trzecia\n\n[[nie-ma-takiej]] i `[[w-kodzie]]`\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("martwy link = kod 1", kod == 1 and "nie-ma-takiej" in wyj, wyj)
    sprawdz("link w backtickach pomijany", "w-kodzie" not in wyj, wyj)
    zapisz(t, "produkt/wiki/trzecia.md", "# Trzecia\n\n| a |\n|---|\n| [[produkt/wiki/strona\\|s]] |\n")
    zapisz(t, "notatka-luzem.md", "x\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("plik poza zakresem = UWAGA, ale kod 0", kod == 0 and "UWAGA" in wyj and "notatka-luzem.md" in wyj, wyj)

    print("5. Martwe ścieżki w źródła:")
    zapisz(t, "produkt/wiki/czwarta.md", "---\ngłos: agent\naktualizacja: 2026-11-02\nźródła: [\"produkt/raw/nie-istnieje.md\"]\n---\n# Czwarta\n\n[[strona]]\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("martwa ścieżka w źródła = kod 1", kod == 1 and "martwe źródło" in wyj and "nie-istnieje.md" in wyj, wyj)
    zapisz(t, "produkt/wiki/czwarta.md", "---\ngłos: agent\naktualizacja: 2026-11-02\nźródła: [\"produkt/raw/zrodlo.md\", \"https://example.com\"]\n---\n# Czwarta\n\n[[strona]]\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("istniejąca ścieżka lokalna i URL w źródła = kod 0 (kontrola)", kod == 0, wyj)

    print("6. Pole głos:")
    zapisz(t, "produkt/wiki/piata.md", "---\ntyp: synteza\naktualizacja: 2026-11-02\n---\n# Piąta\n\n[[strona]]\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("nowa strona bez głos = kod 1", kod == 1 and "brak pola `głos:`" in wyj, wyj)
    zapisz(t, "produkt/wiki/piata.md", "---\ntyp: synteza\naktualizacja: 2026-11-02\ngłos: model\n---\n# Piąta\n\n[[strona]]\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("nieznany głos = kod 1", kod == 1 and "nieznany `głos`" in wyj, wyj)
    zapisz(t, "produkt/wiki/historia/decyzja-2026-11-02-piata.md", "---\ntyp: decyzja\naktualizacja: 2026-11-02\nstatus: obowiązuje\ngłos: agent\n---\n# Piąta\n\n[[strona]]\n")
    (Path(t) / "produkt/wiki/piata.md").unlink()
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("decyzja obowiązuje z głosem agenta = kod 1", kod == 1 and "bez głosu właściciela" in wyj, wyj)
    zapisz(t, "produkt/wiki/historia/decyzja-2026-11-02-piata.md", "---\ntyp: decyzja\naktualizacja: 2026-11-02\nstatus: obowiązuje\ngłos: [wybor-widzet, agent]\n---\n# Piąta\n\n[[strona]]\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("decyzja z wyboru w widżecie = kod 0", kod == 0, wyj)
    git(t, "commit", "-q", "-m", "x")
    zapisz(t, "produkt/wiki/strona.md", "---\ntyp: pojęcie\n---\n# Strona\n\n[[druga]]\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("zmieniona stara strona bez głos = UWAGA, kod 0", kod == 0 and "UWAGA  brak pola `głos:`" in wyj, wyj)
    git(t, "checkout", "HEAD", "--", "produkt/wiki/strona.md")

    print("7. Datowanie i chronologia:")
    zapisz(t, "produkt/wiki/szosta.md", "---\ngłos: agent\n---\n# Szósta\n\n[[strona]]\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("nowa strona bez aktualizacja = kod 1", kod == 1 and "brak pola `aktualizacja:`" in wyj, wyj)
    zapisz(t, "produkt/wiki/szosta.md", "---\ngłos: agent\naktualizacja: 2026-11\n---\n# Szósta\n\n[[strona]]\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("błędny format aktualizacja = kod 1", kod == 1 and "błędny format daty" in wyj, wyj)
    zapisz(t, "produkt/wiki/szosta.md", "---\ngłos: agent\naktualizacja: 2026-11-02\ntyp: decyzja\nstatus: propozycja\n---\n# Szósta\n\n[[strona]]\n")
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("decyzja bez daty w nazwie i poza historia = kod 1", kod == 1 and "błędna nazwa decyzji" in wyj and "musi leżeć w podfolderze `historia/`" in wyj, wyj)
    zapisz(t, "produkt/wiki/historia/decyzja-2026-11-02-szosta.md", "---\ngłos: agent\naktualizacja: 2026-11-02\ntyp: decyzja\nstatus: propozycja\n---\n# Szósta\n\n[[strona]]\n")
    (Path(t) / "produkt/wiki/szosta.md").unlink()
    git(t, "add", "-A")
    kod, wyj = uruchom(t)
    sprawdz("poprawna decyzja z datą w historia/ = kod 0", kod == 0, wyj)
    zapisz(t, "log.md", "## [2026-10-20] lint | claude-code | a | b\n## [2026-10-20] ingest | claude-code | c | d\n## zły wpis bez daty\n")
    git(t, "add", "log.md")
    kod, wyj = uruchom(t)
    sprawdz("błędny format wpisu w log.md = kod 1", kod == 1 and "błędny format wpisu" in wyj, wyj)

print()
if bledy:
    print(f"BŁĘDY: {len(bledy)}")
    raise SystemExit(1)
print("Wszystkie testy przeszły")
