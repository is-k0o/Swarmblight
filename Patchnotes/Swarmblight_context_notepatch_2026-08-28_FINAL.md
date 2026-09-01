# Swarmblight — Contexte projet & notepatch
**Date : 2026-08-28**  
**État couvert : fin de session du 2026-08-28 — autopsie Critic, hardening Structured Output, correction `confidence`, rebuild canonique propre partiel sous budget journalier**

---

## 1. Vue d'ensemble

**Swarmblight** est un système local Python de raisonnement WebSec multi-agents, inspiré notamment des retours sur les agents LLM et du travail PortSwigger/James Kettle. Le principe général est de laisser les LLM proposer des hypothèses, tout en faisant contrôler la validation, l'état, les budgets et les invariants par du code déterministe et par l'humain.

Référence de nom : **Skavenblight**.

Le système reste volontairement **text-only** pour le moment et interdit l'activité réseau/targeting autonome.

### Agents

- **Queek / LogicRat** : business logic, authz, IDOR/BOLA, workflows/états, races, prix/quantités, mass assignment.
- **Ikit / InjectionRat** : XSS/DOM, SQLi, SSTI, command injection, analyse source → transformation → sink, distinction contrôlabilité/reachability/exécution/impact.
- **Snikch / IdentityRat** : auth, sessions, cookies, JWT/JWK/JWKS, OAuth/OIDC, reset/MFA, CSRF/SameSite, refresh tokens, identity confusion.
- **Horned Rat** : coordinateur ; autorité logique sur les spécialistes, mais les règles déterministes de policy/budget restent au-dessus de lui comme des « lois de la physique ».
- **Thanquol** : rôle futur envisagé d'adversarial reviewer, mais **pas prioritaire actuellement**. Priorité : **Ikit d'abord**.

---

## 2. Doctrine d'architecture

Principe directeur :

> **Specialists are creative. The system around them is skeptical.**

Répartition :

- **LLM** → hypothèses, abstraction, raisonnement, propositions.
- **Code** → validation, état, budget, policy, invariants.
- **Humain** → jugement final, arbitrage, grands sauts conceptuels.

Autres invariants :

> **Knowledge ≠ Evidence**

> **Ikit cannot write his own scripture.**

Une carte de connaissance ne devient jamais une preuve d'une vulnérabilité.

---

## 3. Stack / contraintes

- Python 3.12+
- `discord.py`
- OpenAI Python SDK
- Pydantic
- `sqlite3`
- fichiers principaux : `app.py`, `config.py`, `router.py`, `agents.py`, `memory.py`, `renderer.py`, `schemas.py`, `llm.py`, `budget.py`, `forge.py`, `knowledge_store.py`, `source_ingestion.py`, etc.
- commandes Discord : `!swarm`, `!status`, `!reset`
- base : `data/warpstone.db`
- knowledge : `knowledge/`

Pas de Docker, Redis, Celery, PostgreSQL, FastAPI ni framework multi-agent lourd. Pas de navigation Web autonome.

---

# 4. Historique avant Knowledge Forge

## V0.5

Introduction de :
- `evaluation.py`
- `policy.py`
- preuves typées
- hypothèses typées
- findings typés
- discriminating tests
- bounded context
- lessons/cascade
- `BudgetManager`
- abstraction `MemoryStore`

## V0.5.1 — evidence hardening

Suppression de l'inférence lexicale de preuve.

Ajout de `EvidenceFact` :
- `execution_demonstrated`
- `unauthorized_access_demonstrated`
- `unauthorized_action_demonstrated`
- `server_acceptance_demonstrated`
- `security_impact_demonstrated`
- `discriminating_test_passed`
- `hypothesis_contradicted`

Ajouts :
- `Hypothesis.required_facts`
- `EvidenceItem.facts`
- `satisfies_required_evidence`

Gestion explicite des negative evidence et hypothèses `refuted`. Pas de finding pour hypothèse refuted/closed.

## V0.5.2 — budget conservateur

Réservation conservatrice :
- bytes UTF-8 complets
- + 512 bytes de réserve protocole
- approximation 1 token/byte pour l'autorisation worst-case

Règles :
- `finalize()` persiste l'usage avant de libérer la réservation
- échec de persistence → réservation reste active / fail-closed

Limites théoriques connues :
- réservations RAM-only → crash processus possible avant durabilisation
- réserve protocole de 512 à revisiter plus tard
- affichage `remaining_context` ne soustrait pas forcément les réservations actives, mais l'enforcement oui

---

# 5. V0.6 — Knowledge Forge

## Objectif

Construire le cerveau d'Ikit à partir de sources documentaires sans écrire manuellement chaque skill card.

Pipeline :

```text
Source
  ↓
chunking déterministe
  ↓
Generator LLM
  ↓
Critic LLM
  ↓
Validator déterministe
  ↓
Dedup
  ↓
KnowledgeCards approuvées
  ↓
retrieval borné
  ↓
Ikit
```

Contraintes :
- pas de crawling autonome
- sources fournies localement
- Academy/core et Research séparés
- XSS, DOM, SQLi, SSTI comme premiers domaines Ikit
- pas d'embeddings/vector DB au départ
- Generator et Critic passent par `BudgetManager`
- pipeline resumable
- auto-approval seulement si generator + critic + validator acceptent
- provenance stricte
- tests synthétiques uniquement

CLI Forge :

```powershell
python forge.py ingest .\sources\xss.md --agent ikit --source-type academy --topic xss
python forge.py build <document-id>
python forge.py list --kind cards --status approved
python forge.py inspect <card-or-document-id>
python forge.py search "DOM setAttribute context"
python forge.py reject <card-id> --reason "Too lab-specific"
python forge.py approve <card-id>
python forge.py purge-document <document-id>
```

---

# 6. Corpus PortSwigger Ikit

## XSS core

8 documents + README :

1. `01_xss_overview.md`
2. `02_reflected_xss.md`
3. `03_stored_xss.md`
4. `04_xss_contexts.md`
5. `05_exploiting_xss.md`
6. `06_preventing_xss.md`
7. `07_content_security_policy.md`
8. `08_dangling_markup.md`

Chemin :

```text
D:\Swarmblight\sources\portswigger\academy\ikit\xss\
```

Politique : théorie/mental models/prévention ; pas de solutions de labs ; pas de gros payload catalogs dans les KnowledgeCards. Les cheat sheets pourront devenir une référence séparée plus tard.

## DOM core

19 documents + README : overview, DOM XSS, open redirect, cookie manipulation, JS injection, document-domain manipulation, WebSocket URL poisoning, link manipulation, web-message manipulation, Ajax request-header manipulation, local file-path manipulation, client-side SQLi, HTML5 storage manipulation, client-side XPath injection, client-side JSON injection, DOM-data manipulation, DOM DoS, web-message source, DOM clobbering.

Chemin :

```text
D:\Swarmblight\sources\portswigger\academy\ikit\dom\
```

**XSS et DOM restent deux curricula séparés.**

---

# 7. Frontmatter source

Format :

```yaml
---
agent: ikit
topic: xss
source_type: academy
source_title: "Cross-site scripting"
source_reference: "https://portswigger.net/web-security/cross-site-scripting"
corpus: ikit_xss_core_v1
---
```

Le frontmatter sert de provenance canonique.

---

# 8. API / environnement

Première utilisation API OpenAI pour le projet.

Solde initial : **20 USD**, auto-reload désactivé.

Modèle actuel : `gpt-5-mini`.

Tarifs enregistrés au setup :
- input : `$0.25 / 1M tokens`
- cached input : `$0.025 / 1M`
- output : `$2.00 / 1M`

`pricing.json` :

```json
{
  "_comment": "USD per one million tokens; verified for exact configured model.",
  "models": {
    "gpt-5-mini": {
      "input_usd_per_million_tokens": 0.25,
      "output_usd_per_million_tokens": 2.0
    }
  }
}
```

Note environnement : `.venv\Scripts` contient `python.exe`, `pip`, `pytest`, mais l'activation PowerShell est absente/bizarre. Workaround :

```powershell
.\.venv\Scripts\python.exe
```

---

# 9. Premier essai V0.6 — incident live

Premier document :

