from pathlib import Path
import pathspec

def markdown_tree(
    root_dir,
    ignore_file=None,
    show_hidden=False,
    max_depth=None,
    follow_symlinks=False
) -> str:
    """
    Create a Markdown-friendly text tree of the directory.

    Args:
        root_dir (str | Path): Directory to scan.
        ignore_file (str | Path | None): Path to a .gitignore-style file.
        show_hidden (bool): Include dotfiles/directories if True.
        max_depth (int | None): Limit recursion depth (0 shows just the root).
        follow_symlinks (bool): Recurse into symlinked directories if True.
    """
    root = Path(root_dir).resolve()

    # Load ignore rules if specified
    spec = None
    if ignore_file:
        ignore_path = Path(ignore_file)
        if ignore_path.exists():
            spec = pathspec.PathSpec.from_lines("gitwildmatch", ignore_path.read_text().splitlines())

    def is_ignored(p: Path) -> bool:
        """Honor .gitignore-style directory rules (e.g., 'build/' hides the folder)."""
        if not spec:
            return False
        rel = p.relative_to(root).as_posix()
        # Check file-style match
        if spec.match_file(rel):
            return True
        # For directories, also check with a trailing slash (git semantics)
        try:
            is_dir = p.is_dir()
        except Exception:
            is_dir = False
        if is_dir and spec.match_file(rel + "/"):
            return True
        return False

    def is_hidden(p: Path) -> bool:
        return any(part.startswith(".") for part in p.parts)

    def safe_iterdir(p: Path):
        try:
            return sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            return None

    lines = [root.name + ("/" if root.is_dir() else "")]
    
    def walk(dir_path: Path, prefix: str, depth: int):
        if max_depth is not None and depth >= max_depth:
            return

        entries = safe_iterdir(dir_path)
        if entries is None:
            lines.append(prefix + "[permission denied]")
            return

        if not show_hidden:
            entries = [e for e in entries if not is_hidden(e.relative_to(root))]
        if spec:
            entries = [e for e in entries if not is_ignored(e)]

        for i, entry in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(prefix + connector + entry.name + ("/" if entry.is_dir() else ""))

            if entry.is_dir():
                if entry.is_symlink() and not follow_symlinks:
                    continue
                extension_prefix = "    " if i == len(entries) - 1 else "│   "
                walk(entry, prefix + extension_prefix, depth + 1)

    if root.is_dir():
        walk(root, "", 0)

    return "```\n" + "\n".join(lines) + "\n```"

# Example usage:
# print(markdown_tree("my_project", ignore_file="my_project/.gitignore"))
