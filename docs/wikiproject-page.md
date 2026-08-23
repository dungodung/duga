# The WikiProject LGBT subproject page

Duga has a general-audience home on Wikidata, separate from its scope
definition (`docs/scope-definition.md`), following the normal structure for
a WikiProject subproject: an overview page with the rules living underneath
it as a subpage.

- **Overview (this doc):** `Wikidata:WikiProject LGBT/Duga`
- **Scope rules (community-governed, machine-read):** `Wikidata:WikiProject LGBT/Duga/scope`

Paste the wikitext below onto the overview page, then create the scope
subpage per `docs/scope-definition.md`.

```wikitext
'''Duga''' ("rainbow" across the Slavic languages; "to sound the depths" in
Indonesian) is a multilingual hub that shows what queer knowledge is missing
from Wikimedia projects in your language, and gives you the words and the
tools to add it.

* '''Tool:''' https://duga.toolforge.org
* '''Source code:''' https://github.com/dungodung/duga (AGPL-3.0)
* '''Scope definition:''' [[Wikidata:WikiProject LGBT/Duga/scope]] — the
  on-wiki, community-governed rules for what counts as in scope
* '''Initiated by:''' a member of Wikimedia Serbia, as a contribution to the
  global Wikimedia LGBT+ community
* '''Intended custodian:''' Wikimedia LGBT+ User Group (handover planned,
  not immediate)

== Purpose ==

Two problems block queer content work in smaller-language Wikimedia
communities:

# '''You don't know what's missing.''' Existing gap tools are
  English-anchored, single-project, or require a wiki page to be maintained
  by hand.
# '''You don't know what to call it.''' In many languages there is no
  settled neutral vocabulary for queer concepts, no guidance on which terms
  are clinical, outdated, or slurs, and no open resource that records this.

Duga treats these as the same problem: a missing article, a missing label,
a missing image, and a missing ''word'' are all the same kind of record —
(topic, language, project, gap type, evidence, action, status). The
vocabulary layer isn't a separate feature bolted on afterwards; it feeds the
search terms the content-gap detectors need, and emits its own gap records
into the same stream.

== What Duga is not ==

* Not a replacement for PetScan, Listeria, Content Translation,
  QuickStatements, or Wiki Gap Finder — Duga deep-links into them.
* Not a scraper of other tools' output.
* Not a general-purpose gap tool with a queer filter — the scope and the
  vocabulary ''are'' the product.
* Not a ranking of language communities against each other. Duga never
  shows per-language completeness scores or league tables.
* Not a research corpus, dataset dump, or analytics platform.
* Not an inference engine. Duga never guesses anything about a person.

== Safety commitments ==

These are hard constraints on the software, not aspirations — changing any
of them requires explicit human sign-off, never a unilateral code change:

* Duga never writes identity statements (sexual orientation, sex or gender,
  etc.) to any wiki, under any user's credentials. Reading them is core to
  the product; writing them is permanently out of scope.
* A scope rule matching a person via an identity property must require a
  reference on that statement. Unreferenced matches are dropped silently —
  never shown, flagged, or queued.
* Duga never infers, suggests, or ranks likelihood of someone being queer.
  No "candidates for review," no classification of persons.
* Suppressing a topic or term takes effect immediately and everywhere,
  including caches and exports, and needs no upstream edit — just a logged
  reason.
* No public per-editor rankings or leaderboards; no per-language
  completeness scores.
* Living people are excluded from experimental detectors and any bulk/batch
  surface by default.

== Scope definition ==

The set of topics, people, and organisations Duga treats as in scope is
defined on this wiki, not in the tool's source code — see
[[Wikidata:WikiProject LGBT/Duga/scope]]. Duga is the renderer; this
WikiProject is the arbiter. A new revision of the rules never takes effect
automatically (an operator promotes it explicitly), so there's no risk in
proposing changes early and often.

== Status ==

Early development. Currently live: a skeleton web app and the jobs that
fetch the scope definition above and resolve it to a list of in-scope
Wikidata items. No gap list, vocabulary tool, or login yet.

== Get involved ==

* Discuss the scope rules on this page's talk page.
* Report bugs or suggest features on the
  [https://github.com/dungodung/duga/issues issue tracker].
* Native-speaker review of the vocabulary model (coming in a later
  milestone) will be especially welcome, particularly for languages other
  than English and BCMS.
```