```text
sources\portswigger\academy\ikit\xss\01_xss_overview.md
```

Premier document ID historique :

```text
c0d85153-c326-5a4f-b6d2-0fe089458e5c
```

24 chunks initialement.

Problèmes observés :
- plusieurs HTTP 200 avec JSON structuré tronqué
- `MAX_OUTPUT_TOKENS=2000`
- certains appels Generator/Critic consommaient des tokens provider mais les erreurs de parsing pouvaient annuler la réservation locale
- Ctrl+C pendant un appel pouvait créer une ambiguïté de consommation
- frontmatter devenait un chunk
- `Read more` devenait un chunk
- provenance utilisait le chemin Windows local
- le modèle pouvait injecter des détails WebSec corrects mais absents du chunk

Ce premier essai a été abandonné comme expérience de calibration.

---

# 10. V0.6.1 — LLM lifecycle / accounting hardening

Résultat : **62 tests**, compileall OK, imports OK, aucun vrai appel API pendant tests.

### Lifecycle

Extraction depuis la réponse provider de :
- response ID
- status
- incomplete reason
- request ID
- usage
- output text
- puis validation Pydantic

### Cas incomplete

`status=incomplete` + `reason=max_output_tokens` → `IncompleteLLMResponse`. L'usage réel est persisté avant propagation.

### Cas completed mais JSON invalide

→ `InvalidLLMResponse`. Usage réel persisté avant re-raise.

### Interruption ambiguë

Ajout :
- `LLMAmbiguousInterruption`
- table `budget_uncertain_usage`

Si l'appel a pu partir mais qu'on ignore s'il a été facturé, persistance pessimiste de la réservation maximale comme usage incertain. Cela participe aux budgets run/jour sans être présenté comme usage provider exact.

### Retry

- `pending` + `retryable` traités par build normal
- erreurs permanentes → `failed`
- `--retry-failed` explicite pour requalifier les failed

### Generator

0 à 3 cartes ; 0 carte est valide.

Default :

```dotenv
MAX_OUTPUT_TOKENS=4000
```

---

# 11. V0.6.2 — Forge Hygiene

Résultat : **76 tests**, compileall OK, imports OK, aucun appel API réel.

## Frontmatter

Implémentation déterministe sans dépendance YAML externe :
- frontmatter retiré avant chunking
- métadonnées malformées/dupliquées refusées
- mismatch frontmatter/CLI agent-topic-source_type → fail closed
- `source_title` et `source_reference` deviennent canoniques
- chemin local séparé dans `source_path`
- ajout `corpus`

## Navigation filtering

Les sections `#### Read more` composées uniquement de liens sont exclues de la work queue LLM. La prose et les listes techniques avec liens sont préservées.

## Source-bounded Generator / Critic

Principe :

> Every non-speculative factual claim in a KnowledgeCard must be supported by the current source chunk.

Le modèle ne doit plus remplir les trous avec sa connaissance pré-entraînée. Seul `speculative_extensions` peut extrapoler, de façon bornée et explicitement spéculative.

## purge-document

Commande transactionnelle :

```powershell
python forge.py purge-document <document-id>
```

Supprime uniquement les objets Forge causés par le document : document, chunks, runs liés, cartes dont le chunk primaire lui appartient, review state, associations source. Une carte étrangère dédupliquée est conservée ; seule son association additionnelle est supprimée.

Préserve : API usage, budgets, `budget_uncertain_usage`, pricing, sessions, autres documents/cartes.

Migration additive/idempotente : `source_path`, `corpus`, `subtopic`.

---

# 12. Curation réelle de `01_xss_overview.md`

Après V0.6.2 : provenance OK, 24 → 15 chunks, plus de YAML chunk, plus de `Read more` standalone.

Mais le source brut contenait encore :
- un chapitre DOM détaillé
- méthodologie DOM dans le chapitre XSS
- bruit historique PortSwigger `alert()` / `print()` / Chrome 92 / simulated labs

Décision :
- conserver seulement la taxonomie reflected/stored/DOM-based
- retirer le chapitre DOM détaillé du corpus XSS
- retirer la méthodologie DOM détaillée
- garder le principe PoC générique :

```markdown
## XSS proof of concept

You can confirm most kinds of XSS vulnerability by injecting input that
causes your own browser to execute arbitrary JavaScript. A suitable proof of
concept should provide clear, observable evidence that JavaScript execution
occurred in the relevant browser context.
```

Après nettoyage : **14 chunks**.

Document IDs intermédiaires purgés :
- `c0d85153-c326-5a4f-b6d2-0fe089458e5c`
- `af5d2ba6-6174-5241-9b5c-21d4b76090e4`

Document live actuel :

```text
adad9557-327d-55f6-b2b1-8bfdc9779f67
```

---

# 13. Premier build live propre sous V0.6.2

Résultat :

```json
{
  "run_id": "474ac48c-23f2-4d6d-b248-5bb73ccc4279",
  "document_id": "adad9557-327d-55f6-b2b1-8bfdc9779f67",
  "status": "retryable",
  "processed_chunks": 9,
  "retryable_chunks": 5,
  "failed_chunks": 0,
  "approved_cards": 9,
  "rejected_cards": 0,
  "candidate_cards": 5,
  "message": "5 chunk(s) retryable"
}
```

Les 5 warnings avaient tous la forme : HTTP 200, provider `completed`, `Structured output invalid`, schéma `KnowledgeCardCritique`, retryable=True.

Le build continuait correctement et l'usage restait comptabilisé.

---

# 14. Audit des premières KnowledgeCards

Globalement :
- qualité nettement meilleure
- moins « PayloadGPT »
- provenance canonique correcte
- mental models utiles
- `evidence_required` souvent pertinent

Exemple propre : `xss: site returns malicious JavaScript that runs in victim browser` avec preuve = réponse contenant le JS contrôlé + exécution confirmée dans le navigateur.

## Fuites sémantiques encore observées

### Comparaison XSS / CSRF / SQLi
Le chunk disait seulement SQLi = vulnérabilité server-side ciblant la DB. La carte a ajouté `altered queries` / database-level injection dans `evidence_required` : correct en général, mais pas source-bound.

### Stored XSS
Ajout de `exactly as stored`, trop fort par rapport au source.

### CSP
`evidence_required` demandait à la fois preuve que CSP bloque et preuve qu'un bypass fonctionne, créant une ambiguïté AND/OR.

Conclusion : le source-bounding doit s'appliquer à **tous** les champs et `evidence_required` doit être défini plus précisément.

---

# 15. V0.6.3 — Critic Contract / Forge Diagnostics

Résultat : **85 tests**, compileall OK, imports OK, aucune migration, aucun appel API réel, DB live intacte pendant patch.

## Cause racine prouvée

Ancien `KnowledgeCardCritique` :
- `decision`
- `reasons`
- `revised_card` nullable
- `model_validator` local

Le `model_validator` n'était pas représenté dans le JSON Schema provider. Le provider pouvait donc légalement générer `revise + null` ou `approve/reject + revised_card`, puis Pydantic local refusait.

Impossible de savoir quelle combinaison avait produit les 5 warnings historiques car les raw outputs n'étaient pas conservés.

## Nouveau contrat

Trois variantes strictes sous propriété racine `critique` :
- **approve** : decision + reasons, pas de revised_card
- **reject** : decision + reasons, pas de revised_card
- **revise** : decision + reasons + revised_card obligatoire

Provider JSON Schema et Pydantic imposent désormais le même contrat.

## Diagnostics sûrs

`InvalidLLMResponse.validation_diagnostics` contient :
- response ID
- status provider
- schema
- longueur sortie
- nombre d'erreurs
- `loc`
- type
- message concis

Ne logge pas prompt complet, source complète, API key, auth ni sortie brute complète.

## Source fidelity hardening

Le critic vérifie tous les champs non spéculatifs : title, tags sémantiques, triggers, principle, questions_to_ask, false_positive_traps, evidence_required, escalation_topics, technique_assumptions, prerequisites, demonstrated_behavior.

Une information WebSec correcte mais absente du chunk doit être supprimée ou simplifiée.

## `evidence_required`

