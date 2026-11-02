#!/usr/bin/env python3
"""Wyszukiwarka stron sejfu dla agentów (krok 1 Query). Tylko odczyt. Uruchomienie:

    python3 tools/szukaj.py "słowa pytania"          # 8 najlepszych stron
    python3 tools/szukaj.py -n 15 "plakietka"        # więcej wyników

Przeszukuje `<obszar>/wiki/**/*.md` (bez `raw/`). Ranking: każde słowo pytania (bez polskich znaków,
bez słów pomocniczych) liczy się raz na stronę, z wagą najlepszego pola, w którym występuje:
nazwa pliku i `aliases`/H1 = 4, `opis` = 3, `tagi` = 2, nagłówki `##` = 1,5, reszta treści = 0,5.
Dopasowanie po rdzeniu: pierwsze 5 znaków słowa (krótsze słowa w całości), więc „promocji” trafia
„promocja”, a „zamówienia” trafia „zamowienie”. Strony `zastąpiona`/`archiwalna` dostają -1.
Wynik: `wynik  ścieżka  [typ, status]  opis`. Kod wyjścia 1 = brak trafień (wtedy indeks obszaru).
"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import unicodedata
from pathlib import Path

import yaml

SEJF = Path(__file__).resolve().parent.parent / "examples" / "demo-vault"
OBSZARY = ["produkt", "operacje", "narzedziownik", "diy", "firma"]
WAGI = {"nazwa": 4.0, "tytul": 4.0, "opis": 3.0, "tagi": 2.0, "naglowki": 1.5, "tresc": 0.5}
RDZEN = 5
KARA_NIEAKTUALNA = 1.0
POMIJANE = set("""a aby albo ale bo by co czy dla do gdy gdzie i ich jak jaka jaki jakie jest jestem
kiedy kto ktora ktore ktory ma mam mamy mi mnie na nad nie o od po pod przez przy sa sie tak tam ten
to tu w we z za ze oraz czyli jako tez jesli mozna trzeba moje moja moj nasz nasza nasze co wiemy""".split())

# Przykładowe grupy synonimów domenowych.
# Każde słowo w grupie rozwija się w zapytaniu do zbioru rdzeni całej grupy (liczonych jako jedno pojęcie).
GRUPY_SYNONIMOW = [
    ["plakietka", "badge", "etykieta", "omnibus"],
    ["koszyk", "nieudany", "niedokonczone", "przerwana", "porzucony"],
    ["cutover", "przelaczenie", "migracja"],
    ["pulapka", "blad", "bledy", "regresja", "awaria"],
    ["gpsr", "bezpieczenstwo", "ostrzezenie"],
]
SYNONIMY_RDZENI = {}
for _grupa in GRUPY_SYNONIMOW:
    _zbior = {s[:RDZEN] for s in _grupa}
    for _r in _zbior:
        SYNONIMY_RDZENI[_r] = SYNONIMY_RDZENI.get(_r, set()) | _zbior


def wykryj_obszary(sejf: Path) -> list[str]:
    znalezione = [p.name for p in sorted(sejf.iterdir()) if p.is_dir() and (p / "wiki").is_dir()]
    return znalezione or OBSZARY


def bez_ogonkow(t):
    t = t.lower().replace("ł", "l")
    return "".join(z for z in unicodedata.normalize("NFKD", t) if not unicodedata.combining(z))


def slowa(t):
    return re.findall(r"[a-z0-9]+", bez_ogonkow(t))


def rdzen(s):
    return s[:RDZEN]


def rdzenie(t):
    return {rdzen(s) for s in slowa(t)}


def rozdziel(tekst):
    if not tekst.startswith("---\n"):
        return {}, tekst
    koniec = tekst.find("\n---\n", 4)
    if koniec < 0:
        return {}, tekst
    try:
        fm = yaml.safe_load(tekst[4:koniec]) or {}
    except yaml.YAMLError:
        fm = {}
    return (fm if isinstance(fm, dict) else {}), tekst[koniec + 5:]


def jako_tekst(w):
    if w is None:
        return ""
    if isinstance(w, list):
        return " ".join(str(x) for x in w)
    return str(w)


def pola_strony(sciezka):
    fm, tresc = rozdziel(sciezka.read_text(encoding="utf-8"))
    h1 = re.search(r"^# (.+)$", tresc, re.M)
    naglowki = " ".join(re.findall(r"^#{2,6} +(.+)$", tresc, re.M))
    return fm, {
        "nazwa": rdzenie(sciezka.stem.replace("-", " ")),
        "tytul": rdzenie(jako_tekst(fm.get("aliases")) + " " + (h1.group(1) if h1 else "")),
        "opis": rdzenie(jako_tekst(fm.get("opis"))),
        "tagi": rdzenie(jako_tekst(fm.get("tagi"))),
        "naglowki": rdzenie(naglowki),
        "tresc": rdzenie(tresc),
    }


def slowa_pytania(pytanie):
    wynik = []
    for s in slowa(pytanie):
        if s in POMIJANE or (len(s) < 3 and not s.isdigit()):
            continue
        r = rdzen(s)
        if r not in wynik:
            wynik.append(r)
    return wynik


def ocen(rdzenie_pytania, pola, fm):
    wynik = 0.0
    for r in rdzenie_pytania:
        warianty = SYNONIMY_RDZENI.get(r, {r})
        wynik += max((WAGI[p] for p, zbior in pola.items() if warianty & zbior), default=0.0)
    if wynik and str(fm.get("status", "")) in ("zastąpiona", "archiwalna"):
        wynik -= KARA_NIEAKTUALNA
    return wynik


def sciezka_bazy(sejf):
    sejf = Path(sejf)
    git_dir = sejf / ".git"
    if git_dir.is_file():
        try:
            tresc = git_dir.read_text(encoding="utf-8").strip()
            if tresc.startswith("gitdir:"):
                kandydat = Path(tresc.split(":", 1)[1].strip())
                if not kandydat.is_absolute():
                    kandydat = (sejf / kandydat).resolve()
                if kandydat.is_dir():
                    return kandydat / "wiki-search.db"
        except OSError:
            pass
    elif git_dir.is_dir():
        return git_dir / "wiki-search.db"
    h = hashlib.md5(str(sejf.resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"wiki-search-{h}.db"


def zsynchronizuj_baze(con, sejf):
    con.execute("""
        CREATE TABLE IF NOT EXISTS pages_meta (
            sciezka TEXT PRIMARY KEY,
            mtime REAL,
            fm_json TEXT,
            nazwa TEXT,
            tytul TEXT,
            opis TEXT,
            tagi TEXT,
            naglowki TEXT,
            tresc TEXT
        )
    """)
    con.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            sciezka UNINDEXED,
            nazwa,
            tytul,
            opis,
            tagi,
            naglowki,
            tresc,
            tokenize = 'unicode61'
        )
    """)
    cur = con.execute("SELECT sciezka, mtime FROM pages_meta")
    znane = dict(cur.fetchall())

    pliki_na_dysku = {}
    for obszar in wykryj_obszary(sejf):
        katalog = sejf / obszar / "wiki"
        if not katalog.is_dir():
            continue
        for p in katalog.rglob("*.md"):
            rel = str(p.relative_to(sejf))
            try:
                pliki_na_dysku[rel] = (p, p.stat().st_mtime)
            except OSError:
                pass

    usuniete = set(znane) - set(pliki_na_dysku)
    for rel in usuniete:
        con.execute("DELETE FROM pages_meta WHERE sciezka = ?", (rel,))
        con.execute("DELETE FROM pages_fts WHERE sciezka = ?", (rel,))

    zmienione = [rel for rel, (p, mt) in pliki_na_dysku.items() if rel not in znane or znane[rel] != mt]
    for rel in zmienione:
        p, mt = pliki_na_dysku[rel]
        fm, pola = pola_strony(p)
        fm_json = json.dumps(fm, default=str, ensure_ascii=False)
        nazwa_s = " ".join(sorted(pola["nazwa"]))
        tytul_s = " ".join(sorted(pola["tytul"]))
        opis_s = " ".join(sorted(pola["opis"]))
        tagi_s = " ".join(sorted(pola["tagi"]))
        naglowki_s = " ".join(sorted(pola["naglowki"]))
        tresc_s = " ".join(sorted(pola["tresc"]))

        con.execute("DELETE FROM pages_meta WHERE sciezka = ?", (rel,))
        con.execute("DELETE FROM pages_fts WHERE sciezka = ?", (rel,))
        con.execute("INSERT INTO pages_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            rel, mt, fm_json, nazwa_s, tytul_s, opis_s, tagi_s, naglowki_s, tresc_s
        ))
        con.execute("INSERT INTO pages_fts VALUES (?, ?, ?, ?, ?, ?, ?)", (
            rel, nazwa_s, tytul_s, opis_s, tagi_s, naglowki_s, tresc_s
        ))

    if usuniete or zmienione:
        con.commit()


