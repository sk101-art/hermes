"""Quick import sanity check for the explanation-upgrade models and DB layer."""
from app.models.schemas import (
    ProjectMatch,
    ProjectNarrative,
    ProjectMatchExplanation,
    MatchDimension,
    PotentialEffect,
    RecommendedAction,
    ComparisonRow,
    EvidenceReference,
)
from app.storage.db import Database

# Round-trip a match with an explanation through the models
expl = ProjectMatchExplanation(
    subject_kind="release",
    subject_name="Test Release",
    what_happened="A new release was published.",
    matched_dimensions=[
        MatchDimension(
            dimension="storage engine",
            project_value="SQLite",
            intelligence_value="SQLite 3.46",
            connection="Project uses SQLite directly.",
            evidence_strength="strong",
        )
    ],
    recommended_action=RecommendedAction(action="review", rationale="Direct dependency.", urgency="medium"),
    comparison_rows=[
        ComparisonRow(dimension="storage", project_value="SQLite", intelligence_value="SQLite 3.46", why_relevant="Same engine")
    ],
    relationship_label="direct_match",
)
m = ProjectMatch(id="pm:test", project_id="project:x", entity_id="cluster:y", explanation=expl, explanation_version="1")
blob = m.explanation.model_dump_json()
back = ProjectMatchExplanation.model_validate_json(blob)
assert back.subject_name == "Test Release"
assert back.matched_dimensions[0].dimension == "storage engine"

n = ProjectNarrative(purpose_summary="A test project", extraction_status="extracted")
nblob = n.model_dump_json()
nback = ProjectNarrative.model_validate_json(nblob)
assert nback.purpose_summary == "A test project"

print("imports OK")