Définition : preuve nécessaire pour substantier le mécanisme réellement revendiqué par la carte, sans introduire de mécanisme nouveau ni exiger une preuve plus forte que le claim/source.

---

# 16. Retry live après V0.6.3

Résultat :

```json
{
  "status": "retryable",
  "processed_chunks": 12,
  "retryable_chunks": 2,
  "failed_chunks": 0,
  "approved_cards": 11,
  "rejected_cards": 2,
  "candidate_cards": 7
}
```

Bonne nouvelle : **plus aucun `Structured output invalid`**. Le nouveau contrat Critic fonctionne en production réelle.

Problème restant : 2 critics ont terminé `status=incomplete`, `reason=max_output_tokens`.

---

# 17. V0.6.4 — Per-stage Output Budgets

Résultat Codex : **87 tests**, compileall OK, imports OK, aucun appel réel, DB live intacte pendant patch.

Nouvelles variables :

```dotenv
GENERATOR_MAX_OUTPUT_TOKENS=4000
CRITIC_MAX_OUTPUT_TOKENS=6000
```

Fallback :

```dotenv
MAX_OUTPUT_TOKENS=4000
```

Résolution :

```text
Generator → GENERATOR_MAX_OUTPUT_TOKENS → fallback MAX_OUTPUT_TOKENS
Critic    → CRITIC_MAX_OUTPUT_TOKENS    → fallback MAX_OUTPUT_TOKENS
Autres    → MAX_OUTPUT_TOKENS
```

Invariant crucial : la valeur effective utilisée par `BudgetManager` pour réserver est la même que celle passée à Responses API `max_output_tokens`.

---

# 18. Retry live V0.6.4 à 6000 critic

Config utilisée :

```dotenv
GENERATOR_MAX_OUTPUT_TOKENS=4000
CRITIC_MAX_OUTPUT_TOKENS=6000
MAX_OUTPUT_TOKENS=4000
```

Résultat :

```json
{
  "run_id": "474ac48c-23f2-4d6d-b248-5bb73ccc4279",
  "document_id": "adad9557-327d-55f6-b2b1-8bfdc9779f67",
  "status": "retryable",
  "processed_chunks": 13,
  "retryable_chunks": 1,
  "failed_chunks": 0,
  "approved_cards": 12,
  "rejected_cards": 2,
  "candidate_cards": 8,
  "message": "1 chunk(s) retryable"
}
```

Un des deux chunks a donc passé correctement le critic à 6000.

Dernier chunk retryable :

```text
4d48c4c9-06f3-5cdb-90f1-ed2b47ef2975
```

Correspond à :

```text
How to find and test for XSS vulnerabilities
```

Le critic a encore :

```text
status=incomplete
reason=max_output_tokens
retryable=True
```

---

# 19. État live à ce stade de calibration (historique)

## Document

```text
adad9557-327d-55f6-b2b1-8bfdc9779f67
```

## Run

```text
474ac48c-23f2-4d6d-b248-5bb73ccc4279
```

## Progression

```text
14 chunks total
13 processed
1 retryable
0 failed
12 approved cards
2 rejected cards
8 candidate cards
```

Attention : les cartes/candidates actuelles sont issues de plusieurs retries. Ce corpus sert encore de **calibration** et ne doit pas encore être considéré comme corpus final propre.

---

# 20. Action prévue à ce stade (historique)

Augmenter uniquement le critic :

```dotenv
GENERATOR_MAX_OUTPUT_TOKENS=4000
CRITIC_MAX_OUTPUT_TOKENS=8000
MAX_OUTPUT_TOKENS=4000
```

Puis relancer :

```powershell
.\.venv\Scripts\python.exe forge.py build adad9557-327d-55f6-b2b1-8bfdc9779f67
```

Attendu : seul le dernier `retryable` doit être repris.

Objectif idéal :

```text
processed_chunks = 14
retryable_chunks = 0
failed_chunks = 0
```

## Règle d'arrêt

Si le même critic touche encore `max_output_tokens` à **8000**, ne pas escalader automatiquement à 10k/12k. À ce moment : inspecter chunk/candidat, taille du payload, complexité du revised_card, nombre de cartes candidates, prompt critic, éventuelle boucle de révision et niveau de raisonnement.

---

# 21. Plan prévu après validation du dernier retry (historique)

Même si 14/14 passent, **ne pas considérer immédiatement les cartes actuelles comme corpus final**, car certaines ont été générées/critiquées avant V0.6.3.

Plan propre :

```text
finir le dernier retry
        ↓
valider V0.6.4 en réel
        ↓
purge du document complet
        ↓
re-ingest du source curaté
        ↓
rebuild complet sous V0.6.3 + V0.6.4
        ↓
audit final des cartes
        ↓
seulement ensuite : document suivant
```

---

# 22. Commandes utiles actuelles

## Inspect document

```powershell
.\.venv\Scripts\python.exe forge.py inspect adad9557-327d-55f6-b2b1-8bfdc9779f67
```

## Build / reprendre retryables

```powershell
.\.venv\Scripts\python.exe forge.py build adad9557-327d-55f6-b2b1-8bfdc9779f67
```

## Lister cartes approved

```powershell
.\.venv\Scripts\python.exe forge.py list --kind cards --topic xss --status approved
```

## Lister candidates

```powershell
.\.venv\Scripts\python.exe forge.py list --kind cards --topic xss --status candidate
```

## Purge document

```powershell
.\.venv\Scripts\python.exe forge.py purge-document <document-id>
```

## Re-ingest XSS overview

```powershell
.\.venv\Scripts\python.exe forge.py ingest .\sources\portswigger\academy\ikit\xss\01_xss_overview.md --agent ikit --source-type academy --topic xss
```

---

# 23. Configuration `.env` pertinente

```dotenv
COORDINATOR_MODEL=gpt-5-mini
SPECIALIST_MODEL=gpt-5-mini

MAX_AGENT_ROUNDS=2
MAX_SPECIALISTS_PER_ROUND=3
MAX_KNOWLEDGE_FRAGMENTS=5
MAX_CARD_CHARS=2500
SOURCE_CHUNK_MAX_CHARS=6000
MAX_CARD_REVISIONS=1
SKAVEN_LEVEL=2

DATABASE_PATH=data/warpstone.db
KNOWLEDGE_PATH=knowledge
PRICING_PATH=pricing.json

MAX_OUTPUT_TOKENS=4000
GENERATOR_MAX_OUTPUT_TOKENS=4000

# Dernier réglage testé :
# CRITIC_MAX_OUTPUT_TOKENS=6000

# Prochaine calibration proposée :
CRITIC_MAX_OUTPUT_TOKENS=8000

DAILY_TOKEN_BUDGET=250000

DAILY_BUDGET_USD=0.50
MONTHLY_BUDGET_USD=3.00
MAX_COST_PER_RUN_USD=0.25

FAIL_ON_UNKNOWN_PRICING=true
ESTIMATED_CHARS_PER_TOKEN=4
```

---

# 24. Invariants à ne pas casser

## Budget / accounting

- provider response reçue → usage réel finalisé avant parsing/validation finale
- `completed + malformed` → usage compté puis erreur
- `incomplete/max_output_tokens` → usage compté puis retryable
- interruption ambiguë → `budget_uncertain_usage`
- pre-response definite failure → réservation annulée
- persistence failure → fail closed

## Forge

- 0 carte Generator est valide
- 0–3 cartes max par chunk
- candidate ≠ approved
- Knowledge ≠ Evidence
- Refuted/closed ≠ finding
- provenance source stricte
- pas de remplissage depuis connaissance pré-entraînée hors `speculative_extensions`
- critic compare la carte au **chunk courant**
- `Read more` navigation-only ne doit pas coûter un appel LLM
- frontmatter ne doit jamais devenir un chunk

## Sécurité / scope

- pas de crawling autonome
- pas d'action autonome contre une cible
- pas de trafic Web généré par les rats
- le système analyse les matériaux fournis
- policy déterministe > agents

---

# 25. Leçons principales du premier manuel Ikit

