import fnmatch
import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


from app.models.schemas import ProjectFile

# Ignored directory names (case-insensitive)
IGNORED_DIRS: Set[str] = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".cache",
    ".idea",
    ".vscode",
    ".pytest_cache",
    "htmlcov",
    "coverage",
    "out",
    "bin",
    "obj",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
}

# Sensitive / secret file patterns to strictly skip
SENSITIVE_PATTERNS: List[str] = [
    ".env*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    "*credential*",
    "*secret*",
    "*token*",
    "*.pfx",
    "*.p12",
    "*.kdbx",
    "*.keystore",
    "*.jks",
]

# Explicit binary extensions to skip
BINARY_EXTENSIONS: Set[str] = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".db", ".sqlite", ".sqlite3",
    ".pyc", ".pyo", ".pyd", ".class", ".jar", ".war",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".wav", ".avi", ".mkv", ".mov",
    ".safetensors", ".onnx", ".pt", ".pth", ".h5", ".parquet", ".arrow",
    ".pkl", ".pickle", ".npy", ".npz",
}

# Supported text file extensions
SUPPORTED_EXTENSIONS: Set[str] = {
    ".md", ".txt", ".markdown", ".rst",
    ".py", ".pyx", ".pyi",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx",
    ".rs", ".go", ".java", ".kt", ".scala",
    ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    ".sql", ".graphql", ".proto",
    ".html", ".css", ".scss", ".xml",
}

# Explicit supported manifest/config filenames (without typical extension)
SUPPORTED_FILENAMES: Set[str] = {
    "dockerfile", "makefile", "pipfile", "pipfile.lock",
    "requirements.txt", "pyproject.toml", "package.json", "package-lock.json",
    "environment.yml", "environment.yaml", "cargo.toml", "cargo.lock",
    "cmakelists.txt", "gemfile", "go.mod", "go.sum",
}


def is_sensitive_file(filename: str) -> bool:
    """Checks if filename matches any secret/credential pattern."""
    fn_lower = filename.lower()
    for pat in SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(fn_lower, pat.lower()):
            return True
    return False


def is_binary_file(file_path: Path) -> bool:
    """Checks extension and probes for null bytes in initial chunk."""
    ext = file_path.suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return True

    # Read first 1024 bytes to check for null byte
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(1024)
            if b"\x00" in chunk:
                return True
    except Exception:
        return True

    return False


def is_supported_file(file_path: Path) -> bool:
    """Determines if a file is a candidate for text/code scanning."""
    name_lower = file_path.name.lower()
    if name_lower in SUPPORTED_FILENAMES:
        return True

    ext = file_path.suffix.lower()
    if ext in SUPPORTED_EXTENSIONS:
        return True

    return False


def discover_projects(reference_dir: str = "reference") -> List[Path]:
    """
    Finds all valid project subdirectories inside reference_dir.
    """
    ref_path = Path(reference_dir)
    if not ref_path.exists() or not ref_path.is_dir():
        return []

    projects = []
    for item in ref_path.iterdir():
        if item.is_dir() and item.name not in IGNORED_DIRS and not item.name.startswith("."):
            projects.append(item)

    projects.sort(key=lambda p: p.name.lower())
    return projects


def is_path_safe_and_inside_allowed_roots(path: Path) -> bool:
    """Checks if a resolved path is safe and resides within allowed workspace roots, CWD, or temp directories."""
    try:
        resolved = path.resolve()
        allowed_roots = [
            Path("C:/Users/sujay/Downloads/hermes").resolve(),
            Path(os.path.abspath(".")).resolve(),
            Path(tempfile.gettempdir()).resolve(),
        ]
        for root in allowed_roots:
            r_str = str(root).lower().replace("\\", "/")
            path_str = str(resolved).lower().replace("\\", "/")
            if path_str == r_str or path_str.startswith(r_str + "/"):
                return True
    except Exception:
        pass
    return False


def is_subpath(child: Path, parent: Path) -> bool:
    """Determines if the child path is a subpath of (or equal to) the parent path."""
    try:
        c_str = str(child.resolve()).lower().replace("\\", "/")
        p_str = str(parent.resolve()).lower().replace("\\", "/")
        return c_str == p_str or c_str.startswith(p_str + "/")
    except Exception:
        return False


