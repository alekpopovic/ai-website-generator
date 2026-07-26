# Control-Plane API

FastAPI application responsible for authenticated commands and queries, resource lifecycle management, authorization, validation, and starting or signalling Temporal workflows. It returns job state and artifact references; it never runs crawl, browser, AI, embedding, generation, validation, or training workloads in request processes.
