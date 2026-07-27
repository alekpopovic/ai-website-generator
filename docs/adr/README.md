# Architecture Decision Records

ADRs record durable choices and their consequences. Accepted decisions are changed by a later superseding ADR rather than rewriting history.

| ADR                                             | Decision                                              | Status   |
| ----------------------------------------------- | ----------------------------------------------------- | -------- |
| [0001](0001-fastapi-control-plane.md)           | FastAPI as the control-plane API                      | Accepted |
| [0002](0002-angular-frontend.md)                | Angular as the frontend                               | Accepted |
| [0003](0003-temporal-workflows.md)              | Temporal as the durable workflow engine               | Accepted |
| [0004](0004-ollama-local-inference.md)          | Ollama as the initial local inference provider        | Accepted |
| [0005](0005-sitespec-generation-contract.md)    | `SiteSpec` instead of arbitrary generated HTML        | Accepted |
| [0006](0006-storage-responsibilities.md)        | PostgreSQL, MinIO, Redis, and Qdrant responsibilities | Accepted |
| [0007](0007-two-stage-scanning.md)              | Scrapy plus Playwright two-stage scanning             | Accepted |
| [0008](0008-rag-dspy-before-fine-tuning.md)     | RAG and DSPy optimization before fine-tuning          | Accepted |
| [0009](0009-data-ownership-and-transactions.md) | Data ownership and transaction boundaries             | Accepted |
| [0010](0010-scan-campaign-control-state.md)     | Scan campaign control state and workflow dispatch     | Accepted |
| [0011](0011-streamed-scan-target-imports.md)    | Streamed and staged scan-target imports               | Accepted |
| [0012](0012-shared-outbound-network-safety.md)  | Shared outbound URL and network safety boundary       | Accepted |
