import unittest
from datetime import datetime, timedelta

from sanjeevani.llm import LLMClient, facts_preserved
from tests.helpers import RecordingNotifier, make

D = datetime(2026, 10, 8)


def at(h, m=0):
    return D.replace(hour=h, minute=m)


class FlowTests(unittest.TestCase):
    def test_taken_marks_all_due_and_announces_next(self):
        c, pid = make()
        r = c.handle_utterance(pid, "I took my medicine", now=at(8, 5))
        self.assertEqual(r["intent"], "taken")
        self.assertIn("Metformin 500 mg and Aspirin 75 mg", r["reply"])
        self.assertIn("Metformin at 8:00 PM", r["reply"])
        self.assertTrue(all(d["status"] == "taken" for d in c.today(pid, at(8, 6))["doses"] if d["time_label"] == "8:00 AM"))

    def test_nothing_due_early_morning(self):
        c, pid = make()
        r = c.handle_utterance(pid, "I took my medicine", now=at(7, 5))
        self.assertIn("don't see any dose due", r["reply"])
        self.assertFalse(r["actions"])

    def test_double_dose_guard_by_voice(self):
        c, pid = make()
        c.handle_utterance(pid, "I took Metformin", now=at(8, 5))
        r = c.handle_utterance(pid, "I took Metformin again", now=at(8, 30))
        self.assertEqual(r["intent"], "guard")
        self.assertIn("already took Metformin at 8:05 AM", r["reply"])

    def test_double_dose_guard_by_api_and_force(self):
        c, pid = make()
        eve = [d for d in c.today(pid, at(8, 5))["doses"] if d["time_label"] == "8:00 PM"][0]
        morning = [d for d in c.today(pid, at(8, 5))["doses"] if d["med_name"] == "Metformin"][0]
        self.assertTrue(c.take(morning["id"], at(8, 5))["ok"])
        # evening dose taken 'at 8:10 AM' is both too early and too soon
        r = c.take(eve["id"], at(8, 10))
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "too_soon")
        self.assertTrue(c.take(eve["id"], at(8, 10), force=True)["ok"])

    def test_too_early_guard(self):
        c, pid = make()
        eve = [d for d in c.today(pid, at(8, 5))["doses"] if d["time_label"] == "8:00 PM"][0]
        self.assertEqual(c.take(eve["id"], at(9, 0))["reason"], "too_early")

    def test_snooze_hides_reminder_but_taken_still_works(self):
        c, pid = make()
        c.handle_utterance(pid, "remind me in 10 minutes", now=at(8, 0))
        self.assertEqual(c.today(pid, at(8, 5))["due_count"], 0)
        self.assertEqual(c.today(pid, at(8, 11))["due_count"], 2)
        c.handle_utterance(pid, "remind me in 10 minutes", now=at(8, 0))
        r = c.handle_utterance(pid, "taken", now=at(8, 3))
        self.assertEqual(r["intent"], "taken")
        self.assertIn("Metformin", r["reply"])

    def test_skip_alerts_caregiver(self):
        c, pid = make()
        c.handle_utterance(pid, "I don't want to take it", now=at(8, 5))
        self.assertEqual([a["kind"] for a in c.alerts(pid)], ["skipped_dose", "skipped_dose"])

    def test_emergency_alerts_and_advises(self):
        n = RecordingNotifier()
        c, pid = make(n)
        r = c.handle_utterance(pid, "I have chest pain", now=at(8, 5))
        self.assertIn("call 112", r["reply"])
        c.tick(at(8, 5))
        self.assertTrue(any(a["kind"] == "emergency" for a, _ in n.sent))

    def test_hindi_reply(self):
        c, pid = make()
        r = c.handle_utterance(pid, "मैंने दवा ले ली", now=at(8, 5), lang="hi")
        self.assertIn("बहुत अच्छा", r["reply"])
        self.assertIn("शाम 8:00 बजे", r["reply"])

    def test_add_medication_by_voice(self):
        c, pid = make()
        r = c.handle_utterance(pid, "add vitamin c 500 mg at 9 am", now=at(7, 0))
        self.assertEqual(r["intent"], "add_med")
        self.assertIn("Vitamin C", [m["name"] for m in c.list_medications(pid)])

    def test_validation(self):
        c, pid = make()
        for bad in ([], ["8am"], ["25:00"], ["08:00"] * 0):
            with self.assertRaises(ValueError):
                c.add_medication(pid, "X", bad)
        with self.assertRaises(ValueError):
            c.add_medication(pid, "  ", ["08:00"])
        with self.assertRaises(LookupError):
            c.get_patient(999)

    def test_new_medicine_does_not_backfill_earlier_today(self):
        c, pid = make()
        c.add_medication(pid, "Zinc", ["06:00", "21:00"], now=at(15))
        zinc = [d for d in c.today(pid, at(15, 1))["doses"] if d["med_name"] == "Zinc"]
        self.assertEqual([d["time_label"] for d in zinc], ["9:00 PM"])

    def test_default_gap_is_half_the_shortest_interval(self):
        c, pid = make()
        m = c.add_medication(pid, "Antibiotic", ["06:00", "12:00", "18:00", "00:00"], now=at(1))
        self.assertEqual(m["min_gap_hours"], 3.0)
        m2 = c.add_medication(pid, "Quick", ["08:00", "09:00"], now=at(1))
        self.assertEqual(m2["min_gap_hours"], 0.5)


