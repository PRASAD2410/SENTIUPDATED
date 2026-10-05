# SentinelGraph — Criminal Network Intelligence MVP

## Entity extraction and MongoDB storage

Install `backend/requirements.txt` in the backend environment. It includes the
trained `en_core_web_sm` model and PyMongo. `SPACY_MODEL` can select another
installed spaCy pipeline. `/health` reports whether trained NER is ready; a
missing model produces an explicit warning rather than pretending NER ran.

Set `MONGODB_URI` and `MONGODB_DATABASE` in `.env` (see `.env.example`). Local
defaults in the example use `mongodb://localhost:27017` and `sentinelgraph`.
Docker Compose includes MongoDB and a persistent `mongo_data` volume; start
Docker Desktop before running `docker compose up --build`.

Uploads require a working MongoDB connection and accept an optional multipart
`case_id`; pasted-text ingestion accepts `case_id` in JSON. Both default to
`default` for callers that omit it. The UI supports case creation, title search,
selection, multiple source files, and case-scoped cleanup. Select a case before
uploading so its files and findings stay together.

Extraction stores case-scoped entity records in `entities`, each occurrence
and its source location/snippet in `mentions`, and report metadata/completion
status in `reports`. Original uploads are saved to GridFS (`fs.files` and `fs.chunks`) before
parsing, with case-linked metadata in `documents`. Extracted full text remains
in the memory cache; originals can be downloaded and parsed again. The case
workspace reads stored entities, relationships, and document metadata from
MongoDB, so its graph, source records, and metrics survive a backend restart.
Assistant source text currently depends on the backend session. Restarting the
backend does not clear cases; the confirmed Manage Case actions remove stored
data explicitly.

spaCy NER and phone/vehicle/account/IMEI identifier rules exclusively extract
entities. Account numbers require an explicit account label in narrative text.
Recognized call-table columns provide deterministic phone entities and call
events; other tables require a supported source mapping. Person records use
case-level normalized name groups, retaining source mentions and an unverified
identity status. Exact name matching does not establish identity.

Set `RELATIONSHIP_EXTRACTOR=gemini` and configure `GEMINI_API_KEY` and
`GEMINI_MODEL` to use Gemini for narrative relationships. It receives source
passages and existing entity labels, types, and local aliases, with short
request-local IDs mapped back to database IDs; it cannot create entities.
Proposals must use existing IDs and an exact supporting source quote,
then pass local endpoint/evidence validation before storage. Gemini responses
are not proof that every real relationship has been found or correctly
interpreted. Recognized call tables remain deterministic in either mode.
`RELATIONSHIP_EXTRACTOR=regex` selects the optional local narrative rules instead;
an omitted setting also defaults to regex. The legacy `ENABLE_LLM_EXTRACTION`
setting has no effect. Every extracted relationship remains pending investigator
review, and co-occurrence alone never creates an edge. The case assistant is
separate from this extraction choice.

Upload responses expose `nlp`, `warnings`, `storage.saved`, and
`relationshipStatus` (`mode`, `attempted`, `succeeded`, and `complete`). If Gemini
is unavailable, rate-limited, blocked, or returns an invalid/truncated response,
entities and the original upload can still be saved while the source shows
Relationships pending. Counts then describe saved findings, not a completed
relationship analysis. Use Reanalyze to retry. Reanalysis preserves existing
findings when the provider fails rather than replacing them with zero or partial
results. Storage failures remain visible and are not reported as successful
persistence.

Compact narrative context is enabled by default. It keeps entity-bearing
sentences and their neighbours, batches separately marked passages across
pages, and normalizes request whitespace. Original text, entity records, and
source offsets stay intact; every accepted quote must match an original
contiguous passage. If compaction would increase request count or omit entity
context, the original chunks are reused. Set `GEMINI_COMPACT_CONTEXT=false` for
full-context chunks when relationships may depend on more distant context.
Trimming can miss such relationships and produces a warning.

`relationshipStatus.input` exposes `originalChars`, `sentChars`,
`originalRequests`, `plannedRequests`, `passageCount`, and planning `mode`
(`entity-context` or `full-context`). These are character and planning metrics,
not model token counts. Compact JSON, short IDs, and passage batching reduce
input and request usage; they cannot bypass requests-per-minute or daily quotas
and do not guarantee avoidance of HTTP 429.

For offline tests, install `backend/requirements-dev.txt`, then run these commands
from `backend` in a dedicated PowerShell window:

