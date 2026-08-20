import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.evidence.classifier import classify_evidence
from app.models.schemas import Claim, Event, Evidence, StoryCluster


def compute_claim_fingerprint(
    cluster_id: str,
    claim_type: str,
    subject: str,
    predicate: str,
    obj: str,
) -> str:
    """Generate a deterministic fingerprint hash for a claim."""
    norm = f"{cluster_id.lower().strip()}|{claim_type.lower().strip()}|{subject.lower().strip()}|{predicate.lower().strip()}|{obj.lower().strip()}"
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
    return f"claim:{digest}"


def compute_evidence_fingerprint(claim_id: str, event_id: str, stance: str) -> str:
    """Generate a deterministic fingerprint hash for an evidence record."""
    norm = f"{claim_id.lower().strip()}|{event_id.lower().strip()}|{stance.lower().strip()}"
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
    return f"evidence:{digest}"


def build_release_claim(event: Event, cluster_id: str) -> Optional[Tuple[Claim, Evidence]]:
    """Build deterministic claim and evidence from a GitHub release event."""
    if event.source != "github" or event.event_type != "release":
        return None

    repo = event.metadata.get("repository") or event.id.replace("github:release:", "")
    tag = event.metadata.get("tag_name") or "latest"

    claim_type = "release"
    subject = repo
    predicate = "released"
    obj = f"version {tag}"
    claim_text = f"Repository {subject} released {obj}."

    cid = compute_claim_fingerprint(cluster_id, claim_type, subject, predicate, obj)
    e_type, e_class, quality = classify_evidence(event)

    claim = Claim(
        id=cid,
        cluster_id=cluster_id,
        claim_type=claim_type,
        subject=subject,
        predicate=predicate,
        object=obj,
        claim_text=claim_text,
        status="unverified",
        confidence=1.0,
        self_reported=True,
        metadata={"tag_name": tag, "repository": repo},
    )

    eid = compute_evidence_fingerprint(cid, event.id, "supports")
    evidence = Evidence(
        id=eid,
        claim_id=cid,
        event_id=event.id,
        source=event.source,
        evidence_type=e_type,
        evidence_class=e_class,
        stance="supports",
        excerpt=(event.text or event.title)[:500],
        url=event.url,
        quality_score=quality,
        independence_score=0.50,  # Self-published official release
        reproducibility_score=0.85,
    )
    return claim, evidence


def build_repository_claim(event: Event, cluster_id: str) -> Optional[Tuple[Claim, Evidence]]:
    """Build deterministic claim for a GitHub repository artifact."""
    if event.source != "github" or event.event_type != "repository":
        return None

    repo_name = event.metadata.get("full_name") or event.metadata.get("repository")
    if not repo_name:
        if " - " in event.title:
            repo_name = event.title.split(" - ", 1)[0].strip()
        else:
            repo_name = event.id.replace("github:", "").strip()

    if not repo_name:
        return None

    desc = event.text or event.title
    clean_desc = desc.split(" - ", 1)[-1].strip() if " - " in desc else desc.strip()
    if len(clean_desc) > 120:
        clean_desc = clean_desc[:117] + "..."

    claim_type = "architecture"
    subject = repo_name
    predicate = "describes_itself_as"
    obj = clean_desc
    claim_text = f"Project {subject} describes itself as: '{obj}'."

    cid = compute_claim_fingerprint(cluster_id, claim_type, subject, predicate, obj)
    e_type, e_class, quality = classify_evidence(event)

    claim = Claim(
        id=cid,
        cluster_id=cluster_id,
        claim_type=claim_type,
        subject=subject,
        predicate=predicate,
        object=obj,
        claim_text=claim_text,
        status="unverified",
        confidence=1.0,
        self_reported=True,
        metadata={"repository": repo_name},
    )

    eid = compute_evidence_fingerprint(cid, event.id, "supports")
    evidence = Evidence(
        id=eid,
        claim_id=cid,
        event_id=event.id,
        source=event.source,
        evidence_type=e_type,
        evidence_class=e_class,
        stance="supports",
        excerpt=(event.text or event.title)[:500],
        url=event.url,
        quality_score=quality,
        independence_score=0.50,
        reproducibility_score=0.80,
    )
    return claim, evidence


