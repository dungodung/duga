import responses

from jobs.claim_gap import make_compute_fn

API_URL = "https://www.wikidata.org/w/api.php"


class FakeApp:
    def __init__(self, config):
        self.config = config


@responses.activate
def test_make_compute_fn_flags_topics_missing_the_property():
    app = FakeApp({"DUGA_WIKIDATA_API": API_URL, "DUGA_USER_AGENT": "duga-test"})
    responses.add(
        responses.GET,
        API_URL,
        json={
            "entities": {
                "Q1": {"id": "Q1", "claims": {}, "labels": {"sr": {"value": "No image", "language": "sr"}}},
                "Q2": {"id": "Q2", "claims": {"P18": [{"mainsnak": {}}]}, "labels": {}},
            }
        },
        status=200,
    )
    compute = make_compute_fn("P18")
    missing = compute(app, "sr", ["Q1", "Q2"])
    assert missing == {"Q1": {"label": "No image", "label_lang": "sr"}}
