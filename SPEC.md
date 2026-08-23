# Duga — project specification

> **Duga** — *rainbow* across the Slavic languages; in Indonesian, *to sound the depths*.
>
> **Tagline:** Queer knowledge, in every language
>
> **One-sentence description:** Duga is a multilingual hub that shows what queer
> knowledge is missing from Wikimedia projects in your language, and gives you
> the words and the tools to add it.

- **URL:** `https://duga.toolforge.org`
- **Host:** Wikimedia Toolforge (Kubernetes)
- **Initiated by:** a member of Wikimedia Serbia, as a contribution to the global
  Wikimedia LGBT+ community
- **Target milestone:** working, seedable v0.1 by the Queering Wiki conference,
  Montréal, 23–25 October 2026
- **Intended custodian:** Wikimedia LGBT+ User Group (handover planned, not immediate)
- **Licence:** free/open source (AGPL-3.0 recommended); data CC0 where it mirrors
  Wikidata, CC BY-SA for prose contributions

---

## 1. Purpose

Two problems block queer content work in smaller-language Wikimedia communities:

1. **You don't know what's missing.** Existing gap tools are English-anchored,
   single-project, or require a wiki page to be maintained by hand.
2. **You don't know what to call it.** In many languages there is no settled
   neutral vocabulary for queer concepts, no guidance on which terms are
   clinical, outdated, or slurs, and no open resource that records this.

Duga solves both in one place, because they are the same problem: you cannot
reliably detect that an article is missing in a language until you know what that
language calls the topic.

### The unifying insight

A missing article, a missing label, a missing image, and a missing *word* are all
the same record shape:

```
(topic, language, project, gap_type, evidence, action, status)
```

The vocabulary layer is not a separate module. It **emits records into the same
stream** as every content detector, and it **feeds** the content detectors the
search strings they need. If an implementation ever ends up with two parallel
systems joined by a nav bar, the design has been misread.

---

## 2. Non-goals

Explicitly out of scope, permanently or for the foreseeable future:

- **Not** a replacement for PetScan, Listeria, Content Translation, QuickStatements,
  or Wiki Gap Finder. Duga deep-links *into* them.
- **Not** a scraper of other tools' rendered HTML.
- **Not** a general-purpose gap tool with a queer filter. The scope definition and
  the vocabulary are the product.
- **Not** a ranking of language communities against each other.
- **Not** a research corpus, dataset dump, or analytics platform.
- **Not** an inference engine. Duga never guesses anything about a person.

---

## 3. Hard constraints (safety)

These are not preferences. They are the conditions under which this tool is
allowed to exist. Any change that weakens one of these requires explicit
human sign-off, never an autonomous refactor.

**S1. Duga never writes identity statements.**
No write path may ever create or modify `P91` (sexual orientation), `P21` (sex or
gender), or any other claim asserting a person's identity — on any wiki, in any
version, under any user's credentials. Duga writes labels, descriptions,
vocabulary, and media/category associations only. Reading identity statements is
core to the product; writing them is permanently forbidden.

**S2. Unreferenced identity statements never generate gap records for people.**
A scope rule matching a human via an identity property MUST require a reference on
that statement. Unreferenced matches are dropped silently — not shown, not
flagged, not queued.

**S3. Duga never infers, suggests, or ranks likelihood of queerness.**
No "similar people", no "candidates for review", no ML classification of persons,
no "this person may be missing a sexual orientation statement". This is the
outing failure mode and it is closed off by construction.

**S4. Suppression is absolute and immediate.**
A suppressed topic or term is filtered at query time in every code path, including
API responses, exports, and cached pages. Suppression requires no upstream edit
and no justification beyond a logged reason.

**S5. No public per-editor rankings.**
Contribution counts and leaderboards are not shown to anonymous users. Attribution
is opt-out per contributor (see §9).

**S6. No per-language completeness scores or league tables.**
Impact scoring ranks *topics within a language*. It never ranks languages against
each other, and no view may be constructed that does so implicitly (e.g. sorting
languages by gap count).

**S7. Living persons get stricter handling.**
`is_living` topics are excluded from experimental detectors by default and from
any bulk/batch surface.

**S8. Global write kill switch.**
A single config flag disables all outbound wiki edits without a redeploy. It must
be checked immediately before every write, not at startup.

