import os
import pytest
from unittest.mock import patch, MagicMock
from app.storage.db import Database
from app.services.projects import (
    add_project,
    archive_project,
    restore_project,
    scan_single_project
)

@patch("app.context.embeddings.get_or_create_project_embedding")
@patch("app.context.embeddings.unload_embedder")
def test_project_lifecycle_and_archival(mock_unload, mock_get_emb, tmp_path):
    db_file = str(tmp_path / "test_projects.db")
    db = Database(db_path=db_file)

    # 1. Add a project
    proj_dir = tmp_path / "my_project"
    proj_dir.mkdir()
    (proj_dir / "package.json").write_text('{"dependencies": {"express": "^4.18.2"}}')

    proj = add_project(
        name="My Project",
        path=str(proj_dir),
        description="A test project",
        db=db
    )
    assert proj is not None
    assert proj.name == "My Project"
    assert proj.is_active is True

    # 2. Get projects (active only vs all)
    all_projects = db.get_all_projects(active_only=True)
    assert len(all_projects) == 1
    assert all_projects[0].id == proj.id

    # 3. Archive project
    archive_res = archive_project(proj.id, db=db)
    assert archive_res is True

    # Active only should return 0
    active_projects = db.get_all_projects(active_only=True)
    assert len(active_projects) == 0

    # Including archived should return 1
    all_projects = db.get_all_projects(active_only=False)
    assert len(all_projects) == 1
    assert all_projects[0].is_active is False

    # 4. Restore project
    restore_res = restore_project(proj.id, db=db)
    assert restore_res is True

    active_projects = db.get_all_projects(active_only=True)
    assert len(active_projects) == 1
    assert active_projects[0].is_active is True

    # 5. Scan project
    scan_res = scan_single_project(proj.id, db=db)
    assert scan_res["status"] == "completed", f"Scan failed: {scan_res.get('error')}"
