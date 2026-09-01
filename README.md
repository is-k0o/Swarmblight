# Swarmblight

> A multi-agent WebSec swarm with specialized rats,
> shared memory and questionable internal governance.

Swarmblight is a small Discord-driven WebSec analysis foundation. It analyzes text, HTTP messages, and logs pasted manually by a user. V0.6.3 is still not a scanner, crawler, autonomous pentester, browser operator, or exploit framework, and it sends no traffic to a target.

## Core philosophy

> Specialists are creative.
> The system around them is skeptical.

The LLM agents generate observations, hypotheses, discriminating tests, evidence interpretations, and research questions. Deterministic code owns state transitions, policy, budgets, and general evidence checks. A human remains the final authority for confirmation and high-level research jumps.

```text
                    Policy + budget
                    (physical laws)
                           |
                           v
Discord !swarm ---> Horned Rat <------------------------+
                           |                             |
                           | approved tasks only         | structured reviews
                           v                             |
                  Queek / Ikit / Snikch -----------------+
                           |
                           v
                 EvaluationEngine
                           |
             observation -> hypothesis -> evidence
                           |
                           v
               human-reviewable finding
                           |
                           v
               optional cascade questions
                           |
                   SQLite -> renderer
```

Horned Rat has authority over the specialist agents. It does not have authority over system policy or budget. Specialists cannot invoke one another: `peer_review_request` is advisory, and only a subsequent Horned Rat `AgentRequest` can create another round.

## Evidence model

V0.5 makes three concepts explicit:

- **Observation:** supplied or directly visible fact. It is not automatically a vulnerability.
- **Hypothesis:** candidate explanation or security issue, preferably with a discriminating test. Unknown tests are represented as `null`.
- **FindingCandidate:** a demonstrated chain preserved for human review: observations → hypothesis → evidence → deterministic evaluation.

Evidence levels are `observation`, `candidate`, `supported`, `demonstrated`, and `confirmed`. Agents may propose a level, but `EvaluationEngine` independently evaluates it. Agent interpretation alone cannot create a finding. A proposed `confirmed` level is capped, and confirmation remains human-only.

Critical facts such as demonstrated execution, unauthorized access/action, server acceptance, and security impact are represented by typed `EvidenceFact` values. `EvidenceItem.description` is presentation text and never satisfies a critical fact through keyword matching. Textual `required_evidence` entries are satisfied only through an explicit positive `satisfies_required_evidence` link from independent evidence. Contradictory evidence participates in evaluation and blocks demonstrated status; a typed deterministic contradiction may refute the hypothesis.

The initial deterministic guardrails include:

- controllable input is not an exploitable sink;
- unexpected response is not security impact;
- client-controlled identifier is not IDOR;
- editable JWT is not JWT bypass;
- account A/B differences are not authorization bypass without demonstrated unauthorized access or action.

This is a general evaluation framework, not an encoded copy of OWASP.

## Knowledge Forge

V0.6 adds the first real specialist knowledge pipeline for Ikit only; V0.6.1 hardens its live API and resume lifecycle, V0.6.2 tightens ingestion hygiene, and V0.6.3 aligns the critic's provider/local contract and diagnostics:

```text
Local Markdown/text source
          |
          v
 frontmatter provenance
  + deterministic chunk
          |
          v
 LLM card generator
          |
          v
 bounded LLM critic
          |
          v
deterministic validation
          |
          v
 local deduplication
          |
          v
approved KnowledgeCard
          |
          v
 bounded retrieval (<= MAX_KNOWLEDGE_FRAGMENTS)
          |
          v
         Ikit
```

The forge accepts local `.md`, `.markdown`, and `.txt` files only. It does not fetch URLs, crawl Academy material, or contact bounty targets. For curated Markdown, constrained YAML frontmatter supplies canonical `source_title`, `source_reference`, `agent`, `topic`, `source_type`, and corpus metadata. The local filesystem path is retained separately as `source_path`; it is not substituted for a supplied canonical URL. Frontmatter is never sent to the LLM or emitted as a chunk, and a conflict with explicit routing metadata fails ingestion. Link-only `Read more`/navigation sections are omitted conservatively, while prose and technical lists containing links remain available.