---

## 4. Architecture

### The forcing constraint

Toolforge will not support computing gaps on request:

- the public WDQS endpoint times out at 60s and rate-limits
- the wiki replicas are shared infrastructure
- web pods have modest memory ceilings

**Therefore: precompute everything into ToolsDB; the web app only reads.**

No request-path SPARQL. No request-path replica queries beyond trivial lookups.
If a page needs data, a job put it there earlier.

### Flow

```
  on-wiki scope definition ──┐
                             ├──> scheduled detector jobs ──> ToolsDB ──> web app
  WDQS / replicas / APIs ────┘                                              │
                                                                           │
             Wikidata <──── OAuth writes (labels, descriptions, lexemes) ───┘
```

### Components

| Component | Role |
|---|---|
| `scope_fetch` job | Pulls and versions the on-wiki scope definition |
| `topic_refresh` job | Resolves scope rules to topics via WDQS, writes `topic` |
| detector jobs (one per gap type) | Compute gap records, tagged with detector key + maturity |
| `promotion` job | Moves eligible vocabulary records upstream to Wikidata |
| web app | Read-only over ToolsDB, plus authenticated contribution endpoints |

---

## 5. Stack

- **Python 3.11+ / Flask**, server-rendered Jinja templates
- **ToolsDB (MariaDB)** for all Duga-owned state
- **Toolforge jobs framework** for all scheduled work
- **Vanilla JS only**, progressively enhancing forms. No React, Vue, or build step.
- **i18n:** message files compatible with translatewiki.net from the first commit

### Why server-rendered

Target users include contributors on low-end Android phones over slow
connections. An SPA is a worse product for them, harder to translate, and harder
to make accessible. This is a deliberate constraint, not an oversight — do not
"modernise" it.

---

## 6. Scope definition (on-wiki, governed)

Lives on **Wikidata** (WikiProject LGBT namespace), not Meta, not in this repo.
Duga is the renderer; the community is the arbiter.

### Format

A JSON block on a wiki page:

```json
{
  "version": "2026-09-01",
  "rules": [
    {
      "key": "person_orientation_sourced",
      "label": "People with a referenced sexual orientation statement",
      "entity_class": "human",
      "requires_reference": true,
      "risk_level": "high",
      "rationale": "Only sourced, self-identified or well-documented claims.",
      "sparql_fragment": "?item wdt:P31 wd:Q5 . ?item p:P91 ?st . ?st prov:wasDerivedFrom ?ref ."
    },
    {
      "key": "org_lgbt",
      "label": "LGBT+ organisations",
      "entity_class": "organisation",
      "requires_reference": false,
      "risk_level": "low",
      "rationale": "Organisations are not persons; no outing risk.",
      "sparql_fragment": "..."
    }
  ]
}
```

### Rules for the fetcher

- Record the page revision id with every fetch; never lose provenance
- Store the raw JSON verbatim alongside the parsed rules
- A new version does **not** auto-activate; it lands as `active = false` and is
  promoted by an operator. Scope changes must never surprise users.
- Every gap record carries the `scope_version_id` that produced it, so any list is
  reproducible
- `requires_reference = true` is enforced in code, not just trusted from the fragment

---

## 7. Data model

MariaDB DDL. Use migrations from commit one; never hand-edit production schema.

