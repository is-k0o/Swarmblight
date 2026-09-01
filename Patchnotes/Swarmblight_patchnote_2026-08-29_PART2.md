# Swarmblight — Patchnote 2026-08-29 · Part II
## Modality Preservation, Batch Regression & DERIVED_OPERATIONAL Freeze

> Deuxième partie de la journée : reprise de la calibration atomique, découverte d’un bug de modalité normative, correction V0.6.5.4, ajout d’un batch runner V0.6.5.5, puis régression complète sous le contrat courant.

---

## 1. SQLi atomic PASS fixture corrigée

La fixture positive SQLi initiale n’était pas parfaitement atomique.

Ancienne cible :

```text
Confirm that the observed behavior affects the application's database.
```

Source :

```text
SQL injection is a server-side vulnerability that targets the application's database.
```

Le test modifiait à la fois le wrapper et le prédicat :

```text
1. ajout de "Confirm..."
2. targets → affects
```

Correction :

```text
Confirm that SQL injection targets the application's database.
```

Le payload factuel reste désormais inchangé.

Validation déterministe :

```text
158 passed
```

---

## 2. SQLi faithful retest — PASS 5/5

Commande :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval derived-sqli-faithful --repeat 5
```

Résultat :

```text
PASS
PASS
PASS
PASS
PASS
```

Résumé :

```text
pass_count = 5
fail_count = 0
incomplete_count = 0
matches_expected = 5
```

La règle suivante tient donc sur ce cas atomique :

```text
source fact
→ operational confirmation wrapper
→ PASS
```

Le contrôle négatif SQLi déjà mesuré reste :

```text
Confirm crafted input alters SQL queries.
```

Résultat :

```text
FAIL 5/5
target_detected 5/5
```

La frontière SQLi devient :

```text
wrapper only              → PASS
new technical mechanism   → FAIL
```

---

## 3. Calibration CSRF

Fixtures :

```text
derived-csrf-faithful
derived-csrf-mechanism
```

### CSRF faithful

Source :

```text
CSRF involves inducing a victim user to perform actions they do not intend to do.
```

Cible :

```text
Determine whether the victim was induced to perform an unintended action.
```

Résultat :

```text
PASS 5/5
matches_expected = 5
incomplete = 0
```

Ce cas valide une paraphrase fidèle, pas seulement une reprise quasi littérale.

### CSRF mechanism

Cible :

```text
Confirm an authenticated victim action was caused by an induced request.
```

Ajouts attendus comme invalides :

```text
authenticated
induced request
stronger causality / proof requirement
```

Résultat :

```text
FAIL 5/5
target_detected 5/5
incomplete = 0
```

Les cinq runs accusent correctement `evidence_required`.

À ce stade :

```text
SQLi faithful       PASS 5/5
SQLi mechanism      FAIL 5/5 + target 5/5

CSRF faithful       PASS 5/5
CSRF mechanism      FAIL 5/5 + target 5/5

TOTAL               20/20
```

---

# 4. PHP faithful — échec révélateur

Fixture :

```text
SOURCE:
Escape your outputs with htmlentities and ENT_QUOTES for HTML contexts.

TARGET:
Confirm the relevant HTML output path uses htmlentities with ENT_QUOTES.

EXPECTED:
PASS
```

Résultat initial :

```text
FAIL 5/5
matches_expected = 0
```

Les cinq reasons convergent : la source **recommande** d’utiliser `htmlentities + ENT_QUOTES`, mais n’affirme pas qu’un output path les utilise déjà.

Le Gate appliquait trop mécaniquement :

```text
remove operational wrapper
→ judge remainder as SOURCE_FACTUAL
```

Cela provoquait un **modal collapse** :

```text
SHOULD / USE X
↓
X IS CURRENTLY IMPLEMENTED
```

La distinction était conceptuellement incorrecte.

---

# 5. V0.6.5.4 — Modality Preservation for DERIVED_OPERATIONAL

Le contrat partagé conserve désormais :

```text
semantic payload
+
source modality
```

Deux grandes modalités sont distinguées :

```text
DESCRIPTIVE / FACTUAL
NORMATIVE / PRESCRIPTIVE
```

### Source descriptive

Si la source supporte `P`, une dérivation valide peut demander :

```text
Check / determine / observe whether P.
```

sans ajouter de fait.

### Source normative

Si la source prescrit :

```text
Use X.
Do Y.
Avoid Z.
```

une dérivation valide peut demander :

```text
Check whether the implementation conforms to that prescription.
```

Cela **n’affirme pas** que la conformité existe déjà.

Exemple valide :

```text
SOURCE:
Use htmlentities with ENT_QUOTES for HTML contexts.

DERIVED:
Confirm the relevant HTML output path uses htmlentities with ENT_QUOTES.
```

Interprétation correcte :

```text
check whether implementation conforms
```

et non :

```text
source asserts implementation already conforms
```

---

## 6. Garde-fous conservés

La nouvelle permissivité modale ne donne pas un droit général d’inventer.

Toujours invalides :

```text
new mechanism
new implementation state
new qualifier
new actor property
new transport detail
new causal chain
new prerequisite
new impact
new guarantee
stronger proof requirement
```

Exemples :

```text
SOURCE:
Use htmlentities + ENT_QUOTES.

