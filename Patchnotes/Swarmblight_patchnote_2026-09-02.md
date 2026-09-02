# Swarmblight — Patchnote du 2026-09-02

## Résumé

Journée consacrée à l’autopsie du **Source Fidelity Gate** autour du cas historique Stored XSS, puis à la préparation d’un holdout indépendant pour distinguer proprement :

- une **opérationnalisation fidèle** d’une proposition source ;
- une **spécification plus forte** que la source ;
- une **généralisation illégitime d’un exemple** ;
- une **complétion plausible par connaissance WebSec** ;
- un **entailment direct / une coréférence** réellement supporté par le texte.

Aucune modification de comportement production n’a été faite aujourd’hui.

Le **Source Fidelity Gate reste OFF**.

---

## 1. Reprise du diagnostic Stored XSS

Le point de départ était le faux positif historique Stored XSS : un KnowledgeCard avait été approuvé alors qu’il contenait des renforcements tels que `verbatim`, `same payload`, un qualificatif `sessions`, et un workflow de preuve plus spécifique que la source.

Le batch full-card précédent avait montré une faiblesse nette : le mauvais card avait obtenu **PASS 4/5**. L’hypothèse initiale était donc que le Gate connaissait la frontière sémantique, mais manquait certains claims dans une carte entière.

Cette hypothèse a été testée aujourd’hui.

---

## 2. Batch atomique Stored XSS ciblé

Commande :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-stored-xss-later-response-faithful derived-stored-xss-verbatim derived-stored-xss-unsafe-inclusion-faithful derived-stored-xss-same-payload --repeat 5
```

### Résultats

| Cas | Attendu | Résultat |
|---|---:|---:|
| `derived-stored-xss-later-response-faithful` | PASS | PASS 5/5 |
| `derived-stored-xss-verbatim` | FAIL | FAIL 3/5, PASS 2/5 |
| `derived-stored-xss-unsafe-inclusion-faithful` | PASS | PASS 5/5 |
| `derived-stored-xss-same-payload` | FAIL | PASS 5/5 |

Agrégat :

- **13/20** observations conformes ;
- positifs : **10/10** ;
- négatifs : **3/10** ;
- incomplete : **0**.

### Conclusion

Le problème ne pouvait plus être attribué uniquement à la densité multi-field. Le Gate échouait aussi sur certains cas isolés atomiquement.

Cependant, `verbatim` et surtout `same payload` restaient potentiellement ambigus car la source elle-même dit que l’application reçoit des données puis « includes that data » dans une réponse ultérieure, et son exemple de message board précise qu’aucun autre traitement n’est effectué.

Il fallait donc isoler plus précisément la frontière.

---

## 3. Micro-autopsie Stored XSS — première expansion

Commit GitHub :

```text
3768ff2180f74a5120d16f2009573a59789ca9c0
Add Stored XSS fidelity diagnostic fixtures
```

Cinq fixtures atomiques supplémentaires ont été ajoutées :

- `derived-stored-xss-workflow-faithful`
- `derived-stored-xss-exact-bytes`
- `derived-stored-xss-browser-html-context`
- `derived-stored-xss-example-no-processing-scoped`
- `derived-stored-xss-no-processing-generalized`

État après modification :

- fixtures : **38 total / 36 mesurées** ;
- `DERIVED_OPERATIONAL` : **10 PASS / 12 FAIL** ;
- tests : **177 passed** ;
- compile/import/preflight : OK ;
- aucun appel OpenAI pendant la modification ;
- aucune mutation de l’état production.

### Batch live

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-stored-xss-workflow-faithful derived-stored-xss-exact-bytes derived-stored-xss-browser-html-context derived-stored-xss-example-no-processing-scoped derived-stored-xss-no-processing-generalized --repeat 5
```

| Cas | Attendu | Résultat |
|---|---:|---:|
| workflow fidèle | PASS | PASS 5/5 |
| exact byte-for-byte | FAIL | FAIL 5/5 |
| browser parses as HTML | FAIL | PASS 5/5 |
| exemple no-processing scoped | PASS | PASS 5/5 |
| no-processing généralisé | FAIL | FAIL 5/5 |

Agrégat : **20/25**, incomplete **0**.

### Interprétation

Les frontières suivantes sont correctement maîtrisées :

- opérationnalisation d’un workflow source-supported ;
- byte-for-byte / unchanged reproduction plus fort que la source ;
- propriété explicitement limitée à un exemple ;
- généralisation abusive d’une propriété d’exemple vers toute la classe Stored XSS.

