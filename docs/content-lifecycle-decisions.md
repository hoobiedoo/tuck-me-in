# Content Lifecycle & Family Contribution — Decisions

Working record of the architecture decisions for the recording review/release system
(draft → published → released → withdrawn). Companion to `docs/design-document.md`;
this file exists so the reasoning behind these choices survives past the conversation
that produced them.

## Scope

Implementing backend (CDK + Lambda) and the mobile app screens together in one pass:
contributor draft/publish controls, a parent review-queue screen, and an auto-release
settings screen. No changes to child-facing playback (the child has no app UI today —
playback is voice-assistant only) and no changes to subscription billing.

## Core model decision: status splits into two layers

Auto-release is granted **per (contributor, child)** pair. That means a single publish
event can legally leave one child's copy released while another child's copy is still
awaiting manual review (e.g. Grandma is auto-trusted for the 9-year-old, not the
4-year-old). A single flat `lifecycleStatus` field can't represent both states at once.

Resolution:
- `Stories.contributorStatus`: `draft | published | withdrawn` — the contributor-facing
  lifecycle only.
- `Stories.assignments[]`: embedded list, one entry per child once a release decision
  (manual or auto) has been made — `{ childId, assignedAt, releasedAt, releasedBy }`.
  An assignment's existence *is* "released for that child" — there is no
  half-created/pending assignment state, since assignment and release happen atomically
  together (a child is only ever attached to a recording at the moment it's released to
  them).
- `withdrawnAt` is one-way. Unpublish never reverts a recording to `draft`, and applies
  globally across every assignment regardless of per-child release state.

Embedded list, not a new table: assignment counts per recording are small (a handful of
children), so this avoids a new table + GSI for something that never needs independent
querying at the current scale.

## Decisions confirmed 2026-08-22

| Question | Decision | Why |
|---|---|---|
| Build scope | Backend **and** mobile app screens in this pass | End-to-end in one PR rather than a backend-only stub |
| Push notification infra | **Defer.** Use foreground/resume polling against a `contentVersion` counter; publish/withdraw notifications go out through the existing (currently unwired) SNS-topic pattern | No push infra (Expo tokens, SNS platform application) exists anywhere in the app yet — building it is a real separate lift, not something to fold into this feature |
| `Users.role` naming | Keep the stored value `"member"` — do not rename to `"contributor"` | No migration needed; "contributor" is UI/doc language layered on the existing value, not a new access mechanism |

## Other design choices (not asked as questions, applied by default)

- **Contributor access**: reuse the existing household invite-code join flow and
  `member` role rather than building a second, accountless auth path — a contributor
  needs an authenticated API call to upload audio either way, so an account was never
  avoidable, and a parallel auth path would conflict with "all endpoints require
  Cognito" from `CLAUDE.md`.
- **"New" badge for unseen releases**: tracked client-side only (diff the fetched
  content list against a locally cached set of seen story IDs). No server-side
  seen/unseen table. Trade-off: badge state doesn't sync across two devices for the
  same child — acceptable given the actual usage pattern (one shared tablet per child).
- **Notification persistence**: only the "published" event needs anything persisted
  (`PendingPublishNotifications`, for the 5–10 minute digest batching window).
  "Released" sends no notification at all (per spec — it's a silent badge flip).
  "Withdrawn" publishes directly through the same SNS pattern `story_ready_topic`
  already uses, no database write first. Not building a general notification
  audit-log table until something actually needs to read history back.
- **No new GSI** for "recordings assigned to child X" — household-scoped query +
  in-Lambda filter, same pattern `list_stories` already uses for pipeline `status`.
- **Revoked contributor**: their already-published/released recordings are left as-is;
  only their ability to publish *new* recordings is revoked. Revoking an auto-release
  grant is likewise not retroactive.
- **Child profile deleted**: only that child's entry is dropped from the recording's
  `assignments[]`; the recording itself and any other child's assignment is untouched.
- **Pre-existing gap fixed alongside this work**: `PUT /households/{id}` had no
  `role == admin` check. Since "contributors don't get parent settings" is a hard
  requirement here, this is being closed as part of this change rather than left as a
  hole next to new access control.

## New/changed data model summary

| Entity | Change |
|---|---|
| `Stories` | + `contributorStatus`, `publishedAt`, `withdrawnAt`, `assignments[]` |
| `Households` | + `contentVersion` (bumped on every unpublish) |
| `AutoReleaseGrants` | **New table.** PK `contributorId`, SK `childId`, GSI `byChild`. Sparse — a row only exists when the grant is ON. |
| `PendingPublishNotifications` | **New table.** PK `householdId`, SK `windowStartedAt`. Batches publish events into one digest per household every 5–10 min. |

## New endpoints

- `PUT /stories/{id}/publish` — contributor only, must be the recording's own reader
- `PUT /stories/{id}/release` — admin only, body `{ childIds }`
- `PUT /stories/{id}/unpublish` — admin only, works from published or released
- `GET/PUT /households/{id}/auto-release` — admin only, manages `AutoReleaseGrants`
