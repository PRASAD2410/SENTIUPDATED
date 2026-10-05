# Entity-driven relationship extraction

Entity extraction is exclusively local: spaCy identifies narrative people,
organizations, and locations, while identifier rules recognize phones, vehicles,
accounts, and IMEIs. Recognized call tables map their phone columns directly.
Gemini never supplies entities, invents node IDs, or changes their types.

## Narrative relationships with Gemini

Set `RELATIONSHIP_EXTRACTOR=gemini` in the backend environment and configure
`GEMINI_API_KEY` and the intended `GEMINI_MODEL`. Narrative source passages are
sent in bounded requests with existing entity labels, types, and local mention
aliases. `app/llm.py` replaces long database IDs with short request-local IDs
such as `e1` and `e2` in the prompt and endpoint schema, then maps accepted
responses back to the original IDs. Compact JSON and duplicate alias removal
reduce repeated metadata without changing local entities. It requests a strict JSON
object containing relationships with `source`, `target`, `type`, `evidenceText`,
and `origin`. API credentials stay on the backend and are passed in a header.
The legacy `ENABLE_LLM_EXTRACTION` setting no longer has an effect.

`app/gemini_relations.py` validates endpoints against the supplied IDs, finds the
supporting quote in the original source, and requires local endpoint mentions
within that evidence. Negated/uncertain evidence and invalid proposals are
rejected with visible warnings. Findings retain exact source offsets and
page/block provenance. Allegations, complaints, and attributed testimony are
marked `origin: reported`; a direct document statement uses `asserted` without
claiming independent verification. Every relationship has pending review status.

The schema vocabulary includes calls/contact/meetings, transfers, asset
use/ownership/registration, employment/membership, location/residence, family,
posting, reporting, and explicitly stated associations. It does not authorize
connecting all co-occurring entities. Gemini can improve wording coverage but
cannot guarantee the exact true number of entities or relationships. Local
evidence checks help reject unsupported output; they do not prove every semantic
interpretation correct.

### Compact source context

`GEMINI_COMPACT_CONTEXT=true` is the default. `app/relationship_context.py`
keeps entity-bearing sentences and immediate neighbouring sentences, then
batches passages across pages. Disjoint passages are separately marked; a
relationship quote must match one original contiguous passage, never an
artificial join between excerpts. Whitespace is normalized only for requests;
original text and source offsets remain available for local evidence checks.
If compact planning would increase request count or omit entity context, the
original chunks are retained.

Context trimming may miss relationships requiring more distant explanations
or references, and a warning is returned when text is trimmed. Set
`GEMINI_COMPACT_CONTEXT=false` and reanalyze to use the eligible full-context
chunks. Entity extraction remains local in both settings.

`relationshipStatus.input` records `originalChars`, `sentChars`,
`originalRequests`, `plannedRequests`, `passageCount`, and planning `mode`
(`entity-context` or `full-context`). Character metrics describe eligible source
and passage text; they exclude prompt/schema overhead and are not token counts.
Planned requests can differ from attempts when processing stops after a failure.
Compaction reduces input and request usage but cannot bypass requests-per-minute
or daily quota limits; HTTP 429 can still occur.

`relationshipStatus` records the selected mode, chunks attempted/succeeded, and
whether processing completed. A provider error, quota limit, blocked response,
invalid JSON, or output truncation is a retryable failure, not a successful
finding of zero relationships. A new upload can preserve its original and local
entities while displaying Relationships pending. Reanalyze retries without a
second original file or report. Existing saved findings remain unchanged if
reanalysis fails or only part of the document is processed successfully.

## Optional narrative regex mode

Set `RELATIONSHIP_EXTRACTOR=regex` to use local connector rules instead of Gemini
for narratives; this is also the default when the variable is omitted.
This mode passes source mentions (entity ID, type, offsets, and page/block
information) to `app/relations.py`. It compares the text between entity spans to
connectors in `app/relationship_rules.json`. No particular name, telephone
number, or account value belongs in a rule. Changes to these JSON rules affect
regex mode, not the Gemini vocabulary or prompts.

