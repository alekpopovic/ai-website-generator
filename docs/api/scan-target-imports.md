# Scan-target imports

Target imports are project-owner-scoped resources below a draft scan campaign:

`/api/v1/projects/{project_id}/scan-campaigns/{campaign_id}/target-imports`

## Validate an import

Send `POST` with a raw UTF-8 request body and these query parameters:

- `source_type=paste|text|csv`;
- `authorization_attested=true`;
- `dry_run=true` for review before insertion;
- optional sanitized `filename`;
- optional `allow_ip_literals=true`, which is accepted only for configured administrators.

Use `text/plain` for pasted/newline-delimited input and `text/csv` or `application/csv` for CSV.
CSV requires one target column named `domain`, `url`, `hostname`, or `website`; other non-empty
columns become bounded row metadata. The API streams UTF-8 decoding and CSV record parsing, supports
quoted multiline fields, and performs no network requests.

Limits are 50,000 rows, 20 MiB per request, and 128 KiB per CSV record. The response reports
accepted, duplicate, invalid, blocked, already-present, processed, and committed counts.

## Review and commit

- `GET .../target-imports/{import_id}` returns durable progress and summary fields.
- `POST .../target-imports/{import_id}/commit` accepts the current optimistic `version` and
  `authorization_attested=true`. Only a completed dry run can be committed.
- `GET .../target-imports/{import_id}/errors.csv` streams non-accepted rows with row number, source
  value, outcome, reason code, and safe message. Cells that could trigger spreadsheet formulas are
  neutralized.

Imports and commits require a draft campaign. Ownership failures are represented as not found, and
authorization attestations are audited without logging upload contents.
