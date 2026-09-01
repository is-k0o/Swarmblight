# Swarmblight — Patchnote du 1er septembre 2026

## Statut de fin de session

La session du jour a surtout servi à **calibrer et auditer le Source Fidelity Gate (“Thanquol”)** avant toute activation en production.

Résultat principal :

- **100/100 observations atomiques conformes** sur les quatre classes sémantiques évaluées.
- Une **régression full-card réelle** a ensuite révélé une faiblesse importante de couverture sur une carte Stored XSS historiquement faussement approuvée.
- Le diagnostic s’oriente désormais vers un problème de **salience / couverture multi-champs**, et non vers une incompréhension fondamentale des règles sémantiques.
- Un nouveau batch atomique ciblé Stored XSS a été préparé, mais **n’a pas pu démarrer** : le budget journalier de 250 000 tokens a été atteint avant le premier appel.
- **Source Fidelity Gate reste désactivé**. Aucun changement de production ne doit être activé avant la suite de la calibration.

---

# 1. SOURCE_FACTUAL — calibration terminée

## Nettoyage des fixtures positives

Les fixtures positives SOURCE_FACTUAL ont été rendues plus atomiques afin d’éviter des ambiguïtés expérimentales.

### `source_factual_pass_php_encoder`

Ancienne formulation ambiguë :

> `PHP HTML output uses htmlentities with ENT_QUOTES.`

Elle transformait une prescription source en état descriptif.

Nouvelle valeur :

> `In PHP HTML contexts, htmlentities with ENT_QUOTES should be used.`

Objectif : préserver la modalité normative de la source.

### `source_factual_pass_stored_later`

Nouvelle valeur :

> `Stored data appears later in responses.`

Le verbe `emitted` a été retiré afin d’éviter d’ajouter implicitement un mécanisme d’émission.

### `source_factual_pass_xss_users`

Nouvelle valeur :

> `XSS is a client-side issue directed at other application users.`

Le verbe `affecting` a été évité afin de ne pas transformer un ciblage en effet réalisé.

## Batch live SOURCE_FACTUAL

Cas testés, 5 répétitions chacun :

- `source_factual_pass_php_encoder`
- `source_factual_pass_stored_later`
- `source_factual_pass_xss_users`
- `source_factual_fail_sqli_queries`
- `source_factual_fail_encoder_availability`
- `source_factual_fail_browser_precondition`

Résultat :

```text
PASS attendus : 15/15
FAIL attendus : 15/15
Target detected : 15/15
Incomplete : 0
all_expected = true
```

### Verdict

**SOURCE_FACTUAL gelé pour l’instant.**

Aucun tuning supplémentaire sans nouveau contre-exemple réel.

---

# 2. SEMANTIC_LABEL — calibration terminée

## Audit des fixtures

Quatre cas étaient présents :

- `label_pass_taxonomy`
- `label_pass_distinctions`
- `label_fail_oauth`
- `label_fail_rce`

Le cas positif `label_pass_taxonomy` était trop discutable avec la valeur `taxonomy`, car une simple comparaison entre vulnérabilités ne constitue pas nécessairement une taxonomie.

La fixture a donc été nettoyée sans modifier son ID.

Nouvelle valeur :

> `cross-vulnerability comparison`

Rationale :

> faithful non-literal semantic label for content comparing multiple vulnerability classes.

## Batch live SEMANTIC_LABEL

5 répétitions par cas :

```text
label_pass_taxonomy       PASS 5/5
label_pass_distinctions   PASS 5/5

label_fail_oauth          FAIL 5/5, target 5/5
label_fail_rce            FAIL 5/5, target 5/5
```

Agrégat :

```text
expected_matches = 20/20
target_detected = 10/10
incomplete_count = 0
all_expected = true
```

### Point important

Le Gate accepte correctement des labels **non littéraux mais sémantiquement fidèles**.

Il ne fait donc pas du simple matching lexical :

- `cross-vulnerability comparison` passe bien qu’il ne soit pas repris mot pour mot.
- `distinctions` passe comme abstraction fidèle.
- `oauth` et `Remote code execution prevention` sont rejetés comme concepts étrangers.

### Verdict

**SEMANTIC_LABEL gelé pour l’instant.**

---

# 3. ROUTING_METADATA — calibration terminée

## Problème initial : fixture non constructible

Fixture historique :

```text
routing_fail_kerberos
source: XSS ↔ SQLi
value: ["kerberos"]
expected: FAIL
```

