#!/usr/bin/env python3
"""
Ensure each GitHub repository has:
- MIT LICENSE
- README.md
- AGENTS.md with engineering guidance
- .gitignore generated from detected languages / tooling

Optionally compute basic repository statistics and write them
to REPO_STATS.md.

Requirements:
- git installed and on PATH
- You have push access to the repos (e.g. via GitHub PAT / credential manager)
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


MIT_LICENSE_TEMPLATE = """MIT License

Copyright (c) {year} {name}

Permission is hereby granted, free of charge, to any person obtaining a copy \
of this software and associated documentation files (the "Software"), to deal \
in the Software without restriction, including without limitation the rights \
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell \
copies of the Software, and to permit persons to whom the Software is \
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all \
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR \
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, \
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE \
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER \
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, \
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE \
SOFTWARE.
"""


README_TEMPLATE = """# {repo_name}

This project currently has an auto-generated README.

You should replace this with proper documentation for:

- What the project does
- How to install dependencies
- How to build / run / test
"""


AGENTS_TEMPLATE = """# AGENTS

This file documents how we expect humans and automated agents to work
with this repository. Treat it as a lightweight "engineering playbook".

## 1. Engineering values

- Prefer clarity over cleverness.
- Small, composable modules are easier to test and maintain.
- Automate repeatable tasks, but keep the automation simple enough
  that a new contributor can understand and debug it.
- Document why a decision was made, not just what was done.

## 2. Code quality

- Keep functions short and focused on a single responsibility.
- Avoid hidden global state; pass data explicitly.
- Make "failure" a first-class path: handle errors and timeouts.
- Default to immutable data structures where practical.

## 3. Documentation

- Every non-trivial module should explain:
  - What problem it solves.
  - How it is expected to be used.
  - Any surprising trade-offs or limitations.
- Favour short, accurate docs over long, outdated ones.
- Update docs in the same commit as behavioural changes.

## 4. Testing

- Prefer fast, deterministic tests that can run locally.
- When fixing a bug, add a test that would have caught it.
- Keep test fixtures small and readable.
- Make it obvious how to run the whole test suite from the command line.

## 5. Tooling & automation

- Keep CI scripts and dev tooling in version control.
- Fail fast in CI when configuration is wrong or required tools are missing.
- Log enough information that production issues can be diagnosed
  without guessing or re-running the incident.

## 6. Security & privacy

- Do not commit secrets, tokens, or production credentials.
- Treat logs and dumps that might contain user data with care.
- Rotate credentials when people leave the project or roles change.

## 7. Collaboration

- Prefer many small, focussed pull requests over huge "mega" changes.
- Make it easy for reviewers: good titles, summaries, and clear diffs.
- Assume good intent and be generous with explanations and examples.

If you are reading this and something in our workflow feels confusing,
slow, or fragile, open an issue and propose an improvement.
Small, continuous improvements compound over time.
"""


GITIGNORE_TEMPLATES: Dict[str, str] = {
    "base": r"""# General
.DS_Store
Thumbs.db
*.log
*.tmp
*.swp
*.swo

# Editors
.vscode/
.idea/
*.iml

# Environments
.env
.env.*
""",
    "python": r"""# Python
__pycache__/
*.py[cod]
*$py.class

# Distribution / packaging
build/
dist/
.eggs/
*.egg-info/

# Virtual environments
.venv/
venv/
env/

# Tooling
.mypy_cache/
.pytest_cache/
.coverage
htmlcov/
.tox/
""",
    "node": r"""# Node / JS / TS
node_modules/
npm-debug.log*
yarn-debug.log*
pnpm-debug.log*

# Build outputs
dist/
build/
.cache/
.next/
.nuxt/

# Tooling
coverage/
.npm/
.eslintcache
""",
    "java": r"""# Java
*.class
*.jar
*.war
*.ear
hs_err_pid*
out/
target/
""",
    "csharp": r"""# C#
[Bb]in/
[Oo]bj/
*.user
*.suo
*.pdb
*.cache
*.mdb
*.opendb
*.VC.db
""",
    "go": r"""# Go
bin/
*.test
""",
    "rust": r"""# Rust
target/
*.rs.bk
""",
    "cpp": r"""# C / C++
*.o
*.obj
*.so
*.dll
*.dylib
*.exe
*.out
build/
cmake-build-*/
""",
    "php": r"""# PHP