INVALID:
Confirm CSP blocks JavaScript execution.
```

```text
INVALID:
Confirm htmlentities is always available.
```

```text
INVALID:
Confirm every application output is already safely encoded.
```

---

## 7. Rôles mis à jour

### Generator

Peut transformer une prescription en contrôle de conformité, mais pas en assertion d’état actuel.

### Critic

Compare désormais :

```text
payload
+
modality
```

### SourceFidelityGate

Son deuxième contrôle devient conceptuellement :

```text
CHECK 2 — factual payload and modality
```

Il doit distinguer :

```text
"check whether P is followed"
```

de :

```text
"P is already true"
```

Validation V0.6.5.4 :

```text
160 passed
```

---

# 8. PHP faithful après V0.6.5.4 — PASS 5/5

La fixture n’a pas été affaiblie.

Même source, même cible.

Résultat :

```text
PASS 5/5
matches_expected = 5
incomplete = 0
```

Le bug de modalité est donc corrigé sur ce cas.

---

# 9. PHP CSP — contrôle négatif

Fixture :

```text
SOURCE:
Escape your outputs with htmlentities and ENT_QUOTES for HTML contexts.

TARGET:
Confirm CSP blocks JavaScript execution.

EXPECTED:
FAIL
```

Résultat :

```text
FAIL 5/5
matches_expected = 5
target_detected_count = 5
incomplete_count = 0
```

Les cinq runs identifient CSP comme une mitigation/mécanisme absent de la source.

La correction de modalité n’a donc pas créé une permissivité générale.

---

# 10. Besoin d’une régression complète sous V0.6.5.4

V0.6.5.4 modifie le contrat sémantique réellement injecté dans le Gate.

Les anciens résultats SQLi/CSRF obtenus sous des versions précédentes ne suffisent donc plus comme preuve live du comportement courant.

Les 10 runs PHP sont déjà validés sous V0.6.5.4.

Reste à rejouer :

```text
SQLi faithful       5 runs
SQLi mechanism      5 runs
CSRF faithful       5 runs
CSRF mechanism      5 runs

TOTAL               20 runs
```

---

# 11. V0.6.5.5 — Batch Atomic Fidelity Regression Runner

Ajout de :

```text
fidelity-eval-batch
```

Syntaxe :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch <case-id> [<case-id> ...] --repeat N
```

avec :

```text
1 <= N <= 5
```

Le batch réutilise directement :

```text
_run_atomic_fidelity_evaluation
```

Il ne duplique pas la construction synthétique, le scoring, la gestion des incomplets ou `target_detected`.

---

## 12. Préflight batch

Avant initialisation du client API :

```text
unknown case ID       → reject
duplicate case ID     → reject
non-constructible     → reject
```

Aucun token ne doit être consommé pour une erreur triviale de configuration.

---

## 13. Agrégation batch

Le batch expose notamment :

```text
repeat_per_case
case_count
total_attempts
expected_matches
expected_total
target_detected
target_expected_total
pass_expected_cases_clean
fail_expected_cases_clean
incomplete_count
stopped_cases
all_expected
```

Toujours aucun vote.

Chaque appel reste une observation indépendante.

Validation V0.6.5.5 :

```text
167 passed
```

---

# 14. Régression SQLi + CSRF sous le contrat courant

Commande :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-sqli-faithful derived-sqli-mechanism derived-csrf-faithful derived-csrf-mechanism --repeat 5
```

Résultats :

```text
derived-sqli-faithful
→ PASS 5/5

derived-sqli-mechanism
→ FAIL 5/5
→ target_detected 5/5

derived-csrf-faithful
→ PASS 5/5

derived-csrf-mechanism
→ FAIL 5/5
→ target_detected 5/5
```

Agrégat :

```text
expected_matches = 20
expected_total = 20

target_detected = 10
target_expected_total = 10

pass_expected_cases_clean = 2
fail_expected_cases_clean = 2

incomplete_count = 0
stopped_cases = []

all_expected = true
```

Un reason SQLi a produit l’artefact multilingue :

```text
application's数据库
```

Aucun impact sur le verdict, le champ ciblé ou le scoring.

---

# 15. Matrice finale DERIVED_OPERATIONAL sous V0.6.5.4

```text
SQLi
  faithful       PASS 5/5
  mechanism      FAIL 5/5 + target 5/5
                 ---------------------
                 10/10

CSRF
  faithful       PASS 5/5
  mechanism      FAIL 5/5 + target 5/5
                 ---------------------
                 10/10

PHP
  faithful       PASS 5/5
  CSP            FAIL 5/5 + target 5/5
                 ---------------------
                 10/10