def build_model_claim(event: Event, cluster_id: str) -> Optional[Tuple[Claim, Evidence]]:
    """Build deterministic claim for a Hugging Face model/dataset artifact."""
    if event.source != "huggingface":
        return None

    artifact_id = event.metadata.get("repo_id") or event.id.split(":")[-1]
    artifact_type = event.event_type or "model"

    claim_type = "availability"
    subject = artifact_id
    predicate = "is_available_as"
    obj = f"{artifact_type} on Hugging Face"
    claim_text = f"Artifact {subject} is available as a {artifact_type} on Hugging Face Hub."

    cid = compute_claim_fingerprint(cluster_id, claim_type, subject, predicate, obj)
    e_type, e_class, quality = classify_evidence(event)

    claim = Claim(
        id=cid,
        cluster_id=cluster_id,
        claim_type=claim_type,
        subject=subject,
        predicate=predicate,
        object=obj,
        claim_text=claim_text,
        status="unverified",
        confidence=1.0,
        self_reported=True,
        metadata={"artifact_type": artifact_type, "downloads": event.metadata.get("downloads", 0)},
    )

    eid = compute_evidence_fingerprint(cid, event.id, "supports")
    evidence = Evidence(
        id=eid,
        claim_id=cid,
        event_id=event.id,
        source=event.source,
        evidence_type=e_type,
        evidence_class=e_class,
        stance="supports",
        excerpt=(event.text or event.title)[:500],
        url=event.url,
        quality_score=quality,
        independence_score=0.60,
        reproducibility_score=0.75,
    )
    return claim, evidence


def build_scholarly_identity_claim(event: Event, cluster_id: str) -> Optional[Tuple[Claim, Evidence]]:
    """Build deterministic scholarly publication/identity claim."""
    if event.source not in ("crossref", "openalex", "arxiv") or not (event.doi or event.metadata.get("doi")):
        return None

    doi_val = event.doi or event.metadata.get("doi")
    title_short = (event.title[:80] + "...") if len(event.title) > 80 else event.title

    claim_type = "scholarly_identity"
    subject = title_short
    predicate = "is_registered_with_doi"
    obj = doi_val
    claim_text = f"Scholarly work '{subject}' is registered with DOI {doi_val}."

    cid = compute_claim_fingerprint(cluster_id, claim_type, subject, predicate, obj)
    e_type, e_class, quality = classify_evidence(event)

    claim = Claim(
        id=cid,
        cluster_id=cluster_id,
        claim_type=claim_type,
        subject=subject,
        predicate=predicate,
        object=obj,
        claim_text=claim_text,
        status="unverified",
        confidence=1.0,
        self_reported=False,
        metadata={"doi": doi_val, "venue": event.metadata.get("venue")},
    )

    eid = compute_evidence_fingerprint(cid, event.id, "supports")
    evidence = Evidence(
        id=eid,
        claim_id=cid,
        event_id=event.id,
        source=event.source,
        evidence_type=e_type,
        evidence_class=e_class,
        stance="supports",
        excerpt=(event.text or event.title)[:500],
        url=event.url,
        quality_score=quality,
        independence_score=0.90,  # Official registry / independent registry
        reproducibility_score=0.70,
    )
    return claim, evidence


def build_performance_claim(event: Event, cluster_id: str) -> Optional[Tuple[Claim, Evidence]]:
    """Conservative extraction of self-reported performance claims."""
    text_corpus = f"{event.title} {event.text}"

    # Search for speedup, throughput, or low latency patterns
    perf_match = re.search(
        r"\b([0-9]+(?:\.[0-9]+)?x\s+(?:faster|speedup|throughput|lower\s+latency|more\s+efficient))\b",
        text_corpus,
        re.IGNORECASE,
    )
    if not perf_match:
        return None

    metric_phrase = perf_match.group(1).lower()
    subject = event.id.split(":")[-1]
    claim_type = "performance"
    predicate = "reports_performance"
    obj = metric_phrase
    claim_text = f"Project reports {metric_phrase} in self-described benchmark/workload."

    cid = compute_claim_fingerprint(cluster_id, claim_type, subject, predicate, obj)
    e_type, e_class, quality = classify_evidence(event)

    claim = Claim(
        id=cid,
        cluster_id=cluster_id,
        claim_type=claim_type,
        subject=subject,
        predicate=predicate,
        object=obj,
        claim_text=claim_text,
        status="unverified",
        confidence=0.90,
        self_reported=True,
        metadata={"metric_phrase": metric_phrase},
    )

    eid = compute_evidence_fingerprint(cid, event.id, "supports")
    evidence = Evidence(
        id=eid,
        claim_id=cid,
        event_id=event.id,
        source=event.source,
        evidence_type=e_type,
        evidence_class=e_class,
        stance="supports",
        excerpt=text_corpus[:500],
        url=event.url,
        quality_score=quality * 0.85,  # Self-reported benchmark prior
        independence_score=0.40,
        reproducibility_score=0.60,
    )
    return claim, evidence