```powershell
$env:RELATIONSHIP_EXTRACTOR = "regex"
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The explicit regex setting prevents regression tests from using a configured
live Gemini API. Gemini-specific tests select their mode and mock provider
responses; MongoDB tests use an emulator. Live database/provider connectivity
must be verified separately.

An investigator-facing hackathon demo for turning synthetic FIR/police-report text into an explainable relationship network. **All included records are fictional.** Scores and alerts are investigative leads only; they are not evidence or proof of criminality.

## What works

- Polished React + Cytoscape relationship graph
- FIR/report ingestion, spaCy and identifier entity extraction, normalization, evidence-validated candidate relationships, and report provenance
- Person, phone, vehicle, location, account, and organization entities
- NetworkX degree, betweenness, and PageRank analytics
- Explainable high-connectivity and shared-association lead rules
- Case search/selection, source timeline, case metrics, multiple-file uploads, and a natural-language investigation assistant
- FastAPI backend with MongoDB/GridFS persistence for case uploads and findings; optional Neo4j mirroring

## Fastest path on Windows: Docker Desktop

1. Install and start [Docker Desktop](https://www.docker.com/products/docker-desktop/). Enable its WSL 2 integration when prompted.
2. In PowerShell, open this folder:

   ```powershell
   cd C:\Users\prasa\Documents\Codex\2026-09-12\referenced-chatgpt-conversation-this-is-an\criminal
   Copy-Item .env.example .env
   docker compose up --build
   ```

3. Open `http://localhost:5173`. The API docs are at `http://localhost:8000/docs`; Neo4j Browser is at `http://localhost:7474` (user `neo4j`, password `change-me`).
4. Stop with `Ctrl+C`. To remove only the containers, run `docker compose down`. Keep the database volumes unless you intentionally want to erase their stored data.

## Local development (without Docker)

Install Python 3.12+ and Node.js 20+. In one PowerShell window:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

In another:

```powershell
cd frontend
npm install
npm run dev
```

If PowerShell prevents virtual environment activation, run this once for the current window: `Set-ExecutionPolicy -Scope Process Bypass`.

## Architecture

`frontend/` is the React/Vite UI. `backend/app/main.py` serves case-scoped API
routes. `file_reader.py` preserves source pages, paragraphs, and table rows;
`extraction.py` uses the installed spaCy model and identifier rules for entities.
`structured_calls.py` maps recognized call tables directly into events.
`relationship_context.py` plans compact narrative passages;
`gemini_relations.py` batches them and validates Gemini proposals against
original source spans. `llm.py` uses short request-local IDs and compact,
schema-constrained Gemini requests with credentials kept on the
backend. `relations.py` and `relationship_rules.json` provide the optional regex
mode. `mongo_store.py` persists originals, metadata, entities, mentions, and
relationships. NetworkX calculates case graph metrics; Cytoscape renders nodes,
labeled connections, and the supporting source statements.

MongoDB is the read repository for the UI's case workspace. GridFS stores the
original bytes for download and reanalysis. Session caches support legacy graph
routes and the assistant's source-text context; they do not replace durable case
storage. `neo_store.py` can mirror findings to Neo4j when configured. Model and
rule scores are not calibrated probabilities; provenance and pending review
state remain attached to findings.

## Responsible-use guardrails

- Keep raw source reports, confidence, analyst review state, and provenance with all findings.
- Never represent graph centrality or rule matches as guilt, identity verification, or a legal conclusion.
- Require authorized access, human review, retention controls, audit logging, and jurisdiction-specific privacy/legal review before using real-world data.

## Hosting on Render

Deploy the API first from the repository root using `render.yaml`. Set `GEMINI_API_KEY` in Render's secret-environment-variable prompt; never commit it. Once Render provides the API URL, deploy `frontend/` as a Static Site with build command `npm install && npm run build`, publish directory `dist`, and build-time environment variable `VITE_API_URL` set to the API URL. Finally set the API service's `FRONTEND_ORIGIN` to the Static Site URL and redeploy it.

## Original file storage

Each upload returns `documentId` and `fileStorage.saved`, alongside extraction
results. File metadata includes case ID, filename, SHA-256, byte size and
processing status. Entity mentions and reports reference the original document.
If parsing fails, the original is retained with a failed processing status.
Unsupported extensions and files exceeding 10 MB are rejected before storage.

- `GET /api/cases/{case_id}/documents`: list up to 1,000 documents for a case.
- `GET /api/cases/{case_id}/documents/{document_id}/download`: retrieve original bytes.

These endpoints enforce case matching but do not yet implement user authentication
or case permissions. The UI searches/selects stored cases, lists their files,
and supports downloading and reanalyzing individual source records.

## Relationship extraction

For narratives, `RELATIONSHIP_EXTRACTOR=gemini` uses the existing local entities
and requests source-grounded relationships such as CALLED, MET, USES, OWNS,
TRANSFERRED_TO, employment, location, and family links. Unknown endpoints,
unsupported types, invalid source quotes, and locally detected negated or
uncertain evidence are rejected. Allegations and attributed statements remain
reported evidence. No entity comes from Gemini, and no model-generated
confidence is treated as a calibrated probability.

In optional regex mode, `backend/app/relations.py` anchors explicit English
connectors to extracted mentions using `relationship_rules.json`. The supported
wording is narrower; unmatched phrasing produces no edge. Its 0.85 confidence is
a heuristic score, not a calibrated probability. See
[`backend/RELATIONSHIP_RULES.md`](backend/RELATIONSHIP_RULES.md) for rule editing
and the complete ingestion/reanalysis behavior.

