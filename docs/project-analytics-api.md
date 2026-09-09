# Legacy Project Analytics (B5 + B6a)

`GET /programs/<program_id>/project-analytics/` is the manager-facing overview
for the legacy Angular `Project` flow. It is a semantic production port of DEV
#721 and #723. B6a ports assignment drilldowns and delayed experts from DEV #724
into `/project-analytics/`, not the DEV `/manager-overview/` namespace.

## Two independent domains

The existing `/programs/<program_id>/manager-overview/` remains unchanged. It
reports production `Application`, `Team`, `Submission`,
`SubmissionExpertAssignment` and `Evaluation` data.

`/project-analytics/` uses only `PartnerProgramUserProfile`,
`PartnerProgramProject`, `Project`, `Collaborator`, `Expert.programs`,
`ProjectExpertAssignment`, `Criteria` and `ProjectScore`. Its view, serializer
and service are separate modules. It does not read production-domain tables.
Program registrations and expert membership are shared source populations;
creating an Application or Submission alone does not change legacy metrics.

## Access

All three endpoints reuse production `ProgramPermissionMixin`, `IsAuthenticated` and
`IsAdminOrManagerOfProgram`. A manager of the requested program, staff or
superuser can read it. Participant-only, expert-only and managers of other
programs receive 403; anonymous receives 401; an unknown program receives 404.
POST, PUT, PATCH and DELETE are not supported (405 for an authorized caller).
GET has no analytics/lifecycle writes. Standard HEAD/OPTIONS are supported.

## Response

Example with an empty program (the real `activity` array always has 30 entries):

```json
{
  "summary": {
    "participants": {"total": 0},
    "projects": {"total": 0},
    "experts": {"total": 0},
    "regions": {"total": 0, "items": []},
    "participant_regions": {"total": 0, "items": []}
  },
  "participant_funnel": {
    "registrations": 0,
    "unique_participants": 0,
    "with_team": 0,
    "project_creators": 0,
    "submitted_project_creators": 0
  },
  "solution_funnel": {
    "created": 0,
    "not_submitted": 0,
    "submitted": 0,
    "evaluated": 0
  },
  "evaluation_status": {
    "mode": "open",
    "max_evaluations_per_project": null,
    "assignments": {"total": 0, "pending": 0, "evaluated": 0},
    "projects": {
      "submitted": 0,
      "awaiting_evaluation": 0,
      "partially_evaluated": 0,
      "evaluated": 0
    }
  },
  "attention": {
    "participants_without_team": 0,
    "projects_awaiting_evaluation": 0,
    "delayed_experts": {"total": 0, "items": []}
  },
  "activity": [
    {"date": "2026-06-15", "registrations": 0, "submitted_solutions": 0}
  ]
}
```

`ProjectAnalyticsSerializer` validates nonnegative integer counters, `open` or
`distributed` mode, nullable integer maximum >= 1, region `{name, count}` items
and ISO dates. Validation and serialization execute no SQL.

## Populations and regions

- Participants: distinct non-null registered `user_id` in the requested program.
- Projects: number of `PartnerProgramProject` links in the requested program.
  One Project in A and B counts once in each program, with independent submitted
  state. The singular legacy program serializer is not used.
- Experts: distinct authoritative `Expert.programs` membership, including experts
  without assignments. Assignments are not the expert-population source.
- `regions`: `Project.region` through current-program links, distinct projects.
- `participant_regions`: `User.city` of the same registered-user population as
  participants, distinct user IDs.

Both region sets exclude null/empty/whitespace-only values and trim outer
whitespace (including tabs/newlines). SQL first counts distinct identities per
stored value; a bounded in-memory grouping merges the trimmed names. Each
identity has one stored region/city. Items are sorted by count descending, then
exact name; `total` is the number of resulting names, not the population sum.
There is no lowercasing, spelling correction, city-to-region mapping or data
migration. Legacy case/spelling variants remain separate.

