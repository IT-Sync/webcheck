"""Pure notification timing rules shared by scheduled delivery flows."""


def reminder_kind(now, incident, preferences, last_alert_at):
    """Return the one reminder due now; acknowledgement always wins."""
    if not incident or incident.get("acknowledged_at"):
        return None
    elapsed = (now - incident["started_at"]).total_seconds() / 60
    if (preferences["prolonged_minutes"] and
            elapsed >= preferences["prolonged_minutes"] and
            not incident.get("prolonged_notified_at")):
        return "prolonged"
    baseline = incident.get("last_reminder_at") or last_alert_at
    if (preferences["repeat_minutes"] and baseline and
            (now - baseline).total_seconds() >= preferences["repeat_minutes"] * 60):
        return "repeat"
    return None
