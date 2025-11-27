# github_repair

Small, single-file utility for giving a set of GitHub repositories the same baseline housekeeping. Point it at a text file of repo specs and it will clone/pull each one, ensure key project docs exist, optionally generate basic stats, and commit/push the changes for you.

## What it does
- Clones missing repos (or fast-forwards existing ones) into a local base directory.
- Ensures MIT `LICENSE`, `README.md`, and `AGENTS.md` are present.
- Generates a `.gitignore` from built-in templates based on detected languages/tooling.
- Optionally writes `REPO_STATS.md` with simple file/line counts.
- Commits and pushes newly created files unless run in `--dry-run` mode.

## Requirements
- Python 3.8+ (standard library only; no extra deps).
- `git` on PATH.
- Push access to the target repos (e.g., via GitHub credential manager or PAT).
- Optional: `GITHUB_TOKEN` environment variable if you want exporting to include private repos or avoid low anonymous rate limits.

## Quick start
1) Create a file listing repos (one per line) in any of these forms:
```
owner/repo
https://github.com/owner/repo.git
git@github.com:owner/repo.git
```

Or generate the list automatically from a GitHub profile/org URL:
```
python go.py --export-repos-from-url https://github.com/JohnDoe6345789 --export-output-file repos.txt
```
Edit `repos.txt` if you want to remove anything before running the main command.

2) Run the tool (base directory defaults to `./repos`):
```
python go.py --repos-file repos.txt --name "Your Name"
```

Useful flags:
- Preview only: `--dry-run`
- Custom base directory: `--base-dir /path/to/workdir`
- Add stats file: `--write-stats-file`
- Export repo list from a GitHub account: `--export-repos-from-url https://github.com/owner`

## CLI flags
- `--repos-file PATH`: Text file of repo specs, one per line. Required when processing repos; optional when only exporting.
- `--export-repos-from-url URL`: GitHub profile/org URL (or account name) to write all repos into a file.
- `--export-output-file PATH`: Destination for the exported repo list (defaults to `repos.txt` or `--repos-file` if provided).
- `--name STRING`: Name used in the MIT license header. Required when processing repos.
- `--year STRING` (default: current year): Copyright year for the license.
- `--base-dir DIR` (default: `repos`): Where repos are cloned/updated locally.
- `--commit-message STRING` (default provided): Message for the auto-commit.
- `--dry-run`: Show planned git actions without writing commits or pushing.
- `--write-stats-file`: Also generate `REPO_STATS.md`.

## Files it writes
- `LICENSE`: MIT license with your provided name/year.
- `README.md`: Minimal starter README to replace later.
- `AGENTS.md`: Lightweight engineering playbook for humans/agents.
- `.gitignore`: Base ignores plus language/tooling-specific snippets.
- `REPO_STATS.md`: Optional, approximate counts by file extension.

### How language detection works
File extensions map to languages (e.g., `.py` → python, `.js/.ts/.tsx` → node, `.go` → go, `.rs` → rust, `.java` → java, `.rb` → ruby, `.php` → php, `.c/.cpp/.h` → cpp, `.cs` → csharp, `.swift` → swift, `.kt/.kts` → kotlin). Each detected language adds a corresponding template to `.gitignore` alongside a general base set.

## Behavior notes
- Existing files are left untouched; new files are only written when missing.
- `git pull --ff-only` keeps local checkouts in sync before writing.
- Commits include only files the tool created; pushing happens unless `--dry-run` is set.
- Stats are approximate (binary files count as zero lines).

## Development
- Standard library only; run `python go.py --help` to see the current interface.
- No tests are provided; if you add features, consider covering new behaviors with a small test script.