For example, this JSON rule recognizes an explicitly stated connection between
any two extracted entities:

```json
{
  "id": "contact",
  "type": "CONTACTED",
  "sourceTypes": "*",
  "targetTypes": "*",
  "pattern": "\\s+(?:contacted|contacts|communicated\\s+with)\\s+"
}
```

Add an object to the JSON array to add a rule. `pattern` must match the complete
connector between the entity mentions, including surrounding whitespace. Use
`sourceTypes` and `targetTypes` as lists to constrain types, or `"*"` for all
types. Omitting either type restriction also means all types. `type` is the
uppercase graph edge label; `id` is saved as `ruleId` for auditing. Rules are
read on each extraction, so JSON edits do not require restarting the API.

For a sentence `ENTITY_A contacted ENTITY_B`, the stored relationship uses the
actual entity IDs, `CONTACTED`, the original evidence span, page location,
case/report/document IDs, and review status. MongoDB stores the relationship;
the workspace API supplies its endpoints to NetworkX and the graph view.

Rules currently cover calls, transfers, asset use/ownership/registration,
explicit contact/association, employment/membership, residence/location, and
family wording. These are source statements, not verified findings.

Ordinary PDF line wraps are supported. Rules do not cross pages or join table
rows. Leading time/date adjuncts and generic source prefixes such as "The FIR
states that" and "According to call records" retain explicit connectors. Source
attribution is marked as reported evidence. Negation and uncertainty are checked
within the relevant relation clause; a later unrelated negative action does not
erase an affirmative source statement. Named nested subjects, coordinated
subjects, and unsupported wording remain conservatively skipped. Identifier
labels such as "phone no." are not interpreted as the negative word "no".
Exact identifier spans take precedence
over overlapping spaCy guesses when selecting relationship endpoints. Regex
cannot resolve pronouns, determine guilt, or establish a connection from
co-occurrence alone.

Family/residence/posting rules marked `allowEmbedded: true` can match explicit
connectors inside longer narrative sentences. Attribution is retained as
`origin: reported`, with `sentenceContext` for review; negated/uncertain
statements remain excluded. Generic abbreviated family wording (`s/o`, `d/o`,
`w/o`) is supported without embedding entity names. PDF whitespace is flattened
for new spaCy extraction while offsets remain mapped to original text.

## Reanalysis and original-file reuse

Identical file bytes uploaded to the same case reuse the original document and
report, even if renamed. Outdated or incomplete relationship extraction is
retried when the saved file is uploaded again. Choose Reanalyze (the circular
arrow beside a Source Record) to apply the selected relationship mode manually.
Provider failures are reported visibly; they do not overwrite prior findings
with zero or partial results. Original uploads and reports are not duplicated.

Relationship reanalysis is available at
`POST /api/cases/{case_id}/documents/{document_id}/reanalyze`. Narratives reuse
their existing local entities and source mentions with the selected Gemini or
regex mode. Recognized call tables rebuild phone entities and mentions from
columns in the same report. After successful reanalysis, superseded relationships
and mentions remain inactive for audit; obsolete entities are excluded from the
graph when no active report references them. Changing configuration alone does
not automatically reprocess all stored files.

## Deterministic structured call tables

Call tables in CSV, TSV, XLSX and DOCX support caller/receiver column roles, including `CALLER_ID` / `RECEIVER_ID` and common from/to aliases. Each valid row records a directed `CALLED` edge with source row, timestamp, duration in seconds, call type, tower and source case ID when supplied. Caller and receiver columns determine direction; INCOMING does not reverse them. Phones are deduplicated by normalized identifier. Table metadata stays event evidence rather than becoming guessed names or organizations. The selected application's case remains authoritative; a file's CASE_ID is retained only as source metadata. Missing or invalid phone values skip that row with a warning. Unrecognized tables still need explicit column mapping. Numeric spreadsheet cells cannot recover leading zeros already lost in the source.

The graph starts in Connected Only when connections exist; All Entities remains available. Repeated call events are grouped into one labeled visual connection with their separate source statements retained for review.
