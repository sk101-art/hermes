import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.context.embeddings import get_or_create_project_embedding
from app.context.profiler import build_project_technology_profile
from app.context.scanner import compute_project_context_hash, discover_projects, scan_project_files
from app.models.schemas import Project
from app.storage.db import Database


def run_context_scan(reference_dir: str = "reference", force: bool = False) -> None:
    start_time = time.time()
    db = Database()

    print("=" * 65)
    print("HERMES — PROJECT CONTEXT & REFERENCE SCANNER")
    print("=" * 65)

    project_paths = discover_projects(reference_dir)
    print(f"Discovered {len(project_paths)} project directory candidates in '{reference_dir}'...\n")

    projects_indexed = 0
    projects_unchanged = 0
    files_indexed_total = 0
    files_skipped_total = 0
    sensitive_skipped_total = 0
    dirs_skipped_total = 0
    embeddings_generated = 0
    embeddings_reused = 0

    now = datetime.now(timezone.utc)
    active_project_ids = set()

    for ppath in project_paths:
        proj_name = ppath.name
        proj_id = f"project:{proj_name.lower().strip()}"
        active_project_ids.add(proj_id)

        # 1. Scan files
        files, stats = scan_project_files(
            project_id=proj_id,
            project_path=ppath,
        )

        files_indexed_total += stats["files_indexed"]
        files_skipped_total += (stats["files_skipped_binary"] + stats["files_skipped_size"] + stats["files_skipped_unsupported"])
        sensitive_skipped_total += stats["sensitive_files_skipped"]
        dirs_skipped_total += stats["dirs_skipped"]

        # 2. Compute context hash
        context_hash = compute_project_context_hash(files)

        existing_proj = db.get_project(proj_id)
        if existing_proj and existing_proj.context_hash == context_hash and not force:
            projects_unchanged += 1
            # Recheck embedding caching
            profile = db.get_project_profile(proj_id)
            if profile:
                _, was_gen = get_or_create_project_embedding(proj_id, profile.profile_text, profile.profile_hash, db)
                if was_gen:
                    embeddings_generated += 1
                else:
                    embeddings_reused += 1
            continue

        # 3. Build Technology Profile
        profile, meta = build_project_technology_profile(
            project_id=proj_id,
            project_name=proj_name,
            files=files,
        )

        # 4. Save Project File Records (handle deletions)
        existing_files = db.get_project_files(proj_id)
        current_file_ids = {f.id for f in files}
        for ef in existing_files:
            if ef.id not in current_file_ids:
                db.delete_project_file(ef.id)

        for pf in files:
            db.save_project_file(pf)

        # 5. Save Project Record
        project = Project(
            id=proj_id,
            name=proj_name,
            path=str(ppath).replace("\\", "/"),
            description=meta.get("description"),
            languages=meta.get("languages", []),
            frameworks=meta.get("frameworks", []),
            libraries=meta.get("libraries", []),
            databases=meta.get("databases", []),
            infrastructure=meta.get("infrastructure", []),
            models=meta.get("models", []),
            tools=meta.get("tools", []),
            topics=meta.get("topics", []),
            keywords=meta.get("keywords", []),
            is_active=True,
            context_hash=context_hash,
            created_at=existing_proj.created_at if existing_proj else now,
            updated_at=now,
            last_indexed_at=now,
        )
        db.save_project(project)
        db.save_project_profile(profile)

        # 6. Generate or reuse local embedding
        _, was_gen = get_or_create_project_embedding(proj_id, profile.profile_text, profile.profile_hash, db)
        if was_gen:
            embeddings_generated += 1
        else:
            embeddings_reused += 1

        projects_indexed += 1

    # Check for removed projects in DB and deactivate them
    all_db_projects = db.get_all_projects(active_only=True)
    for db_p in all_db_projects:
        if db_p.id not in active_project_ids:
            db.deactivate_project(db_p.id)

    duration = time.time() - start_time
    print("=" * 65)
    print("CONTEXT SCAN SUMMARY")
    print("=" * 65)
    print(f"  Projects Discovered:           {len(project_paths):>5}")
    print(f"  Projects Indexed/Updated:      {projects_indexed:>5}")
    print(f"  Projects Unchanged:            {projects_unchanged:>5}")
    print(f"  Files Indexed:                 {files_indexed_total:>5}")
    print(f"  Files Skipped:                 {files_skipped_total:>5}")
    print(f"  Sensitive Files Skipped:       {sensitive_skipped_total:>5}")
    print(f"  Generated Directories Skipped: {dirs_skipped_total:>5}")
    print(f"  Project Embeddings Generated:  {embeddings_generated:>5}")
    print(f"  Project Embeddings Reused:     {embeddings_reused:>5}")
    print(f"  Scan Duration:               {duration:>5.2f}s")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Project Context Scanner")
    parser.add_argument("--dir", default="reference", help="Reference directory path")
    parser.add_argument("--force", action="store_true", help="Force re-indexing of all projects")
    args = parser.parse_args()
    run_context_scan(reference_dir=args.dir, force=args.force)