Source documents, chunks, card provenance, critic/validation metadata, and forge-run state are persisted in the same SQLite database. Interrupted builds resume from `pending` and `retryable` chunks and do not regenerate `processed` chunks. Generator and critic calls each follow `authorize_call()` → LLM → durable accounting; budget exhaustion stops cleanly and leaves remaining chunks resumable.

Cards are short reusable mental models, not lab recipes. `MAX_CARD_CHARS` is enforced without silent truncation. A generator call returns zero to three concise cards; zero remains valid and prose is not summarized merely to fill the batch. General WebSec correctness never licenses imported knowledge, but field fidelity is semantic rather than lexical: factual claims, operational derivations, labels, routing edges, Forge metadata, extrapolation, and application-owned state have different owners and rules. `speculative_extensions` is the only place for clearly labeled, reasonable bounded extrapolation. Unsupported pretrained knowledge is deleted, simplified, or rejected by the critic, and empty optional fields are preferred to invented detail. Academy material is not converted into Research-style claims.

### KnowledgeCard field ownership

The prompt constant `KNOWLEDGE_CARD_FIELD_SEMANTICS` is the authoritative contract shared by Generator, Critic, and Source Fidelity Gate. Their roles remain separate: construct, revise/review, and read-only admission.

| Field | Class | Producer / owner | Runtime consumers | Source-fidelity rule |
|---|---|---|---|---|
| `subtopic` | semantic label | Generator; Critic may revise | retrieval score, dedup, Ikit display | Semantically representative; literal source wording is unnecessary. |
| `title` | semantic label | Generator; Critic may revise | deterministic card ID input, retrieval, dedup, CLI | Same semantic-relevance rule; an unrelated implied concept fails. |
| `tags` | semantic label | Generator; Critic may revise | tag filters and retrieval ranking | Faithful categorization may introduce labels such as `taxonomy`; unrelated labels fail. |
| `triggers` | derived operational | Generator; Critic may revise | trigger filters and high-weight retrieval ranking | A source-supported claim may become a search/recognition cue; no new mechanism or condition. |
| `principle` | source factual | Generator; Critic may revise | ID input, validation, retrieval, dedup, Ikit display | Every proposition is direct or a faithful abstraction no stronger than the chunk. |
| `questions_to_ask` | derived operational | Generator; Critic may revise | validation and Ikit display | May turn a supported proposition or prescription into a diagnostic/compliance question while preserving modality. |
| `false_positive_traps` | source factual | Generator; Critic may revise | Ikit display | The asserted trap and its causal distinction must be source-supported. |
| `evidence_required` | derived operational | Generator; Critic may revise | validation and Ikit display | Minimum observable evidence or compliance check for the supported payload; source modality must remain intact. |
| `escalation_topics` | routing metadata | Generator; Critic may revise | persisted only today; reserved as a dormant adjacency edge | The source/card must justify semantic adjacency; target curriculum availability is separate. |
| `technique_assumptions` | source factual | Generator; Critic may revise | research validation and Ikit research display | Any claimed assumption or availability condition must be source-supported. |
| `prerequisites` | source factual | Generator; Critic may revise | research validation and Ikit research display | Any prerequisite must be source-supported, not inferred from general practice. |
| `demonstrated_behavior` | source factual | Generator; Critic may revise | research validation and Ikit research display | Must describe only behavior demonstrated or stated by the chunk. |
| `speculative_extensions` | explicit extrapolation | Generator; Critic may revise | research validation and Ikit research display | Bounded extrapolation is allowed only here and must remain isolated. |
| `confidence` | Forge metadata | Generator; Critic may recalibrate | persisted and retrieval tie-break | Advisory fidelity/reusability confidence; not source-owned and not an approval claim. |
| `id` | provenance/state | application (`uuid5`) | identity, persistence, display | Not judged as a source proposition. |
| `agent` | provenance/state | ingested document/application | Ikit-only validation and retrieval filter | Deterministic routing ownership. |
| `topic` | provenance/state | ingested document/application | retrieval ranking/filter, dedup, display | Primary ontology assignment, separate from LLM field fidelity. |
| `source_type` | provenance/state | ingested document/application | validation, retrieval weighting, display | Deterministic provenance. |
| `source_title` | provenance/state | ingested document/application | persistence and Ikit provenance display | Deterministic provenance. |
| `source_reference` | provenance/state | ingested document/application | validation, persistence and Ikit display | Deterministic provenance. |
| `source_chunk_id` | provenance/state | application | exact source association, validation and display | Deterministic provenance. |
| `status` | provenance/state | Forge or explicit human CLI action | admission, retrieval filter, CLI | Workflow state, never an LLM source claim. |
| `created_at` | provenance/state | application | ordering and audit | Application-owned timestamp. |
| `updated_at` | provenance/state | application | ordering and audit | Application-owned timestamp. |