```sql
-- ---------- scope ----------

CREATE TABLE scope_version (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  source_page   VARCHAR(255)  NOT NULL,
  revision_id   BIGINT        NOT NULL,
  raw_json      MEDIUMTEXT    NOT NULL,
  fetched_at    DATETIME      NOT NULL,
  active        BOOLEAN       NOT NULL DEFAULT FALSE,
  activated_at  DATETIME      NULL,
  activated_by  VARCHAR(255)  NULL,
  UNIQUE KEY (source_page, revision_id)
);

CREATE TABLE scope_rule (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  scope_version_id  INT           NOT NULL,
  rule_key          VARCHAR(64)   NOT NULL,
  label             VARCHAR(255)  NOT NULL,
  entity_class      VARCHAR(32)   NOT NULL,
  requires_reference BOOLEAN      NOT NULL DEFAULT FALSE,
  risk_level        ENUM('low','medium','high') NOT NULL DEFAULT 'medium',
  rationale         TEXT          NULL,
  sparql_fragment   TEXT          NOT NULL,
  FOREIGN KEY (scope_version_id) REFERENCES scope_version(id),
  UNIQUE KEY (scope_version_id, rule_key)
);

-- ---------- topics ----------

CREATE TABLE topic (
  qid               VARCHAR(16) PRIMARY KEY,
  entity_class      VARCHAR(32)  NOT NULL,
  is_human          BOOLEAN      NOT NULL DEFAULT FALSE,
  is_living         BOOLEAN      NOT NULL DEFAULT FALSE,
  first_seen        DATETIME     NOT NULL,
  last_seen         DATETIME     NOT NULL,
  suppressed        BOOLEAN      NOT NULL DEFAULT FALSE,
  suppressed_reason TEXT         NULL,
  suppressed_at     DATETIME     NULL,
  suppressed_by     VARCHAR(255) NULL,
  INDEX (suppressed),
  INDEX (is_living)
);

CREATE TABLE topic_rule (
  topic_qid         VARCHAR(16) NOT NULL,
  rule_key          VARCHAR(64) NOT NULL,
  scope_version_id  INT         NOT NULL,
  PRIMARY KEY (topic_qid, rule_key, scope_version_id),
  FOREIGN KEY (topic_qid) REFERENCES topic(qid)
);

-- ---------- reference data ----------

CREATE TABLE language (
  code      VARCHAR(20) PRIMARY KEY,
  autonym   VARCHAR(128) NOT NULL,
  seeded    BOOLEAN      NOT NULL DEFAULT FALSE,
  notes     TEXT         NULL
);

CREATE TABLE project (
  code    VARCHAR(32) PRIMARY KEY,   -- wikipedia, wikidata, commons, wiktionary, ...
  family  VARCHAR(32) NOT NULL
);

-- ---------- detectors and gaps ----------

CREATE TABLE detector (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  detector_key VARCHAR(64) NOT NULL UNIQUE,
  project_code VARCHAR(32) NOT NULL,
  gap_type     VARCHAR(64) NOT NULL,
  maturity     ENUM('stable','beta','experimental') NOT NULL DEFAULT 'experimental',
  enabled      BOOLEAN     NOT NULL DEFAULT TRUE,
  description  TEXT        NULL,
  last_run_at  DATETIME    NULL,
  last_status  VARCHAR(32) NULL
);

CREATE TABLE gap (
  id               BIGINT AUTO_INCREMENT PRIMARY KEY,
  topic_qid        VARCHAR(16) NOT NULL,
  language_code    VARCHAR(20) NOT NULL,
  project_code     VARCHAR(32) NOT NULL,
  gap_type         VARCHAR(64) NOT NULL,
  detector_key     VARCHAR(64) NOT NULL,
  scope_version_id INT         NOT NULL,
  evidence_json    TEXT        NULL,
  action_url       TEXT        NULL,
  impact_score     DECIMAL(10,4) NULL,
  computed_at      DATETIME    NOT NULL,
  UNIQUE KEY uq_gap (topic_qid, language_code, project_code, gap_type),
  INDEX (language_code, project_code, gap_type),
  INDEX (impact_score)
);

-- Human decisions live separately so recomputation never destroys them.
CREATE TABLE gap_override (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  topic_qid     VARCHAR(16) NOT NULL,
  language_code VARCHAR(20) NOT NULL,
  project_code  VARCHAR(32) NOT NULL,
  gap_type      VARCHAR(64) NOT NULL,
  status        ENUM('declined','not_applicable','done') NOT NULL,
  reason        TEXT        NULL,
  set_by        VARCHAR(255) NOT NULL,
  set_at        DATETIME    NOT NULL,
  UNIQUE KEY uq_override (topic_qid, language_code, project_code, gap_type)
);
```

> **Critical:** detector jobs may `DELETE`/`INSERT` freely in `gap`. They must
> **never** touch `gap_override`. Effective status is computed by joining the two
> at read time.

