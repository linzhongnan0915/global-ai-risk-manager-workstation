from src.strategies.research_catalog import flatten_strategy_candidates, load_research_catalog


def test_research_catalog_has_twenty_candidates():
    catalog = load_research_catalog()
    candidates = flatten_strategy_candidates(catalog)

    assert len(candidates) >= 20


def test_research_catalog_has_running_prototypes():
    catalog = load_research_catalog()
    candidates = flatten_strategy_candidates(catalog)
    running = [candidate for candidate in candidates if candidate["current_status"] == "prototype_running"]

    assert len(running) >= 5
