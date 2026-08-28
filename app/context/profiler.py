import ast
import hashlib
import json
import re
import sys
try:
    import tomllib
except ImportError:
    import tomli as tomllib
import yaml
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.models.schemas import Project, ProjectFile, ProjectTechnologyProfile

# Python stdlib module names ship with the interpreter, not with the project.
# They must never be reported as project dependencies (a raw AST import scan
# would otherwise list modules like "re", "os", "json" as dependencies).
_STDLIB_MODULE_NAMES: Set[str] = {
    name.lower() for name in getattr(sys, "stdlib_module_names", frozenset())
}


def is_stdlib_module(name: str) -> bool:
    """True if the given top-level module name is part of the Python stdlib."""
    return name.lower() in _STDLIB_MODULE_NAMES

# Extension to Language mapping
EXTENSION_LANGUAGE_MAP: Dict[str, str] = {
    ".py": "Python",
    ".pyx": "Python",
    ".pyi": "Python",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".c": "C",
    ".h": "C/C++",
    ".hpp": "C++",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".sh": "Shell",
    ".bash": "Shell",
    ".sql": "SQL",
    ".cu": "CUDA",
    ".cuh": "CUDA",
}

# Known library / framework classification dictionaries
KNOWN_ML_STACK = {
    "torch": "PyTorch",
    "pytorch": "PyTorch",
    "torchvision": "TorchVision",
    "torchaudio": "TorchAudio",
    "tensorflow": "TensorFlow",
    "jax": "JAX",
    "transformers": "Hugging Face Transformers",
    "sentence-transformers": "sentence-transformers",
    "sentence_transformers": "sentence-transformers",
    "vllm": "vLLM",
    "sglang": "SGLang",
    "triton": "Triton",
    "cuda": "CUDA",
    "bitsandbytes": "bitsandbytes",
    "deepspeed": "DeepSpeed",
    "accelerate": "Accelerate",
    "onnxruntime": "ONNX Runtime",
    "onnx": "ONNX",
    "llama-cpp-python": "llama.cpp",
    "llama_cpp": "llama.cpp",
    "diffusers": "Diffusers",
    "timm": "timm",
    "flash-attn": "FlashAttention",
    "flash_attn": "FlashAttention",
    "lighteval": "LightEval",
    "peft": "PEFT",
    "unsloth": "Unsloth",
    "vllm-flash-attn": "FlashAttention",
}

KNOWN_STORAGE_DB = {
    "chromadb": "Chroma",
    "qdrant-client": "Qdrant",
    "qdrant_client": "Qdrant",
    "faiss-cpu": "FAISS",
    "faiss-gpu": "FAISS",
    "faiss": "FAISS",
    "weaviate-client": "Weaviate",
    "pymilvus": "Milvus",
    "pinecone-client": "Pinecone",
    "sqlite3": "SQLite",
    "sqlite": "SQLite",
    "psycopg2": "PostgreSQL",
    "psycopg2-binary": "PostgreSQL",
    "asyncpg": "PostgreSQL",
    "redis": "Redis",
    "pymongo": "MongoDB",
    "duckdb": "DuckDB",
    "rocksdb": "RocksDB",
    "sqlalchemy": "SQLAlchemy",
}

KNOWN_FRAMEWORKS = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "uvicorn": "Uvicorn",
    "starlette": "Starlette",
    "litestar": "Litestar",
    "aiohttp": "AIOHTTP",
    "tornado": "Tornado",
    "react": "React",
    "next": "Next.js",
    "vue": "Vue",
    "svelte": "Svelte",
    "express": "Express",
    "hono": "Hono",
}

KNOWN_INFRA = {
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "helm": "Helm",
    "terraform": "Terraform",
    "ray": "Ray",
    "celery": "Celery",
    "airflow": "Apache Airflow",
}

KNOWN_TESTING = {
    "pytest": "pytest",
    "unittest": "unittest",
    "jest": "Jest",
    "mocha": "Mocha",
    "vitest": "Vitest",
}

