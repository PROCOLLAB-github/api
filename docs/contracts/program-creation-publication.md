# Program creation and first publication — API contract

Version: 2026-10-27. Target: dev. Keys below use server snake_case; the existing Angular ApiService camel-cases responses and snake-cases requests.

## Authorization

All new endpoints require an authenticated active account. Creation additionally requires Django permission `partner_programs.add_partnerprogram`, assigned through the existing user/group admin. An ordinary staff account or an existing program manager does not automatically receive creation permission. Django superuser semantics remain unchanged.

Program management, preview and publication use existing `can_manage_program`: program managers or staff/superuser. Removing creation permission does not remove existing program management access.

Drafts are excluded from the public catalog. Program-scoped routes return 404 to outsiders, including registration/news/solutions/published readers. Draft reads/hidden responses and management responses are private/no-store. Unsafe participant actions on a draft return 404 even for a manager. Existing authorized management/news editing remains available.

## Create and list

- `GET /programs/capabilities/` → `{ "can_create_program": true }`.
- `POST /programs/drafts/` accepts exactly `name` (trimmed, nonblank, max255), `format` (`case_championship|hackathon|noncompetitive`) and `idempotency_key` (UUID).
- New object: 201; same creator/key/input retry: 200 with the original object; reuse with different input: 409 `creation_key_reused`. Permission is checked before creation and again under the creator lock.
- Creator becomes a manager, without enrollment. Dates remain null. No emails or publication side effects occur.
- Competitive formats use the existing solution template/storage and opt in only the new program. Noncompetitive uses the existing noncompetitive legacy-project mode.
- `GET /programs/managed/?search=&limit=10&offset=0` → `{count,next,previous,results}`. Limit1–100, offset≥0, search≤255. Managers see their own objects; staff/superusers retain existing all-program management scope. Sort: newest first.

Summary object: `id`, `name`, `draft`, `program_format` (nullable for legacy), `solution_storage_mode`, `updated_at`, `datetime_started`, `datetime_finished`, `datetime_registration_ends` (dates nullable for draft).

Legacy `POST /programs/` also requires the explicit creation permission and assigns creator/manager. Its serializer payload remains compatible and model-default draft status is retained.

## Existing editors

Basic/dates/registration editing continues through existing management endpoints and optimistic-lock contracts. Draft dates can be partial/null; published programs reject null required dates. Migration0040 also enforces nonnull dates when `draft=false`.

Registration settings add `program_draft`. For a draft, `POST .../management/registration/publish/` validates/saves the questionnaire but leaves its public version unset. Angular labels this action “Сохранить анкету”. The program publication transaction opens both program and registration. For existing published programs, questionnaire publication behavior stays unchanged.

## Readiness

`GET /programs/{id}/management/launch/` returns:

- `program`: summary above;
- `revision`: SHA256 of saved launch-affecting state;
- `checks`: three `{code,title,section,ready,detail}` objects; codes `page|dates|registration`, sections `basic|dates|registration`;
- `blockers`: `{code,section,detail}` for unmet checks;
- `warnings`: optional work that does not prevent enrollment;
- `can_publish`: draft with no blockers;
- `links`: `{program,registration}`; registration null until publication.

Minimum: nonblank name/description; all3dates; finish after start; registration deadline in the future; saved valid registration schema. An empty additional questionnaire is valid because account requirements are handled by existing enrollment. External mode additionally requires administrator connection and a valid HTTP(S) URL. No new relative registration/start/finish cutoff is introduced.

URLs use existing `EXPERT_WORKSPACE_FRONTEND_URL`; set it to the dev frontend origin in dev. Native registration URL remains `/program-registration/{id}`. External registration uses the connected URL.

## Preview

`GET /programs/{id}/management/preview/` uses the existing participant detail representation, with `preview=true`, explicit draft status and `preview_widget` for the current empty participant state. It grants no participant permissions. It creates no enrollment/view/email, suppresses welcome/news/certificate side effects, and disables participant actions in Angular.

The preview questionnaire uses existing registration settings, saved `draft.fields` and the same `RegistrationPreviewContentComponent` as settings. Account fields are outside this existing preview dialog. Native controls/required marks/help/order/source selections are unchanged.

## First publication

`POST /programs/{id}/management/publish/` accepts `{ "revision": "64 lowercase hex characters" }`.

- Program and registration are locked in one transaction.
- Current permission, revision, dates and schema are rechecked.
- 409 `stale_program_launch` if saved launch state changed.
- 400 `{code:"program_not_ready",detail,blockers}` if requirements are unmet. Neither object is partially published.
- Success200 returns readiness state with `program.draft=false`, public links and `can_publish=false`.
- A retry after success returns current published state without incrementing questionnaire version again.

New competitive program details for registered participants add `solution_action_available` and `solution_action_blocked_reason`, using the existing canonical solution context. An existing solution remains accessible even if creation is disabled. Before form setup, `form_not_configured` disables creation and supplies a clear explanation. Form setup later enables the existing flow without another rollout command. Existing programs’ operator rollback remains effective.

## Migration and rollout

Apply migration0040 before deploying this API, then deploy Angular. Existing format/creator/key fields remain null; no inferred classification, fake dates or legacy-answer migration occurs. Published dates retain a DB constraint.

Safe operational rollback: revoke creation permission/hide new Angular entry, retain schema and API draft privacy. Do not reverse nullable fields while incomplete drafts exist, and do not restore the old publicly readable draft API over new draft data.

Verification and AC audit are in `docs/feature-specs/program-creation-publication.md`. Live dev acceptance follows API→Angular deployment and is separate from local real-API browser QA.