```text
V0.6 initial
→ lifecycle/API accounting insuffisant

V0.6.1
→ lifecycle/accounting durci

V0.6.2
→ mauvaise hygiène source/provenance
→ frontmatter/read-more/DOM bleed
→ source-bounded learning

V0.6.3
→ contrat JSON Schema provider ≠ Pydantic local
→ source fidelity sur tous les champs

V0.6.4
→ output budget doit être spécifique au stage
```

Le corpus XSS Overview joue donc le rôle de **corpus de calibration** avant industrialisation.

---

# 26. Observations de design utiles pour la suite

### Ne pas confondre « exact scientifiquement » et « source-bound »

Une carte peut contenir un fait WebSec correct mais être invalide pour cette provenance si le chunk ne le supporte pas.

### Le critic est plus cher que prévu

Le critic raisonne plus, peut réviser une carte complète et a dépassé 4000 puis 6000 max output sur certains cas. D'où les limites spécifiques par stage.

### Les limites doivent être liées au budget

Un stage ne doit jamais recevoir un plafond API supérieur à la réservation du `BudgetManager`.

### Une erreur retryable est un état normal

Elle ne doit pas corrompre une carte, produire un approved silencieux, perdre l'usage ni tuer tout le build.

---

# 27. Running jokes / vocabulaire du projet

- JSON truncation = **warpstone reactor overload**
- tokens payés mais non comptés = **Skaven accounting**
- Ctrl+C en vol = **rat disappeared in tunnel; treasury assumes warpstone gone**
- `budget_uncertain_usage` = **dette pessimiste**
- mauvais cerveau = **PayloadGPT**
- sink détecté ≠ vulnérabilité : **SINK SMELL-SMELL. NOT VULN YET-NO.**
- premier vrai manuel : **FIRST REAL SCHOOLBOOK ACQUIRED YES-YES.**
- chunks `Read more` : **IKIT DOES NOT NEED GPT TO LEARN THAT “READ MORE” IS LINK-LINK.**
- première ingestion cassée : **FIRST SCHOOL DAY CANCELLED. IKIT ACCIDENTALLY READ SCHOOL DIRECTORY AND CALLED IT KNOWLEDGE.**
- budget/API/Codex = **Morrslieb**
- critic trop gourmand : **MORE WARPSTONE. NEED-NEED THINK ABOUT ONE CARD.**
- règle actuelle : **If critic eats 8000 and still asks more: stop feeding rat, open skull.**

---

# 28. Résumé ultra-court pour reprise de contexte — FIN DE SESSION

1. **Swarmblight** = système WebSec multi-agent local, text-only, avec policy déterministe, budget strict et séparation Knowledge/Evidence.
2. **Ikit** est le premier agent à recevoir une Knowledge Forge.
3. Forge : `Source → chunks déterministes → Generator → Critic → validator → dedup → approved KnowledgeCards`.
4. **V0.6.1** : lifecycle/API accounting durci.
5. **V0.6.2** : frontmatter/provenance/navigation/source-bounding/purge corrigés.
6. **V0.6.3** : contrat `KnowledgeCardCritique` provider/Pydantic corrigé + source fidelity renforcée sur tous les champs.
7. **V0.6.4** : budgets de sortie par stage ; Generator/Critic utilisent chacun leur plafond effectif et `BudgetManager` réserve sur exactement le même plafond.
8. Configuration de fin de session :
   ```dotenv
   GENERATOR_MAX_OUTPUT_TOKENS=4000
   CRITIC_MAX_OUTPUT_TOKENS=10000
   MAX_OUTPUT_TOKENS=4000
   DAILY_TOKEN_BUDGET=250000
   ```
9. La calibration live du document XSS cobaye a finalement atteint **14/14 processed, 0 retryable, 0 failed** avec Critic à 10k.
10. Le document cobaye a ensuite été **purgé proprement** : 14 chunks, 1 run et 24 cartes/review states/associations supprimés ; accounting/audit préservés.
11. Le source curaté `01_xss_overview.md` a été réingéré et a repris le même ID déterministe :
    `adad9557-327d-55f6-b2b1-8bfdc9779f67`.
12. L'inspection post-réingestion était propre : **14 chunks pending**, provenance PortSwigger canonique, PoC nettoyé, DOM détaillé absent du curriculum XSS.
13. Le **premier rebuild canonique complet** sous V0.6.3/V0.6.4 a été lancé.
14. Ce rebuild canonique n'a **pas terminé**, car le budget journalier local a été atteint :
    `Daily token budget would be exceeded (258304 > 250000)`.
15. État exact du run canonique au stop :
    - run : `59cb0b3a-f0ce-41d7-93e1-ee35b5de6fc9`
    - `processed_chunks = 4`
    - `retryable_chunks = 2`
    - `failed_chunks = 0`
    - `approved_cards = 2`
    - `rejected_cards = 2`
    - `candidate_cards = 3`
    - status : `budget_exhausted`
16. Deux critics du rebuild canonique ont encore atteint `max_output_tokens` **malgré le plafond Critic à 10000** :
    - chunk `c59b4e78-5658-5126-91ba-edbc3dd4ea6b` — taxonomie des types XSS
    - chunk `d97b163f-a596-52c9-a70f-321e71e968cd` — reflected XSS
17. **Ne pas monter automatiquement au-dessus de 10k.** À la prochaine session, diagnostiquer pourquoi certains critic calls deviennent anormalement gourmands avant toute nouvelle escalade.
18. Le build est resumable : à la prochaine session, reprendre le même document après reset/relèvement approprié du budget journalier, sans purge.
19. Projet API renommé **Swarmblight**.
20. Le programme OpenAI **Share inputs and outputs** ne doit pas être activé pour ce projet tel quel tant qu'il ingère des sources tierces PortSwigger et, plus tard, potentiellement des données privées. Un projet séparé pour contenu synthétique/public pourra être envisagé.

---

# 29. Notepatch fin de session — calibration 8k → 10k

## Retry à 8000

Après le passage du Critic de 6000 à 8000 :

```dotenv
GENERATOR_MAX_OUTPUT_TOKENS=4000
CRITIC_MAX_OUTPUT_TOKENS=8000
MAX_OUTPUT_TOKENS=4000
```

le dernier chunk retryable a **encore** terminé :

```text
status=incomplete
reason=max_output_tokens
retryable=True
```

Le document restait :

```text
13 processed
1 retryable
0 failed
```

Conclusion : 8000 n'était pas suffisant pour ce cas.

## Validation à 10000

Le Critic a été porté à :

```dotenv
CRITIC_MAX_OUTPUT_TOKENS=10000
```

Le retry suivant a terminé proprement :

```json
{
  "status": "completed",
  "processed_chunks": 14,
  "retryable_chunks": 0,
  "failed_chunks": 0,
  "approved_cards": 12,
  "rejected_cards": 3,
  "candidate_cards": 9,
  "message": "Forge build completed."
}
```

Cela valide en live :
- le nouveau contrat Structured Output de V0.6.3 ;
- le routage per-stage de V0.6.4 ;
- le couplage plafond API / réservation budgétaire ;
- la reprise normale d'un chunk retryable.

Important : **10000 est un plafond de sécurité, pas une cible de consommation.**

---

# 30. Purge du corpus de calibration et réingestion canonique

Après validation du pipeline, le document cobaye a été purgé :

```json
{
  "document_id": "adad9557-327d-55f6-b2b1-8bfdc9779f67",
  "documents_removed": 1,
  "chunks_removed": 14,
  "forge_runs_removed": 1,
  "cards_removed": 24,
  "card_review_states_removed": 24,
  "card_source_associations_removed": 24,
  "foreign_source_associations_removed": 0,
  "duplicate_links_cleared": 0
}
```

La somme des cartes supprimées correspond bien à l'état final du cobaye :

```text
12 approved + 3 rejected + 9 candidate = 24
```

Le source curaté a ensuite été réingéré :

```powershell
.\.venv\Scripts\python.exe forge.py ingest .\sources\portswigger\academy\ikit\xss\01_xss_overview.md --agent ikit --source-type academy --topic xss
```

Résultat :
- même ID déterministe :
  `adad9557-327d-55f6-b2b1-8bfdc9779f67`
- **14 chunks**
- provenance :
  `https://portswigger.net/web-security/cross-site-scripting`

