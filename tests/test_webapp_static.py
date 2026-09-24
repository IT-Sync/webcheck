import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "bot" / "webapp" / "server.py"
INDEX = ROOT / "bot" / "webapp" / "static" / "index.html"
SCRIPT = ROOT / "bot" / "webapp" / "static" / "app.js"


class WebAppStaticMarkupTest(unittest.TestCase):
    def test_dialog_close_button_bypasses_required_field_validation(self):
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn('id="close-add"', source)
        self.assertIn('value="cancel"', source)
        self.assertIn('type="submit"', source)
        self.assertIn("formnovalidate", source)

    def test_frontend_assets_have_cache_busting_version(self):
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn("/app/static/app.css?v=11", source)
        self.assertIn("/app/static/app.js?v=11", source)

    def test_status_metrics_are_filter_controls(self):
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn('data-filter="attention"', source)
        self.assertIn('id="sort-select"', source)
        self.assertIn('value="priority"', source)
        self.assertIn('id="site-search"', source)
        self.assertIn('id="group-select"', source)
        self.assertIn('id="tag-select"', source)

    def test_history_dialog_and_actions_are_available(self):
        markup = INDEX.read_text(encoding="utf-8")

        self.assertIn('id="history-dialog"', markup)
        self.assertIn('data-days="1"', markup)
        self.assertIn('data-days="7"', markup)
        self.assertIn('data-days="30"', markup)
        self.assertIn('id="history-latency-chart"', markup)
        self.assertIn('id="history-incidents"', markup)
        self.assertIn('data-action="history"', markup)
        self.assertIn('data-action="group"', markup)
        self.assertIn('data-action="tags"', markup)
        self.assertIn('data-action="maintenance"', markup)
        self.assertIn('id="maintenance-dialog"', markup)
        self.assertIn('id="history-maintenance"', markup)
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("history.summary.max_latency_ms", script)
        self.assertIn("historyDays: 7, historyRequest: 0,\n  };", script)
        self.assertIn("historyLatencyChart: document.querySelector", script)
        self.assertIn("historyIncidents: document.querySelector", script)
        self.assertIn("renderTags()", script)
        self.assertEqual(script.count("const groups ="), 1)
        self.assertIn("submitMaintenance", script)
        server = SERVER.read_text(encoding="utf-8")
        self.assertIn("set_site_tags_by_id", server)
        self.assertIn("create_site_maintenance", server)
        self.assertIn("cancel_site_maintenance", server)

    def test_project_controls_and_role_actions_are_available(self):
        markup = INDEX.read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8")
        server = SERVER.read_text(encoding="utf-8")
        for control in ('id="project-select"', 'id="site-project"',
                        'id="team-dialog"', 'id="team-member-form"'):
            self.assertIn(control, markup)
        self.assertIn('site.role === "viewer"', script)
        self.assertIn('project_id: Number(elements.siteProject.value)', script)
        self.assertIn('api/webapp/projects', script)
        self.assertIn('get_site_role(site[0], user.id)', server)
        self.assertIn('add_put("/api/webapp/projects/', server)

    def test_feedback_returns_the_user_to_the_bot(self):
        markup = INDEX.read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('id="open-feedback"', markup)
        self.assertIn('/api/webapp/feedback/start', script)
        self.assertIn('telegram?.close()', script)

    def test_direct_access_uses_a_separate_placeholder(self):
        markup = INDEX.read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('id="access-gate"', markup)
        self.assertIn('id="app-shell" hidden', markup)
        self.assertIn("if (!telegram?.initData)", script)
        self.assertIn("accessGate.hidden = false", script)
        self.assertLess(
            script.index("if (!telegram?.initData)"),
            script.index('fetch(path'),
        )


if __name__ == "__main__":
    unittest.main()