Inspection de `KnowledgeTopic` :

```python
class KnowledgeTopic(str, Enum):
    XSS = "xss"
    DOM = "dom"
    SQLI = "sqli"
    SSTI = "ssti"
```

`kerberos` n’étant pas dans l’enum, la fixture ne pouvait jamais atteindre le Gate : Pydantic la rejetait auparavant.

Ce n’était donc pas un vrai test de jugement sémantique.

## Nettoyage

L’ID historique `routing_fail_kerberos` a été conservé pour stabilité, mais sa valeur a été remplacée par un topic valide :

```text
source:
The source discusses SQL injection targeting the database.

value:
["dom"]

expected:
fail
```

Rationale :

> The source establishes SQL injection behavior but no semantic adjacency to DOM-based XSS.

Un test de régression déterministe a été mis à jour pour refléter cette nouvelle fixture schema-valid.

## Batch live ROUTING_METADATA

```text
routing_pass_sqli       PASS 5/5
routing_pass_dom        PASS 5/5

routing_fail_kerberos   FAIL 5/5, target 5/5
routing_fail_ssti       FAIL 5/5, target 5/5
```

Agrégat :

```text
expected_matches = 20/20
target_detected = 10/10
incomplete_count = 0
all_expected = true
```

### Point important

Le Gate fait correctement la distinction entre :

```text
topic valide dans l’ontologie
```

et :

```text
topic réellement adjacent à la source
```

La disponibilité d’un curriculum approuvé n’est pas requise pour justifier une route ; seule l’adjacence sémantique compte.

### Verdict

**ROUTING_METADATA gelé pour l’instant.**

---

# 4. Bilan atomique global

À ce stade :

```text
DERIVED_OPERATIONAL   30/30
SOURCE_FACTUAL        30/30
SEMANTIC_LABEL        20/20
ROUTING_METADATA      20/20
--------------------------------
TOTAL ATOMIC         100/100
```

Ce résultat signifie :

> Pris isolément, Thanquol comprend correctement les frontières sémantiques que nous lui demandons d’appliquer.

Il ne signifie pas encore :

> Sur une KnowledgeCard complète comportant de nombreux champs et plusieurs propositions simultanées, Thanquol inspecte de manière exhaustive toutes les contaminations.

C’est précisément ce que la phase suivante a testé.

---

# 5. Full-card regression — anciens faux approvals