KNOWN_OBSERVABILITY = {
    "prometheus": "Prometheus",
    "grafana": "Grafana",
    "opentelemetry": "OpenTelemetry",
    "wandb": "Weights & Biases",
    "mlflow": "MLflow",
    "tensorboard": "TensorBoard",
    "sentry-sdk": "Sentry",
}

# Topic pattern detection
TOPIC_PATTERNS = [
    (r"\b(rag|retrieval[- ]augmented\s+generation)\b", "RAG"),
    (r"\b(vector\s+(?:database|search|index|store))\b", "vector search"),
    (r"\b(embeddings?|dense\s+retrieval)\b", "embeddings"),
    (r"\b(compiler\s+(?:optimization|passes?|backend))\b", "compiler optimization"),
    (r"\b(llm[- ]inference|inference\s+engine)\b", "LLM inference"),
    (r"\b(quantization|nvfp4|fp8|int4|int8|gguf|awq)\b", "quantization"),
    (r"\b(kv[- ]cache|attention\s+optimization)\b", "KV-cache optimization"),
    (r"\b(cuda|gpu\s+acceleration|kernel\s+optimization)\b", "CUDA & GPU kernels"),
    (r"\b(agents?|agentic|multi[- ]agent)\b", "agentic workflows"),
    (r"\b(fine[- ]tuning|lora|qlora|sft|rlhf)\b", "fine-tuning"),
    (r"\b(distributed\s+training|model\s+parallelism)\b", "distributed systems"),
]


