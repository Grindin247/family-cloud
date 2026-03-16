# Family Event Privacy Model

## Classification

- `private`: highly sensitive family-only data
- `family`: normal internal family activity data
- `research`: safe for internal research workflows after review
- `commercial`: eligible for broader business/export workflows after review

## Export Policy

- `never`: never export
- `restricted`: internal-only unless explicitly transformed
- `anonymizable`: may be exported after pseudonymization and sanitization
- `exportable`: may be exported in approved workflows

## Flags

Each event may also mark:

- `contains_pii`
- `contains_health_data`
- `contains_financial_data`
- `contains_child_data`
- `contains_free_text`

## Defaults

Phase 1 default:

- `classification=family`
- `export_policy=restricted`

Producers should opt into broader exportability explicitly.