`evidence_required` specifically means the minimum observable evidence that would substantiate the card's source-supported payload. It is not evidence that the source literally prescribes, and it is not a generic penetration-testing workflow. An operational item must preserve both payload and modality: a descriptive proposition may become a check whether that proposition holds, while a normative prescription may become a check whether the relevant implementation conforms. The latter does not assert that conformity is already implemented or that nonconformance currently occurs. This distinction is semantic rather than keyword-based. New mechanisms, states, actor or authentication qualifiers, request paths, preconditions, outcomes, causal chains, implementation assumptions, guarantees, or stronger proof requirements still fail. The same rule applies to `questions_to_ask`; `triggers` may turn supported meaning into a concise retrieval cue.

The repository keeps four distinct layers: the source corpus is local material potentially available for ingestion; ingested documents are the subset represented in Forge; the approved knowledge corpus contains admitted cards; and `KnowledgeTopic` defines the topic ontology/routing space. Mentioning `sqli` or `dom` in a source, semantic label, or justified adjacency edge does not assert that approved curriculum for that topic is currently populated.

Generator output starts as `candidate`; only critic approval, deterministic validation, any enabled source-fidelity admission, and deduplication can promote it automatically. Card `confidence` is an advisory Forge-model meta-confidence, initially set by the generator and optionally recalibrated by the critic; it is range-checked but is not a source-derived claim or an approval gate. The critic contract is schema-native: `approve` and `reject` variants cannot contain a revised card, while `revise` requires one. The union is nested under a root object so the same invariant is visible to Structured Outputs and local Pydantic validation. The critic can revise at most `MAX_CARD_REVISIONS` times. Exact provenance is attached by code, not supplied by the LLM.

V0.6.5 adds an independent `SourceFidelityGate`, disabled by default with `SOURCE_FIDELITY_GATE_ENABLED=false`. When enabled, it sees only the exact current chunk and the final validated card, cannot rewrite the card, and applies the class-specific field contract before deduplication. `pass` continues admission; `fail` preserves the card as `candidate` with an auditable fidelity record and blocks automatic approval. Retryable late-stage failures resume from `fidelity_pending`/`retryable` without rerunning Generator or Critic. `confidence` and isolated `speculative_extensions` are outside its source-support field set; V0.6.5.1 adds the LLM-owned `subtopic` label to mandatory gate coverage. V0.6.5.4 makes DERIVED_OPERATIONAL admission modality-aware: checking compliance with a source prescription is not misread as a claim that the prescribed state already exists.

### Provider response lifecycle

The OpenAI adapter obtains the raw Responses API JSON before Pydantic validation. It records response ID, request ID, model, status, `incomplete_details`, and usage, extracts `output_text`, and only then validates the requested schema. It never calls the raw SDK response's post-parser.

These are three distinct events:

```text
Provider response received
        !=
structured output valid
        !=
KnowledgeCard approved
```

An HTTP 200 response with truncated or malformed structured JSON can therefore fail card generation while still retaining its billable usage. `status=incomplete` with `reason=max_output_tokens` raises a typed retryable error instead of being flattened into “invalid JSON”. Other explicit incomplete reasons, refusals, and completed-but-invalid schemas retain their distinct typed response errors and metadata.

Completed structured-validation failures expose safe diagnostics: response/status identifiers, schema name, output character length, error count, and concise Pydantic `loc`/type/message entries. Logs and exceptions do not retain full prompts, source documents, credentials, or arbitrary complete model output.

Academy/core cards describe stable methodology. Research cards retain explicit assumptions, prerequisites, publication/source references, and speculative extensions. Ordinary retrieval prefers core and admits at most a small amount of research. Retrieval uses deterministic topic, trigger, tag, and keyword scoring—no embeddings or vector database.

> More context is not automatically better.

> Ikit cannot write his own scripture.