Relationships are upserted in MongoDB `relationships` with case, report and
document IDs, and exposed by `GET /api/cases/{case_id}/relationships`. Each
finding retains source span, evidence, source location, extraction version, and
pending review state. Repeated interactions at different spans remain separate.
Reanalyze applies the currently selected mode to an existing stored source;
changing configuration alone does not reprocess every case. Recognized call
tables use column mapping in either mode; unsupported schemas still need a
mapping.

Examples: `Phone 9876543210 called phone 9123456789.` and
`Account 001234567890 transferred INR 5000 to account 009876543210.`
Person rules depend on the trained NER model recognising both names correctly.

### Reference frontend
The frontend follows the ten screens in `frontend/references`: landing page, overview, intake and upload menu, graph explorer with entity tabs, leads with case assistant, investigation-type modal, and new-case modal. Light/dark mode is saved on the device; layouts adapt to mobile. Typography uses Arial for headings/body and Courier New for technical labels, matching the visual style of the screenshots (the original font files were not supplied).

New cases are stored through `POST /api/cases`; `GET /api/cases` supplies title search and selection. `GET /api/cases/{case_id}/workspace` supplies case-filtered graph, source files, connection rankings, and evidence-supported review leads. Uploads retain their selected source type and investigation type in document metadata. Graph search, type filters, zoom/fit/reset, entity tabs, file downloads, and lead evidence expansion are connected to actual case records. The assistant receives the selected case ID.

The entry form is demo access, not authentication. MongoDB is required for case creation and durable uploads. The UI displays connection/storage errors and empty states rather than sample case statistics. Views currently cap each collection at 1,000 records and display a truncation notice. Assistant source text currently comes from the current backend session; graph and uploaded originals persist in MongoDB.

Validation: run `npm run build` from `frontend`, and the offline PowerShell test
commands above from `backend`. Case-management tests use isolated mock MongoDB,
never the configured Atlas cluster.

### Duplicate prevention and graph labels
Uploads are compared by SHA-256 of their bytes within the selected case. A completed identical upload with the current extraction version returns its existing document/report IDs and findings. If the extraction version is older, the original and report are reused while findings are reanalyzed; no second file is stored. Renaming a file does not bypass this check; changed contents do. Deterministic document IDs reserve new uploads before writing GridFS bytes, preventing parallel identical requests from writing two original files. Pending/failed duplicates return a conflict instead of storing another copy. Existing duplicate documents are retained; no historical evidence is purged.

New API extractions use case-level normalized name groups, with `identityStatus: unverified-name-group`, while preserving report IDs and individual source mentions. Exact name matching is not identity verification. The workspace groups historical spelling duplicates for display and maps their relationship endpoints to the displayed node. Historical records remain intact.

Graph edges show short labels (`called`, `met`, `connected to`, `child of`, `posted at`, etc.). Repeated directed relationships share one visual edge with a multiplier and retain every source statement for inspection. The initial view focuses on connected entities when relationships exist. All Entities includes isolated entities in a separate grid. Full labels fit inside measured nodes, and a compact layout keeps connections visible. Frontend edge grouping can be checked with `node frontend/src/graphData.test.mjs` from the repository root.

Entity counts describe unique stored nodes; relationship counts describe saved
source statements/events. The number of visual connections can be smaller when
repeated events share one labeled edge. These counts report extraction output,
not a guarantee of the exact real-world totals.

### Case management
Select a case and use **Manage Case** in the workspace header. **Clear Case Data** permanently removes the selected case's uploaded originals (GridFS files/chunks), documents, reports, entities, mentions, and relationships while keeping its title, summary, and classification. **Delete Case** also removes the case record. Both actions require typing the case title in a confirmation dialog; no existing cases are removed just by adding these controls. A processing file blocks cleanup until processing finishes.

The endpoints are `DELETE /api/cases/{case_id}/data` and `DELETE /api/cases/{case_id}`. Their JSON body must contain `confirm_case_id` matching the path. Cleanup is case-scoped and also clears the corresponding session report/graph cache and the device's current-case draft. Other cases are preserved. Without database transactions, a storage failure can leave partial cleanup; the UI reports the failure rather than claiming success. A missing or mismatched file ownership record blocks cleanup for review. Case-management tests run against mock storage only.


Multiple source files can be selected together with Ctrl/Shift or dropped onto Input. Later selections append rather than replace the queue. Each source has its own type, validation, status and extraction counts. The batch continues after individual failures; failed files remain for retry and successful files are not submitted again. Tests: `node frontend/src/uploadQueue.test.mjs`.

Structured call logs map caller/receiver phone columns directly to CALLED events, retaining timestamp, duration, tower, source case ID and original row evidence. Generic FROM/TO headers require call-specific columns; transfer tables are not inferred to be calls. CSV, TSV, XLSX sheets and DOCX tables keep independent mappings. Source Records show stored entity and relationship counts. `/health` checks the current MongoDB connection rather than trusting a handle created at startup; REFRESH reloads the selected case.