Inspection validée :
- tous les chunks étaient `pending`
- pas de YAML/frontmatter dans la queue LLM
- pas de `Read more` standalone
- PoC XSS générique et propre
- DOM détaillé absent, seule la taxonomie reflected/stored/DOM reste dans l'overview
- provenance canonique + `source_path` local séparé

---

# 31. Premier rebuild canonique — état au stop

Le rebuild complet, cette fois entièrement sous le pipeline durci V0.6.3/V0.6.4, a été lancé avec :

```dotenv
GENERATOR_MAX_OUTPUT_TOKENS=4000
CRITIC_MAX_OUTPUT_TOKENS=10000
MAX_OUTPUT_TOKENS=4000
DAILY_TOKEN_BUDGET=250000
```

Le run est :

```text
59cb0b3a-f0ce-41d7-93e1-ee35b5de6fc9
```

Plusieurs appels Generator et Critic ont terminé normalement avec validation JSON.

Deux critics ont cependant encore frappé `max_output_tokens=10000` :

```text
chunk=c59b4e78-5658-5126-91ba-edbc3dd4ea6b
status=incomplete
reason=max_output_tokens
```

puis :

```text
chunk=d97b163f-a596-52c9-a70f-321e71e968cd
status=incomplete
reason=max_output_tokens
```

Le build s'est ensuite arrêté **proprement sur l'invariant budget local** :

```text
NO-NO MORE WARPSTONE. TREASURY EMPTY.
Daily token budget would be exceeded (258304 > 250000).
```

État sauvegardé :

```json
{
  "run_id": "59cb0b3a-f0ce-41d7-93e1-ee35b5de6fc9",
  "document_id": "adad9557-327d-55f6-b2b1-8bfdc9779f67",
  "status": "budget_exhausted",
  "processed_chunks": 4,
  "retryable_chunks": 2,
  "failed_chunks": 0,
  "approved_cards": 2,
  "rejected_cards": 2,
  "candidate_cards": 3,
  "message": "Daily token budget would be exceeded (258304 > 250000)."
}
```

Ce comportement est sain :
- pas de crash ;
- pas de carte silencieusement approuvée sur réponse tronquée ;
- usage provider comptabilisé ;
- état resumable ;
- budget fail-closed.

---

# 32. Point technique à investiguer à la prochaine session

Le problème `max_output_tokens` n'est plus seulement « un plafond un peu bas ».

Des critics ont réussi avec quelques milliers de tokens, mais certains cas ont atteint successivement :
- 4000
- 6000
- 8000
- et maintenant **10000**

sans produire une réponse complète.

**Ne pas répondre en augmentant encore mécaniquement le plafond.**

À inspecter :
- taille exacte du candidate draft transmis au critic ;
- nombre de candidates/cards dans le chunk ;
- présence d'une révision complète `revised_card` ;
- quantité de raisonnement consommée vs output visible ;
- formulation du prompt source-fidelity ;
- répétition/contradiction éventuelle dans les exigences du critic ;
- possibilité de demander au critic une décision plus compacte ;
- éventuel découplage « critique » / « réécriture » si la révision complète est ce qui fait exploser le budget ;
- si l'anomalie est liée à certains types de chunks plutôt qu'à la taille brute.

Le but n'est pas d'affaiblir le critic, mais d'éviter qu'il puisse consommer arbitrairement une grande partie du budget journalier pour une seule carte.

---

# 33. API project / Content Sharing

Le `Default project` API a été renommé :

```text
Swarmblight
```

Un écran OpenAI proposait :

> Share inputs and outputs with OpenAI

avec usage gratuit quotidien sur le trafic partagé.

Décision pour ce projet :
- **ne pas activer le partage pour l'instant**.

Raison :
- le Forge transmet des chunks provenant de documentation tierce PortSwigger ;
- le Content Sharing Agreement demande au client de garantir qu'il possède les droits/licences/permissions nécessaires pour l'usage de ces Inputs à des fins de développement/entraînement ;
- plus tard Swarmblight pourra aussi manipuler des données privées/confidentielles d'assessment.

Architecture potentielle future :

```text
Swarmblight-ThirdParty / Assessment
  sharing OFF

Swarmblight-Synthetic / FirstParty
  sharing ON éventuellement
```

Le gain de tokens gratuits ne justifie pas de mélanger les tunnels de données.

---

# 34. Reprise recommandée demain / prochaine session

Ordre conseillé :

1. **Ne rien purger.** Le run canonique est partiel mais propre et resumable.
2. Vérifier le reset du budget journalier / l'état du `BudgetManager`.
3. Avant un nouveau build massif, investiguer le comportement des critics à 10k.
4. Garder :
   ```dotenv
   GENERATOR_MAX_OUTPUT_TOKENS=4000
   CRITIC_MAX_OUTPUT_TOKENS=10000
   MAX_OUTPUT_TOKENS=4000
   ```
   tant qu'aucune meilleure politique n'est implémentée.
5. Ne pas augmenter le Critic au-delà de 10k juste pour « faire passer » les deux chunks.
6. Une fois le point critic compris/corrigé, reprendre :
   ```powershell
   .\.venv\Scripts\python.exe forge.py build adad9557-327d-55f6-b2b1-8bfdc9779f67
   ```
7. Quand le rebuild canonique atteint 14/14 sans anomalie structurelle, auditer les KnowledgeCards avant de passer à `02_reflected_xss.md`.

---

# 35. État mental du rat au moment de fermer l'atelier

```text
FIRST CANONICAL SCHOOL DAY:
- school opened
- two critics ate 10k
- treasury reached daily limit
- no database corruption
- no accounting leak
- no uncontrolled approval
```

> **MORRSLIEB EMPTY. WORKSHOP CLOSED. RATS SLEEP-SLEEP.**

---

**End of context snapshot — 2026-08-27, end of session**
---

# 36. Notepatch 2026-08-28 — hygiène secret / environnement

Au début de session, constat qu'un `.env` contenant une clé API OpenAI avait été inclus par erreur dans les fichiers transmis.

Décision appliquée immédiatement :

- ancienne clé **révoquée** ;
- nouvelle clé créée sous un nom explicite de type `swarmblight-local ...` ;
- nouvelle clé conservée uniquement dans l'environnement local ;
- ne plus transmettre le `.env` ;
- utiliser un `.env.example` sans secret si besoin ;
- conserver `.env`, `.env.*` et `.venv/` hors versionnement, avec exception éventuelle pour `.env.example`.

Règle d'hygiène confirmée :

> **Secret sorti de sa zone de confiance prévue → secret considéré compromis → rotation/révocation.**

Le risque concret d'exploitation après envoi privé était probablement faible, mais le coût de rotation était faible également ; l'objectif est d'industrialiser le bon réflexe.

### `.venv`

Nuance importante pour les archives de contexte :

- le **contenu réel** du gros dossier `.venv` n'est volontairement pas transmis ;
- son arborescence / les noms de fichiers peuvent apparaître dans `tree.txt` ;
- ne pas confondre « `.venv` absent de l'archive » avec « aucune trace nominale du `.venv` dans les documents ».

Le lancement local reste :

```powershell
.\.venv\Scripts\python.exe
```

---

# 37. Autopsie du Critic à 10k — reasoning innocent, output visible coupable

Deux Responses historiques du Critic qui avaient atteint `max_output_tokens=10000` ont été récupérées par ID sans nouvel appel génératif.

## Cas anormaux

### Failure 1

```text
response_id:
resp_060fe62b6d90de44006a90191553a487d28c1958a73b393f1b

input_tokens:      1490
output_tokens:    10000
reasoning_tokens:  1024
visible chars:    14461
status: incomplete
reason: max_output_tokens
```

### Failure 2

```text
response_id:
resp_04259bb4485ba761006a9019711ed487d28464e672413c3465

input_tokens:      1774
output_tokens:    10000
reasoning_tokens:  1216
visible chars:    15783
status: incomplete
reason: max_output_tokens
```

## Baselines réussies

```text
resp_02b554a915b0bda3006a90190c5d7487d2886dc1c28c6958e5
input=1463
output=817
reasoning=640
visible chars=877
completed
```

```text
resp_044db6ed92102ee0006a9018e16d0087d295abcd26c5ae9c8c
input=1449
output=2553
reasoning=1472
visible chars=4648
completed
```

