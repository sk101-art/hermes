import sys
from datetime import datetime, timezone
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_context_status() -> None:
    db = Database()
    projects = db.get_all_projects(active_only=True)

    print("=" * 70)
    print("HERMES — PROJECT CONTEXT STATUS")
    print("=" * 70)

    if not projects:
        print("\nNo active projects found in reference context directory.")
        print("To add projects, create subdirectories in 'reference/' with README/requirements.")
        print("=" * 70)
        return

    print(f"\nACTIVE PROJECTS: {len(projects)}\n")

    for idx, proj in enumerate(projects, 1):
        profile = db.get_project_profile(proj.id)
        files = db.get_project_files(proj.id)
        last_idx = proj.last_indexed_at.strftime("%Y-%m-%d %H:%M:%S UTC") if proj.last_indexed_at else "Never"

        print(f"[{idx:02d}] Project: {proj.name}")
        print(f"     Path:          {proj.path}")
        print(f"     Files Indexed: {len(files)}")
        if proj.description:
            print(f"     Description:   {proj.description}")

        if profile:
            print(f"     Languages:     {', '.join(profile.languages) if profile.languages else 'None'}")
            print(f"     Frameworks:    {', '.join(profile.frameworks) if profile.frameworks else 'None'}")
            print(f"     ML & AI Stack: {', '.join(profile.ml_stack) if profile.ml_stack else 'None'}")
            print(f"     Storage & DB:  {', '.join(profile.databases) if profile.databases else 'None'}")
            print(f"     Key Packages:  {', '.join(list(profile.dependencies.keys())[:10]) if profile.dependencies else 'None'}")
            print(f"     Topics:        {', '.join(profile.topics) if profile.topics else 'None'}")

        print(f"     Last Indexed:  {last_idx}")
        print("-" * 70)

    print("=" * 70)


if __name__ == "__main__":
    run_context_status()
