from typing import Annotated, Literal

from pydantic import Field

from ..people_graph.models import StrictModel

POLICY_VERSION = "event-graph:v1"
PROMPT_VERSION = "event-association:v1"
OPERATION = "event_association"


class ViewFilter(StrictModel):
    view: Literal["events", "evidence", "associations"] = "events"
    query: str = Field(default="", max_length=200)
    focus_id: str = Field(default="", max_length=2000)
    relation_kind: Literal["", "event_evidence", "shared_evidence", "analysis_evidence", "analysis_claim",
                           "claim_evidence", "mentioned_in", "participation_candidate", "related_candidate",
                           "inconsistent_candidate"] = ""
    max_nodes: int = Field(default=200, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=100)


class StartRequest(StrictModel):
    task_id: str = Field(min_length=1, max_length=256)
    people_run_id: str | None = Field(default=None, pattern=r"^pg_[a-f0-9]{32}$")
    event_ids: list[Annotated[str, Field(min_length=1, max_length=256)]] = Field(default_factory=list, max_length=50)
    case_description: str = Field(default="", max_length=8000)
    requested_by: str = Field(min_length=1, max_length=256)
    max_pairs: int = Field(default=100, ge=1, le=500)


class Reference(StrictModel):
    source_id: str = Field(min_length=1, max_length=2000)
    quote: str = Field(min_length=2, max_length=1000)


class Suggestion(StrictModel):
    kind: Literal["participation_candidate", "related_candidate", "inconsistent_candidate"]
    reason: str = Field(min_length=1, max_length=1000)
    refs: list[Reference] = Field(min_length=1, max_length=8)


class AssociationResponse(StrictModel):
    # One explicitly scoped pair per request; the model cannot create endpoints.
    suggestions: list[Suggestion] = Field(default_factory=list, max_length=3)