Le cas `browser parses as HTML` restait seul problématique, mais son statut de négatif était lui-même discutable : la source montre du HTML, un `<script>`, et précise que les messages sont affichés à d’autres utilisateurs.

---

## 4. Micro-autopsie Stored XSS — deuxième expansion

Commit GitHub :

```text
abd18e226625b9b72a22ecff1f15fecb1af5cb4c
Added the three fixture-only Stored XSS diagnostics without modifying existing cases
```

Trois fixtures supplémentaires :

- `derived-stored-xss-html-example-scoped`
- `derived-stored-xss-browser-inference-example-scoped`
- `derived-stored-xss-html-generalized`

État après modification :

- fixtures : **41 total / 39 mesurées** ;
- `DERIVED_OPERATIONAL` : **11 PASS / 14 FAIL** ;
- tests : **180 passed** ;
- compile/import/preflight : OK ;
- aucun changement production.

### Batch live

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-stored-xss-html-example-scoped derived-stored-xss-browser-inference-example-scoped derived-stored-xss-html-generalized --repeat 5
```

| Cas | Attendu initial | Résultat |
|---|---:|---:|
| HTML example scoped | PASS | PASS 5/5 |
| browser inference example scoped | FAIL | PASS 5/5 |
| HTML generalized | FAIL | FAIL 5/5 |

Agrégat : **10/15**, incomplete **0**.

### Réévaluation conceptuelle

Le résultat ne justifie pas de modifier le prompt uniquement pour forcer le deuxième cas à FAIL.

Une règle plus générale a émergé :

```text
A. explicit statement
   -> autorisé

B. direct entailment / coreference,
   sans changement de scope, modalité, mécanisme ou hypothèse
   -> potentiellement autorisé

C. plausible domain completion
   -> interdit

D. example -> general rule
   -> interdit
```

Critère de travail :

```text
La source peut-elle rester vraie alors que le claim candidat est faux ?

OUI
-> le claim n'est pas entailed
-> FAIL

NON, sans changer scope/modalité
-> entailment direct
-> PASS potentiel
```

Cette distinction reste à mesurer indépendamment du Stored XSS.

---

## 5. Préparation d’un holdout indépendant entailment vs completion

Commit GitHub :

```text
c68f58f0ad4e6d0571fb794a77c317b62338f6b4
Add fidelity entailment holdout fixtures
```

Huit nouveaux holdouts ont été ajoutés, **sans exécution live aujourd’hui**.

### Paires préparées

1. **q parameter**  
   - PASS : coréférence directe entre valeur reçue et valeur incluse plus tard.  
   - FAIL : ajout d’un contexte HTML non établi.

2. **Comment visible**  
   - PASS : le commentaire soumis est montré à un autre utilisateur.  
   - FAIL : ajout d’un navigateur et d’un rendu HTML.

3. **Nickname stocké**  
   - PASS : le nickname affiché est celui précédemment stocké.  
   - FAIL : ajout d’un stockage en base SQL.

4. **Réponse HTTP littérale**  
   - PASS : vérification de la chaîne exacte `<b>Hello</b>`.  
   - FAIL : ajout de l’interprétation HTML par un navigateur.

### État après préparation

- fixtures : **49 total / 47 mesurées** ;
- `SOURCE_FACTUAL` : **3 PASS / 3 FAIL** ;
- `DERIVED_OPERATIONAL` : **15 PASS / 18 FAIL** ;
- `SEMANTIC_LABEL` : **2 PASS / 2 FAIL** ;
- `ROUTING_METADATA` : **2 PASS / 2 FAIL** ;
- tests : **181 passed** ;
- compileall : OK ;
- import count : **49** ;
- les 8 holdouts passent le preflight constructibilité ;
- aucun appel OpenAI ;
- aucun changement de prompt, contrat, schema, evaluator, Gate ou runtime ;
- aucune mutation de DB / état production.

Les métadonnées de vérité suivantes restent hors entrée Gate :

- `id`
- `expected`
- `rationale`
- `derived_boundary`

---

## 6. Principe expérimental renforcé

Un **5/5** n’a de valeur que si le modèle arrive à la bonne conclusion pour les bonnes raisons.

Le harness continue donc de séparer strictement :

```text
fixture truth
├── expected
├── rationale
├── case_id
└── boundary_kind

                 X

