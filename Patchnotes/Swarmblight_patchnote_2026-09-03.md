# Swarmblight — Patchnote du 3 septembre 2026

## Résumé

Journée centrée sur la **stabilisation du Source Fidelity Gate**, en particulier la frontière `DERIVED_OPERATIONAL / evidence_required`.

Le point principal découvert aujourd’hui est qu’il faut distinguer deux propriétés différentes d’une evidence :

1. **Source licensing** — l’evidence demandée est-elle autorisée par la source ?
2. **Evidentiary sufficiency** — cette evidence est-elle suffisamment forte pour établir la proposition qu’elle prétend substancier ?

Autrement dit :

> **Supported Evidence != Sufficient Evidence**

La journée a aussi permis de nettoyer le harness atomique, d’identifier une mauvaise adjudication dans nos propres fixtures, puis d’ajouter une règle générique d’evidence sufficiency au contrat partagé Generator / Critic / Gate.

Le Gate reste **OFF par défaut** et **V0.6.5.6 n’a pas été implémenté**.

---

## 1. Holdout entailment vs domain completion — premier run de la journée

Commande exécutée :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-entailment-q-coreference derived-completion-q-html-context derived-entailment-comment-visible derived-completion-comment-browser-html derived-entailment-stored-nickname derived-completion-nickname-sql-storage derived-entailment-literal-response derived-completion-literal-response-browser --repeat 5
```

### Résultat brut

- **40 observations**
- **36/40 expected matches**
- **20/20 target detections** sur les quatre cas négatifs de domain completion
- Aucun `incomplete`

### Cas propres

| Cas | Résultat |
|---|---:|
| `derived-entailment-q-coreference` | PASS 5/5 |
| `derived-completion-q-html-context` | FAIL 5/5 |
| `derived-completion-comment-browser-html` | FAIL 5/5 |
| `derived-entailment-stored-nickname` | PASS 5/5 |
| `derived-completion-nickname-sql-storage` | FAIL 5/5 |
| `derived-completion-literal-response-browser` | FAIL 5/5 |

Les quatre domain completions négatives ont été rejetées **5/5 pour les bonnes raisons** :

- HTTP response != HTML context
- shown to another user != browser renders as HTML
- stored != SQL database
- literal response body != browser interpretation as HTML

Cela renforce fortement l’idée que le Gate ne complète pas automatiquement les trous avec du savoir WebSec pré-entraîné.

---

## 2. Deux anomalies importantes découvertes dans le banc de test

### A. Faux FAIL du cas `comment-visible`

`derived-entailment-comment-visible` a fait **PASS 4/5**.

Le FAIL restant ne visait pas `questions_to_ask`, mais le `subtopic` synthétique créé par le harness.

Le builder utilisait un préfixe borné de la source. Dans ce cas, le préfixe tronquait la proposition avant **“another user”**, produisant involontairement un champ sémantiquement incomplet.

Conclusion :

> Le Gate n’avait pas raté l’entailment ; le harness avait fabriqué un mauvais champ neutre.

### B. Notre fixture `literal-response` était mal adjudicée

Source :

```text
The HTTP response body is the exact string '<b>Hello</b>'.
```

Candidate :

```text
Confirm that the HTTP response body contains the exact string '<b>Hello</b>'.
```

Nous l’avions initialement classée PASS.

Thanquol a relevé que :

```text
body == X
```

n’est pas équivalent à :

```text
body contains X
```

La deuxième condition autorise du contenu supplémentaire.

Important : `contains X` est bien **licencié par la source**, car l’égalité implique la contenance. Mais cette evidence est **trop faible pour établir l’égalité**.

C’est la première apparition nette du concept :

> **Source-supported evidence peut quand même être insufficient evidence.**

---

## 3. Cleanup du harness atomique

Commit :

```text
86cef8bce8e609acc49cd1c03b0051aeab377160
atomic evaluator harness cleanup
```

### Modifications

Fichiers :

- `forge.py`
- `tests/corpus/knowledge_card_field_semantics_cases.json`
- `tests/test_fidelity_eval.py`
- `tests/test_field_semantics.py`

### Nouvelle stratégie de scaffolding

- `subtopic` non ciblé -> `general`
- heading synthétique -> `general`
- `title` / `principle` -> unité source complète et bornée
- plus de troncature arbitraire au milieu d’une proposition
- source exacte toujours conservée dans `SourceDocument` et `SourceChunk`
- target candidate réinjecté exactement après construction du scaffold

### Re-adjudication historique

Fixture conservée :

```text
derived-entailment-literal-response
```

Source / field / candidate / ID inchangés.

Changement :

```text
expected: pass -> fail
derived_boundary: operational_wrapper -> factual_payload
```

Raison : **payload weakening / insufficient evidence**.

### Nouveau contrôle positif

Ajout :

```text
derived-entailment-literal-response-exact-equality
```

Candidate :

```text
Confirm that the HTTP response body is exactly the string '<b>Hello</b>'.
```

Attendu : PASS.

### Validation

- **50 total / 48 measured**
- `SOURCE_FACTUAL`: 3 pass / 3 fail
- `DERIVED_OPERATIONAL`: 15 pass / 19 fail
- `SEMANTIC_LABEL`: 2 pass / 2 fail
- `ROUTING_METADATA`: 2 pass / 2 fail
- **185 tests passed**
- compileall OK
- aucun appel OpenAI pendant la modification

---

## 4. Live test après cleanup du harness

Commande :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-entailment-comment-visible derived-entailment-literal-response derived-entailment-literal-response-exact-equality --repeat 5
```

