"""Fixed template explanation of a grade (chapter 2, item 5; the fallback text of chapter 9).

Built only from the stored grade result, so every number in it comes from the snapshot.
"""

from app.grading.letters import GRADES, bands
from app.modelconfig import ModelConfig


def _fmt(v: float) -> str:
    return f"{v:.0f}"


def _metric_points(result: dict, labels: dict[str, str]) -> list[tuple[str, float]]:
    points = []
    for p in result.get("pillars", []):
        for m in p.get("metrics", []):
            if m.get("score") is not None:
                points.append((labels.get(m["id"], m["id"]), float(m["score"])))
    return points


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " en " + items[-1]


def explain(name: str, result: dict, config: ModelConfig, labels: dict[str, str]) -> str:
    template = config.templates[result["template_id"]]
    status = result["status"]
    parts: list[str] = []

    if status == "peg_safety":
        parts.append(f"{name} is een stablecoin en krijgt geen beleggingsgrade maar een pegveiligheid van "
                     f"{result['peg_safety']} op een schaal van 1 (sterk) tot 5 (zwak).")
    elif status == "speculative":
        parts.append(f"{name} wordt beoordeeld als memecoin: er is geen onderbouwde waardering mogelijk, alleen een "
                     f"veiligheidscontrole. De grade is {result['letter']} met het label speculatie; hoger dan C kan "
                     "een memecoin in dit model niet komen.")
        parts.extend(result.get("notes", []))
        if result.get("timing") is not None:
            parts.append(f"De technische score (Timing) is {_fmt(result['timing'])} van 100; die zegt iets over de "
                         "koerstrend, niet over de waarde.")
    elif status == "no_grade":
        parts.append(f"{name} krijgt geen grade. {result.get('reason_nl') or ''}".strip())
        have = [p["name_nl"] for p in result.get("pillars", []) if p.get("score") is not None]
        if have:
            parts.append("Wel beschikbaar: " + _join(have) + ".")
        parts.append("Gegevens waarvoor geen gratis bron bestaat, kunnen handmatig worden aangevuld; ze tellen dan "
                     "mee vanaf het moment van invullen.")
    else:
        prov = " (voorlopig)" if status == "provisional" else ""
        parts.append(f"{name} krijgt {result['letter']}{prov} met een score van {_fmt(result['score'])} van 100 "
                     f"binnen het sjabloon {template.name_nl}.")
        if result.get("quality") is not None and result.get("timing") is not None:
            parts.append(f"Kwaliteit scoort {_fmt(result['quality'])} en Timing {_fmt(result['timing'])}.")
            parts.append(_quality_vs_timing(result["quality"], result["timing"]))
        scored = [p for p in result.get("pillars", []) if p.get("score") is not None]
        if scored:
            parts.append("Per pijler: " + _join([f"{p['name_nl']} {_fmt(p['score'])}" for p in scored]) + ".")
        if result.get("letter_low") and result.get("letter_high") and result["letter_low"] != result["letter_high"]:
            parts.append(f"Met andere gewichten (20% hoger of lager) ligt de grade tussen {result['letter_low']} en "
                         f"{result['letter_high']}.")

    points = _metric_points(result, labels)
    if len(points) >= 2:
        strongest = sorted(points, key=lambda x: -x[1])[:3]
        weakest = sorted(points, key=lambda x: x[1])[:3]
        parts.append("Sterkste punten: " + _join([f"{n} ({_fmt(s)})" for n, s in strongest]) + ".")
        parts.append("Zwakste punten: " + _join([f"{n} ({_fmt(s)})" for n, s in weakest]) + ".")
        parts.append("Getallen tussen haakjes zijn scores van 0 tot 100 ten opzichte van vergelijkbare assets.")

    hit = [g for g in result.get("gates", []) if g["status"] == "hit"]
    for g in hit:
        cap = f" De grade is daarom hoogstens {g['cap']}." if g.get("cap") else ""
        parts.append(f"{g['reason_nl']}{cap}")
    unknown = [g for g in result.get("gates", []) if g["status"] == "unknown"]
    if unknown:
        parts.append(f"{len(unknown)} harde regel(s) konden niet worden gecontroleerd door ontbrekende gegevens.")

    if status in ("graded", "provisional") and result.get("score") is not None:
        parts.append(_what_would_change(result, config))
    if result.get("coverage") is not None and result["coverage"] < 1 and status != "no_grade":
        parts.append(f"De datadekking is {int(result['coverage'] * 100)}%: niet alle maatstaven hebben een bron.")
    if template.note_nl:
        parts.append(template.note_nl.strip())
    return " ".join(p for p in parts if p)


def _quality_vs_timing(quality: float, timing: float) -> str:
    if quality >= 60 and timing < 45:
        return "Dat is een sterke asset op een zwak moment: de kwaliteit is goed, de koerstrend niet."
    if quality < 45 and timing >= 60:
        return "De koers loopt goed, maar de onderliggende kwaliteit blijft achter."
    if quality >= 55 and timing >= 55:
        return "Kwaliteit en koerstrend zijn allebei bovengemiddeld."
    if quality < 45 and timing < 45:
        return "Kwaliteit en koerstrend zijn allebei zwak."
    return "Kwaliteit en koerstrend liggen rond het midden van de groep."


def _what_would_change(result: dict, config: ModelConfig) -> str:
    scale = config.settings.letter_scale
    margin = config.settings.stability.hysteresis_points
    letter = result.get("hysteresis_letter") or result.get("raw_letter")
    if letter not in GRADES:
        return ""
    low, high = bands(scale)[letter]
    i = GRADES.index(letter)
    up = GRADES[i - 1] if i > 0 else None
    down = GRADES[i + 1] if i + 1 < len(GRADES) else None
    pieces = []
    if up:
        pieces.append(f"boven {_fmt(min(high + margin, 100))} wordt het {up}")
    if down:
        pieces.append(f"onder {_fmt(max(low - margin, 0))} zakt het naar {down}")
    if not pieces:
        return ""
    capped = result.get("letter") != letter
    note = " Een harde regel houdt de grade nu lager." if capped else ""
    return f"Wat de grade zou veranderen: {' en '.join(pieces)} (inclusief de marge van {margin:.0f} punten).{note}"