def scan_project_files(
    project_id: str,
    project_path: Path,
    max_file_size_kb: int = 512,
    max_total_project_mb: int = 25,
    exclude_paths: Optional[List[Path]] = None,
) -> Tuple[List[ProjectFile], Dict[str, Any]]:
    """
    Scans a single project folder, extracting text and metadata from supported files.
    Returns: (list of ProjectFiles, scan_stats)
    """
    stats = {
        "files_scanned": 0,
        "files_indexed": 0,
        "files_skipped_binary": 0,
        "files_skipped_size": 0,
        "files_skipped_unsupported": 0,
        "sensitive_files_skipped": 0,
        "dirs_skipped": 0,
        "total_bytes_indexed": 0,
    }

    try:
        resolved_proj_path = project_path.resolve()
    except Exception:
        resolved_proj_path = project_path

    if not is_path_safe_and_inside_allowed_roots(resolved_proj_path):
        return [], stats

    resolved_excludes = []
    if exclude_paths:
        for p in exclude_paths:
            try:
                resolved_excludes.append(p.resolve())
            except Exception:
                resolved_excludes.append(p)

    max_file_bytes = max_file_size_kb * 1024
    max_total_bytes = max_total_project_mb * 1024 * 1024

    project_files: List[ProjectFile] = []
    total_project_bytes = 0
    now = datetime.now(timezone.utc)

    for root, dirs, files in os.walk(resolved_proj_path):
        # Prune dirs that are ignored or are other projects (overlap prevention)
        pruned_dirs = []
        for d in dirs:
            try:
                sub_path = (Path(root) / d).resolve()
            except Exception:
                sub_path = Path(root) / d
            # Check ignored
            if d.lower() in IGNORED_DIRS or d.startswith("."):
                stats["dirs_skipped"] += 1
                continue
            
            # Check overlap
            is_overlap = False
            for ex_path in resolved_excludes:
                if is_subpath(sub_path, ex_path):
                    is_overlap = True
                    break
            if is_overlap:
                stats["dirs_skipped"] += 1
                continue
                
            pruned_dirs.append(d)
        dirs[:] = pruned_dirs

        for fname in sorted(files):
            stats["files_scanned"] += 1
            file_path = Path(root) / fname

            # 1. Check for sensitive files
            if is_sensitive_file(fname):
                stats["sensitive_files_skipped"] += 1
                continue

            # 2. Check for supported format
            if not is_supported_file(file_path):
                stats["files_skipped_unsupported"] += 1
                continue

            # 3. Check for binary
            if is_binary_file(file_path):
                stats["files_skipped_binary"] += 1
                continue

            # 4. Check file size
            try:
                size_bytes = file_path.stat().st_size
            except OSError:
                continue

            if size_bytes > max_file_bytes:
                stats["files_skipped_size"] += 1
                continue

            if total_project_bytes + size_bytes > max_total_bytes:
                stats["files_skipped_size"] += 1
                continue

            # 5. Read file text and compute hash
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content_text = f.read().lstrip("\ufeff")
            except Exception:
                continue

            content_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest()
            try:
                rel_path = str(file_path.relative_to(resolved_proj_path)).replace("\\", "/")
            except Exception:
                rel_path = str(file_path).replace("\\", "/")

            file_id = f"{project_id}:{rel_path}"
            ext = file_path.suffix.lower() or file_path.name.lower()

            pfile = ProjectFile(
                id=file_id,
                project_id=project_id,
                relative_path=rel_path,
                file_type=ext,
                size_bytes=size_bytes,
                content_hash=content_hash,
                extracted_text=content_text,
                created_at=now,
                updated_at=now,
                indexed_at=now,
            )

            project_files.append(pfile)
            stats["files_indexed"] += 1
            stats["total_bytes_indexed"] += size_bytes
            total_project_bytes += size_bytes

    project_files.sort(key=lambda pf: pf.relative_path)
    return project_files, stats



def compute_project_context_hash(files: List[ProjectFile]) -> str:
    """
    Computes a deterministic combined hash representing the entire project's context state.
    """
    if not files:
        return ""
    sorted_files = sorted(files, key=lambda f: f.relative_path)
    combined = "|".join(f"{f.relative_path}:{f.content_hash}" for f in sorted_files)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