vendor/
composer.lock
""",
    "ruby": r"""# Ruby
.bundle/
vendor/bundle/
log/
tmp/
coverage/
""",
    "swift": r"""# Swift
.build/
DerivedData/
Package.resolved
""",
    "kotlin": r"""# Kotlin / Gradle
.gradle/
build/
out/
""",
}


EXTENSION_LANGUAGE_MAP: Dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".js": "node",
    ".mjs": "node",
    ".cjs": "node",
    ".ts": "node",
    ".tsx": "node",
    ".jsx": "node",
    ".java": "java",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".c": "cpp",
    ".h": "cpp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".php": "php",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
}


def parse_github_account(url_or_name: str) -> str:
    """Extract the GitHub account name from a URL or raw string."""
    cleaned = url_or_name.strip()
    if not cleaned:
        raise ValueError("GitHub URL or account name is required")

    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme or parsed.netloc:
        if "github.com" not in parsed.netloc.lower():
            raise ValueError("Provide a GitHub profile or organization URL")
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            raise ValueError("GitHub URL is missing the account name")
        return parts[0]

    if "/" in cleaned:
        raise ValueError("Provide a GitHub account name or profile URL, not a repo URL")

    return cleaned


def parse_next_link(link_header: str) -> str:
    """Return the next page URL from a GitHub Link header, if present."""
    if not link_header:
        return ""

    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        if not section.startswith("<"):
            continue
        url_part = section.split(";")[0].strip()
        if url_part.startswith("<") and url_part.endswith(">"):
            return url_part[1:-1]

    return ""


def fetch_github_repositories(
    account: str,
    token: Optional[str] = None,
) -> List[str]:
    """
    Fetch all repositories for the given GitHub account (user or org).

    Returns a list of full repo names in the form owner/name.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-repair-script",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    repos: List[str] = []
    next_url: Optional[str] = (
        f"https://api.github.com/users/{account}/repos"
        "?per_page=100&type=owner&sort=full_name"
    )

    while next_url:
        req = urllib.request.Request(next_url, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                payload = json.loads(resp.read().decode(charset))
                if not isinstance(payload, list):
                    raise ValueError("Unexpected GitHub API response format")
                for repo in payload:
                    full_name = repo.get("full_name")
                    if full_name:
                        repos.append(full_name)
                next_url = parse_next_link(resp.headers.get("Link", ""))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise ValueError(f"GitHub account '{account}' not found") from exc
            raise RuntimeError(f"GitHub API returned HTTP {exc.code}") from exc

    return repos


def write_repo_list(path: str, repos: List[str]) -> None:
    """Write repository specs (owner/name) to a text file, one per line."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    unique_repos = sorted(dict.fromkeys(repos))
    with open(path, "w", encoding="utf-8") as f:
        for repo in unique_repos:
            f.write(f"{repo}\n")


def export_repos_from_url(
    url_or_name: str,
    output_path: str,
    token: Optional[str],
) -> List[str]:
    """Export all repos for a GitHub account to a file and return the list."""
    account = parse_github_account(url_or_name)
    repos = fetch_github_repositories(account, token)
    write_repo_list(output_path, repos)
    print(f"[+] Exported {len(repos)} repos for '{account}' to {output_path}")
    return repos


class RepoStats:
    """Container for simple repository statistics."""

    def __init__(self) -> None:
        self.total_files: int = 0
        self.total_lines: int = 0
        self.by_ext_files: Dict[str, int] = defaultdict(int)
        self.by_ext_lines: Dict[str, int] = defaultdict(int)

    def record(self, ext: str, line_count: int) -> None:
        self.total_files += 1
        self.total_lines += max(line_count, 0)
        self.by_ext_files[ext] += 1
        self.by_ext_lines[ext] += max(line_count, 0)


def run_git_command(
    repo_dir: str,
    args: List[str],
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a git command in the given repository directory."""
    cmd = ["git", "-C", repo_dir] + args
    return subprocess.run(
        cmd,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def normalize_repo_spec(spec: str) -> Tuple[str, str]:
    """
    Convert a repo spec into:
    - clone_url: full HTTPS clone URL
    - local_name: folder name to use

    Accepts:
    - owner/repo
    - https://github.com/owner/repo.git
    - git@github.com:owner/repo.git
    """
    cleaned = spec.strip()
    if not cleaned:
        raise ValueError("Empty repository spec")

    if "://" in cleaned or cleaned.startswith("git@"):
        clone_url = cleaned
        local_name = os.path.splitext(os.path.basename(cleaned))[0]
        return clone_url, local_name

    clone_url = f"https://github.com/{cleaned}.git"
    local_name = cleaned.split("/")[-1]
    return clone_url, local_name


def ensure_repo_cloned_or_pulled(
    base_dir: str,
    clone_url: str,
    local_name: str,
) -> str:
    """Clone repo if missing, otherwise pull latest changes. Return path."""
    repo_dir = os.path.join(base_dir, local_name)
    os.makedirs(base_dir, exist_ok=True)

    if not os.path.isdir(repo_dir):
        print(f"[+] Cloning {clone_url} -> {repo_dir}")
        subprocess.run(
            ["git", "clone", clone_url, repo_dir],
            check=True,
        )
    else:
        print(f"[+] Updating existing repo {repo_dir}")
        try:
            run_git_command(repo_dir, ["pull", "--ff-only"], check=True)
        except subprocess.CalledProcessError as exc:
            print(
                f"[!] git pull failed for {repo_dir}: {exc.stderr}",
                file=sys.stderr,
            )

    return repo_dir


def has_license(repo_dir: str) -> bool:
    """Check if repo already has a license file."""
    candidates = ["LICENSE", "LICENSE.txt", "LICENSE.md"]
    return any(os.path.isfile(os.path.join(repo_dir, name)) for name in candidates)


def has_readme(repo_dir: str) -> bool:
    """Check if repo already has a README file."""
    candidates = ["README", "README.md", "README.txt"]
    return any(os.path.isfile(os.path.join(repo_dir, name)) for name in candidates)


def has_agents(repo_dir: str) -> bool:
    """Check if repo already has AGENTS.md."""
    return os.path.isfile(os.path.join(repo_dir, "AGENTS.md"))


def has_gitignore(repo_dir: str) -> bool:
    """Check if repo already has a .gitignore file."""
    return os.path.isfile(os.path.join(repo_dir, ".gitignore"))


def write_license(
    repo_dir: str,
    author_name: str,
    year: str,
) -> str:
    """Write MIT LICENSE file, return the created path."""
    path = os.path.join(repo_dir, "LICENSE")
    content = MIT_LICENSE_TEMPLATE.format(name=author_name, year=year)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("    -> Created LICENSE")
    return path


def write_readme(repo_dir: str) -> str:
    """Write minimal README.md, return the created path."""
    repo_name = os.path.basename(os.path.abspath(repo_dir))
    path = os.path.join(repo_dir, "README.md")
    content = README_TEMPLATE.format(repo_name=repo_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("    -> Created README.md")
    return path


def write_agents(repo_dir: str) -> str:
    """Write AGENTS.md with engineering guidance, return the created path."""
    path = os.path.join(repo_dir, "AGENTS.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(AGENTS_TEMPLATE)
    print("    -> Created AGENTS.md")
    return path


def detect_languages(stats: RepoStats) -> List[str]:
    """Infer languages present based on file extensions."""
    languages: List[str] = []
    seen: set = set()

    for ext, file_count in stats.by_ext_files.items():
        if not ext:
            continue
        language = EXTENSION_LANGUAGE_MAP.get(ext)
        if not language:
            continue
        if file_count <= 0:
            continue
        if language in seen:
            continue
        seen.add(language)
        languages.append(language)

    return languages


def generate_gitignore_content(languages: List[str]) -> str:
    """Generate .gitignore content from base and language-specific templates."""
    parts: List[str] = []

    base = GITIGNORE_TEMPLATES.get("base")
    if base:
        parts.append(base.rstrip())

    for language in languages:
        snippet = GITIGNORE_TEMPLATES.get(language)
        if not snippet:
            continue
        parts.append(snippet.rstrip())

    content = "\n\n".join(parts)
    return content.strip() + "\n" if content.strip() else ""


def write_gitignore(repo_dir: str, stats: RepoStats) -> str:
    """
    Generate and write .gitignore based on detected languages.
    Return path if created, or empty string if nothing written.
    """
    languages = detect_languages(stats)
    if not languages:
        print("    -> No recognised languages found, generating base .gitignore")
    else:
        langs_str = ", ".join(languages)
        print(f"    -> Detected languages for .gitignore: {langs_str}")

    content = generate_gitignore_content(languages)
    if not content.strip():
        print("    -> Skipping .gitignore creation (no content)")
        return ""

    path = os.path.join(repo_dir, ".gitignore")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("    -> Created .gitignore")
    return path


def collect_repo_stats(repo_dir: str) -> RepoStats:
    """
    Walk the repository and collect simple statistics.

    - Skips the .git directory.
    - Attempts to count lines for text-like files (binary files may be
      treated as zero-line files).
    """
    stats = RepoStats()
    for root, dirs, files in os.walk(repo_dir):
        if ".git" in dirs:
            dirs.remove(".git")

        for name in files:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, repo_dir)
            if rel.startswith(".git" + os.sep):
                continue

            ext = os.path.splitext(name)[1].lower()
            line_count = 0

            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for _ in f:
                        line_count += 1
            except OSError:
                line_count = 0

            stats.record(ext, line_count)

    return stats


def format_stats_markdown(stats: RepoStats, repo_name: str) -> str:
    """Format repository statistics as a small Markdown document."""
    lines: List[str] = []
    lines.append(f"# Repository statistics for {repo_name}")
    lines.append("")
    lines.append(f"- Total files: {stats.total_files}")
    lines.append(f"- Total lines (approx): {stats.total_lines}")
    lines.append("")
    lines.append("## By extension")
    lines.append("")
    lines.append("| Extension | Files | Approx. lines |")
    lines.append("|-----------|-------|---------------|")

    sorted_exts = sorted(
        stats.by_ext_files.keys(),
        key=lambda e: stats.by_ext_files[e],
        reverse=True,
    )
    for ext in sorted_exts:
        files = stats.by_ext_files[ext]
        lines_count = stats.by_ext_lines[ext]
        display_ext = ext if ext else "(no extension)"
        lines.append(f"| {display_ext} | {files} | {lines_count} |")

    lines.append("")
    lines.append(
        "_These statistics are approximate and were generated automatically._",
    )

    return "\n".join(lines) + "\n"


def write_stats_file(repo_dir: str, stats: RepoStats) -> str:
    """
    Write REPO_STATS.md summarising repository statistics.
    Return path of created file.
    """
    repo_name = os.path.basename(os.path.abspath(repo_dir))
    content = format_stats_markdown(stats, repo_name)
    path = os.path.join(repo_dir, "REPO_STATS.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("    -> Created REPO_STATS.md")
    return path


def get_git_status_porcelain(repo_dir: str) -> str:
    """Return git status in porcelain format."""
    result = run_git_command(repo_dir, ["status", "--porcelain"], check=True)
    return result.stdout.strip()


def commit_and_push_changes(
    repo_dir: str,
    files: List[str],
    commit_message: str,
    dry_run: bool,
) -> None:
    """Stage given files, commit, and push."""
    if not files:
        return

    rel_files = [os.path.relpath(path, repo_dir) for path in files]

    if dry_run:
        print(f"    (dry-run) Would git add: {', '.join(rel_files)}")
        print(f"    (dry-run) Would git commit -m '{commit_message}'")
        print("    (dry-run) Would git push")
        return

    for path in rel_files:
        run_git_command(repo_dir, ["add", path], check=True)

    try:
        run_git_command(repo_dir, ["commit", "-m", commit_message], check=True)
    except subprocess.CalledProcessError as exc:
        if "nothing to commit" in (exc.stderr or "").lower():
            print("    Nothing to commit.")
            return
        raise

    try:
        run_git_command(repo_dir, ["push"], check=True)
        print("    -> Changes pushed.")
    except subprocess.CalledProcessError as exc:
        print(f"    [!] git push failed: {exc.stderr}", file=sys.stderr)


def process_repo(
    repo_spec: str,
    base_dir: str,
    author_name: str,
    year: str,
    commit_message: str,
    dry_run: bool,
    write_stats_file_flag: bool,
) -> None:
    """
    Process a single repo spec: clone/pull, add license/readme/agents/gitignore
    if missing, and optionally write REPO_STATS.md.
    """
    repo_spec = repo_spec.strip()
    if not repo_spec or repo_spec.startswith("#"):
        return

    print(f"\n=== {repo_spec} ===")

    clone_url, local_name = normalize_repo_spec(repo_spec)
    repo_dir = ensure_repo_cloned_or_pulled(base_dir, clone_url, local_name)

    print("    Collecting repository statistics...")
    stats = collect_repo_stats(repo_dir)
    print(
        f"    -> Files: {stats.total_files}, approx lines: {stats.total_lines}",
    )

    created_files: List[str] = []

    if not has_license(repo_dir):
        created_files.append(write_license(repo_dir, author_name, year))
    else:
        print("    LICENSE already present")

    if not has_readme(repo_dir):
        created_files.append(write_readme(repo_dir))
    else:
        print("    README already present")

    if not has_agents(repo_dir):
        created_files.append(write_agents(repo_dir))
    else:
        print("    AGENTS.md already present")

    if not has_gitignore(repo_dir):
        gitignore_path = write_gitignore(repo_dir, stats)
        if gitignore_path:
            created_files.append(gitignore_path)
    else:
        print("    .gitignore already present")

    if write_stats_file_flag:
        created_files.append(write_stats_file(repo_dir, stats))

    if not created_files:
        print("    No changes needed.")
        return

    status = get_git_status_porcelain(repo_dir)
    if not status:
        print("    No changes detected by git.")
        return

    commit_and_push_changes(
        repo_dir=repo_dir,
        files=created_files,
        commit_message=commit_message,
        dry_run=dry_run,
    )


def read_repo_list(path: str) -> List[str]:
    """Read repository specs from a text file."""
    with open(path, "r", encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f]


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    current_year = str(datetime.datetime.now().year)
    parser = argparse.ArgumentParser(
        description=(
            "Ensure MIT LICENSE, README.md, AGENTS.md and .gitignore exist in "
            "multiple GitHub repos, and optionally generate REPO_STATS.md."
        ),
    )
    parser.add_argument(
        "--repos-file",
        help="Path to text file listing repos (one per line).",
    )
    parser.add_argument(
        "--export-repos-from-url",
        help=(
            "GitHub profile/org URL (or account name) to export all repos "
            "to a text file."
        ),
    )
    parser.add_argument(
        "--export-output-file",
        help=(
            "Destination path for exported repo list "
            "(default: repos.txt or --repos-file if set)."
        ),
    )
    parser.add_argument(
        "--base-dir",
        default="repos",
        help="Directory where repos will be cloned/updated (default: ./repos).",
    )
    parser.add_argument(
        "--name",
        help="Author / copyright holder name for the MIT license.",
    )
    parser.add_argument(
        "--year",
        default=current_year,
        help=f"Copyright year for the MIT license (default: {current_year}).",
    )
    parser.add_argument(
        "--commit-message",
        default=(
            "Add MIT license, README, AGENTS, .gitignore, and stats file"
        ),
        help="Commit message to use when adding files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not commit or push, just show what would happen.",
    )
    parser.add_argument(
        "--write-stats-file",
        action="store_true",
        help="Write REPO_STATS.md with basic repository statistics.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point."""
    args = parse_args()

    if args.export_output_file and not args.export_repos_from_url:
        print(
            "[!] --export-output-file is ignored without --export-repos-from-url",
            file=sys.stderr,
        )

    if args.export_repos_from_url:
        output_path = args.export_output_file or args.repos_file or "repos.txt"
        token = os.getenv("GITHUB_TOKEN")
        try:
            export_repos_from_url(
                url_or_name=args.export_repos_from_url,
                output_path=output_path,
                token=token,
            )
        except Exception as exc:
            print(f"[!] Failed to export repo list: {exc}", file=sys.stderr)
            sys.exit(1)

        if not args.repos_file:
            args.repos_file = output_path

        if not args.name:
            print(
                "Repo list exported. Provide --name to process repositories, "
                "or edit the list and rerun.",
            )
            return

    if not args.repos_file:
        print(
            "You must supply --repos-file or --export-repos-from-url to create one.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.name:
        print("--name is required when processing repositories.", file=sys.stderr)
        sys.exit(1)

    try:
        repos = read_repo_list(args.repos_file)
    except FileNotFoundError:
        print(f"[!] Repo list not found: {args.repos_file}", file=sys.stderr)
        sys.exit(1)

    for repo_spec in repos:
        try:
            process_repo(
                repo_spec=repo_spec,
                base_dir=args.base_dir,
                author_name=args.name,
                year=args.year,
                commit_message=args.commit_message,
                dry_run=args.dry_run,
                write_stats_file_flag=args.write_stats_file,
            )
        except Exception as exc:
            print(f"[!] Error processing {repo_spec}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
