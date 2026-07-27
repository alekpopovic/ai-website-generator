# Projects API

A project is a website-generation workspace owned by exactly one user. The MVP has no organization,
team, membership, or shared-ownership model. Every project query derives `owner_id` from the
authenticated principal; request bodies cannot choose or change ownership. A project belonging to a
different user is returned as not found.

The `/api/v1/projects` collection supports offset pagination, bounded text search across name, slug,
and description, status filtering, and deterministic sorting by name, creation time, or update time.
Slugs are unique per owner. When omitted during creation, the API generates a normalized slug and
adds a numeric suffix on collision.

Updates use `PATCH /api/v1/projects/{project_id}` and require the last observed `version`. A stale
version returns `409 project_version_conflict`; clients must reload rather than overwrite newer
state. Lifecycle changes use versioned `POST .../archive` and `POST .../restore` operations. There is
no destructive project deletion endpoint. Restored projects return to draft status.

Project creation, updates, archiving, and restoration are written to the audit log in the same
PostgreSQL transaction as the project mutation.