## Funnels and attention

`participant_funnel.registrations` counts profile rows, including rows whose
user has been deleted. All other participant-funnel counters use distinct
non-null registered users in the current program.

`with_team` requires a leader or Collaborator relation to a Project linked to
this program. `profile.project` alone, production TeamMember or a team in a
different program does not qualify. `project_creators` counts registered
leaders; `submitted_project_creators` counts registered leaders with at least
one submitted current-program link. Multiple projects do not multiply users.

The solution funnel counts links, not users: all links are `created`, split
into `not_submitted` and `submitted` by raw `PartnerProgramProject.submitted`.
Only submitted links can be `evaluated`.

`participants_without_team` is unique participants minus `with_team`.
`projects_awaiting_evaluation` includes awaiting plus partially evaluated links.
These are counters only, without attention detail endpoints.

## Evaluation semantics

`max_evaluations_per_project` is raw `program.max_project_rates`: an optional
maximum limit, never a required evaluation target.

Open mode: one `ProjectScore` for the Project and a criterion of the current
program is enough to evaluate a submitted link. No assignment is required and
there is no partially-evaluated project state in open mode.

Distributed mode: only `ProjectExpertAssignment` rows of the current program
count. Completion uses the final DEV #724 rule (option B), not #721's earlier
first-score rule: the link must be submitted, the current criterion set must
be nonempty, and the assigned expert must have scores for **all** current
criteria. This includes the automatically created comment criterion. Adding
a criterion can make an assignment pending again. The rule counts score rows,
not truthiness/numeric values, and does not invent a lifecycle status.

- No assignments or no completed assignments: project awaits evaluation.
- Some but not all assignments complete: partially evaluated.
- All assignments complete: evaluated, even below the maximum assignment limit.

Scores for other programs, other projects or another assigned expert do not
complete an assignment. Assignments for unsubmitted links or with zero criteria
remain pending. `evaluation_status.assignments` reports this completion rule
in both modes; open-mode project status still uses its independent first-score
rule. No production `Evaluation` objects enter these computations.

## Activity and SQL

`activity` contains every local calendar day from today minus 29 days through
today, ascending, including zero days. Registrations use profile
`datetime_created`; submitted solutions use submitted links with
`datetime_submitted`. Null submission timestamps, future/out-of-window events
and other programs are excluded. Filtering and grouping use Django's active
timezone/local-date semantics.

The service uses eight SELECTs with correlated subqueries and aggregates,
without per-participant/project/assignment queries. The manager HTTP endpoint
uses ten queries including production access checks. Regression fixtures with
0, 1 and 31 participants/projects/regions/assignments have the same query count
in open and distributed modes. Returned region cardinality and in-memory row
processing can still grow with program size; fixed SQL count does not mean
constant memory or database work.

Assignment rows are loaded **once** per overview. The shared read-only
`services/project_assignment_analytics.py` builder supplies statuses for the
overview counters, by-project completion and delayed experts. B5 has no second
completion algorithm or duplicate assignment SELECT. Regions, funnels, activity
and the existing attention counters keep their B5 semantics.

## Assignment list

`GET /programs/<program_id>/project-analytics/assignments/`

Returns a JSON array of real legacy `ProjectExpertAssignment` rows, ordered by
assignment PK, in both open and distributed modes. There is no pagination or
synthetic assignment generation.

- `scope=all` (default): all assignments.
- `scope=completed`: only `status == "completed"`.
- `scope=pending`: every noncompleted assignment, including `not_ready`,
  `pending` and `in_progress`.
- Empty or unsupported scope: 400.

```json
{
  "assignment_id": 10,
  "expert": {
    "expert_id": 4, "user_id": 15,
    "first_name": "Ivan", "last_name": "Ivanov", "full_name": "Ivan Ivanov",
    "avatar": null
  },
  "project": {"id": 42, "name": "Project"},
  "status": "in_progress",
  "criteria_total": 5,
  "criteria_scored": 2,
  "assigned_at": "2026-09-01T12:00:00Z",
  "project_submitted": true,
  "project_submitted_at": "2026-09-02T12:00:00Z",
  "waiting_since": "2026-09-02T12:00:00Z",
  "waiting_seconds": 172800
}
```