```

Total :

```text
30 / 30 décisions conformes
0 incomplete
0 target miss
0 stopped case
```

---

# 16. Ce que cette calibration valide

Le Gate distingue désormais, sur cette première matrice :

```text
operational wrapper
≠
new factual payload
```

Il accepte :

```text
source fact
→ faithful question / confirmation
```

Il accepte :

```text
source prescription
→ compliance check
```

Il refuse :

```text
source fact
→ new technical mechanism
```

Il refuse :

```text
source description
→ new authentication state / request mechanism / stronger causality
```

Il refuse :

```text
source prescription
→ unrelated mitigation
```

---

# 17. Freeze recommandé : DERIVED_OPERATIONAL

État :

```text
DERIVED_OPERATIONAL = FROZEN FOR NOW
```

Pas de nouveau prompt tuning sans nouveau contre-exemple réel.

Raison :

```text
defined semantic rule
+ atomic fixtures
+ positive/negative controls
+ modality preservation
+ batch regression harness
+ 30/30 live observations under current contract
```

Continuer à retoucher le prompt sans nouvelle preuve risquerait davantage de casser une frontière stable que de l’améliorer.

---

# 18. Suite recommandée

Ordre proposé :

```text
1. SOURCE_FACTUAL
2. SEMANTIC_LABEL
3. ROUTING_METADATA
4. full-card regression
5. production gate activation decision
6. clean rebuild + human audit
```

### SOURCE_FACTUAL

Fixtures déjà présentes :

```text
source_factual_pass_php_encoder
source_factual_fail_encoder_availability
```

Objectif :

```text
faithful abstraction → PASS
new guarantee        → FAIL
```

Puis tester :

```text
new prerequisite
new implementation assumption
new causal claim
new impact
```

### SEMANTIC_LABEL

Fixtures déjà présentes :

```text
label_pass_taxonomy
label_pass_distinctions
label_fail_oauth
```

Objectif :

```text
semantic relevance
≠
literal source wording
```

### ROUTING_METADATA

Objectif :

```text
semantic adjacency
≠
current curriculum availability
```

Le Gate ne doit pas exiger qu’un topic cible possède déjà un curriculum approuvé pour reconnaître une relation sémantique valide.

---

# 19. Full-card regression

Après validation atomique des classes principales :

```text
retest known historical bad cards
```

Notamment :

```text
SQLi / CSRF / XSS comparison
Stored XSS
PoC XSS
PHP / Java prevention
```

Objectif : vérifier que la compétence atomique survit à des cartes réalistes multi-champs.

Un simple `FAIL` global ne devra toujours pas être interprété comme preuve que chaque violation spécifique a été détectée.

---

# 20. Activation production — pas encore

Le Gate reste :

```dotenv
SOURCE_FIDELITY_GATE_ENABLED=false
```

Séquence recommandée :

```text
remaining atomic semantic classes
→ realistic full-card regression
→ specificity + sensitivity confidence
→ enable gate
→ clean rebuild
→ human audit
```

---

# 21. État de fin de session

```text
V0.6.5.4 Modality Preservation       ✅
V0.6.5.5 Batch Regression Runner     ✅

DERIVED_OPERATIONAL
  SQLi                               10/10 ✅
  CSRF                               10/10 ✅
  PHP                                10/10 ✅
  TOTAL                              30/30 ✅

Incomplete                           0
Target miss                          0
Stopped case                         0

Production gate enabled              NON
Ikit complete                        NON
Swarmblight complete                 ABSOLUMENT PAS
```

---

# 22. Doctrine consolidée

```text
KNOWLEDGE != EVIDENCE
```

```text
CORRECT WEBSEC KNOWLEDGE
!=
SOURCE-SUPPORTED KNOWLEDGE
```

```text
THE WRAPPER MAY BE DERIVED.
THE FACT MAY NOT BE INVENTED.
```

```text
A PRESCRIPTION IS NOT AN OBSERVATION.
```

```text
"USE X"
DOES NOT MEAN
"X IS ALREADY USED."
```

Mais :

```text
"CHECK WHETHER X IS USED"
MAY FAITHFULLY TEST
"USE X."
```

Et enfin :

```text
MEASURE FIRST.
TUNE ONLY FROM COUNTEREXAMPLES.
```

---

## Rat summary

```text
Ikit:
BRRRRRRRRRRRRRRRRRRRRR

Thanquol:
"Payload?"

Ikit:
BRRRRRRRRRRRRRRRRRRRRR

Thanquol:
"Modality?"

Ikit:
...BRRRRRRRRRRRRRRRRRRRR

Thanquol:
"Approved."
```

État du jour :

```text
DERIVED_OPERATIONAL PRELIMINARY EXAM
30 / 30

YES-YES.
```

Pas la fin d’Ikit.
Pas la fin des deux autres agents.
Encore moins la fin de Swarmblight.

Mais une frontière sémantique du Forge est désormais :

```text
defined
measured
regression-tested
frozen
```

Bon endroit pour arrêter sur une victoire.
