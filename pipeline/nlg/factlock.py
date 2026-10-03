"""Fact-lock: the last gate before a finding is written.

A finding passes only if
  1. every number in its text appears in a value that was registered in its FactSheet
     (so no sentence can state a number the pipeline didn't compute), and
  2. it uses none of the banned overclaiming words, and
  3. no template placeholder was left unfilled.
Failing any check raises FactLockError: the stage stops rather than publish an ungrounded claim.
"""

from __future__ import annotations

import re

NUMBER = re.compile(r"\d+(?:\.\d+)?")
BANNED_WORDS = ("safe", "unsafe", "caused", "definitely", "certainly", "toxic", "guarantee", "guaranteed", "proven")
_BANNED = re.compile(r"\b(" + "|".join(BANNED_WORDS) + r")\b", re.IGNORECASE)


class FactLockError(ValueError):
    """Raised when generated text contains an ungrounded number or banned wording."""


def allowed_numbers(shown_values: list[str]) -> set[str]:
    return {m for s in shown_values for m in NUMBER.findall(s)}


def check(text: str, shown_values: list[str], *, where: str = "") -> None:
    allowed = allowed_numbers(shown_values)
    stray = [n for n in NUMBER.findall(text) if n not in allowed]
    if stray:
        raise FactLockError(f"{where}: number(s) {stray} are not backed by any fact in: {text!r}")
    banned = _BANNED.findall(text)
    if banned:
        raise FactLockError(f"{where}: banned wording {banned} in: {text!r}")
    if "{" in text or "}" in text:
        raise FactLockError(f"{where}: unfilled placeholder in: {text!r}")
