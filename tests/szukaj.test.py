#!/usr/bin/env python3
"""Test wyszukiwarki `szukaj.py`. Uruchomienie:

    python3 tests/szukaj.test.py

Wszystkie części działają na izolowanym sejfie testowym w katalogu tymczasowym.
Każda część ma przypadek kontrolny, nie tylko negatywny.
"""

import contextlib
import importlib.util
import io
import tempfile
from pathlib import Path

MODUL = Path(__file__).resolve().parent.parent / "tools" / "szukaj.py"
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


def strona(sejf, sciezka, fm, tresc):
    p = Path(sejf) / sciezka
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{fm}\n---\n{tresc}", encoding="utf-8")


def sciezki(wyniki):
    return [s for _, s, _ in wyniki]


with tempfile.TemporaryDirectory() as t:
    strona(t, "produkt/wiki/serwisy-www/historia/decyzja-2026-08-13-badge-promocji.md",
           'typ: decyzja\nstatus: obowiązuje\nopis: "Kiedy pokazywać plakietkę promocji"',
           "# Badge promocji\n\nTreść o cenach.\n")
    strona(t, "produkt/wiki/marketing/kampania.md",
           'typ: synteza\nopis: "Kampania jesienna"',
           "# Kampania\n\nW treści pada słowo promocja i cena.\n")
    strona(t, "produkt/wiki/marketing/stara-promocja.md",
           'typ: decyzja\nstatus: zastąpiona\nopis: "Stara zasada plakietki promocji"',
           "# Stara promocja\n")
    strona(t, "produkt/raw/zrodlo-promocja.md", 'typ: źródło\nopis: "promocja plakietka"', "# raw\n")
    strona(t, "firma/wiki/podatki/kalendarz.md", 'typ: synteza\nopis: "Terminy rozliczeń miesięcznych"', "# Kalendarz obowiązków\n")

    print("1. Ranking pól")
    w = sz.szukaj("Kiedy pokazujemy plakietkę promocji?", t)
    sprawdz("opis wygrywa z samą treścią", sciezki(w)[0].endswith("badge-promocji.md"), sciezki(w))
    sprawdz("strona z dopasowaniem tylko w treści jest niżej, ale jest (kontrola)",
            any(s.endswith("kampania.md") for s in sciezki(w)), sciezki(w))

    print("2. Polskie znaki, rdzeń słowa i synonimy")
    sprawdz("„plakietkę” trafia „plakietkę/plakietki” bez ogonków",
            any(s.endswith("badge-promocji.md") for s in sciezki(sz.szukaj("plakietke", t))))
    sprawdz("synonim „etykieta” trafia stronę z „badge/plakietka”",
            any(s.endswith("badge-promocji.md") for s in sciezki(sz.szukaj("etykieta", t))))
    sprawdz("„obowiązków” trafia H1 „Kalendarz obowiązków”",
            sciezki(sz.szukaj("obowiazkow", t))[:1] == ["firma/wiki/podatki/kalendarz.md"])
    sprawdz("słowa pomocnicze same nic nie trafiają", sz.szukaj("kiedy jak co", t) == [])

    print("3. Status i zakres")
    w = sz.szukaj("plakietka promocji", t)
    pozycje = {s.split("/")[-1]: i for i, s in enumerate(sciezki(w))}
    sprawdz("zastąpiona niżej niż obowiązująca o podobnym dopasowaniu",
            pozycje.get("decyzja-2026-08-13-badge-promocji.md", 99) < pozycje.get("stara-promocja.md", -1), pozycje)
    sprawdz("raw/ nie jest przeszukiwany", not any("/raw/" in s for s in sciezki(w)))

    print("4. Kod wyjścia")
    with contextlib.redirect_stdout(io.StringIO()):
        kod_brak = sz.main(["--sejf", t, "xyzzyqq"])
        kod_jest = sz.main(["--sejf", t, "promocja"])
    sprawdz("brak trafień = kod 1", kod_brak == 1)
    sprawdz("trafienie = kod 0 (kontrola)", kod_jest == 0)

    print("4a. SQLite FTS5 i fallback")
    db_p = sz.sciezka_bazy(t)
    sprawdz("plik bazy sqlite istnieje", db_p.exists())
    stary_sqlite = sz.szukaj_sqlite
    try:
        def zepsuj_sqlite(*args, **kwargs):
            raise RuntimeError("Symulowany błąd SQLite")
        sz.szukaj_sqlite = zepsuj_sqlite
        w_fb = sz.szukaj("plakietka", t)
        sprawdz("fallback do przeszukiwania plików przy awarii SQLite", any(s.endswith("badge-promocji.md") for s in sciezki(w_fb)))
    finally:
        sz.szukaj_sqlite = stary_sqlite

print()
if bledy:
    print(f"BŁĘDY: {len(bledy)}")
    raise SystemExit(1)
print("Wszystkie testy przeszły")
