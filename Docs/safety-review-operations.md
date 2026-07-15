# Safety Review Operations

## Boundary

Safety review is asynchronous and is not emergency support, continuous monitoring, medical clearance, or authority to change a training plan. Technical readiness does not prove human staffing, coverage, or a response-time guarantee.

## Enablement Blockers

All fields below must be completed and independently approved before changing any production safety flag from `false`:

- Incident owner: `UNASSIGNED`
- Named trained reviewers: `UNASSIGNED`
- Actual coverage window and timezone: `UNCONFIRMED`
- Queue/access observation owner: `UNASSIGNED`
- Observation cadence: `UNCONFIRMED`
- Controlled athlete audience IDs approved: `NONE`
- Kill-switch drill timestamp and evidence: `NOT RUN`
- Rollback decision owner: `UNASSIGNED`

Any `UNASSIGNED`, `UNCONFIRMED`, `NONE`, or `NOT RUN` value blocks enablement.

## Provisioning

Run inside the backend container after verifying the exact non-demo user ID:

```bash
python -m app.workers.safety_reviewer_admin reviewer grant USER_ID --confirm GRANT
python -m app.workers.safety_reviewer_admin audience add USER_ID --confirm ENROLL
```

Reviewer and audience identities are independent. Neither command changes rollout flags.

## Observation

```bash
python -m app.workers.safety_reviewer_admin status --access-hours 24 --format json
```

The report contains aggregate persisted facts only: grants, enrollments, queue count/age buckets, and access-event counts. It must not be interpreted as presence, staffing, monitoring, coverage, or SLA evidence.

## Stop Criteria

Immediately close rollout when any of these occurs:

- reviewer access is observed after consent, audience, case, or grant revocation;
- an identity, contact, profile, check-in, activity, chat, raw health field, or plan data appears in reviewer context or operational status;
- self-review succeeds;
- lifecycle/event mismatch, repeated server errors, or unexplained queue/access-ledger divergence appears;
- the named incident owner or observation owner becomes unavailable;
- actual coverage no longer matches the approved controlled window.

## Kill Switch

Set all three values to `false` and redeploy immutable images/config:

```text
RUNFORFAN_SAFETY_ESCALATION_ENABLED=false
RUNFORFAN_SAFETY_REVIEW_ENABLED=false
RUNFORFAN_SAFETY_REVIEW_REVIEWER_API_ENABLED=false
```

Verify:

1. Athlete review state reports `available=false`.
2. Reviewer capability and queue are unavailable.
3. Existing deterministic readiness safety rules still operate.
4. No pending request can be claimed or viewed.
5. Record the drill/deactivation timestamp and deployment run URL in the approved incident system.

## Revocation

```bash
python -m app.workers.safety_reviewer_admin reviewer revoke USER_ID --confirm REVOKE
python -m app.workers.safety_reviewer_admin audience revoke USER_ID --confirm REVOKE
```

Reviewer revoke returns active claims to the opaque queue. Audience revoke closes active requests and reviewer access. Both grants are terminal for that identity.
