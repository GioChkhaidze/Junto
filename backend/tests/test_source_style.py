from pathlib import Path

ROOT = Path(__file__).parents[2]
SKIPPED_DIRECTORIES = {
  ".agents",
  ".codex",
  ".git",
  ".impeccable",
  ".mypy_cache",
  ".playwright-cli",
  ".pytest_cache",
  ".ruff_cache",
  ".tmp",
  ".venv",
  ".vite",
  "__pycache__",
  "build",
  "coverage",
  "dist",
  "htmlcov",
  "node_modules",
  "output",
  "playwright-report",
  "test-results",
}
SKIPPED_FILES = {"package-lock.json", "requirements.runtime.lock"}
# Locks are generator-owned; frozen JSON fixtures contain indivisible prose strings whose wrapping would change data.
TEXT_SUFFIXES = {".css", ".html", ".ini", ".json", ".md", ".py", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml"}
TEXT_FILENAMES = {
  ".dockerignore",
  ".editorconfig",
  ".env.example",
  ".gitattributes",
  ".gitignore",
  ".prettierignore",
  "Dockerfile",
}


def _authored_files() -> list[Path]:
  files: list[Path] = []
  for path in ROOT.rglob("*"):
    relative = path.relative_to(ROOT)
    if not path.is_file() or any(part in SKIPPED_DIRECTORIES or part.endswith(".egg-info") for part in relative.parts):
      continue
    if (
      path.name in SKIPPED_FILES
      or relative.parts[:2] in {("docs", "evidence"), ("backend", "tests")}
      and path.suffix == ".json"
    ):
      continue
    if path.suffix in TEXT_SUFFIXES or path.name in TEXT_FILENAMES:
      files.append(path)
  return files


def test_authored_lines_follow_repository_style() -> None:
  violations: list[str] = []
  for path in _authored_files():
    relative = path.relative_to(ROOT)
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
      if len(line) > 120:
        violations.append(f"{relative}:{number}: {len(line)} characters")
      if "\t" in line:
        violations.append(f"{relative}:{number}: tab indentation")
      if path.suffix == ".py" and line.startswith(" ") and (len(line) - len(line.lstrip(" "))) % 2:
        violations.append(f"{relative}:{number}: odd Python indentation")
  assert not violations, "\n" + "\n".join(violations)
