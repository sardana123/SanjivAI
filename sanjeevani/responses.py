"""Reply templates (English / Hindi). Every string is deterministic and fact-checked by tests."""
from __future__ import annotations

T: dict[str, dict[str, str]] = {
    "en": {
        "taken": "Well done, {name}. I've recorded {meds} as taken.{next}",
        "next_suffix": " Your next medicine is {med} at {time}.",
        "nothing_due": "I don't see any dose due right now.{next}",
        "too_soon": (
            "Please wait, {name}. You already took {med} at {time}, and taking it again so soon "
            "may be unsafe. I have not recorded anything. If you are unsure, please call {caregiver}."
        ),
        "next": "Your next medicine is {med} {dose} at {time}.",
        "nothing_next": "You have no more medicines scheduled. Well done, {name}.",
        "snooze": "Okay {name}. I will remind you again in {minutes} minutes.",
        "skip": "Understood. I've noted that you skipped {meds}. I will let {caregiver} know.",
        "emergency": (
            "This sounds serious, {name}. Please call {number} right now or ask someone nearby "
            "for help. I am alerting {caregiver}."
        ),
        "med_added": "Done. I've added {med} {dose} at {times}.",
        "unknown": (
            "Sorry, I didn't catch that. You can say: I took my medicine, what's next, "
            "or remind me later."
        ),
        "reminder": "{name}, it is time for {meds}.{instr}",
        "caregiver_default": "your caregiver",
        "and": "and",
    },
    "hi": {
        "taken": "बहुत अच्छा {name}। मैंने {meds} ली हुई दर्ज कर ली है।{next}",
        "next_suffix": " आपकी अगली दवा {med} है, {time}।",
        "nothing_due": "अभी कोई दवा का समय नहीं है।{next}",
        "too_soon": (
            "{name}, कृपया रुकिए। आपने {med} {time} ले ली थी, इतनी जल्दी दोबारा लेना सुरक्षित नहीं हो सकता। "
            "मैंने कुछ दर्ज नहीं किया। अगर आप निश्चित नहीं हैं तो {caregiver} को फ़ोन करें।"
        ),
        "next": "आपकी अगली दवा {med} {dose} है, {time}।",
        "nothing_next": "{name}, अब कोई और दवा बाकी नहीं है। बहुत अच्छा।",
        "snooze": "ठीक है {name}। मैं {minutes} मिनट बाद फिर याद दिलाऊंगा।",
        "skip": "समझ गया। मैंने दर्ज कर लिया कि आपने {meds} नहीं ली। मैं {caregiver} को बता दूंगा।",
        "emergency": (
            "{name}, यह गंभीर लग रहा है। कृपया अभी {number} पर फ़ोन करें या पास के किसी व्यक्ति से मदद लें। "
            "मैं {caregiver} को सूचित कर रहा हूं।"
        ),
        "med_added": "ठीक है। मैंने {med} {dose} जोड़ दी है, समय: {times}।",
        "unknown": "माफ़ कीजिए, मैं समझ नहीं पाया। आप कह सकते हैं: मैंने दवा ले ली, अगली दवा कौन सी है, या बाद में याद दिलाना।",
        "reminder": "{name}, {meds} लेने का समय हो गया है।{instr}",
        "caregiver_default": "आपके देखभालकर्ता",
        "and": "और",
    },
}


def lang_of(code: str | None) -> str:
    return "hi" if code and code.lower().startswith("hi") else "en"


def t(lang: str, key: str, **kw: object) -> str:
    return T[lang_of(lang)][key].format(**kw)


def join_names(lang: str, names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + f" {T[lang_of(lang)]['and']} " + names[-1]