runtime Gate input
├── exact source
└── candidate card
```

Les vérités de test ne sont jamais envoyées au Gate.

Il n’y a pas de vote majoritaire : chaque observation live reste indépendante.

---

## 7. État actuel du Source Fidelity Gate

### Ce qui est fortement supporté

Le Gate sait actuellement distinguer de manière stable :

- faithful operationalization ;
- mécanisme explicitement absent ;
- universalisation abusive ;
- byte-for-byte / unchanged strengthening ;
- example-scoped vs generalized property ;
- semantic labels ;
- routing metadata ;
- SOURCE_FACTUAL simples ;
- DERIVED_OPERATIONAL descriptifs et normatifs déjà calibrés.

### Ce qui reste ouvert

Le point non résolu est :

> jusqu’où une proposition non littérale peut-elle être considérée comme une implication directe de la source, sans devenir une complétion de domaine issue du pré-entraînement ?

En particulier :

```text
direct entailment / coreference
vs
plausible WebSec completion
```

---

## 8. Décision architecturale

**V0.6.5.6 — Decomposed Fidelity Review n’est pas encore implémenté.**

Raison :

- le full-card Gate présente bien un problème de couverture/salience ;
- mais la frontière atomique doit être stabilisée avant de construire une nouvelle architecture autour d’elle.

Une décomposition par champ/item ne suffit pas si la sémantique atomique est elle-même mal définie.

Une future architecture devra aussi tenir compte du coût : faire naïvement un appel LLM par champ/item serait trop coûteux. La piste actuelle reste :

```text
projection déterministe en unités de fidélité
-> petits batches contrôlés
-> contrôle exact de couverture
-> agrégation fail-closed
```

À ne pas implémenter avant le résultat du holdout.

---

## 9. GitHub / workflow projet

Swarmblight est maintenant versionné sur GitHub privé.

Workflow utilisé :

```bash
git status
git add .
git status
git commit -m "..."
git push
git status
```

Le connecteur GitHub permet désormais de vérifier directement commits, diffs et fichiers sans ré-uploader manuellement chaque modification Codex.

Commits du jour :

```text
3768ff2  Add Stored XSS fidelity diagnostic fixtures
abd18e2  Added the three fixture-only Stored XSS diagnostics without modifying existing cases
c68f58f  Add fidelity entailment holdout fixtures
```

Dernier état connu de `main` :

```text
c68f58f0ad4e6d0571fb794a77c317b62338f6b4
```

---

## 10. Prochaine action

Demain, exécuter **sans modifier le contrat avant mesure** :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-entailment-q-coreference derived-completion-q-html-context derived-entailment-comment-visible derived-completion-comment-browser-html derived-entailment-stored-nickname derived-completion-nickname-sql-storage derived-entailment-literal-response derived-completion-literal-response-browser --repeat 5
```

### Résultat idéal

```text
4 entailments directs
-> PASS 20/20

4 domain completions
-> FAIL 20/20
```

L’analyse devra toutefois porter sur :

- le verdict ;
- le champ réellement détecté ;
- la justification ;
- la stabilité inter-runs ;
- la nature du raisonnement.

### Si le holdout est propre

1. formaliser la règle entailment vs completion ;
2. ré-adjuger proprement les fixtures Stored XSS ambiguës ;
3. seulement ensuite reprendre la conception de V0.6.5.6.

### Si le holdout échoue

1. ne pas implémenter V0.6.5.6 ;
2. identifier la frontière atomique fautive ;
3. modifier le contrat de fidélité ;
4. retester anciens cas + nouveaux holdouts.

---

## 11. Freeze / garde-fous

À la fin du 2026-09-02 :

```text
SOURCE_FIDELITY_GATE_ENABLED=false
```

Toujours inchangé.

Aucun changement production aujourd’hui sur :

- `SOURCE_FIDELITY_PROMPT`
- `KNOWLEDGE_CARD_FIELD_SEMANTICS`
- Generator
- Critic
- schemas
- persistence
- budget
- admission path
- V0.6.5.6

Le travail du jour est exclusivement :

```text
mesurer
-> isoler
-> clarifier
-> préparer un holdout
```

Pas de correction prématurée.

---

## Checkpoint

```text
GitHub main:
c68f58f0ad4e6d0571fb794a77c317b62338f6b4

Tests:
181 passed

Fixtures:
49 total
47 measured

Gate:
OFF

Next:
entailment-vs-domain-completion holdout
40 live observations
```

🐀 **Thanquol passe demain l’examen à livre fermé.**