An Ikit lesson or previous answer cannot write directly to approved knowledge. Promotion still requires source/provenance → candidate → critic → validator → `KnowledgeStore`.

### Knowledge is not evidence

A retrieved card can suggest a source-to-sink model, diagnostic question, false-positive trap, or evidence expectation. It cannot establish execution, unauthorized behavior, server acceptance, or impact in the current analysis. The Ikit context marks cards as fallible reference material below system policy.

### Forge CLI

```powershell
python forge.py ingest .\sources\dom-notes.md --agent ikit --source-type academy --topic dom
python forge.py build <document-id>
python forge.py build <document-id> --retry-failed
python forge.py purge-document <document-id>
python forge.py list --kind documents
python forge.py list --kind cards --status approved --topic dom
python forge.py inspect <card-or-document-id>
python forge.py search "DOM setAttribute context"
python forge.py reject <card-id> --reason "Too lab-specific"
python forge.py approve <card-id>
python forge.py fidelity-check <card-id> --repeat 1
python forge.py fidelity-eval <case-id> --repeat 1
python forge.py fidelity-eval-batch <case-id> [<case-id> ...] --repeat 1
```

`build` processes `pending` and `retryable` chunks. Permanent `failed` chunks are not retried automatically. `--retry-failed` explicitly requeues only failed chunks for that document; it preserves processed chunks and existing candidate, approved, rejected, or superseded cards. Repeated use is idempotent once no failed chunks remain. `--skip-critic` deliberately leaves generated cards as candidates; it never auto-approves them. The `approve` command refuses cards that lack recorded critic approval or deterministic validation.

`purge-document` transactionally removes one document, its chunks and forge runs, and cards whose primary `source_chunk_id` belongs to that document, including their embedded review state. For a card originating elsewhere, only an added source association to the purged document is removed. The command preserves foreign cards and documents, sessions, API/usage rows, `budget_uncertain_usage`, pricing configuration, and the SQLite database file itself. An unknown ID fails without mutation and the command prints a JSON removal summary.

`fidelity-check` is a manual calibration harness for an existing card and its exact associated chunk. It never changes cards, critic/fidelity review state, chunks, runs, or documents and never persists its verdict. `--repeat` is bounded to 1-5 and reports each result separately without majority voting. A retryable incomplete response is reported per attempt with its reason, response ID, usage, and reasoning-token count, then later repetitions continue without a traceback; non-retryable or accounting failures still stop the command. A real evaluation still uses the mandatory `BudgetManager` path, so actual or uncertain provider usage is durably added to the usage ledger even though knowledge/Forge state remains read-only.

`fidelity-eval` measures one target field from `tests/corpus/knowledge_card_field_semantics_cases.json` against that fixture's exact `source` text. The legacy fixture keys are normalized in memory to `case_id`, `semantic_class`, `source_text`, `target_field`, `candidate_value`, `expected_verdict`, `rationale`, and optional `boundary_kind`; fixture truth is not copied into runtime code. The synthetic `KnowledgeCard`, document, and exact chunk exist only in memory. Optional non-target card fields remain empty, while the required `subtopic`, `title`, and `principle` use only verbatim source text, bounded at word boundaries when their schema limits require a prefix, so the harness introduces no second WebSec claim while preserving the complete source in the chunk. This satisfies the `KnowledgeCard` schema without running the production admission validator, whose retrieval-oriented tag/diagnostic requirements would add unrelated judged content. If a target cannot be represented by a neutral schema-valid card, the command reports `not_evaluable` before any provider call.

Each repetition is reported independently; there is no vote. `target_detected_count` counts completed runs whose issues name the fixture's target field. For an expected `fail`, a matching global verdict is a semantic match only when that target was detected; a failure attributed solely to another synthetic field remains a miss. For an expected `pass`, any issue/failing verdict is a miss. No card, chunk, document, run, or fidelity review is persisted, but the normal `BudgetManager` still durably records actual or uncertain provider usage.

`fidelity-eval-batch` is a sequential read-only wrapper over that exact evaluator path. It preflights every requested case before constructing the API client: unknown IDs, duplicate IDs, and non-constructible cases reject the whole batch without starting calls. Duplicate IDs are rejected rather than deduplicated. `--repeat` remains bounded to 1-5 per case. Aggregate counts sum independent attempts and semantic matches; `all_expected` means every planned attempt matched its fixture semantics with no incomplete or prematurely stopped case, not a majority vote. Target totals cover expected-FAIL cases only. A non-retryable incomplete stops repetitions for its current case, is named in `summary.stopped_cases`, and does not silently remove later cases. Any other non-evaluator failure remains fail-fast and names the case that stopped. Synthetic knowledge state remains in memory while normal budget accounting persists for every provider observation.

