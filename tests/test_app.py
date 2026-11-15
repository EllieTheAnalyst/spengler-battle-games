"""Frontend regression tests: python -m unittest discover -s tests -p test_app.py -v."""

from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app" / "app.py"
PLAYER_A = "mock-davos-18"
PLAYER_B = "mock-selects-23"


class FrontendFlowTests(unittest.TestCase):
    def new_app(self):
        app = AppTest.from_file(str(APP)).run()
        self.assertFalse(app.exception)
        app.button(key="enter-battle-next").click().run()
        return app

    def visible_content(self, app):
        # Exclude stylesheet Markdown, but include raw HTML fan bars and tables.
        markdown = [item.value for item in app.markdown if "<style>" not in item.value]
        return "\n".join(markdown + [item.proto.body for item in app.get("html")])

    def assert_no_fan_results(self, app):
        content = self.visible_content(app)
        for text in ("fans agree", "reveal-fan-bar", "62%", "38%", "VOTE LOCKED IN"):
            self.assertNotIn(text, content)

    def confirm_pick(self, app, player_id):
        app.button(key=f"select-{player_id}").click().run()
        app.button(key="statistics-continue").click().run()
        app.button(key="lock-in-vote").click().run()

    def test_both_picks_review_statistics_before_confirmation(self):
        for player_id, name, agreement in ((PLAYER_A, "Mock Player A", 62),
                                           (PLAYER_B, "Mock Player B", 38)):
            with self.subTest(player=player_id):
                app = self.new_app()
                app.button(key=f"select-{player_id}").click().run()
                self.assertEqual(app.session_state["screen"], "statistics")
                self.assertEqual(app.title[0].value, "PLAYER STATISTICS")
                self.assertIsNone(app.session_state["mock_vote"])
                self.assertIn(name, self.visible_content(app))
                self.assert_no_fan_results(app)
                self.assertNotIn("lock-in-vote", [button.key for button in app.button])
                table = next(item.proto.body for item in app.get("html")
                             if item.proto.body.startswith("<table>"))
                rows = ET.fromstring(table).findall("./tbody/tr")
                self.assertEqual(len(rows), 5)
                self.assertEqual([["".join(cell.itertext()) for cell in row.findall("td")]
                                  for row in rows],
                                 [["0.80", "0.50"], ["5", "6"], ["60%", "67%"],
                                  ["8", "4"], ["3", "4"]])
                app.run()
                self.assertIsNone(app.session_state["mock_vote"])
                app.button(key="statistics-continue").click().run()
                self.assertEqual(app.title[0].value, "Still sure?")
                self.assertIn("Keep your pick, or switch.", self.visible_content(app))
                self.assertIsNone(app.session_state["mock_vote"])
                self.assert_no_fan_results(app)
                app.button(key="lock-in-vote").click().run()
                self.assertEqual(app.title[0].value, "RESULTS")
                self.assertEqual(app.session_state["mock_vote"],
                                 {"player_id": player_id, "is_mock": True})
                self.assertIn(f"{agreement}% of fans agree", self.visible_content(app))
                self.assertFalse(app.exception)

    def test_change_pick_after_statistics_and_confirmation(self):
        for change_at in ("statistics", "confirmation"):
            with self.subTest(change_at=change_at):
                app = self.new_app()
                app.button(key=f"select-{PLAYER_A}").click().run()
                if change_at == "confirmation":
                    app.button(key="statistics-continue").click().run()
                key = "statistics-change-pick" if change_at == "statistics" else "change-pick"
                app.button(key=key).click().run()
                self.assertEqual(app.session_state["screen"], "choose")
                self.assertEqual(app.session_state["selected_player_id"], PLAYER_A)
                self.assertIn("✓", app.button(key=f"select-{PLAYER_A}").label)
                app.button(key=f"select-{PLAYER_B}").click().run()
                self.assertEqual(app.session_state["screen"], "statistics")
                self.assertEqual(app.session_state["selected_player_id"], PLAYER_B)
                self.assertIsNone(app.session_state["mock_vote"])
                self.assert_no_fan_results(app)
                app.button(key="statistics-continue").click().run()
                app.button(key="lock-in-vote").click().run()
                self.assertEqual(app.session_state["mock_vote"]["player_id"], PLAYER_B)
                self.assertFalse(app.exception)

    def test_results_reject_missing_or_invalid_votes(self):
        for vote in (None, {}, {"player_id": "unknown"}):
            with self.subTest(vote=vote):
                app = self.new_app()
                app.session_state["selected_player_id"] = PLAYER_A
                app.session_state["mock_vote"] = vote
                app.session_state["screen"] = "reveal"
                app.run()
                self.assertFalse(app.title)
                self.assert_no_fan_results(app)
                self.assertNotIn("<table>", self.visible_content(app))
                app.button[0].click().run()
                self.assertEqual(app.session_state["screen"], "choose")
                self.assertFalse(app.exception)

    def test_statistics_and_confirmation_require_valid_pick(self):
        for screen in ("statistics", "hold_to_vote"):
            for pick in (None, "unknown"):
                with self.subTest(screen=screen, pick=pick):
                    app = self.new_app()
                    app.session_state["selected_player_id"] = pick
                    app.session_state["screen"] = screen
                    app.run()
                    keys = [button.key for button in app.button]
                    self.assertNotIn("statistics-continue", keys)
                    self.assertNotIn("lock-in-vote", keys)
                    self.assertIsNone(app.session_state["mock_vote"])
                    self.assert_no_fan_results(app)
                    self.assertFalse(app.exception)

    def test_home_previous_results_and_explicit_restart(self):
        app = self.new_app()
        self.confirm_pick(app, PLAYER_A)
        vote = app.session_state["mock_vote"].copy()
        app.button(key="reveal-home-button").click().run()
        self.assertEqual(app.session_state["screen"], "enter")
        self.assertEqual(app.session_state["mock_vote"], vote)
        app.button(key="view-previous-results").click().run()
        self.assertEqual(app.session_state["screen"], "reveal")
        app.button(key="reveal-home-button").click().run()
        app.button(key="start-new-demo").click().run()
        self.assertEqual(app.session_state["screen"], "choose")
        self.assertIsNone(app.session_state["mock_vote"])
        self.assertIsNone(app.session_state["selected_player_id"])
        self.confirm_pick(app, PLAYER_B)
        self.assertEqual(app.session_state["mock_vote"]["player_id"], PLAYER_B)
        self.assertFalse(app.exception)

    def test_locked_vote_redirects_pre_vote_screens_and_uses_recorded_pick(self):
        app = self.new_app()
        self.confirm_pick(app, PLAYER_A)
        vote = app.session_state["mock_vote"].copy()
        for screen in ("statistics", "hold_to_vote"):
            app.session_state["screen"] = screen
            app.session_state["selected_player_id"] = PLAYER_B
            app.run()
            self.assertEqual(app.session_state["screen"], "reveal")
            self.assertEqual(app.session_state["mock_vote"], vote)
            self.assertIn("Your pick: **Mock Player A", self.visible_content(app))
            self.assertFalse(app.exception)

    def test_confirmation_callback_rejects_wrong_stage_and_duplicate_votes(self):
        module = runpy.run_path(str(APP), run_name="frontend_test")
        state = SimpleNamespace(screen="statistics", selected_player_id=PLAYER_A, mock_vote=None)
        with patch.object(module["st"], "session_state", state):
            module["confirm_mock_vote"]()
            self.assertIsNone(state.mock_vote)
            state.screen = "hold_to_vote"
            state.selected_player_id = "unknown"
            module["confirm_mock_vote"]()
            self.assertIsNone(state.mock_vote)
            state.selected_player_id = PLAYER_A
            module["confirm_mock_vote"]()
            vote = state.mock_vote
            state.selected_player_id = PLAYER_B
            module["confirm_mock_vote"]()
            self.assertIs(state.mock_vote, vote)
            module["select_player"](PLAYER_B)
            self.assertIs(state.mock_vote, vote)
            self.assertEqual(state.screen, "reveal")


if __name__ == "__main__":
    unittest.main()
