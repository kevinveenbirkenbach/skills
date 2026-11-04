#!/usr/bin/env python3
"""Fold fix confidence, break risk, efficiency and speed into one score line and one gate line.

Args:
    --fix: fix confidence in percent, 0 to 100.
    --break: break risk in percent, 0 to 100.
    --efficiency: efficiency in percent above 0; `-` when not measured or not
        relevant, `new` when the change has no base. Both count as 100 in the score.
    --speed: speed in percent above 0, `-` or `new` as for --efficiency.

Output:
    Line 1: `🎯 fix <f> % · 💥 break <b> % · 🌱 efficiency <e> % · ⚡ speed <s> % · 🏆 score <n>`,
        `–` in place of `<x> %` for `-`, `new` for `new`. Score is
        fix * (100 - break) / 100 * 100 / efficiency * 100 / speed, capped to 0..100, rounded half up.
    Line 2: the gate verdict, `✅ gate: ...`, `⛔ gate: ...` or `⚠️ gate: ...`.

Exit codes:
    0 gate passed, 1 fix under 90 or break over 5, 2 usage error,
    3 efficiency or speed over 100 or new: ask the operator before the commit.
"""

from __future__ import annotations

import argparse
import math
import sys

FIX_MIN = 90
BREAK_MAX = 5
COST_MAX = 100
DASH = "-"
NEW = "new"


def percent(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not 0 <= value <= 100:
        raise argparse.ArgumentTypeError(f"{text!r} is outside 0..100")
    return value


def cost(text: str) -> float | str:
    if text in (DASH, NEW):
        return text
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is neither a number, {DASH!r} nor {NEW!r}") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"{text!r} must be a positive number")
    return value


def number(value: float) -> str:
    return f"{value:g}"


def shown(value: float | str) -> str:
    if value == DASH:
        return "–"
    if value == NEW:
        return NEW
    return f"{number(value)} %"


def factor(value: float | str) -> float:
    return 100 / value if isinstance(value, float) else 1.0


def score(fix: float, risk: float, efficiency: float | str, speed: float | str) -> int:
    raw = fix * (100 - risk) / 100 * factor(efficiency) * factor(speed)
    return math.floor(min(max(raw, 0.0), 100.0) + 0.5)


def over(name: str, value: float | str) -> str | None:
    if value == NEW:
        return f"{name} {NEW}"
    if isinstance(value, float) and value > COST_MAX:
        return f"{name} {number(value)} % > {COST_MAX}"
    return None


def gate(fix: float, risk: float, efficiency: float | str, speed: float | str) -> tuple[str, int]:
    failed = []
    if fix < FIX_MIN:
        failed.append(f"fix {number(fix)} % < {FIX_MIN}")
    if risk > BREAK_MAX:
        failed.append(f"break {number(risk)} % > {BREAK_MAX}")
    if failed:
        return f"⛔ gate: {', '.join(failed)}", 1
    costly = [text for text in (over("efficiency", efficiency), over("speed", speed)) if text]
    if costly:
        return f"⚠️ gate: {', '.join(costly)}: ask the operator before the commit", 3
    return f"✅ gate: {FIX_MIN}/{BREAK_MAX}, efficiency and speed <= {COST_MAX}", 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fix", type=percent, required=True)
    parser.add_argument("--break", dest="risk", type=percent, required=True)
    parser.add_argument("--efficiency", type=cost, required=True)
    parser.add_argument("--speed", type=cost, required=True)
    args = parser.parse_args()
    total = score(args.fix, args.risk, args.efficiency, args.speed)
    print(
        f"🎯 fix {number(args.fix)} % · 💥 break {number(args.risk)} % · "
        f"🌱 efficiency {shown(args.efficiency)} · ⚡ speed {shown(args.speed)} · 🏆 score {total}"
    )
    verdict, code = gate(args.fix, args.risk, args.efficiency, args.speed)
    print(verdict)
    return code


if __name__ == "__main__":
    sys.exit(main())
