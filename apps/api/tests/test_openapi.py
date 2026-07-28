"""Tests for the generated API contract boundary."""

from __future__ import annotations

from platform_api.testing import create_test_app


def test_openapi_contains_stable_operations_and_shared_contracts() -> None:
    """Client generation receives stable IDs and reusable Pydantic primitives."""
    schema = create_test_app().openapi()

    assert schema["paths"]["/api/v1/version"]["get"]["operationId"] == "getApiVersion"
    assert schema["paths"]["/health/dependencies"]["get"]["operationId"] == ("getDependencyHealth")
    assert {"PaginationMeta", "PaginationParams", "ProblemDetail"} <= set(
        schema["components"]["schemas"]
    )


def test_openapi_documents_problem_details_for_version_failures() -> None:
    """Generated clients type central problem responses instead of guessing their shape."""
    responses = create_test_app().openapi()["paths"]["/api/v1/version"]["get"]["responses"]

    problem_schema = responses["503"]["content"]["application/problem+json"]["schema"]
    assert problem_schema == {"$ref": "#/components/schemas/ProblemDetail"}


def test_openapi_exposes_complete_first_party_authentication_contract() -> None:
    schema = create_test_app().openapi()
    expected = {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/logout-all",
        "/api/v1/auth/me",
        "/api/v1/auth/request-password-reset",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/verify-email",
    }

    assert expected <= set(schema["paths"])
    assert schema["paths"]["/api/v1/auth/me"]["get"]["security"] == [{"bearer": []}]


def test_openapi_exposes_model_readiness_and_worker_dispatched_warmup() -> None:
    schema = create_test_app().openapi()

    assert schema["paths"]["/api/v1/models/readiness"]["get"]["operationId"] == (
        "getConfiguredModelReadiness"
    )
    assert (
        schema["paths"]["/api/v1/admin/models/{model_role}/warm-up"]["post"]["operationId"]
        == "warmUpConfiguredModel"
    )


def test_openapi_exposes_streaming_scan_target_import_contract() -> None:
    schema = create_test_app().openapi()
    base = "/api/v1/projects/{project_id}/scan-campaigns/{campaign_id}/target-imports"
    operation = schema["paths"][base]["post"]

    assert operation["operationId"] == "importScanCampaignTargets"
    assert {"text/plain", "text/csv", "application/csv"} <= set(operation["requestBody"]["content"])
    assert schema["paths"][f"{base}/{{import_id}}/commit"]["post"]["operationId"] == (
        "commitScanTargetImport"
    )
    assert schema["paths"][f"{base}/{{import_id}}/errors.csv"]["get"]["operationId"] == (
        "exportScanTargetImportErrors"
    )


def test_openapi_exposes_owned_scan_artifact_reads_and_removal_requests() -> None:
    paths = create_test_app().openapi()["paths"]
    prefix = "/api/v1/projects/{project_id}/scan-campaigns/{campaign_id}"

    assert "get" in paths[f"{prefix}/pages/{{page_id}}/artifacts"]
    assert "get" in paths[f"{prefix}/artifacts/{{artifact_id}}/read-url"]
    assert "get" in paths[f"{prefix}/artifacts/{{artifact_id}}/screenshot"]
    assert "post" in paths[f"{prefix}/artifacts/{{artifact_id}}/removal-request"]


def test_openapi_exposes_complete_scan_review_contract() -> None:
    paths = create_test_app().openapi()["paths"]
    prefix = "/api/v1/projects/{project_id}/scan-campaigns/{campaign_id}"

    assert "get" in paths[f"{prefix}/targets/{{target_id}}/summary"]
    assert "get" in paths[f"{prefix}/pages/{{page_id}}"]
    assert "get" in paths[f"{prefix}/duplicate-groups"]
    assert "get" in paths[f"{prefix}/representative-decisions"]
    assert "get" in paths[f"{prefix}/activity"]
    assert "post" in paths[f"{prefix}/retry-selected-failures"]