### Résultats

| Cas | Résultat |
|---|---:|
| `comment-visible` | PASS 5/5 |
| `contains exact string` | FAIL 1/5, PASS 4/5 |
| `is exactly the string` | PASS 5/5 |

### Conclusion

Le cleanup a confirmé que le faux FAIL `comment-visible` venait bien du harness.

Le contrôle positif exact reste parfaitement accepté.

En revanche, l’evidence insuffisante `contains X` n’est détectée que **1/5**.

La frontière n’est donc plus un problème de fixture : c’est une vraie faiblesse de contrat / salience.

---

## 5. Nouveau principe : Source Licensing vs Evidentiary Sufficiency

On a formalisé la relation suivante.

Soit :

- `P` = proposition source/card que l’evidence doit substancier
- `E` = condition factuelle établie si l’evidence demandée réussit

Une `evidence_required` valide doit satisfaire deux axes :

### Source licensing

`E` ne doit pas inventer de fait absent de la source.

### Evidentiary sufficiency

Il faut également demander :

> **E peut-il être vrai alors que P est faux ?**

Si oui parce que `E` abandonne une contrainte définissant le claim — portée, modalité, identité, conjonction, exactitude, ordre, quantificateur, etc. — l’evidence est insuffisante.

Cette distinction est désormais considérée comme indépendante du simple contrôle “stronger than source”.

---

## 6. Patch du contrat evidence sufficiency

Commit :

```text
516b0497c7142bbaf779f07b02afa36ff4010db7
evidence-sufficiency contract patch
```

### Fichiers

- `forge.py`
- `tests/test_fidelity_gate.py`
- `tests/test_forge.py`

### Contrat partagé

`KNOWLEDGE_CARD_FIELD_SEMANTICS` distingue désormais explicitement :

```text
source licensing
vs
evidentiary sufficiency
```

Le contrat demande d’identifier `P` et `E`, puis de tester si `E` pourrait être vrai alors que `P` est faux.

### Generator

Le Generator ne doit plus émettre une `evidence_required` qui perd une contrainte nécessaire à l’établissement de `P`.

### Critic

Le Critic doit REVISE / REJECT lorsqu’une evidence source-licensed reste insuffisante.

### Source Fidelity Gate

Ajout conceptuel :

```text
CHECK 1 — OPERATIONAL DERIVATION
CHECK 2 — FACTUAL PAYLOAD AND MODALITY
CHECK 3 — EVIDENTIARY SUFFICIENCY
```

`CHECK 3` ne s’applique qu’à `evidence_required`.

