import unittest

from sanjeevani import nlu

MEDS = ["Metformin", "Aspirin"]


class NluTests(unittest.TestCase):
    def check(self, text, name, **kw):
        i = nlu.parse(text, MEDS)
        self.assertEqual(i.name, name, text)
        for k, v in kw.items():
            self.assertEqual(getattr(i, k), v, text)

    def test_taken(self):
        for s in ["I took my medicine", "taken", "मैंने दवा ले ली", "dawai kha li", "done"]:
            self.check(s, "taken")

    def test_negated_taken_is_not_taken(self):
        for s in ["I have not taken it yet", "haven't taken", "abhi nahi li", "मैंने नहीं ली"]:
            self.check(s, "snooze")

    def test_skip(self):
        for s in ["I don't want to take it", "skip this one", "nahi lunga", "मन नहीं है"]:
            self.check(s, "skip")

    def test_snooze_minutes(self):
        self.check("remind me in 20 minutes", "snooze", minutes=20)
        self.check("remind me later", "snooze", minutes=None)
        self.check("remind me in 1 minute", "snooze", minutes=5)  # clamped

    def test_next(self):
        for s in ["what's next", "which medicine now", "अगली दवा कौन सी है", "dawai kab leni hai"]:
            self.check(s, "next")

    def test_emergency_beats_everything(self):
        for s in ["I have chest pain and took my pill", "I can't breathe", "सीने में दर्द है", "I took too many"]:
            self.check(s, "emergency")

    def test_med_hint(self):
        self.check("I took the metformin", "taken", med_hint="Metformin")

    def test_add_med(self):
        i = nlu.parse("add paracetamol 500 mg at 8 am and 8:30 pm")
        self.assertEqual(i.name, "add_med")
        self.assertEqual(i.payload, {"name": "Paracetamol", "dose": "500 mg", "times": ["08:00", "20:30"]})

    def test_parse_times(self):
        self.assertEqual(nlu.parse_times("morning and night"), ["08:00", "21:00"])
        self.assertEqual(nlu.parse_times("12 am and 12 pm"), ["00:00", "12:00"])
        self.assertEqual(nlu.parse_times("25:00 and 13 pm"), [])

    def test_unknown(self):
        self.check("banana", "unknown")
        self.check("", "unknown")
