import re

from app.glossary import load_glossary
from app.modelconfig import load_model_config
from app.universes import load_universes

EXPECTED_TABS = ["crypto", "stocks", "etfs", "commodities", "fx", "bonds", "indices", "watchlist", "model"]


def test_every_metric_has_a_tooltip(config_dir):
    config = load_model_config(config_dir / "model")
    glossary = load_glossary(config_dir / "glossary.nl.yaml")
    assert set(config.metrics) == set(glossary.metrics)


def test_core_terms_have_a_tooltip(config_dir):
    glossary = load_glossary(config_dir / "glossary.nl.yaml")
    for term in ["grade", "score", "kwaliteit", "timing", "datadekking", "pijler", "gate", "modelversie",
                 "peildatum", "horizon", "bandbreedte", "hysterese", "marktregime"]:
        assert term in glossary.terms


def test_no_forbidden_words_in_interface_texts(config_dir):
    config = load_model_config(config_dir / "model")
    glossary = load_glossary(config_dir / "glossary.nl.yaml")
    texts = [e.label + " " + e.uitleg for e in [*glossary.terms.values(), *glossary.metrics.values()]]
    for t in config.templates.values():
        texts += [t.name_nl, t.note_nl or "", t.label_nl or ""]
        texts += [g.reason_nl for g in t.gates]
    pattern = re.compile(r"\b(" + "|".join(config.settings.forbidden_words_nl) + r")\b", re.IGNORECASE)
    offenders = [text for text in texts if pattern.search(text)]
    assert offenders == []


def test_tabs_are_complete_and_ordered(config_dir):
    universes = load_universes(config_dir / "universes.yaml")
    assert [t.slug for t in universes.tabs] == EXPECTED_TABS
    assert universes.size_options == [25, 50, 100]


def test_every_template_belongs_to_its_tab(config_dir):
    config = load_model_config(config_dir / "model")
    universes = load_universes(config_dir / "universes.yaml")
    assigned = {}
    for tab in universes.tabs:
        for template_id in tab.templates:
            assigned[template_id] = tab.slug
    assert set(assigned) == set(config.templates)
    for template_id, slug in assigned.items():
        assert config.templates[template_id].tab == slug