class EscalationTests(unittest.TestCase):
    def test_late_then_missed_alerts_once_each(self):
        n = RecordingNotifier()
        c, pid = make(n)
        c.tick(at(8, 20))
        self.assertEqual(len(n.sent), 0)
        c.tick(at(8, 50))  # 50 min late -> level 1 for both 08:00 doses
        c.tick(at(8, 55))
        self.assertEqual([a["kind"] for a, _ in n.sent], ["late_dose", "late_dose"])
        c.tick(at(11, 5))  # 185 min -> missed
        c.tick(at(11, 10))
        kinds = [a["kind"] for a, _ in n.sent]
        self.assertEqual(kinds.count("missed_dose"), 2)
        self.assertEqual(len(kinds), 4)
        statuses = {d["status"] for d in c.today(pid, at(11, 10))["doses"] if d["time_label"] == "8:00 AM"}
        self.assertEqual(statuses, {"missed"})

    def test_taken_dose_never_alerts(self):
        n = RecordingNotifier()
        c, pid = make(n)
        c.handle_utterance(pid, "taken", now=at(8, 5))
        c.tick(at(9, 30))
        self.assertEqual(n.sent, [])

    def test_failed_delivery_is_retried_then_capped(self):
        n = RecordingNotifier(ok=False)
        c, pid = make(n)
        c.handle_utterance(pid, "chest pain", now=at(8, 5))
        for _ in range(8):
            c.tick(at(8, 6))
        self.assertEqual(len(n.sent), 5)


class InsightTests(unittest.TestCase):
    def test_adherence_numbers_and_streak(self):
        c, pid = make()
        c.db.execute("UPDATE medications SET created_at='2026-10-01T00:00'")
        for back in (3, 2, 1):  # Oct 5, 6, 7: fully taken
            c.ensure_events(pid, (D - timedelta(days=back)).date())
        c.db.execute("UPDATE dose_events SET status='taken' WHERE scheduled_for < '2026-10-08'")
        ins = c.insights(pid, 7, now=at(8, 30))  # today's 08:00 doses are still inside their window
        self.assertEqual(ins["streak_days"], 3)
        self.assertEqual(ins["overall_rate"], 1.0)

    def test_pending_inside_window_is_not_judged(self):
        c, pid = make()
        c.today(pid, at(8, 5))
        ins = c.insights(pid, 1, now=at(8, 30))
        self.assertIsNone(ins["overall_rate"])

    def test_old_pending_counts_as_missed(self):
        c, pid = make()
        c.today(pid, at(8, 5))
        ins = c.insights(pid, 1, now=at(12, 0))
        self.assertEqual(ins["missed"], 2)
        self.assertEqual(ins["worst_slot"], "08:00")


class LlmGuardTests(unittest.TestCase):
    def test_rewrite_must_keep_facts(self):
        o = "Your next medicine is Metformin at 8:00 PM."
        self.assertTrue(facts_preserved(o, "Remember Metformin at 8:00 PM, dear.", ("Metformin",)))
        self.assertFalse(facts_preserved(o, "Take Metformin at 9:00 PM.", ("Metformin",)))
        self.assertFalse(facts_preserved(o, "Take it at 8:00 PM.", ("Metformin",)))

    def test_falls_back_on_error_and_on_bad_rewrite(self):
        class Boom(LLMClient):
            def _complete(self, text): raise OSError("offline")

        class Bad(LLMClient):
            def _complete(self, text): return "Take double the dose."

        o = "Your next medicine is Metformin at 8:00 PM."
        self.assertEqual(Boom("k").warm(o, ("Metformin",)), o)
        self.assertEqual(Bad("k").warm(o, ("Metformin",)), o)
        self.assertEqual(LLMClient("").warm(o), o)

    def test_llm_is_never_used_for_safety_replies(self):
        class Spy(LLMClient):
            calls = 0
            def _complete(self, text):
                Spy.calls += 1
                return text

        c, pid = make()
        c.llm = Spy("k")
        c.handle_utterance(pid, "chest pain", now=at(8, 5))
        c.handle_utterance(pid, "I don't want to take it", now=at(8, 5))
        self.assertEqual(Spy.calls, 0)
        c.handle_utterance(pid, "what's next", now=at(8, 5))
        self.assertEqual(Spy.calls, 1)


if __name__ == "__main__":
    unittest.main()
