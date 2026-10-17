# Organizer: cases and common project fields

`GET /programs/{pk}/management/project-form/` and `PUT` at the same URL require an authenticated manager of that exact program or staff/superuser. They edit definitions; answer writes remain leader-only and submitted competitive answers remain frozen.

GET returns `updated_at`, definition `revision`, `has_projects`, `cases: [{name, projects_count}]`, `fields` (existing field contract plus `answers_count` and `editable_type`) and `supported_types`.

PUT replaces the definition configuration atomically:

```json
{
  "expected_updated_at": "2026-10-17T10:00:00Z",
  "expected_revision": "sha256 returned by GET",
  "cases": ["Кейс А", "Кейс Б"],
  "fields": [{"id": null, "label": "Прототип", "field_type": "text", "is_required": true, "help_text": "Откройте доступ", "options": []}]
}
```

Existing IDs must belong to the URL program. New field names are generated server-side; existing names and filter settings are preserved. Cases use the existing reserved `case` select field; descriptions and tasks stay in materials. All cases share the same fields. Order follows existing primary keys, with new fields appended; this endpoint does not offer reordering.

New types: text, textarea, select, file. Existing checkbox/radio definitions remain readable and can have their labels/help edited while retaining their type/options/required settings. File answers use the existing uploaded-file URL contract.

Used case names cannot be renamed/deleted. Fields with nonempty saved answers cannot be deleted or change type; used choices cannot be removed/renamed. Empty historical value rows do not lock a generic field. Labels, help and required-before-submission settings can change. New required fields are allowed after projects exist: only projects not yet submitted must fill them before submission. Already submitted projects retain status and answers.

Draft apply and field PUT accept missing/empty additional fields and case. Explicit empty values remove the answer row; omission in partial PUT leaves it unchanged. Invalid nonempty values still fail validation. Required values are checked at submission; a generic missing-field error retains `detail` and additionally returns `code: required_program_fields` so clients can reload current definitions while preserving edits. Case/deadline/team/leader guards remain in force.

400 is validation failure without partial writes; 401/403 enforce authentication/scope; 409 rejects an old program timestamp or definition revision. The revision detects direct admin definition changes too. Program/link/definition locking serializes organizer saves against project creation, answer PUT and submission.

No schema or data migration. Deploy backend before the frontend. Old clients and other form consumers retain their existing response shapes; draft validation is intentionally relaxed.
