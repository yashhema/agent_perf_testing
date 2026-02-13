"""Pydantic models for API requests and responses."""

from app.api.models.requests import (
    CreateLabRequest,
    UpdateLabRequest,
    CreateServerRequest,
    UpdateServerRequest,
    CreateBaselineRequest,
    UpdateBaselineRequest,
    CreateTestRunRequest,
    UpdateTestRunRequest,
    CreateTestRunTargetRequest,
    CreateExecutionRequest,
    ExecutionActionRequest,
)
from app.api.models.responses import (
    LabResponse,
    ServerResponse,
    BaselineResponse,
    BaselineConfigResponse,
    TestRunResponse,
    TestRunTargetResponse,
    ExecutionResponse,
    ExecutionListResponse,
    ActionResultResponse,
    WorkflowStateResponse,
)

__all__ = [
    # Requests
    "CreateLabRequest",
    "UpdateLabRequest",
    "CreateServerRequest",
    "UpdateServerRequest",
    "CreateBaselineRequest",
    "UpdateBaselineRequest",
    "CreateTestRunRequest",
    "UpdateTestRunRequest",
    "CreateTestRunTargetRequest",
    "CreateExecutionRequest",
    "ExecutionActionRequest",
    # Responses
    "LabResponse",
    "ServerResponse",
    "BaselineResponse",
    "BaselineConfigResponse",
    "TestRunResponse",
    "TestRunTargetResponse",
    "ExecutionResponse",
    "ExecutionListResponse",
    "ActionResultResponse",
    "WorkflowStateResponse",
]
