# `llm-wiki-toolkit` - Deterministic Guardrails, Hybrid FTS5 Search & Batch Queue for Agentic Knowledge Bases

A zero-bloat Python toolkit for operating a personal or team **LLM Wiki** in Obsidian/Markdown with multiple AI agents (Claude Code, Gemini, Codex, Hermes).

Inspired by **[Andrej Karpathy's LLM Wiki pattern](https://x.com/karpathy)**: instead of relying on fragile chunk-based RAG over raw documents, an AI "librarian" compiles immutable raw sources (`raw/`) into strongly-typed, interlinked Markdown pages (`wiki/`), while deterministic Python scripts enforce structural integrity, provenance, and zero-token indexing.

---

## Why This Exists (Problem -> Solution)

When multiple AI coding agents read and write to a shared Markdown knowledge base (hundreds of pages), four failure modes appear quickly:
1. **Context bloat & slow search:** Grepping hundreds of files on every turn wastes tokens and misses inflected words (especially in morphologically rich languages like Polish).
2. **Epistemic pollution ("Who said this?"):** Agents paraphrase user ideas or present their own suggestions as binding architectural decisions.
3. **Silent link rot & chronological drift:** Agents invent dead `[[wikilinks]]`, cite non-existent local file paths in YAML frontmatter, or overwrite historical logs.
4. **High API costs on background tasks:** Running bulk translations, SEO summaries, or source classifications inside interactive agent sessions burns expensive interactive context.

`llm-wiki-toolkit` solves all four with **deterministic scripts (0 LLM tokens)** that run as CLI tools and pre-commit guards:

| Tool | Role | Key Technical Mechanism |
|---|---|---|
| [`tools/szukaj.py`](tools/szukaj.py) | **Hybrid FTS5 + Stem/Synonym Search** | Incremental `SQLite FTS5` index (`unicode61`) stored inside `.git/` (worktree-aware) + 5-character morphological stem matching + domain synonym expansion + field-weighted ranking (`H1/aliases: 4.0`, `opis: 3.0`, `tagi: 2.0`, `headers: 1.5`, `body: 0.5`, penalty for `archived/superseded` pages). Automatic fallback to file scanning if SQLite is unavailable. |
| [`tools/sprawdz-zapis.py`](tools/sprawdz-zapis.py) | **Pre-Commit Governance & Provenance Guard** | Inspects `git diff --cached` before any commit: enforces append-only `raw/` and `log.md`, detects dead `[[wikilinks]]` and missing local paths in `źródła:`, validates **Voice Provenance (`głos:`)** (blocks `status: obowiązuje` decisions unless backed by `wlasciciel` or `wybor-widzet`), and enforces `YYYY-MM-DD` naming and `historia/` placement. |
| [`tools/batch-kolejka.py`](tools/batch-kolejka.py) | **Anthropic Message Batches API Queue (-50% cost)** | Zero-dependency CLI queue (`add`, `list`, `submit`, `status --fetch`) that batches non-urgent LLM jobs (translations, classifications, source digests) to the official [Anthropic Message Batches API](https://docs.anthropic.com/en/docs/build-with-claude/batch-processing) at **50% cost** and **0 interactive session tokens**, writing completed outputs directly to `_inbox/` with `głos: agent` frontmatter. |

---

## Architectural Highlights

### 1. Voice Provenance Tracking (`głos:`) - Preventing Agent Hallucinated Decisions

Every page in the wiki must declare who authored its claims via the `głos` frontmatter field, enforced by [`tools/sprawdz-zapis.py`](tools/sprawdz-zapis.py):

| Voice (`głos`) | Meaning | Allowed to set `decyzja` -> `status: obowiązuje`? |
|---|---|---|
| `wlasciciel` | Written or dictated verbatim by the human owner | **Yes** (requires `> [!wlasciciel] YYYY-MM-DD` callout on mixed pages) |
| `wybor-widzet` | Selected by the human owner from structured options presented by an agent (`ask_question` widget) | **Yes** (records both the chosen option and rejected alternatives in `> [!wybor]`) |
| `agent` | Synthesis, summary, recommendation, or inference by an LLM | **No** - blocked by pre-commit guard (must use `status: propozycja`) |
| `zrodlo` | Digest of an external document (PDF, web page, spec) | **No** |

### 2. Two-Stage Hybrid Search (`SQLite FTS5` + Weighted Field Scoring)

```text
Agent Query: "Kiedy pokazujemy plakietkę promocji?"
       │
       ▼
1. Tokenize + Strip Diacritics + 5-char Stem ("plaki", "promo")
       │
       ▼
2. Expand Domain Synonym Groups ("plaki" -> {"plaki", "badge", "etyki", "omnib"})
       │
       ▼
3. Incremental SQLite FTS5 Match (`pages_fts` synced by mtime in <15 ms)
       │
       ▼
4. Field-Weighted Scoring:
   - Filename / H1 / aliases : +4.0
   - Description (`opis`)    : +3.0
   - Tags (`tagi`)           : +2.0
   - H2-H6 Headers           : +1.5
   - Body Text               : +0.5
   - Superseded / Archived   : -1.0 penalty
```

---

## Quick Start & Running the Test Suite

Requirements: **Python 3.10+** and `PyYAML` (`pip install pyyaml`). No heavy frameworks or vector databases required.

```bash
# 1. Run unit tests for the FTS5 search engine (creates an isolated temp vault)
python3 tests/szukaj.test.py

# 2. Run unit tests for the pre-commit governance guard (creates an isolated temp git repo)
python3 tests/sprawdz-zapis.test.py

# 3. Search an example vault
python3 tools/szukaj.py --sejf ./examples/demo-vault "plakietka promocji"

# 4. Queue a background task for Anthropic Message Batches API (-50% cost)
python3 tools/batch-kolejka.py add \
  --id "summarize-rfc" \
  --model haiku \
  --prompt "Summarize key architectural trade-offs in 5 bullet points:" \
  --file ./README.md
python3 tools/batch-kolejka.py list
```

---

## Credits & Inspirations

- **[Andrej Karpathy](https://github.com/karpathy)** - for articulating the *LLM Wiki* concept (agents maintaining a compiled, interlinked Markdown wiki over immutable raw sources rather than relying solely on ad-hoc RAG).
- **[Obsidian](https://obsidian.md/)** - used as the human-facing IDE/browser over the plain-text Markdown vault.
- **[Anthropic](https://www.anthropic.com/)** - Claude Code CLI & [Message Batches API](https://docs.anthropic.com/en/docs/build-with-claude/batch-processing).
- **[SQLite FTS5](https://www.sqlite.org/fts5.html)** - embedded full-text search engine included in Python's standard library.

## License

MIT License - Copyright (c) 2026 Mateusz Piernikarczyk (`@Piernikon`). See [LICENSE](LICENSE).
