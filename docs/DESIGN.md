# File Finder design

Local search over many folders and repositories. People get in through either a filename fragment or a description of what the file contains. They often know the contents and do not know the name.

## Decision

Build an index, then a search box. Name search and descriptive search are both part of the product.

Name search is a path catalog in SQLite: configured roots, filename and directory tokens, incremental updates.

Descriptive search is an index of what those files contain. During indexing, text-like files are split into chunks. Those chunks are stored for word overlap, and embedded locally so a paraphrase still matches. A query is a lookup against that index. A model, if used at all, reranks the top 15 snippets and stays off by default.

| Constraint | Target |
| --- | --- |
| Interactive search | Under 2 seconds |
| Snippets a model may see | 15 |
| Default network egress | None |

Numbers below are planning estimates for a few hundred thousand files, not measured benchmarks. A lookup against the content index stays inside the 2 second budget. A model pass over that tree is tens of millions of tokens, and it still skips files.

## How a query runs

Four lanes can run. Rank fusion merges whichever lanes ran into one list of paths. Each hit includes the matching chunk so the user can recognize the contents.

```
Query
  ├─ Path index        name and directory tokens in SQLite
  ├─ Content text      chunks extracted at index time
  ├─ Local vectors     same chunks, embedded locally
  └─ Ripgrep           exact symbol or quoted string
        │
        ▼
   Rank fusion
        │
        ▼
    Top paths + the chunk that matched
```

| Query | Example | Lanes |
| --- | --- | --- |
| Name fragment | `auth middleware` | Path index. File bodies stay unread. |
| Description | `how we bill annual customers` | Content text and local vectors. The filename is irrelevant. Path tokens still run as a weak signal when the sentence names a project or folder. |
| Exact text | `ValidateRefund` | Path index and ripgrep. An exact filename or symbol can outrank a vague content hit. |

A description is a sentence about the file, written in the user's words. It matches in two ways:

- Shared words. "annual invoice export" hits a chunk that contains those words, via the content text index.
- Paraphrase. "how we bill annual customers" hits a chunk about subscription invoicing, via the local vector index, even when the file never uses that sentence.

Ripgrep stays for a bare identifier or a quoted string. It is a poor fit for a description, because the user is not quoting the file.

## Where each approach belongs

| Approach | Job | Work per query | File bytes leave the machine |
| --- | --- | --- | --- |
| Path catalog | Find by name | One SQLite lookup | No |
| Content text index | Description that shares words with the file | One full-text lookup | No |
| Local vectors | Description in the user's own words | One nearest-neighbor lookup | No |
| Ripgrep | Exact symbol or quoted string | One scoped disk scan | No |
| Model rerank | Optional explanation | One prompt of top snippets | Only if a remote model is opted in |
| Read every file into a model | Would replace retrieval | Full corpus, every search | Yes, when the model is hosted |
| Agent rotating free model tiers | Would replace retrieval | Full corpus plus provider rate limits | Yes |

Descriptive search is retrieval over chunks that were extracted once. It is not a model reading the tree on every query.

An agent that rotates through free model tiers does not fix retrieval. It still has to see the files, so each search pays corpus-sized token use, rate limits, and reliability problems. Internal files would also leave the machine. An agent can sit in front later and call the index as a client. Retrieval stays in the index either way.

## What gets stored

The walker records metadata for every file under the configured roots. For text-like files it also extracts chunks. It follows gitignore, skips VCS directories, dependency folders, and known binary extensions, and ignores files larger than 5 MB. Updates are incremental: size plus mtime, with a periodic reconcile so a missed watch event cannot rot the catalog.

Text-like means source, markdown, and plain text. Office documents and PDFs wait until extraction for those formats exists. Chunks are a search representation, about a few hundred words each, not a second copy of the raw file.

| Store | Contents | When it is built |
| --- | --- | --- |
| Path catalog | Root id, full path, name tokens, extension, size, mtime | Phase 0, every file that passes the ignore rules |
| Content text | Chunk text, path, offset | Phase 1, text-like files under the size cap, at index time |
| Vector index | The same chunks, plus a local embedding | Phase 1, same files, at index time |
| Exact-symbol scan | Nothing stored. Ripgrep reads the bytes it needs | Phase 2, at query time |

The SQLite file is as sensitive as the tree it describes. It stays in a user config directory with normal file permissions. Roots are an explicit list, so the default is a set of repos and document folders, not the whole disk.

## Rank order

Fusion depends on the shape of the query.

A name-like query is short, or it looks like a path or a filename. Rank it as follows.

| Priority | Signal |
| --- | --- |
| 1 | Exact filename |
| 2 | Filename token overlap |
| 3 | Directory token overlap |
| 4 | Rare exact content tokens |
| 5 | Vector similarity |

A descriptive query is a phrase or sentence. Content outranks the filename, because the user does not know the name.

| Priority | Signal |
| --- | --- |
| 1 | Vector similarity to a chunk |
| 2 | Rare words shared with a chunk |
| 3 | Directory token overlap, when the sentence names a folder or project |
| 4 | Filename token overlap |

A perfect filename match still wins when the query actually is a filename. Each result shows the path, the matching chunk, and which lane produced it.

## Build order

Python CLI plus SQLite FTS5. Embeddings use a local model. Ripgrep is a system dependency for exact symbols. A single static binary in Go is the later packaging choice if install friction shows up. The walker is the piece to rewrite if a profile says the first full walk is too slow.

| Phase | Command outcome | Engine | Model |
| --- | --- | --- | --- |
| 0 | `ff query` finds files by name across roots | SQLite FTS5 path catalog | None |
| 1 | A sentence about the contents returns the file, with the matching chunk | Content text plus local embeddings, built by `ff index` | Local embedder only |
| 2 | A quoted string or bare identifier returns the exact line | Ripgrep merged with the index | None |
| 3 | `ff query --explain` reorders the shortlist and gives one sentence | Same retrieval as phase 1 | Optional, off by default |

### Phase 0 slice

`ff init` writes a root list. `ff index` walks those roots into one SQLite file. `ff query` prints ranked paths. Tests cover filename versus directory versus unrelated names, ignore rules, and an incremental second index that skips unchanged files.

### Phase 1 slice

`ff index` extracts chunks from text-like files and embeds them locally. `ff query` on a sentence searches those chunks and prints the path plus the chunk. Tests cover a description that reuses the file's words, a paraphrase that does not, and a filename query that still prefers the path catalog.

### Later, still the same index

An agent can sit in front as a client that calls `ff query` and opens a path. That is a different product surface.

## Interfaces

The CLI is the engine and the first interface. The desktop launcher is specified in [DESKTOP.md](DESKTOP.md). A GitHub App is a different product.

### GitHub App

A GitHub App can be built as a server that indexes repositories the installation can see. It only helps inside GitHub. It misses local-only folders, uncommitted files, and anything that is not a git repository. GitHub code search already covers exact text across an organization. Descriptive search inside github.com would need a hosted index of private source, installation permissions, and accounts. That is a different trust boundary from the local index.

Cloned repositories are already roots on disk, so the desktop app covers them. Leave the GitHub App until someone needs to search repositories they have not cloned.

## Held out of the first build

- A GitHub App, or any hosted index of private repositories
- Multi-tenant hosting, accounts, and billing
- OCR and image search
- A second copy of raw file bytes, including binaries
- Sending the tree to a hosted model
- Using a free-tier rotation as the search engine