`not_ready` means the current-program link is not submitted. `completed` uses
the shared B5 rule: submitted, nonempty current criteria, all criteria scored
by the assigned expert's **user ID** for this Project. `in_progress` means at
least one but not all current criteria scored; otherwise a submitted assignment
is `pending`, including zero criteria. Adding a criterion can make a previously
completed assignment incomplete. No new lifecycle semantics are introduced.

Only the six listed expert fields and project ID/name are exposed, without
full User/Project serializers, email, phone, auth data or personal forms.

## Assignment scores

`GET /programs/<program_id>/project-analytics/assignments/<assignment_id>/scores/`

Returns the same assignment object with a `scores` array containing **all**
current-program criteria in criterion-PK order:

```json
{
  "criterion_id": 7, "name": "Quality", "description": null, "type": "int",
  "min_value": 0, "max_value": 10, "value": null, "is_scored": false
}
```

A missing score is `value=null, is_scored=false`. An existing score retains
its exact string/null value and has `is_scored=true`, including blank strings,
whitespace and null. There is no numeric conversion, trimming or averaging.
Scores of another expert, Project or program cannot affect progress or values.
Unknown or foreign-program assignment IDs return 404, even for a manager of
both programs. Lookup is scoped before resolving the assignment ID.

For a Project linked to A and B, each endpoint uses its own program's link,
submission state/timestamp, criteria, scores and assignments. The singular
legacy project program serializer is not consulted.

## Waiting and delayed experts

Waiting is defined only for incomplete submitted assignments with a real
`PartnerProgramProject.datetime_submitted`. Its start is the later of that
timestamp and `ProjectExpertAssignment.datetime_created`; seconds are measured
against one timezone-aware `now` and clamped to zero. Completed/not-ready rows
have null waiting fields. Historical `submitted=true` with a missing timestamp
also has null waiting fields: timestamps are never inferred or written.

`attention.delayed_experts` is additive to B5. In **open** mode it is always
`{"total": 0, "items": []}` even when real legacy assignments exist. Open-mode
project evaluation continues to depend on the first current-program score.

In **distributed** mode, each item includes the six safe expert fields above
plus `assignments_total`, `completed`, `pending`, `overdue_24h`, `overdue_48h`,
`oldest_waiting_since`, `oldest_waiting_seconds` and `severity`:

- `critical`: at least one incomplete assignment waiting **>= 48 hours**.
- Otherwise `warning`: at least two incomplete assignments waiting **>= 24 hours**.
- Otherwise the expert is omitted.

Totals include all real assignments; `pending` includes every noncompleted
status. Completed, not-ready and missing-timestamp rows contribute no waiting
SLA. Items sort critical first, then oldest waiting seconds descending, then
expert ID ascending. All counts and seconds are nonnegative; assignment waiting
fields are nullable. Serializers have strict status/severity choices and no SQL.

SQL budgets (manager requests): list **3**, scores **5**, overview **10**.
List/overview counts are unchanged for 1 versus 31 assignments; scores are
unchanged for 1 versus 20 criteria. The overview service remains **8 SELECTs**.
Delayed aggregation and serialization add no queries.

## Scope

No models, migrations, scoring writes, deadline or lifecycle/permission changes.
No B6b attention-list endpoints, projects-not-submitted object or case analytics.
Foundation #732-#735, production `/manager-overview/`, `/submission-assignments/`
and `/evaluations/`, frontend, dependencies and deployment remain untouched.
Production Application/Team/Submission/SubmissionExpertAssignment/Evaluation
records do not enter legacy assignment analytics; legacy assignments/scores
likewise do not affect those production APIs.
