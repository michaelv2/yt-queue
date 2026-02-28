#!/usr/bin/env python3
"""Build scoring criteria from local projects + goals, then call yt-queue's scoring endpoint."""

import argparse
import re
import time
from pathlib import Path

import requests

PROJECT_DIRS = [Path.home() / "projects", Path.home() / "projects_safe"]
STACK_FILES = {
    "pyproject.toml": "Python",
    "setup.py": "Python",
    "requirements.txt": "Python",
    "package.json": "JS/TS",
    "tsconfig.json": "TypeScript",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "Gemfile": "Ruby",
    "build.gradle": "Java/Kotlin",
    "pom.xml": "Java",
    "mix.exs": "Elixir",
    "CMakeLists.txt": "C/C++",
}
MAX_DESC = 100
MAX_CRITERIA = 3000
GOALS_BUDGET = 1000  # reserve chars for goals section


def detect_stack(project_dir: Path) -> str | None:
    for filename, lang in STACK_FILES.items():
        if (project_dir / filename).exists():
            return lang
    return None


def extract_description(filepath: Path) -> str | None:
    """Extract first meaningful paragraph from a markdown file."""
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    # Try to find a "Project Overview" section first
    match = re.search(
        r"##\s+Project\s+Overview\s*\n+(.*?)(?:\n#|\n\n\n|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        paragraph = match.group(1).strip().split("\n\n")[0].strip()
        if paragraph and not paragraph.startswith("#"):
            return paragraph[:MAX_DESC]

    # Fallback: first non-heading, non-empty paragraph with real prose
    for block in text.split("\n\n"):
        block = block.strip()
        if not block or block.startswith("#") or block.startswith("```"):
            continue
        # Skip blocks that are just images, badges, links, or HTML
        if re.match(r"^(\s*(!?\[|<|<!--))", block):
            continue
        # Skip generic CLAUDE.md boilerplate
        if "provides guidance to Claude Code" in block:
            continue
        # Must have some actual words
        words = re.findall(r"[a-zA-Z]{2,}", block)
        if len(words) >= 3:
            return block[:MAX_DESC]
    return None


def scan_projects(dirs: list[Path]) -> list[str]:
    """Scan project directories and return one-line summaries."""
    summaries = []
    for base in dirs:
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue

            stack = detect_stack(child)
            desc = None
            for md in ("CLAUDE.md", "README.md"):
                candidate = child / md
                if candidate.exists():
                    desc = extract_description(candidate)
                    if desc:
                        break

            label = child.name
            if stack:
                label += f" ({stack})"

            if desc:
                # Collapse whitespace for a single-line summary
                desc = " ".join(desc.split())
                summaries.append(f"- {label}: {desc}")
            else:
                summaries.append(f"- {label}")
    return summaries


def build_criteria(project_summaries: list[str], goals_text: str | None) -> str:
    tail = (
        "\nScore videos higher if they directly help with these projects, "
        "teach relevant skills, or align with these goals."
    )
    goals_section = ""
    if goals_text:
        gt = goals_text.strip()[:GOALS_BUDGET]
        goals_section = f"\nMy goals:\n{gt}\n"

    # Budget for projects = total - goals - tail - some padding
    project_budget = MAX_CRITERIA - len(goals_section) - len(tail) - 50
    project_lines = []
    if project_summaries:
        project_lines.append("My current projects and interests:")
        used = len(project_lines[0])
        for line in project_summaries:
            if used + len(line) + 1 > project_budget:
                break
            project_lines.append(line)
            used += len(line) + 1

    return "\n".join(project_lines) + "\n" + goals_section + tail


def main():
    parser = argparse.ArgumentParser(description="Build and submit scoring criteria to yt-queue")
    parser.add_argument(
        "--projects",
        nargs="+",
        type=Path,
        default=PROJECT_DIRS,
        help="Directories to scan for projects (default: ~/projects ~/projects_safe)",
    )
    parser.add_argument(
        "--goals",
        type=Path,
        default=Path("goals.md"),
        help="Path to goals markdown file (default: ./goals.md)",
    )
    parser.add_argument(
        "--server",
        default="http://localhost:9000",
        help="yt-queue base URL (default: http://localhost:9000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the criteria string without calling the API",
    )
    args = parser.parse_args()

    # Scan projects
    project_summaries = scan_projects(args.projects)
    print(f"Found {len(project_summaries)} projects")

    # Read goals
    goals_text = None
    if args.goals.exists():
        goals_text = args.goals.read_text(encoding="utf-8")
    else:
        print(f"No goals file at {args.goals} — create one from the template (goals.md) for better results")

    # Build criteria
    criteria = build_criteria(project_summaries, goals_text)

    if args.dry_run:
        print("\n--- Criteria string ---")
        print(criteria)
        print(f"--- {len(criteria)} chars ---")
        return

    # Call scoring endpoint
    url = f"{args.server.rstrip('/')}/api/archive/score"
    try:
        resp = requests.post(url, json={"criteria": criteria}, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"Error calling {url}: {e}")
        raise SystemExit(1)

    data = resp.json()
    print(f"Scoring {data.get('status', '?')} — {data.get('count', '?')} transcripts")

    # Poll until done
    status_url = f"{args.server.rstrip('/')}/api/archive/score/status"
    while True:
        time.sleep(2)
        try:
            sr = requests.get(status_url, timeout=5).json()
        except requests.RequestException:
            break
        if not sr.get("running"):
            break
        print("  still scoring...")

    print("Done")


if __name__ == "__main__":
    main()
