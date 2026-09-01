# Swarmblight — Patchnote 2026-08-29 · Part I
## Forge Source Fidelity, Thanquol Admission Gate & Atomic Calibration

> Première partie de la journée : consolidation du premier corpus XSS, ajout du Source Fidelity Gate, clarification de l’ownership épistémique des champs, puis mise en place d’un harness d’évaluation atomique.

---

## 1. Finalisation du rebuild propre de `01_xss_overview.md`

Reprise du build propre du premier document canonique XSS après le correctif précédent sur l’ownership de `confidence`.

```text
document_id = adad9557-327d-55f6-b2b1-8bfdc9779f67
run_id      = 9ecc833b-c1d1-428a-8761-0fd3ee622687

status = completed
processed_chunks = 14
retryable_chunks = 0
failed_chunks = 0
approved_cards = 13
rejected_cards = 1
candidate_cards = 1
```

La reprise des quatre chunks restants s’est terminée proprement : `200 OK`, appels Generator/Critic `completed`, JSON structurés valides, aucun nouveau `400`, aucune boucle de whitespace et aucune troncature.

Le pipeline technique était donc stable.

---

## 2. Audit humain : `approved` ne veut pas encore dire `canonical`

L’audit des cartes a montré trois faux approvals source-fidelity.

### SQLi / CSRF / XSS

Source :

```text
SQL injection is a server-side vulnerability that targets the application's database.
```

Carte :

```text
crafted input alters database queries
```

Le mécanisme `alters database queries` est plausible en WebSec, mais absent du chunk.

### Stored XSS

La carte généralisait notamment :

```text
verbatim
same payload
```

alors que le chunk établissait surtout la persistance et l’inclusion ultérieure dangereuse dans une réponse.

### PoC XSS

La source établissait :

```text
injecting input
→ browser executes arbitrary JavaScript
→ clear observable evidence in the relevant browser context
```

La carte ajoutait des hypothèses plus spécifiques sur `application output`, `target page` et certains chemins de réflexion.

### Contrôle négatif utile

La carte taxonomique rejetée :

```text
0117510c-6487-5415-90ba-783a4beda714
```

était, elle, légitimement rejetée.

Conclusion :

```text
le Critic sait détecter cette famille d’erreurs
mais ne la détecte pas de manière constante
```

On sort donc du debug primaire de lifecycle/schema pour entrer dans la calibration sémantique du reviewer LLM.

---

# 3. V0.6.5 — Source Fidelity Gate

Ajout d’un second reviewer spécialisé, plus étroit que le Critic :

```text
Source
  ↓
Generator
  ↓
Critic
  ↓
validation déterministe
  ↓
candidate final
  ↓
SourceFidelityGate
  ↓
dedup
  ↓
approved
```

Nom technique :

```text
SourceFidelityGate
```

Nom de rat officieux :

```text
Thanquol
```

Le Gate ne peut ni réécrire, ni améliorer, ni enrichir une carte. Il retourne seulement :

```text
PASS
FAIL
```

Sa seule question est :

```text
Does every non-speculative factual statement stay within
the semantic boundary of this exact source chunk?
```

Principe :

```text
General cybersecurity correctness is irrelevant.
The current chunk is the authority.
```

---

## 4. Contrat strict

`SourceFidelityReview` impose :

```text
PASS
→ decision = "pass"
→ checked_fields = tous obligatoirement true
→ issues = []

FAIL
→ decision = "fail"
→ checked_fields = tous obligatoirement true
→ issues = 1..8
```

Chaque issue contient :

```text
field
classification = stronger_than_source | unsupported
reason <= 300 caractères
```

Aucun `revised_card` n’existe dans le contrat.

Le Gate reste désactivé par défaut :

```dotenv
SOURCE_FIDELITY_GATE_ENABLED=false
```

Objectif :

```text
mesurer d’abord
activer ensuite
```

---

# 5. Resumability par stage

V0.6.5 corrige aussi une dette du Forge.

Avant :

```text
Generator ✅
Critic ✅
late-stage failure ❌

retry
→ Generator repaid
→ Critic repaid
```

Après finalisation du candidat :

```text
fidelity_pending
```

permet une reprise directe au Gate.

```text
retry
→ Fidelity Gate uniquement
→ Generator non rejoué
→ Critic non rejoué
```

---