def build_research_result_claim(event: Event, cluster_id: str) -> Optional[Tuple[Claim, Evidence]]:
    """Build deterministic claim for research paper proposals / investigations."""
    if event.source != "arxiv" and event.source_type != "research_paper":
        return None

    title_short = (event.title[:80] + "...") if len(event.title) > 80 else event.title
    summary_text = (event.text or event.title).strip()
    if "Abstract:" in summary_text:
        summary_text = summary_text.split("Abstract:", 1)[-1].strip()
    if len(summary_text) > 120:
        summary_text = summary_text[:117] + "..."

    claim_type = "research_result"
    subject = title_short
    predicate = "investigates_or_proposes"
    obj = summary_text
    claim_text = f"Research work '{subject}' investigates: '{obj}'."

    cid = compute_claim_fingerprint(cluster_id, claim_type, subject, predicate, obj)
    e_type, e_class, quality = classify_evidence(event)

    claim = Claim(
        id=cid,
        cluster_id=cluster_id,
        claim_type=claim_type,
        subject=subject,
        predicate=predicate,
        object=obj,
        claim_text=claim_text,
        status="unverified",
        confidence=1.0,
        self_reported=False,
        metadata={"venue": "arXiv preprint"},
    )

    eid = compute_evidence_fingerprint(cid, event.id, "supports")
    evidence = Evidence(
        id=eid,
        claim_id=cid,
        event_id=event.id,
        source=event.source,
        evidence_type=e_type,
        evidence_class=e_class,
        stance="supports",
        excerpt=(event.text or event.title)[:500],
        url=event.url,
        quality_score=quality,
        independence_score=0.80,
        reproducibility_score=0.70,
    )
    return claim, evidence


def extract_claims_for_cluster(
    cluster: StoryCluster,
    events: List[Event],
) -> List[Tuple[Claim, List[Evidence]]]:
    """
    Extracts all deterministic claims and associated evidence for a cluster.
    Ensures Rule 30: Claims without at least 1 evidence record are NEVER returned.
    """
    claims_dict: Dict[str, Claim] = {}
    evidence_dict: Dict[str, Dict[str, Evidence]] = {}

    builders = [
        build_release_claim,
        build_repository_claim,
        build_model_claim,
        build_scholarly_identity_claim,
        build_research_result_claim,
        build_performance_claim,
    ]

    for ev in events:
        for builder in builders:
            try:
                res = builder(ev, cluster.id)
                if res:
                    claim, evid = res
                    if claim.id not in claims_dict:
                        claims_dict[claim.id] = claim
                        evidence_dict[claim.id] = {}
                    evidence_dict[claim.id][evid.id] = evid
            except Exception:
                continue

    # Also link other events in the cluster as supporting/contextual evidence if relevant
    for cid, claim in claims_dict.items():
        for ev in events:
            # Check if event already provided primary evidence
            existing_event_ids = {e.event_id for e in evidence_dict[cid].values()}
            if ev.id not in existing_event_ids:
                e_type, e_class, quality = classify_evidence(ev)
                stance = "context"
                # If event has discussion or blog mentioning subject
                if claim.subject.lower() in (ev.title + " " + ev.text).lower():
                    stance = "supports" if ev.source in ("github", "arxiv", "huggingface", "openalex", "crossref") else "context"

                eid = compute_evidence_fingerprint(cid, ev.id, stance)
                evid = Evidence(
                    id=eid,
                    claim_id=cid,
                    event_id=ev.id,
                    source=ev.source,
                    evidence_type=e_type,
                    evidence_class=e_class,
                    stance=stance,
                    excerpt=(ev.text or ev.title)[:500],
                    url=ev.url,
                    quality_score=quality * 0.8,
                    independence_score=0.70 if ev.source != events[0].source else 0.40,
                    reproducibility_score=0.50,
                )
                evidence_dict[cid][eid] = evid

    results: List[Tuple[Claim, List[Evidence]]] = []
    for cid, claim in claims_dict.items():
        ev_list = list(evidence_dict[cid].values())
        if ev_list:  # Rule 30: >= 1 Evidence row
            results.append((claim, ev_list))

    return results
