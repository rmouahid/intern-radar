from intern_radar.sources import SOURCE_NAMES, build_sources
from tests.factories import make_profile, mock_client


def test_registry_builds_every_named_source():
    sources = build_sources(mock_client({}), companies=[], profile=make_profile())
    assert set(sources) | {"none"} == SOURCE_NAMES
    assert all(hasattr(source, "fetch") for source in sources.values())