## 6. Persistance des revues

Ajout de :

```text
knowledge_fidelity_reviews
```

avec notamment :

```text
card_id
status
checked_fields
issues
response_id
checked_at
updated_at
```

Un `FAIL` ne détruit pas la carte :

```text
Fidelity FAIL
→ reste candidate
→ auto-approval bloquée
→ motif auditable
```

Doctrine asymétrique :

```text
false rejection
→ coût de revue

false approval
→ pollution silencieuse du savoir Ikit
```

---

# 7. Premier test live : plafond 2k trop faible

Configuration initiale :

```dotenv
FIDELITY_MAX_OUTPUT_TOKENS=2000
```

Premier appel réel :

```text
status = incomplete
reason = max_output_tokens
reasoning_tokens = 1792
output_chars = 734
```

Diagnostic :

```text
raw_decode = false
semantic_complete = false
unclosed_depth = 4
inside_string = true
trailing_whitespace_chars = 0
```

Il s’agissait d’une vraie troncature JSON, pas de l’ancien problème de dégénérescence en whitespace.

Correction :

```dotenv
FIDELITY_MAX_OUTPUT_TOKENS=4000
```

Invariant conservé :

```text
BudgetManager reservation
==
effective Responses API max_output_tokens
```

Le harness `fidelity-check` gère désormais les `IncompleteLLMResponse` proprement et poursuit les répétitions retryables.

Validation :

```text
130 passed
```

---

# 8. Thanquol V0.6.5 : trop littéral

Sur une carte XSS/CSRF/SQLi connue comme incorrecte :

```text
FAIL / FAIL / FAIL
```

Mais certaines accusations étaient mauvaises :

```text
tag = taxonomy
→ rejeté parce que le mot "taxonomy" n’est pas littéralement dans le source
```

```text
trigger = vulnerability classification
→ même problème
```

```text
escalation_topics = ["sqli"]
→ rejeté parce que la source ne dit pas "escalation topic"
```

Le Gate confondait :

```text
fidélité sémantique
```

avec :

```text
présence lexicale littérale
```

et appliquait presque la même règle à des champs qui n’avaient pas le même rôle épistémique.

---

# 9. V0.6.5.1 — KnowledgeCard Field Semantics

Audit des 24 champs de `KnowledgeCard`.

Nouvelle classification :

```text
SOURCE_FACTUAL
DERIVED_OPERATIONAL
SEMANTIC_LABEL
ROUTING_METADATA
FORGE_METADATA
EXPLICIT_EXTRAPOLATION
PROVENANCE_STATE
```

## SOURCE_FACTUAL

```text
principle
false_positive_traps
technique_assumptions
prerequisites
demonstrated_behavior
```

Règle :

```text
chaque proposition doit être DIRECT
ou
FAITHFUL_ABSTRACTION
```

Aucun nouveau mécanisme, prérequis, état, impact ou détail d’implémentation.

## DERIVED_OPERATIONAL

```text
triggers
questions_to_ask
evidence_required
```

Ces champs peuvent transformer un fait supporté en :

```text
cue
question
observation
preuve minimale
```

Exemple valide :

```text
SOURCE:
Use htmlentities with ENT_QUOTES for HTML contexts.

EVIDENCE:
Confirm the HTML output path uses htmlentities with ENT_QUOTES.
```

La source n’a pas besoin de contenir le mot `confirm`.

## SEMANTIC_LABEL

```text
subtopic
title
tags
```

Règle :

```text
pertinence sémantique
≠
identité lexicale
```

Un chunk comparant XSS, CSRF et SQLi peut recevoir :

```text
taxonomy
comparison
distinctions
```

sans que ces mots soient littéralement présents.

## ROUTING_METADATA

```text
escalation_topics
```

Interprétation :

```text
arête conceptuelle vers un autre topic
```

Par exemple :

```text
escalation_topics = ["sqli"]
```

n’implique ni que la source emploie le terme `escalation`, ni qu’un curriculum SQLi soit déjà ingéré.

## FORGE_METADATA

```text
confidence
```

Appartient au Forge/modèle, pas à la source.

## EXPLICIT_EXTRAPOLATION

```text
speculative_extensions
```

Seule zone explicitement autorisée à dépasser la source, tant que l’extrapolation reste isolée.

## PROVENANCE_STATE

