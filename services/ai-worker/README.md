# AI Worker

Runs private Ollama inference and DSPy programs for visual interpretation, structured extraction,
planning, and repair proposals. Outputs must validate against shared Pydantic schemas and may never
be executed as code, templates, commands, SQL, or arbitrary URLs.

The initial process polls the Temporal `ai-analysis` queue and implements the administrator-approved
`warm-up-model` activity. It receives only IDs and a configured model role, heartbeats during model
loading, and never pulls a model. Start it with `task ai-worker` after Temporal and private Ollama are
available.