Trois KnowledgeCards historiquement problématiques ont été rejouées avec :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-check <card-id> --repeat 5
```

## 5.1 SQLi / CSRF / XSS comparison

Card :

```text
4d6a500e-5a57-51bb-b423-20b52e77a95c
```

Chunk :

```text
8661ddb6-71ea-5514-a5be-0c9b5867f94d
```

Résultat :

```text
FAIL 5/5
```

Le Gate détecte notamment :

- `authenticated action`
- `induced request` / causal framing
- parfois l’ajout d’un transport `HTTP response`

Le vieux renforcement SQLi :

```text
crafted input alters database queries
```

n’a pas été explicitement remonté dans ces 5 reviews, alors qu’il était détecté 5/5 en atomique.

### Interprétation

Le verdict production serait correct : la carte est bloquée.

Mais `issues[]` ne doit pas être interprété comme une **autopsie exhaustive** de tous les problèmes.

---

## 5.2 Stored XSS

Card :

```text
7b1a66e5-1437-5820-8785-c981ca438fa1
```

Résultat :

```text
PASS 4/5
FAIL 1/5
```

C’est le premier vrai contre-exemple important après les 100/100 atomiques.

La carte contenait historiquement des renforcements tels que :

- exigence `verbatim`
- exigence `same payload`
- qualification `sessions`

Le seul FAIL observé a détecté :

> `Which users or sessions view the pages that include the persisted data?`

et a rejeté `sessions` comme concept session/auth absent du chunk.

En revanche, dans 4 runs sur 5, la carte complète a été acceptée malgré les renforcements historiques connus.

### Conclusion

```text
KNOWN BAD FULL CARD
→ accepted 4/5
```

C’est insuffisant pour un admission gate fail-closed.

Il ne faut toutefois pas lire `4/5` comme une estimation statistique fiable d’un taux de faux approval en production : l’échantillon est trop petit.

Le constat valide est simplement :

> Une carte connue comme non fidèle peut encore passer lorsqu’elle est évaluée sous forme full-card.

---

## 5.3 XSS PoC

Card :

```text
c5bcfb72-3485-50ea-918a-e4874e34223e
```

Résultat :

```text
FAIL 5/5
```

Le Gate détecte plusieurs renforcements :

- `should` → `must`
- `observable` → `reproducible`
- ajout d’une exigence `same injected input`
- ajout d’un workflow de preuve spécifique
- parfois `reflected`
- parfois des artefacts spécifiques comme `server logs` / `network captures`

### Conclusion

Très bon rejet sur cette carte.

---

# 6. Diagnostic : compétence atomique ≠ couverture full-card

Le contraste observé est maintenant :

```text
ATOMIC SEMANTIC COMPETENCE        OK
FULL-CARD COVERAGE / SALIENCE     INSUFFICIENT
```

Le problème ne ressemble plus à :

> Thanquol ne comprend pas les frontières sémantiques.

Il ressemble davantage à :

> Une carte contenant beaucoup de champs et de propositions simultanées peut diluer l’attention du modèle ; certaines contaminations passent malgré des règles atomiquement maîtrisées.

Le fait que SQLi et PoC soient rejetés ne suffit pas à résoudre le problème : Stored XSS constitue un vrai faux négatif de la Gate.

---

# 7. Direction envisagée : V0.6.5.6 — Decomposed Field Fidelity Review

Aucune implémentation production n’a encore été faite.

La direction architecturale privilégiée est désormais une Gate décomposée.

Au lieu de :

```text
SOURCE + FULL CARD
→ 1 gros jugement
```

viser :

```text
SOURCE + subtopic
SOURCE + title
SOURCE + tags
SOURCE + triggers
SOURCE + principle
SOURCE + questions_to_ask
SOURCE + false_positive_traps
SOURCE + evidence_required
SOURCE + escalation_topics
SOURCE + technique_assumptions
SOURCE + prerequisites
SOURCE + demonstrated_behavior
→ reviews ciblées
→ agrégation déterministe
```

Pour les champs listés, envisager une granularité encore plus fine :

```text
questions_to_ask[0] → review
questions_to_ask[1] → review
questions_to_ask[2] → review
...
```

Le code devrait vérifier :

```text
nombre d’items projetés
==
nombre d’items réellement évalués
```

et faire du fail-closed en cas d’incomplete.

### Principe

```text
LLM:
jugement sémantique

CODE:
projection
couverture
agrégation
fail-closed
```

Cette direction est cohérente avec la doctrine Swarmblight :

> le modèle peut juger ; le code doit garantir structure, couverture et scepticisme.

---

# 8. Diagnostic préalable V0.6.5.6 : quatre fixtures Stored XSS ciblées

Avant de modifier l’architecture, quatre nouvelles fixtures atomiques ont été ajoutées afin de déterminer si les anciens crimes Stored XSS sont bien détectables lorsqu’ils sont isolés.

## Fixture 1 — PASS fidèle

```text
id:
derived-stored-xss-later-response-faithful

field:
questions_to_ask

value:
Which later HTTP responses include the persisted data?

expected:
PASS
```

## Fixture 2 — FAIL verbatim

```text
id:
derived-stored-xss-verbatim

field:
questions_to_ask

value:
Is the persisted data included verbatim in later HTTP responses?

expected:
FAIL
```

Cette fixture teste la généralisation abusive d’un exemple particulier où le message board ne transforme pas les données.

Le source général établit :

```text
untrusted source
→ later HTTP response
→ unsafe inclusion
```

Il n’établit pas :

```text
Stored XSS
→ données nécessairement reproduites verbatim
```

## Fixture 3 — PASS fidèle

```text
id:
derived-stored-xss-unsafe-inclusion-faithful

field:
evidence_required

value:
Confirm that data received from an untrusted source is later included
in an HTTP response in an unsafe way.

expected:
PASS
```

## Fixture 4 — FAIL same-payload

```text
id:
derived-stored-xss-same-payload

field:
evidence_required

value:
Submit a payload via an input path that the application persists,
and show the same payload is later present in an HTTP response
where a browser would parse it.

