import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pytest

from app.context.embeddings import get_or_create_project_embedding
from app.context.matcher import match_project_with_cluster
from app.context.profiler import (
    build_project_technology_profile,
    parse_cargo_toml,
    parse_environment_yml,
    parse_package_json,
    parse_pyproject_toml,
    parse_requirements_txt,
)
from app.context.scanner import (
    compute_project_context_hash,
    discover_projects,
    is_binary_file,
    is_sensitive_file,
    scan_project_files,
)
from app.models.schemas import (
    Claim,
    Event,
    Project,
    ProjectFile,
    ProjectMatch,
    ProjectTechnologyProfile,
    StoryCluster,
    TechnologyAssessment,
    TechnologyState,
)
from app.storage.db import Database


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "test_context.db")
    db = Database(db_path=db_file)
    yield db
    db.close()


def test_dependency_extraction():
    # 1. requirements.txt
    req_text = """
    # Comment
    torch==2.5.1
    fastapi>=0.115.0
    sentence-transformers~=3.0.0
    -e .
    """
    req_deps = parse_requirements_txt(req_text)
    assert "torch" in req_deps
    assert req_deps["torch"] == "==2.5.1"
    assert "fastapi" in req_deps
    assert "sentence-transformers" in req_deps

    # 2. pyproject.toml
    toml_text = """
    [project]
    dependencies = [
        "vllm>=0.6.0",
        "chromadb==0.5.0",
    ]
    """
    toml_deps = parse_pyproject_toml(toml_text)
    assert "vllm" in toml_deps
    assert "chromadb" in toml_deps

    # 3. package.json
    pkg_json = """
    {
      "dependencies": {
        "react": "^18.2.0",
        "next": "14.0.0"
      },
      "devDependencies": {
        "typescript": "^5.0.0"
      }
    }
    """
    pkg_deps = parse_package_json(pkg_json)
    assert "react" in pkg_deps
    assert "next" in pkg_deps
    assert "typescript" in pkg_deps

    # 4. environment.yml
    env_yml = """
    name: test_env
    dependencies:
      - python=3.11
      - numpy>=1.24
      - pip:
        - triton==3.0.0
    """
    env_deps = parse_environment_yml(env_yml)
    assert "numpy" in env_deps
    assert "triton" in env_deps

    # 5. Cargo.toml
    cargo_toml = """
    [package]
    name = "cuda-engine"
    version = "0.1.0"

    [dependencies]
    tokio = "1.0"
    cudarc = "0.9.0"
    """
    cargo_deps = parse_cargo_toml(cargo_toml)
    assert "tokio" in cargo_deps
    assert "cudarc" in cargo_deps


def test_secret_and_sensitive_ignore():
    assert is_sensitive_file(".env")
    assert is_sensitive_file(".env.local")
    assert is_sensitive_file(".env.production")
    assert is_sensitive_file("id_rsa")
    assert is_sensitive_file("server.key")
    assert is_sensitive_file("cert.pem")
    assert is_sensitive_file("credentials.json")
    assert is_sensitive_file("api_token.txt")

    assert not is_sensitive_file("README.md")
    assert not is_sensitive_file("requirements.txt")
    assert not is_sensitive_file("main.py")


