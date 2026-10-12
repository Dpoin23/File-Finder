# File Finder

Local search over folders and repositories. A filename fragment and a sentence about the contents both hit the same index. File bytes stay on the machine. A model, if used at all, only reranks the top 15 snippets and stays off unless you opt in.

The search behavior is specified in [docs/DESIGN.md](docs/DESIGN.md). The desktop launcher is a later surface, specified in [docs/DESKTOP.md](docs/DESKTOP.md).

## Setup

Python 3.11 or newer, and [ripgrep](https://github.com/BurntSushi/ripgrep) on `PATH` for exact symbols and quoted strings.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # optional
```

`.env.example` lists every setting. The usual ones:

| Variable | Role |
| --- | --- |
| `FF_CONFIG_DIR` | Where `config.json` and `index.sqlite` live. Default is `${XDG_CONFIG_HOME:-~/.config}/file-finder`. |
| `FF_EMBED_MODEL` | Local fastembed model. Default `BAAI/bge-small-en-v1.5`. |
| `FF_EXPLAIN_BASE_URL`, `FF_EXPLAIN_MODEL`, `FF_EXPLAIN_API_KEY` | Optional remote rerank. Unused unless you pass `--explain`. |

The config directory is created mode `0700`. The SQLite file is mode `0600`.

## Commands

```bash
ff init ~/src/billing ~/notes
ff index
ff query "auth middleware"
ff query "how we bill annual customers"
ff query ValidateRefund
ff query --explain "how we bill annual customers"
```

`ff init` writes an explicit root list. It does not index the whole disk.

`ff index` walks those roots. It follows `.gitignore`, skips VCS and dependency directories, known binary extensions, secret files (`.env`, private keys), and anything larger than 5 MB. Text-like files are split into chunks of about 400 words and embedded with the local model. The first index downloads that model into the config directory. Later runs compare size and mtime, skip unchanged files, and delete catalog rows that disappeared.

`ff index --skip-embed` builds the path catalog and the word index without vectors.

`ff query` prints the path, the matching chunk, and the lane that produced the hit (`path`, `content`, `vector`, or `ripgrep`).

| Query | What runs |
| --- | --- |
| Short name fragment | Path catalog, plus a weak lookup in the content index. File bodies are not opened. |
| Sentence about the contents | Chunk text and the local vector index. Path tokens are a weak signal. |
| Quoted string or bare identifier (`ValidateRefund`) | Path catalog and ripgrep. |

`--explain` adds one sentence. With no remote settings, that sentence is written locally and the order does not change. With `FF_EXPLAIN_BASE_URL` and `FF_EXPLAIN_MODEL`, only the top 15 snippets are sent and the shortlist is reordered.

## Tests

```bash
make test
make check
```

The tests inject a tiny stand-in embedder so they do not download model weights. `ff index` and descriptive `ff query` use the real local model.

GitHub Actions runs the same lint, syntax, test, and smoke checks on `main` and on pull requests. CodeQL scans Python weekly. Dependabot opens weekly update PRs for Python packages and GitHub Actions.