### Classification

Pas de nouvel enum.

Une insuffisance seule utilise :

```text
unsupported
```

`stronger_than_source` reste réservé aux claims indépendamment plus forts que la source.

### Précaution méthodologique

Aucun prompt production ne contient :

- les IDs de fixtures
- `<b>Hello</b>`
- l’exemple exact equality vs containment
- les réponses de calibration

Donc le rat n’a pas reçu le corrigé de son examen.

### Validation

- **186 tests passed**
- compileall OK
- **50 fixtures**
- corpus inchangé
- pas de modification schema / persistence / admission architecture
- aucun appel OpenAI pendant le patch

---

## 7. Live calibration du nouveau CHECK 3

Commande :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-entailment-literal-response derived-entailment-literal-response-exact-equality --repeat 5
```

### Résultat

#### Weak evidence — `contains X`

```text
FAIL 3/5
PASS 2/5
```

Les trois FAIL utilisent désormais exactement le nouveau raisonnement :

- `contains` autorise du contenu supplémentaire
- `E` peut être vrai alors que `P` est faux
- classification : `unsupported`

#### Exact evidence — `is exactly X`

```text
PASS 5/5
```

### Interprétation

Avant le patch :

```text
weak evidence -> FAIL 1/5
```

Après le patch :

```text
weak evidence -> FAIL 3/5
```

Le contrôle positif reste :

```text
PASS 5/5
```

Le patch améliore donc réellement la frontière sans rendre le Gate simplement plus sévère.

Mais **3/5 reste insuffisant pour freezer la sous-frontière evidence sufficiency**.

---

## 8. Holdouts neufs d’evidentiary sufficiency

Pour vérifier la généralisation sans réutiliser `contains/exact`, six fixtures complètement nouvelles ont été préparées.

Commit :

```text
f381b40862b9a1db3d1573b6f4ba9e4bd94d1e25
fixture-only evidentiary-sufficiency holdouts
```

### Paires

#### Conjonction

```text
P = username AND account_identifier avant acceptation
E faible = username avant acceptation
```

#### Quantificateur

```text
P = all three requests rejected
E faible = at least one rejected
```

#### Ordre temporel

```text
P = authorization BEFORE state-changing action
E faible = authorization AND action
```

Dans les trois cas :

```text
P => E
```

Donc `E` est source-licensed.

Mais :

```text
E !=> P
```

Donc `E` est insuffisante.

### Inventaire après ajout

- **56 total / 54 measured**
- `SOURCE_FACTUAL`: 3 pass / 3 fail
- `DERIVED_OPERATIONAL`: 18 pass / 22 fail
- `SEMANTIC_LABEL`: 2 pass / 2 fail
- `ROUTING_METADATA`: 2 pass / 2 fail
- **187 tests passed**
- aucune modification de `forge.py`
- aucun changement de prompt/contrat/runtime

---

## 9. La ruche n’a plus de malepierre

Commande lancée :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-sufficiency-conjunction-complete derived-sufficiency-conjunction-partial derived-sufficiency-quantifier-complete derived-sufficiency-quantifier-partial derived-sufficiency-order-complete derived-sufficiency-order-dropped --repeat 5
```

Le batch s’est arrêté sur :

```text
Daily token budget would be exceeded (250644 > 250000)
```

### État au moment de l’arrêt

17 appels provider avaient terminé :

```text
conjunction-complete     5/5 appels
conjunction-partial      5/5
quantifier-complete      5/5
quantifier-partial       2/5
order-complete           0/5
order-dropped            0/5
```

Le batch a été interrompu **avant impression du JSON agrégé**.

Les 17 observations ne doivent donc pas être interprétées à partir des logs `output_chars` seuls.

### Suite prévue après reset budget

