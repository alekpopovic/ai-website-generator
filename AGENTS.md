# Engineering Instructions

These rules apply permanently to all work in this repository. The platform consists of an Angular web application; a FastAPI control-plane API; PostgreSQL; Redis; Temporal workers; Scrapy and Playwright scanners; MinIO or compatible S3 storage; Qdrant; DSPy; private Ollama inference; deterministic Jinja2 rendering backed by a controlled component registry; and optional later-stage TRL, PEFT, and QLoRA fine-tuning.

1. Inspect the existing repository before changing files.
2. Preserve existing working behavior unless the current task explicitly changes it.
3. Use stable, mutually compatible dependency versions and commit all lock files.
4. Never execute heavy crawl, browser, AI, embedding, rendering, validation, or training jobs inside FastAPI request processes.
5. FastAPI is the control plane. Temporal workers execute long-running jobs.
6. Angular must never communicate directly with Ollama, Qdrant, MinIO, Temporal, Redis, or PostgreSQL.
7. Ollama must remain on a private internal network and must not be publicly exposed.
8. Models must return validated Pydantic structures such as `WebsiteProfile`, `PageSpec`, and `SiteSpec`. Do not rely on arbitrary raw HTML generation.
9. Generated websites may use only registered components and controlled JavaScript authored by this project.
10. Never execute model-generated JavaScript, shell commands, SQL, Python, templates, or URLs.
11. Never reuse scraped logos, brand names, proprietary copy, photographs, illustrations, source code, or complete page compositions.
12. Scanned websites are converted into abstract design patterns, component structures, design tokens, and layout metadata.
13. Respect `robots.txt`, crawl rate limits, authorization attestations, provenance, removal requests, and source licensing metadata.
14. Implement SSRF protection for every crawler, browser, redirect, asset, and webhook URL.
15. All workflow activities must be idempotent, retry-safe, cancellable where practical, and observable.
16. Pass database IDs and object-storage keys through Temporal, not large HTML documents, screenshots, model outputs, or binary data.
17. Store secrets only through environment variables or secret managers. Never commit secrets.
18. Use migrations for every database schema change.
19. Use strict typing in Python and TypeScript.
20. Add unit and integration tests for all important business logic.
21. Default CI must not require internet access, GPUs, or real Ollama models.
22. Provide fake services and deterministic fixtures for model, crawl, browser, storage, and vector tests.
23. Do not push code, deploy infrastructure, run `terraform apply`, or execute destructive operations.
24. Update `docs/implementation-status.md` after each task.
25. Record important architectural decisions in `docs/adr/`.
26. At the end of every task:
    - run relevant formatters;
    - run linters;
    - run type checks;
    - run relevant tests;
    - report changed files;
    - report commands executed;
    - report unresolved risks;
    - provide a suggested commit message.