def extract_python_ast_imports(code_text: str) -> Set[str]:
    """Safely parses Python AST to identify imported top-level modules."""
    imports = set()
    try:
        tree = ast.parse(code_text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_name = alias.name.split(".")[0].lower()
                    if top_name:
                        imports.add(top_name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top_name = node.module.split(".")[0].lower()
                    if top_name:
                        imports.add(top_name)
    except Exception:
        # Fallback regex for non-standard or partial Python code
        matches = re.findall(r"^(?:from|import)\s+([a-zA-Z0-9_-]+)", code_text, re.MULTILINE)
        for m in matches:
            imports.add(m.lower())
    return imports


def parse_requirements_txt(content: str) -> Dict[str, str]:
    """Parses requirements.txt into dict of package -> version constraint."""
    deps = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Split package name from version operators
        match = re.match(r"^([a-zA-Z0-9_.-]+)\s*([><=~!].*)?$", line)
        if match:
            pkg = match.group(1).lower().replace("_", "-")
            ver = match.group(2).strip() if match.group(2) else ""
            deps[pkg] = ver
    return deps


def parse_pyproject_toml(content: str) -> Dict[str, str]:
    """Parses dependencies from pyproject.toml."""
    deps = {}
    try:
        data = tomllib.loads(content)
        # 1. PEP 621 [project.dependencies]
        project_deps = data.get("project", {}).get("dependencies", [])
        if isinstance(project_deps, list):
            for d in project_deps:
                match = re.match(r"^([a-zA-Z0-9_.-]+)\s*([><=~!].*)?$", d)
                if match:
                    deps[match.group(1).lower().replace("_", "-")] = match.group(2).strip() if match.group(2) else ""

        # 2. Poetry [tool.poetry.dependencies]
        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        if isinstance(poetry_deps, dict):
            for k, v in poetry_deps.items():
                if k.lower() != "python":
                    ver = str(v) if not isinstance(v, dict) else str(v.get("version", ""))
                    deps[k.lower().replace("_", "-")] = ver
    except Exception:
        pass
    return deps


def parse_package_json(content: str) -> Dict[str, str]:
    """Parses dependencies from package.json."""
    deps = {}
    try:
        data = json.loads(content)
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            sec_dict = data.get(section, {})
            if isinstance(sec_dict, dict):
                for k, v in sec_dict.items():
                    deps[k.lower()] = str(v)
    except Exception:
        pass
    return deps


def parse_environment_yml(content: str) -> Dict[str, str]:
    """Parses dependencies from Conda environment.yml."""
    deps = {}
    try:
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            dep_list = data.get("dependencies", [])
            for item in dep_list:
                if isinstance(item, str):
                    match = re.match(r"^([a-zA-Z0-9_.-]+)\s*([><=~!].*)?$", item)
                    if match:
                        deps[match.group(1).lower().replace("_", "-")] = match.group(2).strip() if match.group(2) else ""
                elif isinstance(item, dict) and "pip" in item:
                    for pip_dep in item["pip"]:
                        match = re.match(r"^([a-zA-Z0-9_.-]+)\s*([><=~!].*)?$", str(pip_dep))
                        if match:
                            deps[match.group(1).lower().replace("_", "-")] = match.group(2).strip() if match.group(2) else ""
    except Exception:
        pass
    return deps


def parse_cargo_toml(content: str) -> Dict[str, str]:
    """Parses dependencies from Cargo.toml."""
    deps = {}
    try:
        data = tomllib.loads(content)
        dep_dict = data.get("dependencies", {})
        if isinstance(dep_dict, dict):
            for k, v in dep_dict.items():
                ver = str(v) if not isinstance(v, dict) else str(v.get("version", ""))
                deps[k.lower()] = ver
    except Exception:
        pass
    return deps


def build_project_technology_profile(
    project_id: str,
    project_name: str,
    files: List[ProjectFile],
) -> Tuple[ProjectTechnologyProfile, Dict[str, Any]]:
    """
    Statically analyzes project files to build a deterministic TechnologyProfile.
    """
    dependencies: Dict[str, str] = {}
    lang_counter: Counter = Counter()
    detected_frameworks: Set[str] = set()
    detected_libraries: Set[str] = set()
    detected_databases: Set[str] = set()
    detected_storage: Set[str] = set()
    detected_infra: Set[str] = set()
    detected_ml_stack: Set[str] = set()
    detected_deployment: Set[str] = set()
    detected_observability: Set[str] = set()
    detected_testing: Set[str] = set()
    detected_topics: Set[str] = set()

    corpus_for_topics: List[str] = []
    description: Optional[str] = None

    for pf in files:
        # Language counts
        lang = EXTENSION_LANGUAGE_MAP.get(pf.file_type)
        if lang:
            lang_counter[lang] += 1

        fname_lower = Path(pf.relative_path).name.lower()
        content = pf.extracted_text or ""

        # Collect text for topic parsing from documentation & config
        if pf.file_type in (".md", ".txt", ".rst") or fname_lower in ("dockerfile", "makefile"):
            corpus_for_topics.append(content)
            if not description and "readme" in fname_lower and content:
                # Extract first non-heading line as description
                for line in content.splitlines():
                    cleaned = line.strip().lstrip("\ufeff").lstrip("#").strip()
                    if cleaned and len(cleaned) > 5 and not cleaned.startswith("```"):
                        description = cleaned[:160]
                        break

        # Manifest parsing
        if fname_lower == "requirements.txt":
            dependencies.update(parse_requirements_txt(content))
        elif fname_lower == "pyproject.toml":
            dependencies.update(parse_pyproject_toml(content))
        elif fname_lower == "package.json":
            dependencies.update(parse_package_json(content))
        elif fname_lower in ("environment.yml", "environment.yaml"):
            dependencies.update(parse_environment_yml(content))
        elif fname_lower == "cargo.toml":
            dependencies.update(parse_cargo_toml(content))
        elif fname_lower == "cmakelists.txt":
            for pkg in re.findall(r"find_package\s*\(\s*([a-zA-Z0-9_-]+)", content, re.IGNORECASE):
                dependencies[pkg.lower()] = ""
            lang_match = re.search(r"LANGUAGES\s+([a-zA-Z0-9_\s]+)\)", content, re.IGNORECASE)
            if lang_match:
                for l in lang_match.group(1).split():
                    if l.upper() in ("CXX", "C++"):
                        lang_counter["C++"] += 1
                    elif l.upper() == "CUDA":
                        lang_counter["CUDA"] += 1
                    elif l.upper() == "C":
                        lang_counter["C"] += 1

        # Python import AST analysis
        if pf.file_type == ".py" and content:
            imports = extract_python_ast_imports(content)
            for imp in imports:
                if is_stdlib_module(imp):
                    continue
                norm_imp = imp.replace("_", "-")
                if norm_imp not in dependencies:
                    dependencies[norm_imp] = ""

        # Dockerfile & Makefile infra detection
        if fname_lower == "dockerfile" or "docker-compose" in fname_lower:
            detected_infra.add("Docker")
            detected_deployment.add("Docker Container")

    # Classify detected dependencies into technology domains
    for dep, ver in dependencies.items():
        norm_dep = dep.lower().replace("_", "-")

        if norm_dep in KNOWN_ML_STACK:
            detected_ml_stack.add(KNOWN_ML_STACK[norm_dep])
            detected_frameworks.add(KNOWN_ML_STACK[norm_dep])
        elif norm_dep in KNOWN_STORAGE_DB:
            detected_databases.add(KNOWN_STORAGE_DB[norm_dep])
            detected_storage.add(KNOWN_STORAGE_DB[norm_dep])
        elif norm_dep in KNOWN_FRAMEWORKS:
            detected_frameworks.add(KNOWN_FRAMEWORKS[norm_dep])
        elif norm_dep in KNOWN_INFRA:
            detected_infra.add(KNOWN_INFRA[norm_dep])
        elif norm_dep in KNOWN_TESTING:
            detected_testing.add(KNOWN_TESTING[norm_dep])
        elif norm_dep in KNOWN_OBSERVABILITY:
            detected_observability.add(KNOWN_OBSERVABILITY[norm_dep])
        else:
            detected_libraries.add(dep)

    # Detect topics from corpus and project metadata
    full_text_corpus = " ".join(corpus_for_topics) + " " + " ".join(dependencies.keys())
    for pattern, topic_name in TOPIC_PATTERNS:
        if re.search(pattern, full_text_corpus, re.IGNORECASE):
            detected_topics.add(topic_name)

    languages = [lang for lang, _ in lang_counter.most_common()]

    # Format structured profile_text for deterministic embedding and display
    profile_lines = [
        f"Project: {project_name}",
        f"Languages: {', '.join(sorted(languages)) if languages else 'Unknown'}",
        f"Frameworks: {', '.join(sorted(detected_frameworks)) if detected_frameworks else 'None'}",
        f"ML & AI Stack: {', '.join(sorted(detected_ml_stack)) if detected_ml_stack else 'None'}",
        f"Databases & Storage: {', '.join(sorted(detected_databases)) if detected_databases else 'None'}",
        f"Infrastructure: {', '.join(sorted(detected_infra)) if detected_infra else 'None'}",
        f"Key Dependencies: {', '.join(sorted(list(dependencies.keys())[:20])) if dependencies else 'None'}",
        f"Topics: {', '.join(sorted(detected_topics)) if detected_topics else 'General Software'}",
    ]
    if description:
        profile_lines.append(f"Description: {description}")

    profile_text = "\n".join(profile_lines)
    profile_hash = hashlib.sha256(profile_text.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)

    profile = ProjectTechnologyProfile(
        project_id=project_id,
        languages=sorted(languages),
        frameworks=sorted(list(detected_frameworks)),
        libraries=sorted(list(detected_libraries)),
        dependencies=dependencies,
        databases=sorted(list(detected_databases)),
        storage=sorted(list(detected_storage)),
        infrastructure=sorted(list(detected_infra)),
        ml_stack=sorted(list(detected_ml_stack)),
        deployment=sorted(list(detected_deployment)),
        observability=sorted(list(detected_observability)),
        testing=sorted(list(detected_testing)),
        topics=sorted(list(detected_topics)),
        profile_text=profile_text,
        profile_hash=profile_hash,
        updated_at=now,
    )

    metadata = {
        "description": description,
        "languages": sorted(languages),
        "frameworks": sorted(list(detected_frameworks)),
        "libraries": sorted(list(detected_libraries)),
        "databases": sorted(list(detected_databases)),
        "infrastructure": sorted(list(detected_infra)),
        "models": sorted(list(detected_ml_stack)),
        "tools": sorted(list(detected_testing | detected_observability)),
        "topics": sorted(list(detected_topics)),
        "keywords": sorted(list(set(dependencies.keys()) | detected_topics)),
    }

    return profile, metadata