## Knowledge, memory, evidence, and lessons

- **Knowledge** is curated methodology stored as short Markdown fragments and approved SQLite `KnowledgeCard` records. Keyword/tag retrieval selects at most `MAX_KNOWLEDGE_FRAGMENTS`; the full corpus is never injected automatically.
- **Memory** is session state: messages, agent runs, open hypotheses, observations, decisions, evaluations, findings, and usage.
- **Evidence** is an item explicitly linked to one hypothesis, including its source, type, direction, confidence, and agent-proposed level.
- **Lessons** are durable discoveries with tags and optional source hypotheses. They are persisted but not generated or injected aggressively.

`MemoryStore` and `KnowledgeStore` are lightweight protocols. `SQLiteMemoryStore` and `SQLiteKnowledgeStore` keep V0.6 local and replaceable without an ORM or a second database backend.

## Bounded context and routing

Each analysis call receives only:

- the agent's role prompt;
- the current manually supplied request;
- relevant open hypotheses;
- a small targeted set of knowledge fragments, plus approved cards for Ikit only;
- policy and, for coordinator reviews, remaining budget context.

`MAX_AGENT_ROUNDS` and `MAX_SPECIALISTS_PER_ROUND` are enforced by `PolicyEngine`, outside the prompts. Browser automation, scanning, crawling, payload execution, and target network requests are forbidden action types in code.

Cascade questions default to:

- “How could similar behavior be detected elsewhere?”
- “Could the underlying cause enable a different attack class?”

They create optional research directions only. They never launch tests automatically.

## Budget and pricing

`BudgetManager` runs before every LLM call. It keeps a normal characters-per-token estimate for telemetry, but hard authorization does not rely on that average. The reservation pessimistically counts the UTF-8 byte size as input tokens and adds a fixed protocol-envelope reserve, then adds the effective output-token ceiling for the call. It checks daily tokens plus daily, monthly, and per-run USD limits against that conservative reservation.

The accounting invariant is stricter than API success: a reservation never disappears after a provider response has been received unless that response's usage has first been persisted. Valid structured output and response-bearing parse/incomplete errors both call `finalize()` with actual reported usage before returning or re-raising. A definite pre-response rejection may cancel without creating fake usage.

Cancellation, Ctrl+C, timeout, connection loss, or another outcome that may have occurred after dispatch is ambiguous. V0.6.1 persists the conservative maximum reservation in `budget_uncertain_usage`, then releases the in-memory reservation. Subsequent daily and per-run token/USD checks include that unresolved conservative charge. It is explicitly stored as uncertain reservation accounting, never mislabeled as known provider usage. Any persistence failure leaves the reservation active and fails closed.

Prices are not embedded in Python. Add only verified current prices for exact configured model IDs to `pricing.json`, using numeric fields:

```text
models
  exact-model-id
    input_usd_per_million_tokens
    output_usd_per_million_tokens
```

USD limits are disabled when set to `0`. When any USD limit is active and the configured model has no known price, `FAIL_ON_UNKNOWN_PRICING=true` refuses the call before contacting the LLM.

## Installation

Use Python 3.12 or newer:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill in at least:

```dotenv
DISCORD_TOKEN=your-discord-bot-token
DISCORD_CHANNEL_ID=123456789012345678
OPENAI_API_KEY=your-openai-api-key
COORDINATOR_MODEL=your-exact-coordinator-model
SPECIALIST_MODEL=your-exact-specialist-model
```

An empty `DISCORD_CHANNEL_ID` allows commands in every visible channel. For a real server, set it explicitly. Enable Discord's privileged **Message Content Intent**, then give the bot permission to view and send messages in the configured channel.

## Run and commands

```powershell
python app.py
```

