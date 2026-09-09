# Legacy Project Analytics (B5)

`GET /programs/<program_id>/project-analytics/` is the manager-facing overview
for the legacy Angular `Project` flow. It is a semantic production port of DEV
#721 and #723, with the small assignment-completion rule from #724.

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

The endpoint reuses production `ProgramPermissionMixin`, `IsAuthenticated` and
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
    "projects_awaiting_evaluation": 0
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

## Scope

No models, migrations, lifecycle/permissions changes, case analytics, delayed
experts, projects-not-submitted objects, assignments/score drilldowns or
attention lists. B6 endpoints are intentionally absent. Foundation #732-#735,
production manager overview, frontend, dependencies and deployment are untouched.
