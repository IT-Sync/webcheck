# TODO

Last updated: 2026-09-26

This file tracks unresolved work and technical debt. Completed work should be
removed or moved into the current-state sections of `PROJECT_MEMORY.md`; it
should not become a chronological changelog.

## Medium Priority

- Introduce one validated settings object instead of reading environment
  variables across module imports.
- Adopt versioned, forward-only database migrations after baselining the current
  production schema. Do not combine this with destructive schema changes.
- Replace the raw admin-token cookie with a short-lived signed session, set
  secure cookie attributes, and add CSRF protection while retaining a compatible
  operator login path for one release.
- Expand disposable PostgreSQL and aiohttp integration tests beyond repository
  transaction and pool coverage to include Mini App ownership checks, startup
  against old and current schemas, scheduler behavior,
  notification deduplication, feedback persistence, media proxying, album
  capture and reply delivery, retention boundaries and rollback, aggregation,
  and WebSocket-agent timeouts.
- Continue separating the remaining Telegram callbacks, scheduler monitoring
  flow, admin request handlers, and database query domains behind existing
  compatibility imports. Owner-only commands, scheduled reporting, the admin
  page shell, and base schema setup already have dedicated modules.
- Apply explicit timeouts and bounded concurrency to remaining synchronous or
  external lookup paths.

## Scaling Limitations

- Mini App manual-check locks are process-local. Before running multiple central
  application replicas, move deduplication to PostgreSQL or a distributed lock
  with a short lease.
- The remote-agent registry is process-local and assumes one central agent
  server instance.
- Network-check behavior exists in both `bot/checks/` and `agent/checks.py` and
  must be kept deliberately synchronized until a shared contract or test suite
  is introduced.

## Product Feature Backlog

These are planned capabilities, not implemented behavior. Team projects with
owner, viewer, and manager roles and Telegram deep-link invitations are implemented. Retention, hourly and
daily aggregation, selectable one-day, seven-day, and 30-day resource history,
groups, multiple tags, combined search/filtering, structured maintenance windows,
the searchable all-customer site registry, sortable administrative tables, and
the feedback inbox with media support and bot replies are implemented. The
current history includes availability, average and peak latency, a per-agent
regional breakdown, durable central incident intervals, acknowledgement,
configurable notification policies, bounded bulk operations, and deliberately
published status pages. Incident alerts create an auto-expiring one-hour
maintenance window. Suggested next delivery order is regional classification.

### High Priority

- [ ] Extend the implemented per-agent regional availability breakdown to show
  network/provider comparisons and automatically distinguish a global outage
  from a failure limited to one region.
- [ ] Turn the live agent heartbeat and result timestamps already shown in the
  admin console into durable monitoring-health alerts. Notify operators when
  agents disconnect, checks become overdue, or monitoring stops running, and
  include an independent watchdog for a stopped central process.
- [ ] Use the existing multi-agent alert checks for configurable incident
  confirmation. Agent results currently enrich notifications after the central
  threshold is reached; allow them to gate global outage alerts while retaining
  separately configurable regional alerts and defined unavailable-agent
  behavior.

### Medium Priority

- [ ] Content and API checks: validate expected HTTP status codes, required page
  text, or JSON values. Preserve public-target validation for new check paths.
- [ ] Build DNS change monitoring on the existing last-successful resolved-IP
  snapshot: detect and notify about IP, NS, and MX changes and retain both the
  previous and new values in event history instead of only overwriting the
  current IP.

### Later
