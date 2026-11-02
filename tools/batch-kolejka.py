#!/usr/bin/env python3
"""
batch-kolejka.py - Lekka kolejka zadań dla Anthropic Message Batches API (-50% ceny, 0 tokenów kontekstu w sesji).

Zastosowanie:
  1. Dodanie zadania z terminala lub przez dowolnego agenta (Claude Code / Gemini / Codex):
     python3 tools/batch-kolejka.py add \
       --id "katalog-en" \
       --model haiku \
       --prompt "Przetłumacz poniższe opisy produktów na język angielski..." \
       --file ./data/katalog.csv \
       --out ./out/tlumaczenia-en.md

  2. Wysłanie oczekujących zadań jako jednej paczki Batch API (-50% ceny):
     ANTHROPIC_API_KEY="..." python3 tools/batch-kolejka.py submit

  3. Sprawdzenie statusu i pobranie gotowych wyników do plików docelowych (--out lub _inbox/):
     ANTHROPIC_API_KEY="..." python3 tools/batch-kolejka.py status --fetch

  4. Podgląd lokalnej kolejki (0 tokenów, bez klucza API):
     python3 tools/batch-kolejka.py list
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(os.environ.get("LLM_WIKI_BATCH_DIR", Path.home() / ".config" / "anthropic-batch"))
QUEUE_FILE = BASE_DIR / "kolejka.jsonl"
BATCHES_FILE = BASE_DIR / "aktywne-paczki.json"
DEFAULT_OUT_DIR = Path(os.environ.get("LLM_WIKI_INBOX_DIR", "./_inbox"))
KEY_FILE = Path.home() / ".config" / "anthropic" / "api-key"

MODEL_ALIASES = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-5-20251101",
}

API_URL = "https://api.anthropic.com/v1/messages/batches"
API_VERSION = "2023-06-01"


def ensure_dirs() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not QUEUE_FILE.exists():
        QUEUE_FILE.write_text("", encoding="utf-8")
    if not BATCHES_FILE.exists():
        BATCHES_FILE.write_text("[]", encoding="utf-8")


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip()
    sys.exit(
        "BŁĄD: Brak klucza API. Podaj zmienną ANTHROPIC_API_KEY=... przed komendą "
        f"lub zapisz klucz w {KEY_FILE} (chmod 600)."
    )


def sanitize_custom_id(raw_id: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]", "-", raw_id).strip("-")
    return (clean or "zadanie")[:64]


def load_queue() -> list[dict]:
    ensure_dirs()
    items = []
    for line in QUEUE_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            items.append(json.loads(line))
    return items


def save_queue(items: list[dict]) -> None:
    ensure_dirs()
    content = "\n".join(json.dumps(x, ensure_ascii=False) for x in items)
    if content:
        content += "\n"
    QUEUE_FILE.write_text(content, encoding="utf-8")


def load_batches() -> list[dict]:
    ensure_dirs()
    return json.loads(BATCHES_FILE.read_text(encoding="utf-8"))


def save_batches(batches: list[dict]) -> None:
    ensure_dirs()
    BATCHES_FILE.write_text(json.dumps(batches, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def api_request(method: str, url: str, api_key: str, payload: dict | None = None) -> dict | str:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            ctype = resp.headers.get("content-type", "")
            if "application/json" in ctype:
                return json.loads(raw)
            return raw
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"BŁĄD API ({e.code}): {err_body}")


def cmd_add(args: argparse.Namespace) -> None:
    items = load_queue()
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    cid = sanitize_custom_id(f"{args.id}-{ts}")
    model = MODEL_ALIASES.get(args.model, args.model)

    prompt_parts = [args.prompt.strip()]
    for fpath in args.file or []:
        p = Path(fpath).expanduser().resolve()
        if not p.exists():
            sys.exit(f"BŁĄD: Plik wejściowy nie istnieje: {p}")
        text = p.read_text(encoding="utf-8", errors="replace")
        prompt_parts.append(f"\n--- PLIK: {p.name} ---\n{text}")

    full_prompt = "\n".join(prompt_parts)
    out_path = (
        str(Path(args.out).expanduser().resolve())
        if args.out
        else str(DEFAULT_OUT_DIR / f"{dt.date.today().isoformat()}-batch-{sanitize_custom_id(args.id)}.md")
    )

    entry = {
        "custom_id": cid,
        "title": args.id,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "max_tokens": args.max_tokens,
        "system": args.system or "Odpowiadaj po polsku z pełną diakrytyką, konkretnie i bez lania wody. W tekstach używaj zwykłego dywizu (-).",
        "prompt": full_prompt,
        "out_path": out_path,
        "obszar": args.obszar,
    }
    items.append(entry)
    save_queue(items)
    est_tokens = len(full_prompt) // 4
    print(f"Dodano do kolejki Batch: {cid}")
    print(f"  Model: {model} | Szacowane wejście: ~{est_tokens} tok | Wyjście: {out_path}")
    print(f"  Łącznie w kolejce oczekuje: {len(items)} zadań.")


def cmd_list(_: argparse.Namespace) -> None:
    items = load_queue()
    batches = load_batches()
    print(f"=== Oczekujące w kolejce lokalnej ({len(items)}) ===")
    for i, it in enumerate(items, 1):
        est_tok = len(it["prompt"]) // 4
        print(f"  {i}. [{it['custom_id']}] model={it['model']} (~{est_tok} tok) -> {it['out_path']}")
    print(f"\n=== Wysłane paczki Batch ({len(batches)}) ===")
    for b in batches[-10:]:
        print(
            f"  - {b['batch_id']} | wysłano: {b['submitted_at']} | zadań: {len(b['tasks'])} | status: {b.get('status', 'unknown')}"
        )


def cmd_submit(_: argparse.Namespace) -> None:
    items = load_queue()
    if not items:
        print("Kolejka lokalna jest pusta - nie ma czego wysyłać.")
        return
    api_key = get_api_key()
    requests_payload = []
    task_map = {}
    for it in items:
        req_item = {
            "custom_id": it["custom_id"],
            "params": {
                "model": it["model"],
                "max_tokens": it["max_tokens"],
                "system": it["system"],
                "messages": [{"role": "user", "content": it["prompt"]}],
            },
        }
        requests_payload.append(req_item)
        task_map[it["custom_id"]] = {
            "title": it["title"],
            "out_path": it["out_path"],
            "obszar": it.get("obszar", "narzedziownik"),
            "model": it["model"],
        }

    resp = api_request("POST", API_URL, api_key, {"requests": requests_payload})
    assert isinstance(resp, dict)
    batch_id = resp["id"]
    batches = load_batches()
    batches.append(
        {
            "batch_id": batch_id,
            "submitted_at": dt.datetime.now().isoformat(timespec="seconds"),
            "status": resp.get("processing_status", "in_progress"),
            "tasks": task_map,
            "fetched": False,
        }
    )
    save_batches(batches)
    save_queue([])
    print(f"Wysłano paczkę Batch API: {batch_id} ({len(requests_payload)} zadań, -50% stawki API).")
    print("Aby sprawdzić wynik i zapisać pliki: python3 tools/batch-kolejka.py status --fetch")


def cmd_status(args: argparse.Namespace) -> None:
    batches = load_batches()
    if not batches:
        print("Brak wysłanych paczek Batch.")
        return
    api_key = get_api_key()
    changed = False
    for b in batches:
        if b.get("fetched") and not args.all:
            continue
        bid = b["batch_id"]
        info = api_request("GET", f"{API_URL}/{bid}", api_key)
        assert isinstance(info, dict)
        status = info.get("processing_status", "unknown")
        counts = info.get("request_counts", {})
        b["status"] = status
        changed = True
        print(f"Paczka {bid}: status={status} | {counts}")

        if status == "ended" and args.fetch and not b.get("fetched"):
            results_url = info.get("results_url")
            if not results_url:
                continue
            raw_jsonl = api_request("GET", results_url, api_key)
            assert isinstance(raw_jsonl, str)
            for line in raw_jsonl.splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                cid = row["custom_id"]
                meta = b["tasks"].get(cid, {})
                out_path = Path(meta.get("out_path", DEFAULT_OUT_DIR / f"{cid}.md"))
                out_path.parent.mkdir(parents=True, exist_ok=True)
                res_obj = row.get("result", {})
                if res_obj.get("type") == "succeeded":
                    msg = res_obj["message"]
                    text_blocks = [blk.get("text", "") for blk in msg.get("content", []) if blk.get("type") == "text"]
                    body = "\n\n".join(text_blocks).strip()
                    usage = msg.get("usage", {})
                    if str(out_path).startswith(str(DEFAULT_OUT_DIR)):
                        header = (
                            f"---\n"
                            f"obszar: {meta.get('obszar', 'narzedziownik')}\n"
                            f"źródło: Batch API ({meta.get('model', 'claude')}, batch={bid})\n"
                            f"data: {dt.date.today().isoformat()}\n"
                            f"głos: agent\n"
                            f"---\n\n"
                        )
                        out_path.write_text(header + body + "\n", encoding="utf-8")
                    else:
                        out_path.write_text(body + "\n", encoding="utf-8")
                    print(f"  [ZAPISANO] {cid} -> {out_path} (in={usage.get('input_tokens')}, out={usage.get('output_tokens')})")
                else:
                    print(f"  [BŁĄD ZADANIA] {cid}: {res_obj}")
            b["fetched"] = True
            changed = True
    if changed:
        save_batches(batches)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lekka kolejka zadań Anthropic Message Batches API (-50% ceny).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Dodaj zadanie do lokalnej kolejki (0 tokenów, bez wysyłania)")
    p_add.add_argument("--id", required=True, help="Krótki identyfikator zadania, np. katalog-en")
    p_add.add_argument("--model", default="sonnet", help="haiku | sonnet | opus lub pełny ID modelu (domyślnie: sonnet)")
    p_add.add_argument("--prompt", required=True, help="Instrukcja dla modelu")
    p_add.add_argument("--file", action="append", help="Ścieżka do pliku wejściowego (można podać wielokrotnie)")
    p_add.add_argument("--out", help="Ścieżka zapisu wyniku (domyślnie: ./_inbox/RRRR-MM-DD-batch-<id>.md)")
    p_add.add_argument("--obszar", default="narzedziownik", help="Obszar sejfu, jeśli wynik trafia do _inbox/")
    p_add.add_argument("--max-tokens", type=int, default=8192, help="Maksymalna liczba tokenów odpowiedzi")
    p_add.add_argument("--system", help="Opcjonalny system prompt")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="Pokaż oczekujące zadania i wysłane paczki")
    p_list.set_defaults(func=cmd_list)

    p_sub = sub.add_parser("submit", help="Wyślij całą kolejkę do Anthropic Batch API")
    p_sub.set_defaults(func=cmd_submit)

    p_stat = sub.add_parser("status", help="Sprawdź status paczek i pobierz gotowe wyniki")
    p_stat.add_argument("--fetch", action="store_true", help="Pobierz i zapisz ukończone wyniki do plików")
    p_stat.add_argument("--all", action="store_true", help="Pokaż też już pobrane paczki")
    p_stat.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
