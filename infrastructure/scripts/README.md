# Infrastructure Scripts

Auditable bootstrap, migration, verification, and operational helper scripts belong here. Scripts must be non-destructive by default, validate targets, avoid embedded secrets, and document required privileges.

Current helpers provide cross-platform pytest category selection and a guarded cleanup command. Cleanup removes only explicitly allowlisted generated directories located below the repository root.
