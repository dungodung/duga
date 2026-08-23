# The on-wiki scope definition page

Duga's scope (which topics/people/organisations count as in-scope, and under
what conditions) is governed on-wiki, not in this repo (SPEC.md section 6).
`scope_fetch` reads it; it never writes it. This doc is what to paste onto
Wikidata to get M1 running for real, and how the fetcher parses it.

## 1. Create the page

Recommended title: **`Wikidata:WikiProject LGBT/Duga scope`**

Paste the wikitext below. The important part is the exact pair of HTML
comments (`<!-- DUGA-SCOPE-START -->` / `<!-- DUGA-SCOPE-END -->`) around the
JSON — `jobs/scope_fetch.py` parses only what's between them, so prose
elsewhere on the page is free-form and safe to edit. The `<syntaxhighlight>`
wrapper is just for readability on-wiki; the fetcher strips it if present and
still works without it.

```wikitext
This page defines what '''[[m:Special:MyLanguage/Duga|Duga]]''' (a queer-knowledge-gap
tool for Wikimedia projects, see the [https://github.com/dungodung/duga project repository])
treats as in scope. Duga reads this page on a schedule; it never edits it.
Changes here take effect only after an operator explicitly activates the new
revision (Duga never auto-activates a scope change), so there is no rush and
no risk in iterating.

Each rule below becomes a WDQS query. <code>requires_reference: true</code>
is mandatory for any rule that matches a person via an identity statement
(sexual orientation, gender identity, etc.) — Duga's code refuses to run such
a rule at all unless its SPARQL fragment actually filters on a reference.
Unreferenced matches are never shown, by design.

Discuss changes on the talk page. This is a first draft seeded to get the
pipeline running end-to-end for milestone M1 — please rewrite the rules
themselves; nothing about their content is final.

<!-- DUGA-SCOPE-START -->
<syntaxhighlight lang="json">
{
  "version": "2026-08-23",
  "rules": [
    {
      "key": "person_orientation_sourced",
      "label": "People with a referenced sexual orientation or gender identity statement",
      "entity_class": "human",
      "requires_reference": true,
      "risk_level": "high",
      "rationale": "Only sourced, self-identified or well-documented claims -- see SPEC.md S1/S2.",
      "sparql_fragment": "?item wdt:P31 wd:Q5 . ?item p:P91 ?st . ?st prov:wasDerivedFrom ?ref ."
    },
    {
      "key": "org_lgbt",
      "label": "LGBT+ rights organisations",
      "entity_class": "organisation",
      "requires_reference": false,
      "risk_level": "low",
      "rationale": "Organisations are not persons; no outing risk.",
      "sparql_fragment": "?item wdt:P31/wdt:P279* wd:Q6458277 ."
    },
    {
      "key": "lgbt_event",
      "label": "Pride parades and other LGBT+ events",
      "entity_class": "event",
      "requires_reference": false,
      "risk_level": "low",
      "rationale": "Public events, not persons; no outing risk.",
      "sparql_fragment": "?item wdt:P31/wdt:P279* wd:Q51404 ."
    },
    {
      "key": "lgbt_concept",
      "label": "Concepts and works whose main subject is LGBT+",
      "entity_class": "concept",
      "requires_reference": false,
      "risk_level": "low",
      "rationale": "General knowledge gap, not about any individual.",
      "sparql_fragment": "?item wdt:P921 wd:Q17884 ."
    }
  ]
}
</syntaxhighlight>
<!-- DUGA-SCOPE-END -->
```

## 2. Get informal WikiProject LGBT buy-in

Post a short note on `Wikidata talk:WikiProject LGBT` linking the new page,
per SPEC.md section 17 ("at least informal buy-in... before building the
engine around it"). You don't need consensus before M1's plumbing works —
you need it before the *rules themselves* are treated as settled. Feel free
to run `scope_fetch`/`topic_refresh` against a draft to sanity-check the
pipeline while that conversation is ongoing.

## 3. Fetch and activate it

```bash
# on Toolforge, as the tool account
python3 jobs/scope_fetch.py
python3 scripts/activate_scope_version.py --list
python3 scripts/activate_scope_version.py <id> --by <your-wiki-username>
python3 jobs/topic_refresh.py
```

`scope_fetch` is safe to run repeatedly: re-fetching the same revision is a
no-op (SPEC.md guardrail 8). A new on-wiki edit produces a new inactive
`scope_version` row alongside old ones — nothing changes for users until you
explicitly activate it.

## 4. Iterating on the rules later

Edit the JSON block on-wiki, save (creates a new revision), run
`scope_fetch` again, review the new `scope_version` it created, then
activate it when ready. Old scope_versions are kept, not deleted — every gap
record (from M2 onward) carries the `scope_version_id` that produced it, so
any historical list stays reproducible (SPEC.md section 6).

## Format notes

- `entity_class` is free text (not an enum) matched against in
  `jobs/topic_refresh.py` — only the literal string `"human"` gets
  `is_human`/`is_living` treatment (SPEC.md S7); everything else is treated
  as non-human and `is_living` is always `False` for it.
- `risk_level` must be one of `low` / `medium` / `high`.
- `sparql_fragment` is a WHERE-clause body, not a full query -- the code
  wraps it (see `jobs/topic_refresh.py:build_query`).
