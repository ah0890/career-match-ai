"""Company research: Wikidata/Wikipedia parsing, relevance and rendering. Synthetic payloads only."""

from datetime import datetime, timezone

import httpx
import pytest

from src.company.models import CompanyCandidate
from src.company.relevance import companies_in, relevance, same_company
from src.company.wikimedia import format_time, get_company, looks_like_organisation, search_companies
from src.providers.base import ProviderError, ProviderUnavailable
from src.providers.http import ProviderHttp
from src.ui.company_view import facts_html, summary_html
from tests.fixtures.match_factory import job


def _item(qid, prop_values):
    return {"id": qid, "labels": {"en": {"value": "Example Devices"}}, "descriptions": {"en": {"value": "fictional "
            "medical device manufacturer"}}, "sitelinks": {"enwiki": {"title": "Example Devices"}}, "claims": prop_values}


def _entity_claim(qid, rank="normal", qualifiers=None):
    return {"rank": rank, "mainsnak": {"snaktype": "value", "datavalue": {"type": "wikibase-entityid",
                                                                          "value": {"id": qid}}},
            "qualifiers": qualifiers or {}}


def _time(t, precision=11):
    return {"time": t, "precision": precision}


CLAIMS = {
    "P452": [_entity_claim("Q1")],
    "P571": [{"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"type": "time",
                                                                               "value": _time("+1990-05-04T00:00:00Z")}}}],
    "P159": [_entity_claim("Q2")],
    "P1128": [
        {"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"type": "quantity", "value": {"amount": "+900"}}},
         "qualifiers": {"P585": [{"datavalue": {"value": _time("+2020-01-01T00:00:00Z", 9)}}]}},
        {"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"type": "quantity", "value": {"amount": "+1200"}}},
         "qualifiers": {"P585": [{"datavalue": {"value": _time("+2024-01-01T00:00:00Z", 9)}}]}},
    ],
    "P414": [_entity_claim("Q5", qualifiers={"P580": [{"datavalue": {"value": _time("+1999-01-01T00:00:00Z", 9)}}]})],
    "P169": [
        _entity_claim("Q3", qualifiers={"P582": [{"datavalue": {"value": _time("+2019-01-01T00:00:00Z", 9)}}]}),
        _entity_claim("Q4", qualifiers={"P580": [{"datavalue": {"value": _time("+2019-02-01T00:00:00Z", 10)}}]}),
    ],
    "P856": [{"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"type": "string",
                                                                               "value": "https://devices.example.com"}}}],
    "P1056": [_entity_claim("Q6", rank="deprecated")],
}
NAMES = {"Q1": "medical technology", "Q2": "Example City", "Q3": "Former Boss", "Q4": "Sam Example",
         "Q5": "Example Exchange", "Q6": "Old Product"}


def _handler(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    if request.url.host == "www.wikidata.org" and params.get("action") == "wbsearchentities":
        return httpx.Response(200, json={"search": [
            {"id": "Q900", "label": "Example", "description": "family name"},
            {"id": "Q901", "label": "Example Devices", "description": "fictional medical device manufacturer"},
            {"id": "bad id", "label": "Injected"},
        ]})
    if request.url.host == "www.wikidata.org" and params.get("action") == "wbgetentities":
        ids = params["ids"].split("|")
        if "claims" in params["props"]:
            return httpx.Response(200, json={"entities": {ids[0]: _item(ids[0], CLAIMS)}})
        return httpx.Response(200, json={"entities": {i: {"labels": {"en": {"value": NAMES[i]}}} for i in ids}})
    if request.url.host == "en.wikipedia.org":
        return httpx.Response(200, json={"type": "standard", "extract": "Example Devices is a fictional company.",
                                         "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Example_Devices"}}})
    return httpx.Response(404)


def _http(**kw):
    return ProviderHttp(transport=httpx.MockTransport(_handler), sleep=lambda s: None, **kw)


def test_search_lists_organisations_first_and_drops_invalid_ids():
    found = search_companies("Example", _http())
    assert [c.entity_id for c in found] == ["Q901", "Q900"]
    assert looks_like_organisation(found[0]) and not looks_like_organisation(found[1])


def test_profile_facts_come_with_source_and_dates():
    p = get_company("Q901", _http())
    facts = {f.label: f for f in p.facts}
    assert facts["Industry"].value == "medical technology"
    assert facts["Founded"].value == "4 May 1990"
    assert facts["Headquarters"].value == "Example City"
    assert facts["Employees"].value == "1,200" and facts["Employees"].as_of == "2024"  # latest dated figure
    assert facts["Stock exchange"].as_of is None  # a start date is not an "as of" date
    assert all(f.source.name == "Wikidata" and f.source.url == "https://www.wikidata.org/wiki/Q901" for f in p.facts)