```sql
-- ---------- vocabulary ----------

CREATE TABLE concept (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  qid          VARCHAR(16)  NULL,          -- null while purely local
  local_label  VARCHAR(255) NULL,
  lifecycle    ENUM('local','proposed','upstream') NOT NULL DEFAULT 'local',
  created_by   VARCHAR(255) NOT NULL,
  created_at   DATETIME     NOT NULL,
  suppressed   BOOLEAN      NOT NULL DEFAULT FALSE,
  UNIQUE KEY (qid)
);

CREATE TABLE term (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  concept_id     INT          NOT NULL,
  language_code  VARCHAR(20)  NOT NULL,
  written_form   VARCHAR(255) NOT NULL,
  lexeme_id      VARCHAR(16)  NULL,
  sense_id       VARCHAR(24)  NULL,
  register       ENUM('neutral','clinical','outdated','slur','reclaimed',
                      'regional','unknown') NOT NULL DEFAULT 'unknown',
  evidence_grade ENUM('documented','organisational','community','single_report')
                 NOT NULL DEFAULT 'single_report',
  lifecycle      ENUM('local','proposed','upstream') NOT NULL DEFAULT 'local',
  upstream_ref   VARCHAR(24)  NULL,
  usage_note     TEXT         NULL,
  created_by     VARCHAR(255) NOT NULL,
  created_at     DATETIME     NOT NULL,
  updated_at     DATETIME     NOT NULL,
  suppressed     BOOLEAN      NOT NULL DEFAULT FALSE,
  FOREIGN KEY (concept_id) REFERENCES concept(id),
  UNIQUE KEY uq_term (concept_id, language_code, written_form),
  INDEX (language_code, register)
);

CREATE TABLE term_evidence (
  id        INT AUTO_INCREMENT PRIMARY KEY,
  term_id   INT          NOT NULL,
  kind      ENUM('publication','style_guide','dictionary','law',
                 'organisation','other') NOT NULL,
  citation  TEXT         NOT NULL,
  url       TEXT         NULL,
  org_name  VARCHAR(255) NULL,
  year      SMALLINT     NULL,
  added_by  VARCHAR(255) NOT NULL,
  added_at  DATETIME     NOT NULL,
  FOREIGN KEY (term_id) REFERENCES term(id)
);

CREATE TABLE term_assertion (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  term_id           INT          NOT NULL,
  contributor       VARCHAR(255) NOT NULL,
  agrees            BOOLEAN      NOT NULL,
  register_asserted VARCHAR(32)  NULL,
  note              TEXT         NULL,
  created_at        DATETIME     NOT NULL,
  FOREIGN KEY (term_id) REFERENCES term(id),
  UNIQUE KEY uq_assertion (term_id, contributor)
);

-- ---------- people and audit ----------

CREATE TABLE contributor (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  wiki_username  VARCHAR(255) NOT NULL UNIQUE,
  display_public BOOLEAN      NOT NULL DEFAULT TRUE,   -- opt-out
  languages_json TEXT         NULL,
  created_at     DATETIME     NOT NULL,
  last_seen_at   DATETIME     NULL
);

CREATE TABLE audit_log (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  actor        VARCHAR(255) NOT NULL,
  action       VARCHAR(64)  NOT NULL,
  entity_type  VARCHAR(32)  NOT NULL,
  entity_id    VARCHAR(64)  NOT NULL,
  before_json  MEDIUMTEXT   NULL,
  after_json   MEDIUMTEXT   NULL,
  created_at   DATETIME     NOT NULL,
  INDEX (entity_type, entity_id),
  INDEX (created_at)
);

CREATE TABLE wiki_edit (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  contributor   VARCHAR(255) NOT NULL,
  target_wiki   VARCHAR(64)  NOT NULL,
  target_entity VARCHAR(64)  NOT NULL,
  edit_kind     VARCHAR(64)  NOT NULL,   -- label | description | lexeme | sense
  summary       TEXT         NOT NULL,
  revid         BIGINT       NULL,
  status        ENUM('pending','success','failed','blocked') NOT NULL,
  error         TEXT         NULL,
  created_at    DATETIME     NOT NULL
);
```

---

## 8. Evidence grading

Requiring citations for every sensitivity claim would make Duga work for German
and be empty for Yoruba — reproducing the bias it exists to fight. Instead,
evidence is **graded and displayed**, never demanded:

| Grade | Meaning |
|---|---|
| `documented` | Published source, dictionary, style guide, or law |
| `organisational` | A named LGBT+ organisation in that community says so, dated |
| `community` | N distinct verified contributors asserted it in Duga, dated |
| `single_report` | One person said so |