```text
id
agent
topic
source_type
source_title
source_reference
source_chunk_id
status
created_at
updated_at
```

Champs applicatifs déterministes.

Validation V0.6.5.1 :

```text
136 passed
```

---

# 10. Source corpus ≠ knowledge corpus ≠ ontology

Clarification importante.

Le corpus source local contient :

```text
01_xss_overview.md
02_reflected_xss.md
03_stored_xss.md
04_xss_contexts.md
05_exploiting_xss.md
06_preventing_xss.md
07_content_security_policy.md
08_dangling_markup.md
```

Mais le build canonique calibré concerne encore le savoir issu de :

```text
01_xss_overview.md
```

Ce document mentionne déjà :

```text
DOM-based XSS
SQL injection
PHP
Java
```

même si les curricula détaillés ne sont pas encore présents dans les KnowledgeCards d’Ikit.

Séparation retenue :

```text
SOURCE CORPUS
→ fichiers disponibles

INGESTED DOCUMENTS
→ documents réellement ingérés

APPROVED KNOWLEDGE CORPUS
→ cartes réellement admises

TOPIC ONTOLOGY / ROUTING SPACE
→ concepts pouvant exister sans curriculum approuvé
```

---

# 11. Retest V0.6.5.1 : nuance excessive

La même mauvaise carte SQLi donne :

```text
FAIL / PASS / PASS
```

Les faux griefs lexicaux diminuent, mais `DERIVED_OPERATIONAL` devient parfois trop permissif.

Un fait nouveau peut se cacher dans une question ou une exigence de preuve :

```text
Confirm crafted input alters SQL queries.
```

Le modèle semble parfois interpréter :

```text
derived operational field
```

comme :

```text
permission générale de dériver du contenu
```

---

# 12. V0.6.5.2 — Operational wrapper vs factual payload

Nouvelle règle :

```text
Only the operational framing may be introduced by Forge;
the factual payload inside that framing may not be invented.
```

Méthode mentale :

```text
1. retirer le wrapper
2. auditer la proposition restante
```

Exemple :

```text
Confirm crafted input alters SQL queries.
```

devient :

```text
crafted input alters SQL queries
```

Puis :

```text
source supporte cette proposition ?
→ non
→ FAIL
```

Thanquol effectue désormais deux checks :

```text
CHECK 1 — OPERATIONAL DERIVATION
Le wrapper opérationnalise-t-il un concept supporté ?

CHECK 2 — FACTUAL PAYLOAD
Le fait restant est-il source-bound ?
```

Le patch conserve les acquis de V0.6.5.1 :

- pas de matching lexical;
- `taxonomy` peut rester valide;
- `escalation_topics=["sqli"]` peut rester valide;
- les verbes d’observation n’ont pas besoin d’être présents dans la source.

Validation :

```text
138 passed
```

---

# 13. Retest V0.6.5.2 sur la carte complète

Résultat :

```text
FAIL / FAIL / FAIL
```

La régression `F / P / P` disparaît.

Mais la fuite précise :

```text
crafted input alters database queries
```

n’est explicitement identifiée que dans un run.

La carte contient plusieurs erreurs simultanées :

```text
authenticated
induced request
alters database queries
```

Un `FAIL` global ne prouve donc pas que Thanquol maîtrise une frontière sémantique précise.

Il faut un test atomique.

---

# 14. V0.6.5.3 — Atomic Fidelity Evaluation Harness

Ajout de :

```text
forge.py fidelity-eval <case-id> --repeat N
```

avec :

```text
1 <= N <= 5
```

Objectif :

```text
ONE CASE
ONE TARGET FIELD
ONE EXPECTED BOUNDARY
ONE VERDICT
```

Aucun vote automatique.

Source de vérité unique :

```text
tests/corpus/knowledge_card_field_semantics_cases.json
```

Le harness construit uniquement en mémoire :

```text
synthetic document
synthetic chunk
synthetic KnowledgeCard
```

Aucune carte, revue ou exécution Forge synthétique n’est persistée.

Seule la comptabilité provider reste persistée via `BudgetManager`.

---

## 15. Isolation des champs et métrique cible

Pour réduire les contaminations :

```text
arrays non ciblés → []
title → source verbatim
principle → source verbatim
subtopic → préfixe source-faithful
```

Nouvelle métrique :