Relancer uniquement :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-sufficiency-quantifier-partial derived-sufficiency-order-complete derived-sufficiency-order-dropped --repeat 5
```

On préfère repartir sur 15 observations fraîches plutôt que concaténer manuellement deux runs partiels sans agrégat propre.

---

## 10. État conceptuel à la fin de la journée

### SOURCE_FACTUAL

Toujours considéré comme stabilisé sur les fixtures actuelles.

### SEMANTIC_LABEL

Toujours stabilisé.

### ROUTING_METADATA

Toujours stabilisé.

### DERIVED_OPERATIONAL — source licensing

Les derniers holdouts renforcent nettement l’idée que la frontière source-supported vs domain completion est solide atomiquement.

### DERIVED_OPERATIONAL — evidentiary sufficiency

Concept désormais explicite et aligné dans :

- contrat partagé
- Generator
- Critic
- Source Fidelity Gate

Mais la stabilité live reste à confirmer.

Statut :

```text
concept correct
implementation prompt-level improved
robustesse encore ouverte
```

Ne pas freezer cette sous-frontière pour l’instant.

### Full-card coverage

Toujours le grand chantier restant.

Les résultats accumulés continuent de suggérer qu’après stabilisation atomique, le problème principal sera probablement **salience / coverage sur carte complète**, ce qui pourra motiver la future V0.6.5.6.

V0.6.5.6 reste **non implémentée**.

---

## 11. Direction architecturale explorée aujourd’hui — probabilistic evidence

Une idée importante a également émergé pour la future évaluation d’hypothèses :

> **Les contraintes sont binaires ; les croyances sont probabilistes.**

Le Source Fidelity Gate resterait un mécanisme d’admission fail-closed :

```text
faithful / not faithful
```

En revanche, Queek / Ikit / Snikch / Horned Rat pourraient à terme utiliser un système probabiliste ou bayésien pour agréger les observations d’une hypothèse.

Conceptuellement :

```text
prior hypothesis belief
        ↓
evidence likelihoods / Bayes factors
        ↓
dependency-aware aggregation
        ↓
posterior belief
        ↓
deterministic EvidenceFact requirements
        ↓
SUPPORTED / DEMONSTRATED / CONFIRMED
```

Points importants identifiés :

- ne pas demander naïvement une probabilité absolue au LLM
- préférer éventuellement des catégories de force d’evidence mappées déterministiquement vers des likelihood ratios
- gérer les dépendances entre evidences pour ne pas compter plusieurs fois le même signal
- distinguer `belief` de `evidence quality`
- conserver les niveaux déterministes comme projection lisible, pas comme moteur de croyance

Aucun code n’a été modifié pour cette idée aujourd’hui.

---

## 12. Commits du jour

```text
86cef8bce8e609acc49cd1c03b0051aeab377160
atomic evaluator harness cleanup
```

```text
516b0497c7142bbaf779f07b02afa36ff4010db7
evidence-sufficiency contract patch
```

```text
f381b40862b9a1db3d1573b6f4ba9e4bd94d1e25
fixture-only evidentiary-sufficiency holdouts
```

Tous poussés sur `main`.

Dernier état Git confirmé après `f381b40` :

```text
Your branch is up to date with 'origin/main'.
nothing to commit, working tree clean
```

---

## 13. Checkpoint de fin de journée

```text
Source Fidelity Gate: OFF
V0.6.5.6: not implemented

Fixtures: 56 total / 54 measured
Deterministic tests: 187 passed at latest fixture-only checkpoint

SOURCE_FACTUAL: frozen on current calibration
SEMANTIC_LABEL: frozen
ROUTING_METADATA: frozen

DERIVED_OPERATIONAL:
- source licensing: strong
- evidentiary sufficiency: improved, not yet frozen
- full-card salience/coverage: still open
```

### Prochaine reprise

1. attendre le reset de malepierre ;
2. exécuter les 15 observations restantes sur quantifier/order holdouts ;
3. analyser la matrice par structure logique ;
4. décider si la règle evidence-sufficiency généralise suffisamment ;
5. seulement ensuite reprendre la question de la décomposition full-card / V0.6.5.6.

---

🐀 **Thanquol a appris aujourd’hui qu’une evidence peut être vraie, fidèle à la source… et quand même ne pas suffire à prouver ce qu’on voulait prouver.**

Et la ruche a consommé exactement assez de malepierre pour empêcher le dernier examen.
