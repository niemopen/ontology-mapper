"""Pydantic models for API request and response payloads."""

from pydantic import BaseModel
from typing import Optional


# --- Runs ---

class CreateRunRequest(BaseModel):
    organization: str
    source: str
    target_ontology: str
    target_version: str


class RunSummary(BaseModel):
    run_id: str
    organization: str
    source: str
    target_ontology: str
    target_version: str
    current_stage: Optional[str] = None
    created_at: str


# --- Review actions ---

class ApproveRequest(BaseModel):
    concept: str
    confidence: str = "confident"  # "confident" or "best-guess"


class ChangeTargetRequest(BaseModel):
    concept: str
    new_target_type: str


class ResolvePropertyRequest(BaseModel):
    concept: str
    source_property: str
    property_action: str  # "reuse-property" or "create-property"
    target_property: Optional[str] = None
    confidence: str = "confident"  # "confident" or "best-guess"


# --- Ontology requests ---

class OntologyRequestCreate(BaseModel):
    name: str
    version: str = ""
    reference_url: str = ""
    notes: str = ""
