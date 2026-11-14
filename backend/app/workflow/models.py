from typing import TypedDict, Literal
from pydantic import BaseModel, ConfigDict, Field


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Plan(Output):
    steps: list[str] = Field(min_length=1, max_length=6)
    areas: list[str] = Field(max_length=6)


class InvestigationRequest(Output):
    queries: list[str] = Field(max_length=3)
    files: list[str] = Field(max_length=4)


class Investigation(Output):
    summary: str = Field(max_length=6000)


class Development(Output):
    patch: str = Field(max_length=65536)
    explanation: str = Field(max_length=3000)


class Review(Output):
    verdict: Literal["pass", "fail"]
    feedback: str = Field(max_length=4000)


class WorkflowState(TypedDict, total=False):
    task_id: str
    repository: str
    issue_number: int
    issue_details: dict
    plan: dict
    relevant_files: dict[str, str]
    investigation_summary: str
    patch: str
    changed_files: list[str]
    test_results: dict
    review_feedback: str
    retry_count: int
    approval_status: str
    current_step: str
    task_status: str
    pr_url: str | None
    error: str | None
    diff: dict
    base: str
    branch: str
    review_passed: bool