```text
target_detected_count
```

Règle :

```text
expected FAIL
+ Gate retourne FAIL
+ issue uniquement sur un autre champ
=
MISS sémantique
```

Le harness mesure donc le champ ciblé, pas seulement le verdict global.

Validation :

```text
158 passed
```

---

# 16. Premier test atomique — SQLi faithful

Commande :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval derived-sqli-faithful --repeat 5
```

Source :

```text
SQL injection is a server-side vulnerability that targets the application's database.
```

Fixture :

```text
Confirm that the observed behavior affects the application's database.
```

Résultat :

```text
PASS
PASS
PASS
FAIL
PASS
```

Soit :

```text
pass_count = 4
fail_count = 1
matches_expected = 4/5
incomplete_count = 0
```

Le seul FAIL conteste la transformation :

```text
targets database
```

vers :

```text
observed behavior affects database
```

La fixture positive n’était donc pas parfaitement atomique : elle changeait à la fois le wrapper et le prédicat.

---

# 17. Premier test atomique — SQLi mechanism

Commande :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval derived-sqli-mechanism --repeat 5
```

Source :

```text
SQL injection is a server-side vulnerability that targets the application's database.
```

Candidate :

```text
Confirm crafted input alters SQL queries.
```

Résultat :

```text
FAIL
FAIL
FAIL
FAIL
FAIL
```

Avec :

```text
pass_count = 0
fail_count = 5
matches_expected = 5
target_detected_count = 5
incomplete_count = 0
```

Les cinq runs identifient le champ exact :

```text
evidence_required
```

et le mécanisme exact :

```text
crafted input alters SQL queries
```

comme absent ou plus fort que la source.

C’est le meilleur résultat sémantique obtenu jusqu’ici sur cette frontière précise.

---

# 18. État à la pause

```text
Harness infrastructure        ✅
SourceFidelityGate            ✅
Stage resumability            ✅
Budget/accounting             ✅
4000 token ceiling            ✅
Field ownership model         ✅
Wrapper/payload distinction   ✅
Atomic evaluation harness     ✅

SQLi mechanism FAIL case      5/5 ✅
target detected               5/5 ✅

SQLi faithful PASS case       4/5 ⚠️
fixture purity                contestable ⚠️

Production gate enabled       NON
Canonical XSS corpus          PAS ENCORE
```

---

# 19. Prochaine étape

Ne pas retoucher le prompt immédiatement.

Rendre d’abord la fixture PASS réellement atomique.

Au lieu de :

```text
Confirm that the observed behavior affects the application's database.
```

utiliser quelque chose comme :

```text
Confirm that SQL injection targets the application's database.
```

La paire devient :

```text
PASS CASE

SOURCE:
SQL injection targets the application's database.

DERIVED:
Confirm that SQL injection targets the application's database.
```

contre :

```text
FAIL CASE

SOURCE:
SQL injection targets the application's database.

DERIVED:
Confirm crafted input alters SQL queries.
```

Objectif :

```text
wrapper-only faithful case
→ PASS 5/5

unsupported mechanism case
→ FAIL 5/5
→ target_detected 5/5
```

Ensuite seulement :

```text
CSRF pair
PHP pair
semantic labels
routing metadata
source-factual cases
```

---

# 20. Doctrine consolidée

```text
Knowledge != Evidence.
```

```text
Correct WebSec knowledge != source-supported knowledge.
```

```text
Not every KnowledgeCard field is testimony.
```

```text
Some fields are facts.
Some are questions.
Some are observations.
Some are semantic labels.
Some are routing edges.
Some belong to Forge itself.
```

Pour les champs opérationnels :

```text
THE WRAPPER MAY BE DERIVED.
THE FACT MAY NOT BE INVENTED.
```

---

## Rat summary

```text
Generator:
"I found knowledge."

Critic:
"I reviewed and edited knowledge."

Thanquol:
"I don't care whether it is useful.
Show me where this chunk gives you permission to say it."
```

Puis :

```text
THANQUOL MAY INVENT THE QUESTION.

THANQUOL MAY NOT INVENT
THE ANSWER HIDDEN INSIDE THE QUESTION.
```

Et enfin :

```text
ONE RAT.
ONE CRIME.
ONE RECEIPT.

MEASURE FIRST.
TUNE LATER.

YES-YES.
```