def szukaj_sqlite(pytanie, sejf, n):
    rp = slowa_pytania(pytanie)
    if not rp:
        return []
    wszystkie_rdzenie = set().union(*(SYNONIMY_RDZENI.get(r, {r}) for r in rp))
    if not wszystkie_rdzenie:
        return []
    db_p = sciezka_bazy(sejf)
    db_p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_p))
    try:
        zsynchronizuj_baze(con, sejf)
        fts_q = " OR ".join(f'"{r}"' for r in sorted(wszystkie_rdzenie))
        cur = con.execute("""
            SELECT sciezka, nazwa, tytul, opis, tagi, naglowki, tresc, fm_json 
            FROM pages_meta 
            WHERE sciezka IN (SELECT sciezka FROM pages_fts WHERE pages_fts MATCH ?)
        """, (fts_q,))
        trafienia = []
        for row in cur.fetchall():
            pola = {
                "nazwa": set(row[1].split()),
                "tytul": set(row[2].split()),
                "opis": set(row[3].split()),
                "tagi": set(row[4].split()),
                "naglowki": set(row[5].split()),
                "tresc": set(row[6].split()),
            }
            fm = json.loads(row[7])
            w = ocen(rp, pola, fm)
            if w > 0:
                trafienia.append((w, row[0], fm))
        trafienia.sort(key=lambda t: (-t[0], t[1]))
        return trafienia[:n]
    finally:
        con.close()