Conclusion ferme :

> **Le problème n'était pas une explosion des reasoning tokens.**

Les 10k étaient surtout consommés par de la sortie structurée visible dégénérée.

---

# 38. Première cause prouvée — degeneration de sortie structurée

Autopsie Codex :

- Failure 1 : environ **12 895 caractères** de répétition `.  ` à l'intérieur de `critique.reasons[*]`.
- Failure 2 : environ **12 749 caractères** de whitespace JSON après `revised_card.speculative_extensions`.
- Les inputs étaient de taille normale.
- Un baseline `revise` réussi montrait déjà un précurseur :
  - une raison très longue (~1518 caractères) ;
  - plusieurs centaines de caractères de whitespace.

Le JSON Schema strict permettait alors des chaînes pratiquement non bornées dans plusieurs champs.

## Patch anti-dégénérescence

Ajouts :

- `Critic reasons` :
  - 1 à 4 éléments ;
  - max 400 caractères par élément.
- éléments textuels de cartes : max 400 caractères.
- tags : max 40 caractères.
- `principle` : max 800 caractères.
- `demonstrated_behavior` : max 800 caractères.
- bornes présentes côté Pydantic **et** dans le JSON Schema strict provider.
- prompt Critic :
  - sortie compacte ;
  - pas de variantes successives ;
  - pas de répétition ;
  - pas de ponctuation/whitespace de remplissage.
- Critic en verbosity basse.
- `reasoning_tokens` ajouté dans `UsageDetails`.
- longueur visible exposée dans `LLMResponseMetadata`.
- aucune sortie brute complète ajoutée aux logs.

Validation :

```text
91 tests passed
compileall OK
smoke imports OK
```

Aucune migration.

Important :

> `MAX_CARD_CHARS` post-génération ne suffit pas contre un token burn provider-side ; les bornes doivent être visibles pendant la génération.

---

# 39. Régression HTTP 400 — mauvais placement de `verbosity`

Premier live build après le patch anti-dégénérescence :

- tous les Generators → HTTP 200 ;
- tous les Critics → HTTP 400 immédiat ;
- 10 chunks finissent `retryable`.

Le compteur :

```text
4 processed + 10 retryable = 14
```

était cohérent ; le problème était la requête Critic.

## Cause

`verbosity="low"` était envoyé à la racine de la requête Responses.

Le contrat provider attend :

```text
text.verbosity
```

Une sonde unique a confirmé :

```text
HTTP 400
type=invalid_request_error
code=unsupported_parameter
```

Le Generator continuait de fonctionner parce qu'il n'envoyait aucune `verbosity`.

## Correction

Le Critic envoie désormais :

```python
text={"verbosity": "low"}
```

et laisse le SDK fusionner cela avec `text.format`.

Les protections `maxLength` sont restées intactes.

Diagnostics 400 durcis :

- status ;
- type ;
- code ;
- param ;
- request ID ;
- message provider uniquement via allow-list sûre.

Jamais :

- prompt complet ;
- source ;
- clé ;
- Authorization ;
- raw request complet.

Accounting :

- 400 = definite pre-response rejection dans le chemin actuel ;
- réservation annulée ;
- aucun faux usage provider.

Validation :

```text
96 tests passed
compileall OK
smoke imports OK
```

---

# 40. Live validation après correction `text.verbosity`

Le build a ensuite largement progressé normalement.

Les Critics réussis revenaient typiquement vers :

```text
~1800–2600 visible chars
~1000–2000 reasoning tokens
status=completed
```

Mais le chunk :

```text
d97b163f-a596-52c9-a70f-321e71e968cd
```

a encore produit :

```text
response_id:
resp_04b72055d9e2a339006a9110cb25c887d2b9c88f60f758d6d5

status=incomplete
reason=max_output_tokens
input_tokens=1770
output_tokens=10000
reasoning_tokens=1920
visible_output_chars=9790
```

Le build a ensuite atteint le budget per-run :

```text
processed_chunks = 10
retryable_chunks = 4
failed_chunks = 0
approved_cards = 3
rejected_cards = 7
candidate_cards = 15
```

Le plafond per-run a ensuite été volontairement porté de :

```dotenv
MAX_COST_PER_RUN_USD=0.25
```

à :

```dotenv
MAX_COST_PER_RUN_USD=0.50
```

pour permettre la calibration complète, tout en gardant les autres garde-fous.

---

# 41. Autopsie whitespace — CASE B prouvé

Autopsie de :

```text
resp_04b72055d9e2a339006a9110cb25c887d2b9c88f60f758d6d5
```

Résultat exact :

```text
longueur totale : 9790
début boucle whitespace : offset 1978
dernier caractère non blanc : ] à l'offset 1977
suffixe : 7812 caractères

espaces : 4981
CR (\r) : 2830
LF (\n) : 1
tabs/autres : 0
```

Le début du JSON était normal et contenait :

```json
{
  "critique": {
    "decision": "revise",
    "reasons": [...],
    "revised_card": {
      ...
```

Puis le modèle a fermé le dernier tableau et s'est mis à produire :

```text
 \r  \r  \r  \r  \r ...
```

jusqu'au plafond.

## Point critique : CASE B

Le JSON n'était **pas** complet avant le whitespace.

`json.JSONDecoder().raw_decode(...)` échoue à EOF.

Trois objets étaient encore ouverts :

- objet racine ;
- objet `critique` ;
- objet `revised_card`.

Il aurait fallu ajouter artificiellement trois `}` pour rendre le document valide.

Décision correcte :

> **Aucune récupération sémantique. Fail-closed maintenu.**

Pas de :

- `rstrip()` + accept ;
- ajout d'accolades ;
- réparation JSON ;
- troncature de chaîne ;
- inférence de champs manquants.

## Incident historique comparé

`resp_04259bb...` montrait exactement la même famille :

```text
longueur : 15783
boucle à partir de : 3034
whitespace : 12749 caractères
espaces : 4537
CR : 2283
LF : 5929
3 objets encore ouverts
```

Conclusion :

> **Dégénérescence provider/model dans la fermeture d'une structure JSON ; `maxLength` ne peut pas borner le whitespace structurel légal.**

---

# 42. Diagnostics supplémentaires des réponses `incomplete`

`llm.py` a été durci pour produire un diagnostic sûr sur les réponses :

```text
status=incomplete
reason=max_output_tokens
```

Le diagnostic peut maintenant indiquer :

- résultat `raw_decode` ;
- offset de fin si un JSON complet existe ;
- validation éventuelle du schema ;
- composition du suffixe ;
- profondeur de structures JSON encore ouvertes ;
- état de chaîne JSON.

Il ne répare rien.

Même un CASE A hypothétique reste actuellement refusé par `IncompleteLLMResponse`.

Validation après ce patch :

```text
105 tests passed
compileall OK
smoke imports OK
```

`critic_autopsy/` a ensuite été exclu du repo / traité comme temporaire.

---

# 43. Reprise du run et première complétion canonique

Avec :

```dotenv
CRITIC_MAX_OUTPUT_TOKENS=10000
MAX_COST_PER_RUN_USD=0.50
```

le run :

```text
59cb0b3a-f0ce-41d7-93e1-ee35b5de6fc9
```

a finalement atteint :

```json
{
  "status": "completed",
  "processed_chunks": 14,
  "retryable_chunks": 0,
  "failed_chunks": 0,
  "approved_cards": 4,
  "rejected_cards": 11,
  "candidate_cards": 15
}
```

Aucun nouveau whitespace-loop pendant cette dernière reprise.

Interprétation prudente :

> Le bug provider n'est pas « corrigé » ; Swarmblight sait désormais l'identifier, refuser la réponse incomplète, conserver l'accounting, puis reprendre ultérieurement.

---

# 44. Audit du corpus — problème de `confidence`

Audit des 4 approved et 11 rejected.

Constat important :

- aucune trace évidente de troncature liée aux nouvelles bornes 400/800 ;
- phrases complètes ;
- pas de champs systématiquement collés aux limites ;
- le hardening anti-dégénérescence ne semblait pas mutiler les KnowledgeCards.