expected:
FAIL
```

Cette fixture reproduit le renforcement historique :

- identité stricte `same payload`
- workflow spécifique
- browser parsing condition

---

# 9. Modification du harness pour source longue — audit

L’ajout des quatre fixtures Stored XSS a nécessité une modification de `forge.py`, car le chunk source complet dépasse certaines limites scalaires de `KnowledgeCard`.

Une fonction a été ajoutée :

```python
_source_prefix(source_text, max_length)
```

Le builder synthétique utilise désormais des prefixes verbatim bornés pour les champs neutres :

```text
subtopic   <= 80 caractères
title      <= 160 caractères
principle  <= 800 caractères
```

Mais :

```text
document.content == source complète exacte
chunk.content    == source complète exacte
target field     == candidate_value exacte
```

Les fonctions de scoring et d’évaluation :

- `_run_atomic_fidelity_evaluation`
- `_run_atomic_fidelity_evaluation_batch`

n’ont pas changé dans leur comportement sémantique.

Les tests ajoutés vérifient explicitement :

- même source complète pour les quatre fixtures ;
- target exact ;
- champs neutres source-derived ;
- aucune injection de l’answer key ;
- pas de mutation du corpus ;
- aucune modification des prompts/contracts.

Résultat de validation :

```text
pytest: 172 passed
compileall: passed
```

---

# 10. Batch Stored XSS ciblé — non exécuté à cause du budget journalier

Commande prévue :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch `
  derived-stored-xss-later-response-faithful `
  derived-stored-xss-verbatim `
  derived-stored-xss-unsafe-inclusion-faithful `
  derived-stored-xss-same-payload `
  --repeat 5
```

Le batch n’a pas démarré.

BudgetManager a refusé le premier appel :

```text
Daily token budget would be exceeded (250305 > 250000).
```

Important :

- le rejet intervient **avant le provider call** ;
- aucune observation du batch ciblé n’a été produite ;
- le protocole n’a pas été partiellement exécuté ;
- aucune raison de modifier artificiellement le quota pour continuer aujourd’hui.

La limite quotidienne de 250k tokens a joué exactement son rôle de garde-fou.

---

# 11. Point de reprise pour demain

## Première action

Relancer exactement :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-stored-xss-later-response-faithful derived-stored-xss-verbatim derived-stored-xss-unsafe-inclusion-faithful derived-stored-xss-same-payload --repeat 5
```

## Résultat attendu idéal

```text
later-response-faithful     PASS 5/5
verbatim                    FAIL 5/5 + target 5/5
unsafe-inclusion-faithful   PASS 5/5
same-payload                FAIL 5/5 + target 5/5

TOTAL                       20/20
```

## Interprétation si 20/20

Cela renforcerait fortement le diagnostic :

```text
THANQUOL SEMANTIC KNOWLEDGE     OK
THANQUOL FULL-CARD COVERAGE     NOT OK
```

Suite logique :

> concevoir puis implémenter V0.6.5.6 — Decomposed Field Fidelity Review.

## Interprétation si `verbatim` ou `same-payload` passent atomiquement

Alors le problème n’est pas seulement architectural.

Il faudra d’abord retravailler la frontière DERIVED_OPERATIONAL / factual payload avant toute décomposition field-wise.

---

# 12. État des décisions

## Gelé

```text
DERIVED_OPERATIONAL
SOURCE_FACTUAL
SEMANTIC_LABEL
ROUTING_METADATA
```

Aucun prompt-tuning supplémentaire sans nouveau contre-exemple.

## À ne pas faire

- Ne pas activer Source Fidelity Gate.
- Ne pas transformer les 100/100 atomiques en “production ready”.
- Ne pas utiliser un vote majoritaire sur plusieurs runs.
- Ne pas considérer `issues[]` comme exhaustif.
- Ne pas augmenter mécaniquement les reasoning tokens en espérant résoudre la couverture.
- Ne pas monter le budget uniquement pour contourner le garde-fou de la session.
- Ne pas construire V0.6.5.6 avant le batch Stored XSS ciblé.

## Feature flag

Reste :

```dotenv
SOURCE_FIDELITY_GATE_ENABLED=false
```

---

# 13. Résumé ultra-court

```text
Atomic Gate calibration:
100/100 ✅

Historical full-card regression:
SQLi/CSRF     FAIL 5/5 ✅
Stored XSS    FAIL 1/5 ❌
PoC           FAIL 5/5 ✅

Main finding:
atomic competence != full-card coverage

Next diagnostic:
4 Stored-XSS atomic fixtures × 5 runs

Status:
blocked only by daily 250k token budget

Production Gate:
still OFF
```

---

## Rat status

```text
Thanquol knows the rules.
Thanquol does not reliably inspect every cheat hidden in a full exam sheet.

Next experiment:
put the exact Stored-XSS cheats alone on his desk.

NO-NO MORE WARPSTONE TODAY.
TREASURY EMPTY.

YES-YES TOMORROW.
```