def test_generated_directories_and_scanner(tmp_path):
    project_dir = tmp_path / "sample_project"
    project_dir.mkdir()

    # Normal files
    (project_dir / "README.md").write_text("# RAG Engine\nA retrieval system", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nchromadb\n", encoding="utf-8")
    (project_dir / "main.py").write_text("import fastapi\nimport chromadb\n", encoding="utf-8")

    # Sensitive files (should be skipped)
    (project_dir / ".env").write_text("SECRET_KEY=12345", encoding="utf-8")
    (project_dir / "private.key").write_text("PRIVATE KEY DATA", encoding="utf-8")

    # Generated / vendor directories (should be skipped)
    node_dir = project_dir / "node_modules" / "some-pkg"
    node_dir.mkdir(parents=True)
    (node_dir / "index.js").write_text("console.log(1);", encoding="utf-8")

    venv_dir = project_dir / ".venv" / "lib"
    venv_dir.mkdir(parents=True)
    (venv_dir / "site.py").write_text("# venv code", encoding="utf-8")

    files, stats = scan_project_files("project:sample", project_dir)

    indexed_names = [Path(f.relative_path).name for f in files]
    assert "README.md" in indexed_names
    assert "requirements.txt" in indexed_names
    assert "main.py" in indexed_names

    # Verify sensitive files skipped
    assert ".env" not in indexed_names
    assert "private.key" not in indexed_names
    assert stats["sensitive_files_skipped"] >= 2

    # Verify generated directories skipped
    assert "index.js" not in indexed_names
    assert "site.py" not in indexed_names


def test_technology_profile_generation(tmp_path):
    project_dir = tmp_path / "rag_project"
    project_dir.mkdir()

    (project_dir / "README.md").write_text("# Document RAG System\nQuestion answering with embeddings and vector database.", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi==0.115.0\nsentence-transformers>=3.0.0\nchromadb==0.5.0\ntorch>=2.4.0\n", encoding="utf-8")
    (project_dir / "app.py").write_text("import fastapi\nfrom sentence_transformers import SentenceTransformer\n", encoding="utf-8")

    files, _ = scan_project_files("project:rag", project_dir)
    profile, meta = build_project_technology_profile("project:rag", "rag_project", files)

    assert "Python" in profile.languages
    assert "FastAPI" in profile.frameworks
    assert "sentence-transformers" in profile.ml_stack
    assert "PyTorch" in profile.ml_stack
    assert "Chroma" in profile.databases
    assert any(t in profile.topics for t in ["RAG", "embeddings", "vector search"])
    assert "fastapi" in profile.dependencies
    assert "chromadb" in profile.dependencies


def test_hash_idempotence_and_change_detection(tmp_path):
    project_dir = tmp_path / "hasher_project"
    project_dir.mkdir()

    req_file = project_dir / "requirements.txt"
    req_file.write_text("torch==2.5.0\n", encoding="utf-8")

    files1, _ = scan_project_files("project:h", project_dir)
    hash1 = compute_project_context_hash(files1)

    # Re-scan unchanged -> hash identical
    files2, _ = scan_project_files("project:h", project_dir)
    hash2 = compute_project_context_hash(files2)
    assert hash1 == hash2

    # Modify requirements.txt
    req_file.write_text("torch==2.5.0\nqdrant-client>=1.9.0\n", encoding="utf-8")

    files3, _ = scan_project_files("project:h", project_dir)
    hash3 = compute_project_context_hash(files3)
    assert hash3 != hash1

    profile, _ = build_project_technology_profile("project:h", "hasher_project", files3)
    assert "Qdrant" in profile.databases


def test_deleted_file_cleanup(tmp_path, test_db):
    project_dir = tmp_path / "del_project"
    project_dir.mkdir()

    f1 = project_dir / "README.md"
    f1.write_text("# Project", encoding="utf-8")
    f2 = project_dir / "extra.py"
    f2.write_text("import sqlite3", encoding="utf-8")

    files, _ = scan_project_files("project:del", project_dir)
    for f in files:
        test_db.save_project_file(f)

    db_files = test_db.get_project_files("project:del")
    assert len(db_files) == 2

    # Delete extra.py
    f2.unlink()
    files_after, _ = scan_project_files("project:del", project_dir)

    # Sync deletions
    current_ids = {f.id for f in files_after}
    for ef in db_files:
        if ef.id not in current_ids:
            test_db.delete_project_file(ef.id)

    db_files_after = test_db.get_project_files("project:del")
    assert len(db_files_after) == 1
    assert db_files_after[0].relative_path == "README.md"


def test_direct_dependency_match(test_db):
    now = datetime.now(timezone.utc)
    project = Project(
        id="project:test_torch",
        name="Torch Project",
        path="reference/torch_project",
        context_hash="hash123",
        created_at=now,
        updated_at=now,
    )
    profile = ProjectTechnologyProfile(
        project_id=project.id,
        languages=["Python"],
        frameworks=["PyTorch"],
        dependencies={"torch": "==2.5.1", "torchvision": "==0.20.1"},
        ml_stack=["PyTorch"],
        topics=["deep learning"],
        profile_text="Project: Torch Project\nLanguages: Python\nFrameworks: PyTorch",
        profile_hash="phash1",
        updated_at=now,
    )

    cluster = StoryCluster(
        id="cluster:pytorch_rel",
        canonical_title="PyTorch 2.6.0 Released",
        sources=["github"],
        event_ids=["github:release:pytorch/pytorch:v2.6.0"],
    )
    ev = Event(
        id="github:release:pytorch/pytorch:v2.6.0",
        source="github",
        event_type="release",
        source_type="release",
        title="Release v2.6.0 for pytorch/pytorch",
        text="Official release of PyTorch 2.6.0 with CUDA 12.4 support.",
    )
    claim = Claim(
        id="claim:pytorch_rel",
        cluster_id=cluster.id,
        claim_type="release",
        assertion_level="artifact_fact",
        subject="pytorch/pytorch",
        predicate="released",
        object="version v2.6.0",
        claim_text="Repository pytorch/pytorch released version v2.6.0.",
        status="strongly_supported",
        verification_score=0.85,
    )
    assessment = TechnologyAssessment(
        cluster_id=cluster.id,
        maturity_stage="established",
        assessment_score=0.90,
    )
    tech_state = TechnologyState(
        cluster_id=cluster.id,
        risk_score=0.10,
    )

    match = match_project_with_cluster(
        project=project,
        profile=profile,
        project_embedding=None,
        cluster=cluster,
        cluster_events=[ev],
        cluster_claims=[claim],
        assessment=assessment,
        tech_state=tech_state,
        db=test_db,
    )

    assert match is not None
    assert match.match_type == "direct_dependency"
    assert match.relevance_score >= 0.75
    assert match.impact_score >= 0.70
    assert match.recommendation == "upgrade_candidate"
    assert any("dependency_match" in r for r in match.reason_codes)


def test_recommendation_downgrade_for_high_risk_and_prototype(test_db):
    now = datetime.now(timezone.utc)
    project = Project(
        id="project:cpp_opt",
        name="Compiler Lab",
        path="reference/compiler_lab",
        context_hash="hash456",
        created_at=now,
        updated_at=now,
    )
    profile = ProjectTechnologyProfile(
        project_id=project.id,
        languages=["C++"],
        frameworks=["CUDA"],
        dependencies={"cuda": ""},
        topics=["compiler optimization", "GPU kernels"],
        profile_text="Project: Compiler Lab\nLanguages: C++\nTopics: compiler optimization",
        profile_hash="phash2",
        updated_at=now,
    )

    cluster = StoryCluster(
        id="cluster:proto_opt",
        canonical_title="Experimental CUDA Compiler Hack",
        sources=["hacker_news"],
        event_ids=["hn:123"],
    )
    ev = Event(
        id="hn:123",
        source="hacker_news",
        event_type="discussion",
        source_type="community_discussion",
        title="Experimental CUDA Compiler Hack 100x faster",
        text="A prototype compiler pass with unverified claims.",
    )
    claim = Claim(
        id="claim:proto_opt",
        cluster_id=cluster.id,
        claim_type="performance",
        assertion_level="performance_claim",
        subject="hack",
        predicate="reports_performance",
        object="100x faster",
        claim_text="Reports 100x faster in custom benchmark",
        status="weakly_supported",
        verification_score=0.40,
    )
    assessment = TechnologyAssessment(
        cluster_id=cluster.id,
        maturity_stage="prototype",
        assessment_score=0.20,
    )
    tech_state = TechnologyState(
        cluster_id=cluster.id,
        risk_score=0.85,  # High risk
    )

    match = match_project_with_cluster(
        project=project,
        profile=profile,
        project_embedding=None,
        cluster=cluster,
        cluster_events=[ev],
        cluster_claims=[claim],
        assessment=assessment,
        tech_state=tech_state,
        db=test_db,
    )

    assert match is not None
    # High risk & prototype must result in WATCH or EVALUATE, not UPGRADE or CONSIDER
    assert match.recommendation in ("watch", "evaluate", "potential_risk")


def test_unrelated_match_rejection(test_db):
    now = datetime.now(timezone.utc)
    project = Project(
        id="project:cpp_opt",
        name="Compiler Lab",
        path="reference/compiler_lab",
        context_hash="hash456",
        created_at=now,
        updated_at=now,
    )
    profile = ProjectTechnologyProfile(
        project_id=project.id,
        languages=["C++"],
        frameworks=["LLVM"],
        dependencies={"llvm": ""},
        topics=["compiler optimization", "llvm"],
        profile_text="Project: Compiler Lab\nLanguages: C++",
        profile_hash="phash2",
        updated_at=now,
    )

    cluster = StoryCluster(
        id="cluster:css_fw",
        canonical_title="Tailwind CSS v4.0 Alpha",
        sources=["github"],
        event_ids=["gh:css"],
    )
    ev = Event(
        id="gh:css",
        source="github",
        event_type="release",
        source_type="release",
        title="Tailwind CSS v4.0",
        text="A utility-first CSS framework for web design.",
    )
    claim = Claim(
        id="claim:css",
        cluster_id=cluster.id,
        claim_type="release",
        assertion_level="artifact_fact",
        subject="tailwindcss",
        predicate="released",
        object="v4.0",
        claim_text="Tailwind CSS released v4.0",
        status="supported",
        verification_score=0.60,
    )

    match = match_project_with_cluster(
        project=project,
        profile=profile,
        project_embedding=None,
        cluster=cluster,
        cluster_events=[ev],
        cluster_claims=[claim],
        assessment=None,
        tech_state=None,
        db=test_db,
    )

    # Completely unrelated technology should NOT produce a match
    assert match is None