Mais plusieurs cartes apparemment bonnes étaient rejetées après révision.

## Cinq cartes inspectées

### Contrôle approved

```text
6e1bc11c-b1f6-5793-87ef-9cde80d4b2e8
xss prevention guidance referenced for php and java
```

`confidence=0.9` accepté.

Les détails PHP/Java étaient bien supportés par le chunk source.

### PoC XSS

```text
dc2e518e-3261-5b0e-bc02-3b4425af19b6
```

Le Critic disait que presque tout était fidèle, avec deux réserves :

- `attacker-controlled input` un peu plus fort que `injecting input` ;
- `confidence=0.0` « non supporté par le chunk ».

### Manual XSS discovery

```text
44a6b544-5dab-532d-87b3-dcfc77427363
```

Le Critic disait explicitement :

> faithful, source-bounded abstraction

mais demandait de retirer le `confidence` numérique.

### General XSS prevention

```text
3476bfa8-5867-5065-b9a4-84bf3a3ae015
```

Même anomalie :

> contenu fidèle, mais `confidence=0.0` non supporté par le chunk.

### Detailed reflected XSS

```text
e4337b47-652d-56c2-a205-cf00e714c118
```

Ici la révision était légitime et indépendante de `confidence` :
le `false_positive_traps` ajoutait une distinction mécanistique non explicitement présente dans le chunk.

---

# 45. `confidence` ownership — erreur de catégorie corrigée

Cause conceptuelle :

`confidence` était à la fois :

- produit par le modèle ;
- utilisé comme score de classement ;
- traité par le prompt Critic comme si la source devait justifier littéralement le nombre.

Or :

```text
principle / evidence / triggers / etc.
→ factual claims about the source
→ source-bound

confidence = 0.9
→ meta-judgment of Swarmblight
→ not a source claim
```

Le Critic pouvait donc rejeter une bonne carte parce que PortSwigger n'avait évidemment jamais écrit :

```text
confidence = 0.9
```

## Sémantique retenue

Modèle B :

> **`confidence` = méta-confiance advisory du modèle dans la fidélité et la réutilisabilité de la carte.**

Ownership :

- Generator : valeur initiale ;
- Critic : peut préserver/recalibrer pendant une révision ;
- système déterministe : vérifie seulement `0 <= confidence <= 1` ;
- source : ne possède pas ce nombre.

## Consumers réels

`confidence` est utilisé pour :

- persistence dans `knowledge_cards.confidence` / `card_json` ;
- départage secondaire du retrieval après pertinence et type de source.

Il n'est pas utilisé pour :

- approbation déterministe ;
- validation sémantique ;
- dedup ;
- injection explicite dans le contexte Ikit ;
- affichage KnowledgeCard spécifique.

Les autres champs `confidence` ailleurs concernent d'autres objets (hypothèses, preuves, réponses).

## Patch

Le prompt :

- retire `confidence` de la liste des champs source-bound ;
- interdit revise/reject uniquement parce que la source ne contient pas le score ;
- conserve source fidelity stricte pour les champs factuels ;
- conserve `speculative_extensions` comme exception extrapolative.

`MAX_CARD_REVISIONS=1` reste inchangé.

Validation :

```text
110 tests passed
compileall OK
smoke imports OK
```

Aucune migration.

Incertitude restante :

> le score reste une auto-évaluation non calibrée ; s'il devient plus important qu'un tie-breaker, il faudra une métrique de review calibrée.

---

# 46. Pourquoi `MAX_CARD_REVISIONS=1` n'a pas été changé

Séquence actuelle :

```text
candidate
  ↓
Critic review
  ↓
first revise applied
revision_count = 1
  ↓
Critic review again
  ↓
second revise requested
  ↓
rejected: maximum revisions exceeded
```

Les audits ont montré que plusieurs secondes révisions venaient du mauvais contrat sur `confidence`.

Donc :

> **ne pas augmenter le budget de révision pour compenser une erreur de contrat.**

Le budget reste à 1 tant qu'on n'a pas prouvé que de bonnes cartes nécessitent régulièrement plusieurs révisions légitimes après correction de `confidence`.

---

# 47. Purge après correction `confidence`

Comme les statuses du corpus précédent étaient contaminés par le contrat de `confidence`, une reconstruction propre a été décidée.

Purge exécutée :

```json
{
  "document_id": "adad9557-327d-55f6-b2b1-8bfdc9779f67",
  "documents_removed": 1,
  "chunks_removed": 14,
  "forge_runs_removed": 1,
  "cards_removed": 30,
  "card_review_states_removed": 30,
  "card_source_associations_removed": 30,
  "foreign_source_associations_removed": 0,
  "duplicate_links_cleared": 0
}
```

Puis re-ingest :

```powershell
.\.venv\Scripts\python.exe forge.py ingest .\sources\portswigger\academy\ikit\xss\01_xss_overview.md --agent ikit --source-type academy --topic xss
```

Résultat :

```text
document_id:
adad9557-327d-55f6-b2b1-8bfdc9779f67

chunks: 14
source_reference:
https://portswigger.net/web-security/cross-site-scripting
```

Le même UUID déterministe a été retrouvé.

---

# 48. Rebuild propre post-`confidence` — état actuel

Nouveau run :

```text
9ecc833b-c1d1-428a-8761-0fd3ee622687
```

Le build a démarré entièrement sous le contrat corrigé.

Aucune anomalie technique observée avant le stop :

- Generators → `completed` ;
- Critics → `completed` ;
- aucune HTTP 400 ;
- aucun `max_output_tokens` ;
- aucun whitespace-loop ;
- aucun `retryable` ;
- aucun `failed`.

Premier Generator du run :

```text
output_chars=13
reasoning_tokens=128
```

Interprétation probable : 0 KnowledgeCard générée, ce qui est explicitement valide.

## Stop actuel

Le build s'est arrêté uniquement sur le budget journalier :

```text
Daily token budget would be exceeded (250476 > 250000)
```

État exact :

```json
{
  "run_id": "9ecc833b-c1d1-428a-8761-0fd3ee622687",
  "document_id": "adad9557-327d-55f6-b2b1-8bfdc9779f67",
  "status": "budget_exhausted",
  "processed_chunks": 10,
  "retryable_chunks": 0,
  "failed_chunks": 0,
  "approved_cards": 8,
  "rejected_cards": 1,
  "candidate_cards": 1,
  "message": "NO-NO MORE WARPSTONE. TREASURY EMPTY. Daily token budget would be exceeded (250476 > 250000)."
}
```

Signal qualitatif intéressant :

```text
ancien corpus avant fix confidence :
4 approved / 11 rejected / 15 candidate

nouveau corpus à seulement 10/14 chunks :
8 approved / 1 rejected / 1 candidate
```

Ce n'est pas un A/B strict à cause de la stochasticité du Generator/LLM, mais le changement est cohérent avec l'hypothèse que l'ancien contrat `confidence` provoquait de nombreux faux rejets.

---

# 49. État de configuration pertinent à la fermeture du 2026-08-28

Configuration effective à conserver pour la reprise immédiate :

```dotenv
MAX_OUTPUT_TOKENS=4000
GENERATOR_MAX_OUTPUT_TOKENS=4000
CRITIC_MAX_OUTPUT_TOKENS=10000

DAILY_TOKEN_BUDGET=250000

DAILY_BUDGET_USD=0.50
MONTHLY_BUDGET_USD=3.00

MAX_COST_PER_RUN_USD=0.50
```

Notes :

- `CRITIC_MAX_OUTPUT_TOKENS=10000` reste un **plafond de sécurité**, pas une cible.
- Ne pas l'augmenter au-delà de 10k mécaniquement.
- Les Critics normaux observés post-hardening sont très en dessous de 10k.
- `MAX_COST_PER_RUN_USD` a été relevé de 0.25 à 0.50 pour la calibration ; réévaluer plus tard si nécessaire.
- Le garde-fou journalier a correctement stoppé le rebuild.

---

# 50. Reprise recommandée au prochain jour

## Important : NE PAS PURGER

Le corpus courant a déjà été purgé puis re-ingéré **après** la correction `confidence`.

Les 10 chunks déjà traités ont donc été générés/reviewés sous le même contrat que les 4 chunks restants.