SQLite is created automatically at `data/warpstone.db`. Existing V0/V0.5/V0.6 databases are migrated in place. V0.6 adds `knowledge_documents`, `knowledge_chunks`, `knowledge_cards`, `knowledge_card_sources`, and `knowledge_forge_runs`. V0.6.1 additively creates `budget_uncertain_usage`; V0.6.2 additively adds `source_path`, `corpus`, and `subtopic` document metadata. V0.6.3/V0.6.4 require no database migration. V0.6.5 additively creates `knowledge_fidelity_reviews`; existing usage, chunks, cards, critic reviews, forge runs, and successful outputs are preserved. V0.6.5.1 adds no column or table; any legacy fidelity `pass` lacking mandatory `subtopic` coverage is idempotently returned to `pending` for recheck, while prior failures remain blocked and auditable.

- `!swarm <text>` analyzes manually supplied material through the bounded workflow.
- `!status` shows open/closed hypotheses, stored analyses, tokens, and known cost.
- `!reset` explains the destructive reset; `!reset confirm` deletes the active session and starts a new one. Durable lessons keep their content and lose a deleted source link when applicable.

`SKAVEN_LEVEL=0` gives technical output. Level `2` gives obvious Skaven presentation while preserving technical data. The renderer never mutates stored structures.

## Configuration

See `.env.example`. Knowledge Forge uses:

- `MAX_KNOWLEDGE_FRAGMENTS=5`
- `MAX_CARD_CHARS=2500`
- `SOURCE_CHUNK_MAX_CHARS=6000`
- `MAX_CARD_REVISIONS=1`
- `SOURCE_FIDELITY_GATE_ENABLED=false`
- `MAX_OUTPUT_TOKENS=4000`
- `GENERATOR_MAX_OUTPUT_TOKENS=4000`
- `CRITIC_MAX_OUTPUT_TOKENS=6000`
- `FIDELITY_MAX_OUTPUT_TOKENS=4000`

Generator and critic calls use their stage-specific ceiling when configured; an absent stage setting falls back to `MAX_OUTPUT_TOKENS`, which remains the ceiling for unrelated LLM calls. The bounded fidelity verdict uses its dedicated 4000-token ceiling: the initial 2000-token calibration ceiling proved too small once reasoning and visible output shared the same limit. Responses API output limits include visible output and reasoning tokens. `BudgetManager` reserves the same effective ceiling sent to the provider, so raising any stage value does not bypass token or USD authorization.

Budget configuration remains:

- `DAILY_BUDGET_USD=0`
- `MONTHLY_BUDGET_USD=0`
- `MAX_COST_PER_RUN_USD=0`
- `PRICING_PATH=pricing.json`
- `FAIL_ON_UNKNOWN_PRICING=true`
- `ESTIMATED_CHARS_PER_TOKEN=4`

`DAILY_TOKEN_BUDGET` remains supported and is now checked against the estimated maximum of the next call before it starts.

## Tests

```powershell
python -m pytest
python -c "import app, budget, evaluation, forge, knowledge, knowledge_store, source_ingestion, policy, pricing, router, memory, renderer, schemas, llm"
```

Tests cover the original behavior plus evaluation caps, evidence linkage, lessons, policy and budget enforcement, raw HTTP response accounting, critic contract/schema equivalence, safe structured-validation diagnostics, incomplete and malformed structured output, conservative cancellation accounting, canonical frontmatter provenance, conservative navigation filtering, source-bounded generator/critic prompts, transactional document purge, retryable/failed chunk recovery, bounded Ikit-only retrieval, core/research ranking, and mocked end-to-end knowledge injection. Tests use fakes and temporary databases only and never contact the live API.

## Current limitations

- No autonomous traffic, Burp integration, browser, scanner, crawler, payload execution, or exploitation.
- Knowledge ingestion is local-file-only; URL fetching is intentionally deferred.
- V0.6 builds approved knowledge only for Ikit topics `xss`, `dom`, `sqli`, and `ssti`.
- Pricing data must be maintained manually and verified for exact model IDs.
- Input telemetry remains an approximate characters-per-token estimate. Hard budget reservation is separately based on UTF-8 bytes plus protocol overhead; it is deliberately pessimistic but is not a model-specific tokenizer.
- Evaluation rules are intentionally general and do not understand every vulnerability class.
- Lessons remain separate candidates and cannot bypass the knowledge forge trust path.
- One active global session, without per-user or per-channel isolation.
- No rich Discord embeds, advanced permissions, automatic malformed-output repair, vector database, or external infrastructure.