Rules:

- `community` grade is **computed** from `term_assertion` rows, never typed in.
  Threshold configurable, default 3 distinct contributors agreeing.
- The grade is always visible in the UI next to the claim. Never render a
  `community` claim as though it were `documented`.
- Grades upgrade over time. "Add a source for this term" is itself a gap record.
- Attribution is always shown for `organisational` claims — the org name and year
  are what makes the claim a citation rather than an opinion.

---

## 9. OAuth, editing, and attribution

### Authentication

Wikimedia OAuth. A contributor row is created on first login. No Duga-local
passwords, ever.

### Attribution

**Opt-out.** `display_public` defaults to `TRUE`. The opt-out control must be
presented prominently at first login, not buried in settings, with a plain
explanation of what public attribution means. Changing it applies retroactively to
all displayed contributions.

### Editing rules

Duga may write, via the logged-in user's own credentials:

- Wikidata **labels**, **descriptions**, **aliases**
- Wikidata **Lexemes**, **Forms**, **Senses** (post-v0.1)

Duga may **never** write:

- identity statements of any kind (see S1) — this is enforced by an allowlist of
  permitted properties, not a denylist
- anything on behalf of a user without an explicit per-edit confirmation
- batch/bulk edits (out of scope for v0.1 entirely)

Every write path must:

1. check the global kill switch immediately before the request
2. show the user an exact preview of the change and require confirmation
3. include an edit summary naming Duga and linking to the tool
4. log to `wiki_edit` and `audit_log` before and after
5. respect per-user and global rate limits

---

## 10. Vocabulary lifecycle

The local store is a **staging area with an exit**, not a fork.

```
local  ──>  proposed  ──>  upstream
  │            │              │
  │            │              └─ lives in Wikidata; Duga holds a pointer only
  │            └─ has enough structure + evidence to go upstream
  └─ captured in Duga (e.g. someone on their phone at a conference)
```

- Origin and lifecycle state are **always visible** on every term
- A `promotion` job or an authenticated user action moves `proposed` → `upstream`
- Once `upstream`, Duga stops being the source of truth and reads from Wikidata
- Success metric: **the proportion of the local store successfully given away**

