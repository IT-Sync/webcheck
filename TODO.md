# TODO

Last updated: 2026-09-23

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
- Continue separating large Telegram, scheduler, admin, and database modules
  behind existing compatibility imports.
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

These are planned capabilities, not implemented behavior. Retention,
hourly and daily aggregation, selectable one-day, seven-day, and 30-day resource
history, groups, search, the searchable all-customer site registry, sortable
administrative tables, and the feedback inbox with media support and bot replies
are implemented. The current history includes availability, average and peak
latency, a per-agent regional breakdown, and durable central incident intervals.
Incident alerts also provide an auto-expiring one-hour pause. Suggested next
delivery order is full maintenance windows, then public status pages.

### High Priority

- [ ] Add multiple tags per resource alongside the implemented single group,
  search, and group filter.
- [ ] Generalize the implemented immediate one-hour incident pause into full
  maintenance windows with scheduled starts, arbitrary duration, and automatic
  expiry. Make monitoring behavior during maintenance explicit and distinguish
  planned maintenance from outages in history and reports.
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
- [ ] Incident acknowledgement: add a "Take ownership" action, track the
  responder and acknowledgement time, and coordinate incident handling with
  notification reminders and future team permissions.

### Medium Priority

- [ ] Make the existing global notification rules configurable per user or
  resource: select event types, configure repeat reminders, and notify about
  prolonged outages. Apply acknowledgement and maintenance rules consistently
  to avoid duplicate or unwanted notifications.
- [ ] Bulk operations: add resources from a list, assign groups, and pause or
  resume selected sites. Preserve ownership checks, limits, validation, and
  per-resource feedback for partial failures.
- [ ] Public status pages: publish an explicitly selected subset of services
  with current availability and operator-written incident updates. Require
  deliberate publication and keep private monitoring details out of public views.
- [ ] Content and API checks: validate expected HTTP status codes, required page
  text, or JSON values. Preserve public-target validation for new check paths.
- [ ] Build DNS change monitoring on the existing last-successful resolved-IP
  snapshot: detect and notify about IP, NS, and MX changes and retain both the
  previous and new values in event history instead of only overwriting the
  current IP.

### Later

- [ ] Team access: support multiple project members with viewer and manager
  roles. Introduce explicit project ownership and permissions while preserving
  access to existing personal resources.
