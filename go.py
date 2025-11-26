#!/usr/bin/env python3
"""
Loop through a list of GitHub repositories and ensure each has:
- MIT LICENSE
- README.md

If missing, generate them, commit, and push.

Requirements:
- git installed and on PATH
- You have push access to the repos (e.g. via GitHub PAT / credential manager)
"""

import argparse
import datetime
import os
import subprocess
import sys
from typing import List, Tuple


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
    spec = spec.strip()
    if not spec:
        raise ValueError("Empty repository spec")

    if "://" in spec or spec.startswith("git@"):
        clone_url = spec
        local_name = os.path.splitext(os.path.basename(spec))[0]
        return clone_url, local_name

    # Assume owner/repo format
    clone_url = f"https://github.com/{spec}.git"
    local_name = spec.split("/")[-1]
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
            print(f"[!] git pull failed for {repo_dir}: {exc.stderr}", file=sys.stderr)

    return repo_dir


def has_license(repo_dir: str) -> bool:
    """Check if repo already has a license file."""
    candidates = ["LICENSE", "LICENSE.txt", "LICENSE.md"]
    return any(os.path.isfile(os.path.join(repo_dir, name)) for name in candidates)


def has_readme(repo_dir: str) -> bool:
    """Check if repo already has a README file."""
    candidates = ["README", "README.md", "README.txt"]
    return any(os.path.isfile(os.path.join(repo_dir, name)) for name in candidates)


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
    print(f"    -> Created LICENSE")
    return path


def write_readme(repo_dir: str) -> str:
    """Write minimal README.md, return the created path."""
    repo_name = os.path.basename(os.path.abspath(repo_dir))
    path = os.path.join(repo_dir, "README.md")
    content = README_TEMPLATE.format(repo_name=repo_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"    -> Created README.md")
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
        print(f"    (dry-run) Would git push")
        return

    for path in rel_files:
        run_git_command(repo_dir, ["add", path], check=True)

    try:
        run_git_command(repo_dir, ["commit", "-m", commit_message], check=True)
    except subprocess.CalledProcessError as exc:
        if "nothing to commit" in exc.stderr.lower():
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
) -> None:
    """Process a single repo spec: clone/pull, add license/readme if missing."""
    repo_spec = repo_spec.strip()
    if not repo_spec or repo_spec.startswith("#"):
        return

    print(f"\n=== {repo_spec} ===")

    clone_url, local_name = normalize_repo_spec(repo_spec)
    repo_dir = ensure_repo_cloned_or_pulled(base_dir, clone_url, local_name)

    created_files: List[str] = []

    if not has_license(repo_dir):
        created_files.append(write_license(repo_dir, author_name, year))
    else:
        print("    LICENSE already present")

    if not has_readme(repo_dir):
        created_files.append(write_readme(repo_dir))
    else:
        print("    README already present")

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
        description="Ensure MIT LICENSE and README.md exist in multiple GitHub repos.",
    )
    parser.add_argument(
        "--repos-file",
        required=True,
        help="Path to text file listing repos (one per line).",
    )
    parser.add_argument(
        "--base-dir",
        default="repos",
        help="Directory where repos will be cloned/updated (default: ./repos).",
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Author / copyright holder name for the MIT license.",
    )
    parser.add_argument(
        "--year",
        default=current_year,
        help=f"Copyright year for the MIT license (default: {current_year}).",
    )
    parser.add_argument(
        "--commit-message",
        default="Add MIT license and README",
        help="Commit message to use when adding files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not commit or push, just show what would happen.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point."""
    args = parse_args()
    repos = read_repo_list(args.repos_file)

    for repo_spec in repos:
        try:
            process_repo(
                repo_spec=repo_spec,
                base_dir=args.base_dir,
                author_name=args.name,
                year=args.year,
                commit_message=args.commit_message,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            print(f"[!] Error processing {repo_spec}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
