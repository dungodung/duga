import responses

from jobs.sitelink_gap import make_compute_fn, sitelink_dbname

API_URL = "https://www.wikidata.org/w/api.php"


def entities_response(entities):
    return {"entities": entities}


def entity(sitelinks=None, label=None, language="sr"):
    body = {"sitelinks": {site: {"site": site, "title": "x", "badges": []} for site in (sitelinks or [])}}
    body["labels"] = {language: {"value": label, "language": language}} if label is not None else {}
    return body


def test_sitelink_dbname_default_and_override():
    assert sitelink_dbname("sr", "wiktionary") == "srwiktionary"
    assert sitelink_dbname("nb", "wikiquote") == "nowikiquote"


class FakeApp:
    def __init__(self, config):
        self.config = config


@responses.activate
def test_make_compute_fn_flags_topics_missing_the_family_sitelink():
    app = FakeApp({"DUGA_WIKIDATA_API": API_URL, "DUGA_USER_AGENT": "duga-test"})
    responses.add(
        responses.GET,
        API_URL,
        json=entities_response(
            {
                "Q1": entity(sitelinks=["enwiktionary"], label="Has no sr entry"),
                "Q2": entity(sitelinks=["srwiktionary"], label="Has sr entry"),
            }
        ),
        status=200,
    )
    compute = make_compute_fn("wiktionary")
    missing = compute(app, "sr", ["Q1", "Q2"])
    assert missing == {"Q1": {"label": "Has no sr entry"}}
