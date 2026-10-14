"""Number check for generated text (chapter 9): every number in the text must occur in the input.

Numbers are compared by value, so "4,9", "4.9" and "4,9%" all match an input value of 4,9. Signs are
ignored ("een daling van 3%" for -3). Numbers written out in words count too and must also be in the
input. Grade letters are checked the same way: a letter the input does not contain is an error.
"""

import json
import re

NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*")
GRADE = re.compile(r"(?<![\w&+\-/])([A-D][+\-]|[A-DF])(?![\w&+\-/])")

UNITS = {"één": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "zes": 6, "zeven": 7, "acht": 8, "negen": 9}
TEENS = {"tien": 10, "elf": 11, "twaalf": 12, "dertien": 13, "veertien": 14, "vijftien": 15, "zestien": 16,
         "zeventien": 17, "achttien": 18, "negentien": 19}
TENS = {"twintig": 20, "dertig": 30, "veertig": 40, "vijftig": 50, "zestig": 60, "zeventig": 70, "tachtig": 80,
        "negentig": 90}
BIG = {"honderd": 100, "duizend": 1000, "miljoen": 1_000_000, "miljard": 1_000_000_000}
COMPOUND_UNITS = {"een": 1, "één": 1, "eenen": 1, **UNITS}
WORD = re.compile(r"(?<![\w-])[a-zéë]+(?![\w-])", re.IGNORECASE)
# "in acht nemen" is not a number.
NOT_NUMBERS = re.compile(r"\bin acht\b", re.IGNORECASE)
FORBIDDEN = re.compile(r"\b(kopen|koop|koopt|verkopen|verkoop|verkoopt|koersdoel\w*)\b", re.IGNORECASE)


def interpretations(token: str) -> set[float]:
    """All values a written number can mean: Dutch and English decimal and thousands separators."""
    out: set[float] = set()
    if "," in token and "." in token:
        # 1.234,5 (Dutch) or 1,234.5 (English): the last separator is the decimal one.
        last = max(token.rfind(","), token.rfind("."))
        whole, frac = token[:last], token[last + 1:]
        out.add(float(re.sub(r"[.,]", "", whole) + "." + frac))
        return out
    for sep in (",", "."):
        if sep in token:
            parts = token.split(sep)
            if len(parts) == 2:
                out.add(float(parts[0] + "." + parts[1]))
            if all(len(p) == 3 for p in parts[1:]):
                out.add(float("".join(parts)))
            return out or {float("nan")}
    return {float(token)}


def _word_value(word: str) -> float | None:
    w = word.lower()
    if w in UNITS or w in TEENS or w in TENS or w in BIG:
        return float({**UNITS, **TEENS, **TENS, **BIG}[w])
    for tens, value in TENS.items():
        if w.endswith("en" + tens) or w.endswith("ën" + tens):
            head = w[: -len(tens) - 2]
            unit = COMPOUND_UNITS.get(head) or COMPOUND_UNITS.get(head.replace("ë", "e"))
            if unit:
                return float(value + unit)
    return None


def numbers_in(text: str) -> list[tuple[str, set[float]]]:
    """Every number in a text, written in digits or in words, with the values it can stand for."""
    found = [(m.group(0), interpretations(m.group(0))) for m in NUMBER.finditer(text)]
    cleaned = NOT_NUMBERS.sub(" ", text)
    for m in WORD.finditer(cleaned):
        value = _word_value(m.group(0))
        if value is not None:
            found.append((m.group(0), {value}))
    return found


def grades_in(text: str) -> set[str]:
    return set(GRADE.findall(text))


def allowed_values(payload: dict) -> set[float]:
    text = json.dumps(payload, ensure_ascii=False)
    values: set[float] = set()
    for _, vals in numbers_in(text):
        values |= vals
    return values


def _matches(vals: set[float], allowed: set[float]) -> bool:
    return any(abs(v - a) < 1e-9 for v in vals for a in allowed)


def check_text(text: str, payload: dict, min_words: int = 0, max_words: int = 10_000) -> list[str]:
    """Problems with a generated text, in Dutch; an empty list means the text passes."""
    problems: list[str] = []
    allowed = allowed_values(payload)
    bad = sorted({tok for tok, vals in numbers_in(text) if not _matches(vals, allowed)})
    if bad:
        problems.append("getallen die niet in de invoer staan: " + ", ".join(bad))
    allowed_grades = grades_in(json.dumps(payload, ensure_ascii=False))
    wrong = sorted(grades_in(text) - allowed_grades)
    if wrong:
        problems.append("grades die niet in de invoer staan: " + ", ".join(wrong))
    words = len(text.split())
    if not min_words <= words <= max_words:
        problems.append(f"{words} woorden, verwacht {min_words} tot {max_words}")
    hit = sorted({m.group(0).lower() for m in FORBIDDEN.finditer(text)})
    if hit:
        problems.append("verboden woorden: " + ", ".join(hit))
    return problems
