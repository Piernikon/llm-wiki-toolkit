#!/usr/bin/env python3
"""Kontrola zapisu do sejfu przed commitem (strażnik pre-commit). Tylko odczyt. Uruchomienie:

    git add -- <pliki> && python3 tools/sprawdz-zapis.py --sejf <sciezka>

Sprawdza zmiany przygotowane do commitu (`git diff --cached`) i stan sejfu:
1. `raw/` tylko dodawane: zmiana, usunięcie albo przeniesienie istniejącego pliku w `*/raw/` = BŁĄD;
2. `log.md` tylko dopisywany na końcu: usunięta albo zmieniona linia = BŁĄD;
3. pliki poza ścieżkami bibliotekarza (`*/wiki/`, `*/raw/`, indeksy, `log.md`, `overview.md`, `AGENTS.md`,
   `CLAUDE.md`, `_szablony/`, `_narzedzia/`, `.obsidian/`, `.gitignore`, `.gitattributes`) = UWAGA;
4. `zbuduj-indeksy.py --sprawdz` ma kod 0 (indeksy aktualne) - inaczej BŁĄD;
5. martwe linki `[[...]]` w stronach (bez `raw/`, `_szablony/`, `AGENTS.md`, kodu w backtickach) = BŁĄD;
6. martwe lokalne ścieżki w polu `źródła:` w frontmatterze stron `*/wiki/**` = BŁĄD;
7. pole `głos:` (pochodzenie treści): nowa strona `*/wiki/**` bez pola albo z wartością spoza
   GLOSY = BŁĄD; `decyzja` ze `status: obowiązuje` bez głosu `wlasciciel`/`wybor-widzet` = BŁĄD;
   zmieniona stara strona bez pola = UWAGA;
8. datowanie i chronologia:
   - format `aktualizacja: RRRR-MM-DD` w nowej stronie `*/wiki/**` = BŁĄD (zmieniona stara brak = UWAGA, zły format = BŁĄD);
   - `typ: decyzja` nazwa `decyzja-RRRR-MM-DD-slug.md` i podfolder `historia/` = BŁĄD;
   - `typ: źródło` nazwa `zrodlo-RRRR-MM-DD-slug.md` i podfolder `historia/` = BŁĄD;
   - nowy wpis nagłówka w `log.md` musi mieć format `## [RRRR-MM-DD] ...` = BŁĄD.
Kod wyjścia 1 = jest BŁĄD (nie commituj, popraw); 0 = można commitować. `--bez-indeksow` pomija punkt 4.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
import yaml

SEJF = Path(__file__).resolve().parent.parent
DOZWOLONE = re.compile(r"^([^/]+/(wiki|raw)/|[^/]+/index\.md$|(index|log|overview|AGENTS|CLAUDE)\.md$|"
                       r"_szablony/|_narzedzia/|tools/|tests/|examples/|\.obsidian/|\.gitignore$|\.gitattributes$)")
RAW = re.compile(r"^[^/]+/raw/")
LINK = re.compile(r"\[\[([^\]|#]+)")
KOD = re.compile(r"`[^`]*`")


def git(sejf, *argumenty):
    return subprocess.run(["git", "-C", str(sejf), "-c", "core.quotepath=false", *argumenty], capture_output=True, text=True, check=True).stdout


def zmiany(sejf):
    """Lista (status, ścieżka) ze staged; przy przeniesieniu ścieżka źródłowa."""
    wynik = []
    for linia in git(sejf, "diff", "--cached", "--name-status", "-M").splitlines():
        czesci = linia.split("\t")
        wynik.append((czesci[0][0], czesci[1]))
        if czesci[0][0] in "RC" and len(czesci) > 2:
            wynik.append(("A", czesci[2]))
    return wynik


def bledy_raw(lista):
    return [f"raw/ zmieniony ({s}): {p}" for s, p in lista if RAW.match(p) and s in "MDR"]


WZOR_LOG = re.compile(r"^## \[\d{4}-\d{2}-\d{2}\] [^|]+ \| [^|]+ \| .+")


def bledy_logu(sejf):
    diff = git(sejf, "diff", "--cached", "-U0", "--", "log.md")
    linie = diff.splitlines()
    dodane = {l[1:] for l in linie if l.startswith("+") and not l.startswith("+++")}
    usuniete = [l for l in linie if l.startswith("-") and not l.startswith("---") and l[1:] not in dodane]
    bledy = [f"log.md: usunięta/zmieniona linia: {l[1:80]}" for l in usuniete]
    for l in dodane:
        if l.startswith("## ") and not WZOR_LOG.match(l):
            bledy.append(f"log.md: błędny format wpisu (wymagany: ## [RRRR-MM-DD] <operacja> | <agent> | <tytuł> | <strony>): {l[:80]}")
    return bledy


def uwagi_sciezek(lista):
    return [f"ścieżka poza zakresem bibliotekarza: {p}" for s, p in lista if s != "D" and not DOZWOLONE.match(p)]


def martwe_linki(sejf):
    sejf = Path(sejf)
    nazwy = {p.stem for p in sejf.rglob("*.md") if ".git" not in p.parts}
    martwe = set()
    for p in sejf.rglob("*.md"):
        rel = p.relative_to(sejf)
        if ".git" in rel.parts or "_szablony" in rel.parts or "raw" in rel.parts or rel.name in ("AGENTS.md", "README.md"):
            continue
        tekst = re.sub(r"```.*?```", "", p.read_text(encoding="utf-8"), flags=re.S)
        for cel in LINK.findall(KOD.sub("", tekst)):
            cel = cel.strip().rstrip("\\")
            if Path(cel).name not in nazwy:
                martwe.add(f"martwy link [[{cel}]] w {rel}")
    return sorted(martwe)


def martwe_zrodla(sejf):
    sejf = Path(sejf)
    martwe = []
    for p in sorted(sejf.rglob("*.md")):
        rel = p.relative_to(sejf)
        if ".git" in rel.parts or len(rel.parts) < 2 or rel.parts[1] != "wiki":
            continue
        tekst = p.read_text(encoding="utf-8")
        if not tekst.startswith("---\n"):
            continue
        czesci = tekst.split("\n---\n", 1)
        if len(czesci) != 2:
            continue
        fm = yaml.safe_load(czesci[0][4:]) or {}
        zr = fm.get("źródła") or []
        if isinstance(zr, str):
            zr = [zr]
        for wpis in zr:
            if not isinstance(wpis, str) or wpis.startswith(("http://", "https://")):
                continue
            czysta = wpis.split("#")[0].strip()
            sciezka = Path(os.path.expanduser(czysta))
            if not sciezka.is_absolute():
                sciezka = sejf / sciezka
            if not sciezka.exists() and " (" in czysta:
                czysta = czysta.split(" (")[0].strip()
                sciezka = Path(os.path.expanduser(czysta))
                if not sciezka.is_absolute():
                    sciezka = sejf / sciezka
            if not sciezka.exists():
                martwe.append(f"martwe źródło w {rel}: {wpis}")
    return martwe


GLOSY = {"wlasciciel", "wybor-widzet", "agent", "zrodlo"}


def frontmatter(p):
    tekst = p.read_text(encoding="utf-8")
    if not tekst.startswith("---\n"):
        return None
    czesci = tekst.split("\n---\n", 1)
    if len(czesci) != 2:
        return None
    try:
        return yaml.safe_load(czesci[0][4:]) or {}
    except yaml.YAMLError:
        return None


def kontrola_glosu(sejf, lista):
    """Zwraca (bledy, uwagi) dla pola `głos:` w dodanych/zmienionych stronach `*/wiki/**`."""
    bledy, uwagi = [], []
    for s, rel in lista:
        czesci = Path(rel).parts
        if s == "D" or len(czesci) < 3 or czesci[1] != "wiki" or not rel.endswith(".md"):
            continue
        p = Path(sejf) / rel
        if not p.exists():
            continue
        fm = frontmatter(p)
        if fm is None:
            continue
        glos = fm.get("głos")
        if glos is None:
            (bledy if s == "A" else uwagi).append(f"brak pola `głos:` w {rel}")
            continue
        glosy = set(glos if isinstance(glos, list) else [glos])
        zle = glosy - GLOSY
        if zle:
            bledy.append(f"nieznany `głos` {sorted(zle)} w {rel} (dozwolone: {sorted(GLOSY)})")
        if fm.get("typ") == "decyzja" and fm.get("status") == "obowiązuje" \
                and not glosy & {"wlasciciel", "wybor-widzet"}:
            bledy.append(f"decyzja `obowiązuje` bez głosu właściciela w {rel} (ustaw `status: propozycja`)")
    return bledy, uwagi


NAZWA_DECYZJI = re.compile(r"^decyzja-\d{4}-\d{2}-\d{2}-.+\.md$")
NAZWA_ZRODLA = re.compile(r"^zrodlo-\d{4}-\d{2}-\d{2}-.+\.md$")
DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def kontrola_dat_i_nazw(sejf, lista):
    """Sprawdza datowanie i nazewnictwo decyzji/źródeł w dodanych/zmienionych stronach `*/wiki/**`."""
    bledy, uwagi = [], []
    for s, rel in lista:
        czesci = Path(rel).parts
        if s == "D" or len(czesci) < 3 or czesci[1] != "wiki" or not rel.endswith(".md"):
            continue
        p = Path(sejf) / rel
        if not p.exists():
            continue
        fm = frontmatter(p)
        if fm is None:
            continue
        typ = fm.get("typ")
        akt = fm.get("aktualizacja")
        nazwa = p.name

        if akt is None:
            (bledy if s == "A" else uwagi).append(f"brak pola `aktualizacja:` w {rel}")
        elif not DATA_ISO.match(str(akt)):
            bledy.append(f"błędny format daty `aktualizacja:` w {rel}: '{akt}' (wymagany: RRRR-MM-DD)")

        if typ == "decyzja":
            if not NAZWA_DECYZJI.match(nazwa):
                bledy.append(f"błędna nazwa decyzji {rel} (wymagany format: decyzja-RRRR-MM-DD-slug.md dla zachowania chronologii)")
            if "historia" not in czesci:
                bledy.append(f"decyzja {rel} musi leżeć w podfolderze `historia/` tematu lub kursu")

        if typ == "źródło":
            if not NAZWA_ZRODLA.match(nazwa):
                bledy.append(f"błędna nazwa źródła {rel} (wymagany format: zrodlo-RRRR-MM-DD-slug.md)")
            if "historia" not in czesci:
                bledy.append(f"źródło {rel} musi leżeć w podfolderze `historia/` tematu lub kursu")

        if nazwa.startswith("decyzja-") and typ != "decyzja":
            bledy.append(f"plik {rel} zaczyna się od `decyzja-`, ale ma `typ: {typ}` (wymagany: `typ: decyzja`)")
        if nazwa.startswith("zrodlo-") and typ != "źródło":
            bledy.append(f"plik {rel} zaczyna się od `zrodlo-`, ale ma `typ: {typ}` (wymagany: `typ: źródło`)")

    return bledy, uwagi


def main(argv):
    ap = argparse.ArgumentParser(description="Kontrola zapisu do sejfu przed commitem.")
    ap.add_argument("--sejf", default=str(SEJF))
    ap.add_argument("--bez-indeksow", action="store_true")
    a = ap.parse_args(argv)
    lista = zmiany(a.sejf)
    bledy = bledy_raw(lista) + bledy_logu(a.sejf) + martwe_linki(a.sejf) + martwe_zrodla(a.sejf)
    b_glos, u_glos = kontrola_glosu(a.sejf, lista)
    b_daty, u_daty = kontrola_dat_i_nazw(a.sejf, lista)
    bledy += b_glos + b_daty
    uwagi = uwagi_sciezek(lista) + u_glos + u_daty
    for u in uwagi:
        print(f"UWAGA  {u}")
    for b in bledy:
        print(f"BŁĄD   {b}")
    print(f"zmienionych plików: {len(lista)}, błędów: {len(bledy)}, uwag: {len(uwagi)}")
    return 1 if bledy else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
