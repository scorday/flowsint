# flowsint-api

## Installation

1. Install Python dependencies:
2. 
```bash
uv sync
```

## Run

```bash
# dev
uv run uvicorn app.main:app --host 0.0.0.0 --port 5001 --reload
# prod
uv run uvicorn app.main:app --host 0.0.0.0 --port 5001
```

## Enricher administration

Provider and API-key columns describe the integration used by each enricher.
Click a name for the full description and key requirements. Keys can be required,
optional, conditional on a mode, not required, or unknown for an unannotated custom
template. These values do not reveal whether a vault key is configured.
The [complete metadata audit](../docs/enricher-metadata-audit.md) documents all 49
built-ins, implementation limits and the optional template `metadata` block.

Open **Enricher administration** in the sidebar, or `/dashboard/admin/enrichers`.
The table includes all registered built-in enrichers and stored templates,
including hidden entries, in one flat table with a Category column. Search and
filters narrow the rows directly. Use a row's visibility switch to save changes
immediately. Template content and credentials are not returned by this API.

In AVL4 mode, administration requires the current Auth user to have the
`global_access_admin` role or belong to `/Administrator`, in addition to access to
Flowsint and the selected project. Settings are shared within that project and
isolated from other projects. Standalone mode uses instance-wide settings; set
`FLOWSINT_ADMIN_USER_IDS` on the API to a comma-separated list of existing local
Profile UUIDs. With an empty list, standalone administration is denied. An
investigation's admin role does not grant instance administration.

Apply the schema migration with the usual API release procedure before serving
this version (`uv run alembic upgrade head` from `flowsint-api`). It adds
`enricher_visibility`; no overrides are required for existing enrichers. The legacy
hidden default for `n8n_connector` is preserved and can be changed in the table.

Visibility controls `/api/enrichers`, `/api/flows/raw_materials` and
`/api/flows/input_type/{input_type}`. Hiding removes an enricher from selection
menus and the flow builder catalog; it does not disable execution of saved flows
or direct launches and does not change template ownership or `is_public` sharing.
New enrichers are visible by default. The administration endpoints are
`GET /api/enrichers/administration/access`, `GET /api/enrichers/administration`, and
`PATCH /api/enrichers/administration/{kind}/{id}` with `{"is_visible": false}`.
Use `builtin` and the registered name, or `template` and the template UUID.
