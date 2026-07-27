# Web API Client

Generated and contract-checked Angular client for the FastAPI control plane. OpenAPI-derived files
live in `src/generated/` and must never be edited manually. Auth, correlation, problem mapping, URL
construction, and testing adapters live outside that directory.

Run `task generate-api-client` at the repository root after changing an API route or Pydantic
contract. `task verify-generated-api-client` regenerates into a temporary directory and fails when
the committed schema or client is stale.