def szukaj_pliki(pytanie, sejf=SEJF, n=8):
    rp = slowa_pytania(pytanie)
    if not rp:
        return []
    trafienia = []
    sejf_p = Path(sejf)
    for obszar in wykryj_obszary(sejf_p):
        katalog = sejf_p / obszar / "wiki"
        if not katalog.is_dir():
            continue
        for p in sorted(katalog.rglob("*.md")):
            fm, pola = pola_strony(p)
            w = ocen(rp, pola, fm)
            if w > 0:
                trafienia.append((w, str(p.relative_to(sejf_p)), fm))
    trafienia.sort(key=lambda t: (-t[0], t[1]))
    return trafienia[:n]


def szukaj(pytanie, sejf=SEJF, n=8):
    sejf = Path(sejf)
    try:
        return szukaj_sqlite(pytanie, sejf, n)
    except Exception:
        return szukaj_pliki(pytanie, sejf, n)


def main(argv):
    ap = argparse.ArgumentParser(description="Wyszukiwarka stron sejfu (tylko odczyt).")
    ap.add_argument("pytanie", nargs="+")
    ap.add_argument("-n", type=int, default=8)
    ap.add_argument("--sejf", default=str(SEJF))
    a = ap.parse_args(argv)
    wyniki = szukaj(" ".join(a.pytanie), Path(a.sejf), a.n)
    if not wyniki:
        print("brak trafień - spróbuj innych słów, potem index.md i indeks obszaru")
        return 1
    for w, sciezka, fm in wyniki:
        opis = jako_tekst(fm.get("opis"))[:140]
        status = fm.get("status")
        znacznik = f"{fm.get('typ', '?')}" + (f", {status}" if status else "")
        if fm.get("hub_folderu"):
            znacznik += ", wejście folderu"
        print(f"{w:5.1f}  {sciezka}  [{znacznik}]  {opis}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