Data that legitimately stays local (document this in the UI, don't hide it):

- register/sensitivity annotations that don't fit Wikidata's sourcing norms
- prose usage notes
- the community-assertion evidence layer itself

---

## 11. Detectors

Each detector is an independent scheduled job. Adding one must not require
touching the web app.

### v0.1 detectors

| Key | Project | Gap type | Maturity |
|---|---|---|---|
| `wp_no_article` | wikipedia | `no_article` | stable |
| `wd_no_label` | wikidata | `no_label` | stable |
| `wd_no_description` | wikidata | `no_description` | stable |

### Post-v0.1 (build if time and external guidance permit)

`commons_no_image`, `commons_no_category`, `wiktionary_no_entry`,
`wikiquote_no_quotes`, `wikisource_no_text`, `vocab_no_term`,
`vocab_no_evidence`, lexeme write-back, impact scoring.

Ship these behind `maturity = 'experimental'`, disabled by default. Promotion to
`beta`/`stable` is a human decision after review with native speakers of at least
two affected languages.

### Detector contract

- reads the active `scope_version` and the `topic` table
- respects `topic.suppressed` and (for experimental detectors) `topic.is_living`
- writes only to `gap` and its own `detector` row
- is idempotent — re-running produces the same rows
- emits an `action_url` deep-linking to the real editing surface
- fails loudly into `detector.last_status`; a failed detector shows as stale in
  the UI rather than silently serving old data as current

---

## 12. Web app

### Routes (v0.1)

```
GET  /                          language picker + what Duga is
GET  /<lang>/                   overview for a language
GET  /<lang>/gaps               gap list, filterable by project/type/maturity
GET  /<lang>/vocabulary         terms in this language
GET  /<lang>/vocabulary/<id>    single term: registers, evidence, assertions
GET  /concept/<id>              concept across all languages
POST /<lang>/vocabulary/add     add a term (auth required)
POST /term/<id>/assert          agree/disagree on register (auth required)
POST /term/<id>/evidence        add a source (auth required)
POST /gap/override              mark declined / not applicable (auth required)
GET  /about                     name explanation, scope definition link, policy
GET  /health                    for monitoring
```

### UI principles

- Every page works without JavaScript
- Every gap row shows: what's missing, why it's in scope, its detector maturity,
  and a single button that goes to the place where you fix it
- Never show a raw completeness percentage for a language
- The add-a-term flow must be completable on a phone in under 60 seconds — this is
  the conference seeding path and it is the highest-value flow in the product

---

## 13. Internationalisation

- Message files structured for **translatewiki.net** from the first commit.
  Retrofitting means auditing every hardcoded string later.
- No English string literals in templates or Python. All user-facing text goes
  through the message layer, including error messages and button labels.
- Language codes follow Wikimedia conventions, not ISO where they differ.
- Interface language and content language are **independent** — someone may browse
  Serbian gaps with a Spanish interface.
- Translator notes required for terminology strings, explicitly telling translators
  they may choose a local term rather than transliterating "queer".

### Terminology policy

- **LGBT+** in institutional/formal strings (Toolhub entry, grant text, handover docs)
- **queer** in conversational copy and the tagline
- Documented in one line on `/about`, and flagged to translators

---

## 14. Milestones

| # | Deliverable | Notes |
|---|---|---|
| M0 | Skeleton on Toolforge; health check; i18n scaffolding; hello world in 3 languages | Deploy on day one, not at the end |
| M1 | `scope_fetch` + `topic_refresh` jobs; topic table populated | Scope page must exist on-wiki first |
| M2 | `wp_no_article` detector + gap list UI + language picker | First end-to-end slice |
| M3 | Remaining v0.1 detectors; gap overrides; suppression | |
| M4 | OAuth login; contributor rows; attribution opt-out; audit log | |
| M5 | Vocabulary read + add-a-term (local only) + evidence grading + assertions | The conference flow |
| M6 | OAuth writes: labels/descriptions with preview + kill switch | S1 allowlist enforced |
| M7 | Promotion path: `local` → `proposed` → `upstream` | |
| S1+ | Additional detectors, lexeme write-back, impact scoring | Behind maturity flags |

**Conference-critical path: M0 → M2 → M5.** If time runs short, cut M6/M7 before
cutting M5 — a tool where fifty people added their language beats a tool that can
edit Wikidata but has nothing in it.

---

## 15. Guardrails for implementation

Directives for anyone (human or AI) writing code in this repo:

1. **Never weaken a §3 constraint.** If a task seems to require it, stop and ask.
2. **No request-path SPARQL.** If a page needs data, add a job.
3. **No JS framework, no build step, no client-side routing.**
4. **No hardcoded user-facing English.** Message layer, always.
5. **Never delete or modify `gap_override` rows from a detector.**
6. **Property allowlist for writes**, never a denylist. Adding a property to the
   allowlist is a human decision.
7. **Migrations for every schema change.** No hand-edited production schema.
8. **Idempotent jobs.** Assume every job will be re-run, possibly concurrently.
9. **Fail loudly.** A stale detector must be visible as stale. Never serve old data
   as though it were fresh.
10. **Don't scrape other tools.** Deep-link or use documented APIs.
11. **Log every write** to `audit_log` before and after.
12. **When in doubt about a sensitive display decision, show less.**

---

## 16. Open questions

- Exact WDQS query shape for `requires_reference` enforcement at scale — may need
  chunking by entity class to stay inside the 60s timeout
- Whether the scope definition page should be a `.json` subpage or a wiki page with
  an embedded JSON block (affects fetch and community editability)
- Seed concept list: which ~50 concepts, chosen with input from the Wikidata
  WikiProject LGBT community, not unilaterally
- Impact scoring formula — deferred; must satisfy S6
- Handover terms with Wikimedia LGBT+ User Group
- Whether `commons_no_image` on living people is ever acceptable (probably not)

---

## 17. Before writing code

1. Create the scope definition page on Wikidata and get at least informal buy-in
   from WikiProject LGBT. Duga cannot detect anything without it, and building the
   engine before the definition exists risks baking in unilateral choices.
2. Confirm `duga.toolforge.org` and create the Toolforge tool account.
3. Check Toolhub for name collisions.
4. Line up two or three native-speaker reviewers in languages other than
   English and BCMS, for sanity-checking the vocabulary model before it hardens.
