# Dusk

A macOS disk usage tracker that shows where your space is going, finds your biggest files, and tracks how usage changes over time.

## What it does

- Scans any directory and shows the biggest subdirectories and files
- Displays a color-coded disk usage overview (green/yellow/red)
- Saves every scan so you can see what grew or shrank since last time
- Lets you ask Claude or Codex questions about your disk usage ("what can I safely delete?")

## Install

Requires Python 3.11+ and macOS.

```bash
git clone <repo-url> && cd dust-disk-usage-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

You now have the `dusk` command available.

## Quick start

Run your first scan (defaults to your home directory):

```bash
dusk scan
```

This will show:

1. **Disk Overview** — total/used/free space with a usage bar
2. **Top Directories** — largest folders sorted by size
3. **Largest Files** — biggest individual files with folder and filename separated
4. **Trends** — what changed since your last scan (appears from the second scan onward)

## Commands

### `dusk scan [PATH]`

Scan a directory and display results. The scan is automatically saved for future comparison.

```bash
dusk scan                # Scan home directory
dusk scan ~/Projects     # Scan a specific folder
dusk scan . -d2          # Go 2 levels deep
dusk scan ~ -t10 -f5     # Show top 10 dirs and 5 largest files
dusk scan --no-history   # Scan without saving to history
```

Options:
| Flag | Description |
|------|-------------|
| `-d`, `--depth N` | How many directory levels deep to scan (default: 1) |
| `-t`, `--top N` | Number of top directories to show (default: 20) |
| `-f`, `--files N` | Number of largest files to show (default: 10) |
| `--min-size N` | Minimum file size in MB to include (default: 100) |
| `--no-history` | Don't save this scan |
| `--no-trend` | Don't show the trend comparison |

### `dusk history`

List all past scans with timestamps, sizes, and disk usage percentages.

```bash
dusk history             # Show all scans
dusk history ~            # Show scans for home directory only
dusk history -n 5        # Show last 5 scans
```

### `dusk show ID`

Re-display a past scan report by its ID (from `dusk history`).

```bash
dusk show 3              # Show the full report for scan #3
```

### `dusk compare [PATH]`

Show a detailed comparison of the two most recent scans for a path. Highlights which directories grew (orange) and which shrank (cyan).

```bash
dusk compare             # Compare last two scans of ~
dusk compare ~/Projects  # Compare last two scans of ~/Projects
```

### `dusk ask "QUESTION"`

Send your latest scan report to Claude (or Codex) and ask a question about it. Claude has web search enabled, so it can look up what unfamiliar apps or files are.

```bash
dusk ask "what can I safely delete?"
dusk ask "why is ~/Library so big?"
dusk ask "what is this .raw file taking 8TB?"
dusk ask --scan-id 3 "summarize this scan"
dusk ask --codex "suggest cleanup commands"
```

Options:
| Flag | Description |
|------|-------------|
| `--scan-id N` | Ask about a specific scan instead of the latest |
| `--codex` | Use Codex instead of Claude |

Requires [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or [Codex](https://github.com/openai/codex) CLI to be installed.

### `dusk prune`

Delete old scan data to free up space. Keeps the 10 most recent scans per path by default.

```bash
dusk prune               # Keep last 10 scans per path
dusk prune -k 3          # Keep only last 3
```

## How it works

Dusk uses native macOS tools for speed:

- **`du`** — measures directory sizes (stays on the same filesystem)
- **`mdfind`** (Spotlight) — finds large files instantly via the search index
- **`diskutil`** — reads volume info (APFS container, filesystem type)

All three run in parallel, so a typical scan of your home directory takes a few seconds.

Scan history is stored in a SQLite database at `~/.dusk/dusk.db`.

## Data storage

All data stays local on your machine:

- `~/.dusk/dusk.db` — scan history database
- No network requests (except when using `dusk ask`)
- No telemetry or analytics
