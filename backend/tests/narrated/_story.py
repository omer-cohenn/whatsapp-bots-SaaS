"""Shared narration helpers for the Hebrew/English "baby-language" story runners.

The narrated `*_full_test.py` scripts each print, per check:
    🧪 what we tried   ·   💡 why it matters   ·   ✅/❌ what happened
and end with a pass/total scoreboard.

Historically every runner re-declared identical `banner`/`explain`/`result`
helpers plus a module-global `_passed`/`_total` pair. This module centralizes
that boilerplate WITHOUT changing a single byte of printed output: a runner
builds a `Story` with its OWN exact wording (Hebrew vs English, and its own
"needs a fix" phrasing), and the helpers print precisely what that runner
printed before. The tally lives on the Story instance (no module globals).

This is pure narration plumbing — it touches no product code and asserts
nothing. The runners still own all their test logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Story:
    """A per-runner narration bundle: same printed output, shared plumbing.

    Wording knobs (defaults match the English runners m5/m6a/m7/m12/...):
      * test_label   — the banner's per-check prefix ("TEST" or Hebrew "בדיקה").
      * try_label / because_label — the 🧪 / 💡 line labels.
      * good_label / bad_label    — the ✅ / ❌ line labels.
      * bad_suffix   — the trailing nudge on a failure line.
    """

    test_label: str = "TEST"
    try_label: str = "We try "
    because_label: str = "Because"
    good_label: str = "GOOD   "
    bad_label: str = "BAD    "
    bad_suffix: str = "<-- THIS NEEDS A FIX!"
    passed: int = field(default=0)
    total: int = field(default=0)

    def banner(self, num: str, title: str) -> None:
        print()
        print("─" * 74)
        print(f"  {self.test_label} {num}: {title}")
        print("─" * 74)

    def explain(self, what: str, why: str) -> None:
        print(f"  🧪 {self.try_label}: {what}")
        print(f"  💡 {self.because_label}: {why}")

    def result(self, ok: bool, detail: str) -> None:
        self.total += 1
        if ok:
            self.passed += 1
            print(f"  ✅ {self.good_label}: {detail}")
        else:
            print(f"  ❌ {self.bad_label}: {detail}   {self.bad_suffix}")