Tant qu'aucun nouveau patch modifiant :

- prompts ;
- schema ;
- logique Generator/Critic ;
- validation Forge

n'est appliqué avant la reprise, il faut simplement reprendre le run.

Commande :

```powershell
Set-Location 'D:\Swarmblight'

.\.venv\Scripts\python.exe forge.py build adad9557-327d-55f6-b2b1-8bfdc9779f67
```

Attendu après reset du budget journalier :

```text
processed_chunks = 14
retryable_chunks = 0
failed_chunks = 0
```

## Quand purger à nouveau ?

Seulement si un nouveau défaut structurel impose un changement de contrat en cours de corpus :

```text
pipeline changé
→ résultats produits sous deux contrats différents
→ purge
→ re-ingest
→ rebuild intégral
```

Une simple nuit / un reset budget n'est **pas** une raison de purger.

---

# 51. Audit à faire après 14/14

Une fois le document terminé :

```powershell
.\.venv\Scripts\python.exe forge.py list --kind cards --topic xss --status approved

.\.venv\Scripts\python.exe forge.py list --kind cards --topic xss --status rejected
```

Puis auditer :

- source fidelity ;
- couverture du document ;
- qualité de `principle` ;
- qualité de `triggers` ;
- qualité et sémantique de `evidence_required` ;
- éventuelles ambiguïtés AND/OR dans les preuves ;
- duplication / fragmentation ;
- distribution des longueurs ;
- champs proches des bornes 400/800 ;
- qualité des raisons de rejet ;
- stabilité de `confidence` comme tie-breaker advisory ;
- absence de compression artificielle due aux contraintes.

Ne passer à :

```text
02_reflected_xss.md
```

qu'après validation qualitative de `01_xss_overview.md`.

---

# 52. Backlog technique issu du 2026-08-28

## Prioritaire après stabilisation du premier corpus

### Stage resumability

Actuellement un chunk `retryable` après échec Critic peut refaire son Generator.

Architecture future possible :

```text
pending
→ generator_completed
→ critic_pending
→ processed
```

Objectif :

- ne pas repayer un Generator déjà valide ;
- reprendre directement le candidat au stage Critic.

### Accounting HTTP

Le code classe actuellement les 4xx comme definite pre-response failures.

Backlog :

> auditer la certitude par statut HTTP plutôt que généraliser aveuglément à tous les 4xx.

Pas de changement pendant la calibration actuelle.

### Critic max output

Après obtention d'une distribution plus propre des Critics :

- mesurer `output_tokens`, pas seulement `visible chars` ;
- envisager éventuellement un plafond 4k/6k ;
- ne pas baisser avant d'avoir un échantillon suffisant.

### `confidence`

Tant qu'il n'est qu'un tie-breaker secondaire :

- méta-confiance advisory acceptable.

Si son poids augmente :

- sortir vers une métrique de review calibrée ;
- éviter la pseudo-précision auto-évaluée.

### `evidence_required`

Continuer à surveiller les cartes où plusieurs preuves sont listées sans sémantique AND/OR explicite.

---

# 53. Invariants confirmés le 2026-08-28

## LLM lifecycle

- usage réel extrait avant validation finale ;
- reasoning tokens observables séparément ;
- incomplete/max_output_tokens reste fail-closed ;
- aucun JSON incomplet réparé ;
- raw output non loggé ;
- erreurs provider diagnostiquées de manière bornée.

## Structured Output

- provider schema et Pydantic restent alignés ;
- maxLength agit pendant la génération ;
- aucune troncature silencieuse post-hoc ;
- whitespace structurel peut encore dégénérer côté provider ;
- une telle dégénérescence produit retryable, pas approved.

## Forge

- 0 card Generator reste valide ;
- source fidelity ne s'applique pas aux méta-jugements comme `confidence` ;
- `confidence` reste borné `0..1` ;
- `MAX_CARD_REVISIONS=1` reste inchangé ;
- policy/budget/code déterministe > LLM.

## Corpus

- XSS Overview reste le corpus de calibration ;
- aucune transition vers `02_reflected_xss.md` avant audit final du 14/14.

---

# 54. Résumé ultra-court pour reprise — FIN DE SESSION 2026-08-28

1. Ancienne clé API accidentellement transmise via `.env` → **révoquée et remplacée** ; ne plus transmettre `.env`.
2. `.venv` réel absent des archives, mais son arborescence nominale peut exister dans `tree.txt`.
3. Les Critics à 10k n'étaient **pas** victimes d'un reasoning explosion.
4. Autopsie : sortie visible dégénérée :
   - `reasons[*]` remplie de `.  .  .` ;
   - whitespace JSON structurel massif.
5. Hardening ajouté :
   - maxLength provider/Pydantic ;
   - reasons 1–4 × 400 chars ;
   - text items 400 ;
   - principle/demonstrated 800 ;
   - tags 40 ;
   - Critic compact ;
   - reasoning/output diagnostics.
6. Régression HTTP 400 trouvée : `verbosity` envoyé à la racine.
7. Correctif : Critic envoie désormais `text.verbosity="low"`.
8. White-space loop reproduit malgré maxLength sur `d97...`.
9. Autopsie CASE B :
   - JSON incomplet ;
   - 3 objets ouverts ;
   - milliers de `space + CR/LF` ;
   - **aucune récupération** ; fail-closed maintenu.
10. Diagnostics structurels `incomplete` ajoutés ; suite à **105 tests**.
11. Run `59cb...` a finalement atteint **14/14** mais corpus audit = `4 approved / 11 rejected`.
12. Audit a révélé une erreur de catégorie : `confidence` était traité comme claim source-bound.
13. `confidence` est désormais défini comme **méta-confiance advisory Forge**, Generator-owned / Critic-recalibrable / validation déterministe 0..1.
14. `confidence` sert surtout de tie-breaker retrieval + persistence ; pas d'approbation/dedup/context Ikit.
15. `MAX_CARD_REVISIONS=1` reste inchangé.
16. Patch `confidence` validé : **110 tests**, compileall/imports OK, aucune migration.
17. Ancien corpus contaminé purgé : **30 cartes** supprimées avec le document/run/chunks associés.
18. Re-ingest propre → même document ID :
    `adad9557-327d-55f6-b2b1-8bfdc9779f67`.
19. Nouveau run propre :
    `9ecc833b-c1d1-428a-8761-0fd3ee622687`.
20. État actuel :
    ```text
    status = budget_exhausted
    processed_chunks = 10
    retryable_chunks = 0
    failed_chunks = 0
    approved_cards = 8
    rejected_cards = 1
    candidate_cards = 1
    ```
21. Stop uniquement sur :
    `Daily token budget would be exceeded (250476 > 250000)`.
22. **Ne pas purger demain.**
23. Après reset du budget journalier, reprendre simplement :
    ```powershell
    .\.venv\Scripts\python.exe forge.py build adad9557-327d-55f6-b2b1-8bfdc9779f67
    ```
24. Si 14/14 propre → audit approved/rejected → seulement ensuite `02_reflected_xss.md`.
25. Config de reprise :
    ```dotenv
    GENERATOR_MAX_OUTPUT_TOKENS=4000
    CRITIC_MAX_OUTPUT_TOKENS=10000
    MAX_OUTPUT_TOKENS=4000
    DAILY_TOKEN_BUDGET=250000
    DAILY_BUDGET_USD=0.50
    MONTHLY_BUDGET_USD=3.00
    MAX_COST_PER_RUN_USD=0.50
    ```

---

# 55. État mental du rat au moment de fermer l'atelier — 2026-08-28

```text
SECOND SCHOOL DAY:

- critic skull opened
- reasoning acquitted
- dot-loop imprisoned
- whitespace-loop identified
- fake JSON recovery refused
- verbosity door repaired
- confidence grading policy abolished
- school rebuilt clean
- 10/14 lessons completed
- daily treasury reached exact wall
- no retryable
- no failed
- no database corruption
```

> **MORRSLIEB EMPTY AGAIN. THIS TIME RATS ACTUALLY LEARNED SOMETHING. SLEEP-SLEEP.**

---

**End of context snapshot — 2026-08-28, end of session**