def test_missing_and_deprecated_values_are_reported_not_guessed():
    p = get_company("Q901", _http())
    assert "Products" in p.not_available  # the only product statement is deprecated
    assert "Country" in p.not_available


def test_leadership_excludes_former_holders():
    p = get_company("Q901", _http())
    ceo = next(f for f in p.leadership if f.label == "Chief executive officer")
    assert ceo.value == "Sam Example" and ceo.as_of == "since Feb 2019"


def test_summary_and_website_are_attributed():
    p = get_company("Q901", _http())
    assert p.official_website == "https://devices.example.com"
    assert p.summary.text == "Example Devices is a fictional company."
    assert p.summary.source.licence == "CC BY-SA 4.0"
    assert {s.name for s in p.sources} == {"Wikidata", "Wikipedia"}


def test_invalid_reference_and_offline_mode():
    with pytest.raises(ProviderError):
        get_company("../etc", _http())
    with pytest.raises(ProviderUnavailable):
        search_companies("Example", _http(offline=True))


@pytest.mark.parametrize("value, text", [
    (_time("+1847-10-01T00:00:00Z", 11), "1 Oct 1847"), (_time("+2021-02-00T00:00:00Z", 10), "Feb 2021"),
    (_time("+1999-00-00T00:00:00Z", 9), "1999"), ({"time": "garbage"}, None),
])
def test_format_time(value, text):
    assert format_time(value) == text


def test_same_company_ignores_suffixes_but_not_different_names():
    assert same_company("Siemens AG", "Siemens")
    assert same_company("Example Devices Ltd", "Example Devices")
    assert not same_company("Siemens", "Siemens Energy")  # a different employer
    assert not same_company("Apple", "Applebee's")
    assert not same_company(None, "Example")


def test_companies_in_results_are_distinct():
    jobs = [job(company="Example Devices Ltd"), job(company="Example Devices", source_job_id="2"),
            job(company="Other Co", source_job_id="3"), job(company=None, source_job_id="4")]
    assert companies_in(jobs) == ["Example Devices Ltd", "Other Co"]


def test_relevance_finds_roles_and_cv_mentions():
    p = get_company("Q901", _http())
    jobs = [job(company="Example Devices Ltd"), job(company="Other Co", source_job_id="2")]
    rel = relevance(p, jobs, [], "Five years in medical technology quality.")
    assert [j.company for j in rel.roles] == ["Example Devices Ltd"]
    assert rel.cv_mentions == ("medical technology",)


def test_views_escape_content_and_link_sources():
    p = get_company("Q901", _http())
    html = facts_html(p.facts, "none")
    assert 'href="https://www.wikidata.org/wiki/Q901"' in html and "As of 2024" in html
    from dataclasses import replace
    evil = replace(p.facts[0], value="<script>x</script>")
    assert "<script>" not in facts_html((evil,), "none")
    assert "CC BY-SA 4.0" in summary_html(p.summary)
    assert "No encyclopaedia summary" in summary_html(None)


def test_candidate_without_description_is_not_called_an_organisation():
    assert not looks_like_organisation(CompanyCandidate("Q1", "X", None, "https://www.wikidata.org/wiki/Q1"))


@pytest.mark.parametrize("name, short", [("Inseego Corp", "Inseego"), ("Example Devices Ltd.", "Example Devices"),
                                         ("Siemens AG", "Siemens"), ("Acme, Inc.", "Acme"),
                                         ("Example Group", "Example Group"), ("The Company", "The Company")])
def test_without_legal_suffix(name, short):
    from src.company.wikimedia import without_legal_suffix
    assert without_legal_suffix(name) == short


def test_find_companies_retries_without_legal_suffix():
    from src.company.wikimedia import find_companies

    def handler(request):
        if request.url.params.get("search") == "Example Devices":
            return httpx.Response(200, json={"search": [{"id": "Q901", "label": "Example Devices",
                                                         "description": "fictional manufacturer"}]})
        return httpx.Response(200, json={"search": []})

    http = ProviderHttp(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    found, searched = find_companies("Example Devices Corp", http)
    assert searched == "Example Devices" and [c.entity_id for c in found] == ["Q901"]
    none, searched_full = find_companies("Unknown Name", http)
    assert none == [] and searched_full == "Unknown Name"
