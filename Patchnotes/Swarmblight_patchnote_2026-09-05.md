# Swarmblight — Patchnote du 5 septembre 2026

## Résumé

Reprise du chantier **Source Fidelity** après la journée bug bounty du 4 septembre.

La journée a eu deux objectifs :

1. terminer la calibration atomique de **`DERIVED_OPERATIONAL / evidence_required`** après l’arrêt précédent sur quota ;
2. implémenter **V0.6.5.6A**, un reviewer de fidélité **décomposé field/item + cross-field**, strictement diagnostic et non branché sur l’admission production.

Le résultat principal est que l’**evidentiary sufficiency atomique est désormais considérée suffisamment stabilisée** pour arrêter de tuner le prompt sur cette frontière et revenir au vrai problème restant : la **salience / coverage sur carte complète**.

V0.6.5.6A fournit maintenant l’outil expérimental pour tester directement ce problème.

Le Source Fidelity Gate production reste **OFF par défaut**.  
**V0.6.5.6B n’est pas implémentée.**

---

## 1. Reprise de l’examen d’evidentiary sufficiency

Le run du 3 septembre avait été interrompu par le budget journalier avant d’obtenir un agrégat complet.

Les cas restants ont donc été relancés proprement.

Commande :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-sufficiency-quantifier-partial derived-sufficiency-order-complete derived-sufficiency-order-dropped --repeat 5
```

### Résultats

#### Quantificateur — weakening

```text
P = all three requests were rejected
E = at least one request was rejected
```

Résultat :

```text
FAIL 5/5
target detected 5/5
```

Les cinq FAIL utilisent le bon raisonnement : `E` peut être vraie alors que `P` est fausse, donc l’evidence est insuffisante.

#### Ordre temporel — contrôle positif

```text
P = authorization check BEFORE state-changing action
E = authorization check BEFORE state-changing action
```

Résultat :

```text
PASS 5/5
```

#### Ordre temporel — weakening

```text
P = authorization BEFORE action
E = authorization AND action
```

Premier batch :

```text
FAIL 4/4 completed
1 incomplete
```

L’incomplete provenait de `max_output_tokens`, pas d’une mauvaise décision sémantique.

Retry :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval derived-sufficiency-order-dropped --repeat 1
```

Résultat :

```text
FAIL 1/1
target detected 1/1
```

---

## 2. Fermeture de la paire conjunction

Commande :

```powershell
.\.venv\Scripts\python.exe forge.py fidelity-eval-batch derived-sufficiency-conjunction-complete derived-sufficiency-conjunction-partial --repeat 5
```

### Contrôle positif

```text
P = validate username AND account identifier
E = validate username AND account identifier
```

Résultat :

```text
PASS 5/5
```

### Weak evidence

```text
P = validate username AND account identifier
E = validate username
```

Résultat :

```text
FAIL 4/5
PASS 1/5
target detected 4/5
```

Les quatre FAIL corrects identifient bien la perte du deuxième membre de la conjonction.

---

## 3. Bilan final de la calibration atomique

| Structure logique | Contrôle positif | Weak evidence |
|---|---:|---:|
| Conjonction | PASS 5/5 | FAIL 4/5 |
| Quantificateur | — | FAIL 5/5 |
| Ordre temporel | PASS 5/5 | FAIL 5/5 completed/retry |

Soit :

```text
positifs de contrôle : 10/10

négatifs neufs :
conjunction : 4/5
quantifier  : 5/5
ordering    : 5/5

total weakenings : 14/15
```

Conclusion :

```text
DERIVED_OPERATIONAL / evidentiary sufficiency atomique
= suffisamment stabilisée
```

Continuer à tuner le prompt sur cette frontière risquerait davantage de sur-calibrer le modèle que d’apporter un gain général.

---

## 4. Retour au vrai problème : full-card salience / coverage

Le problème historique restant n’est plus principalement :

> “Thanquol comprend-il la règle ?”

mais :

> “Thanquol applique-t-il la règle à chaque claim lorsqu’une carte entière contient de nombreux champs et items ?”

Même si le schema monolithique exige que les 12 champs soient marqués comme examinés, cela ne force pas un verdict explicite pour chaque item d’un champ liste.

Diagnostic actuel :

```text
atomic semantic competence
✅ suffisamment bonne

source licensing
✅ stabilisé

evidence sufficiency
✅ suffisamment stabilisé

full-card salience / item coverage
❌ encore ouverte
```

---

## 5. Design V0.6.5.6A

V0.6.5.6A est **diagnostic-only**.

Architecture :

```text
              FINAL CARD + EXACT CHUNK
                        │
          ┌─────────────┴─────────────┐
          │                           │
 FIELD / ITEM SOURCE REVIEW     CROSS-FIELD REVIEW
          │                           │
 verdict explicite pour         relations seulement :
 chaque item/index              contradictions,
                                joint strengthening,
                                scope/modality,
                                cross-field semantics
          └─────────────┬─────────────┘
                        │
             DETERMINISTIC AGGREGATOR
                        │
               PASS iff ALL PASS
```

La stratégie ne consiste plus à demander au modèle de “regarder mieux”, mais à forcer une structure de correction par champ et par index.

---

## 6. Implémentation V0.6.5.6A

Commit :

```text
890e22c7d398c07e19d0c1d8d7b9d28c6d2042c7
Implemented V0.6.5.6A
```

Fichiers modifiés :

- `forge.py`
- `schemas.py`
- `tests/test_decomposed_fidelity.py`
- `README.md`

Diff annoncé :

```text
+1053
-7
```

Ajout principal :

```text
DecomposedSourceFidelityGate
```

Le reviewer reste séparé de l’admission production.

---

## 7. Field / item review

Chaque champ gate-owned non vide produit **un appel LLM par champ**, avec un verdict indépendant pour chaque item/index.

Champs concernés :

```text
subtopic
title
tags
triggers
principle
questions_to_ask
false_positive_traps
evidence_required
escalation_topics
technique_assumptions
prerequisites
demonstrated_behavior
```

Exclus :

```text
speculative_extensions
confidence
provenance/application state
```

Décomposition :

```text
scalar non vide -> index 0
liste            -> un item par index exact
```

Aucune concaténation, aucune paraphrase, aucune mutation.

Les champs optionnels vides sont couverts déterministiquement sans appel provider.

---

## 8. Nouveau prompt field/item

Ajout :

```text
SOURCE_FIDELITY_FIELD_PROMPT
```

Le prompt réutilise directement :

```text
KNOWLEDGE_CARD_FIELD_SEMANTICS
```

et impose notamment :

```text
Judge ONLY the target field in this call.
Other card fields are contextual and are not being certified by this call.
```

Les règles existantes restent inchangées :

- source licensing ;
- modality preservation ;
- operational framing ;
- evidence sufficiency P/E ;
- semantic label relevance ;
- routing adjacency.

Aucun exemple historique de calibration n’a été injecté.

---

## 9. Coverage déterministe

Après chaque field review, le code vérifie :

- champ retourné = target field exact ;
- chaque index attendu apparaît exactement une fois ;
- aucun index attendu ne manque ;
- aucun index supplémentaire ;
- aucun doublon ;
- bon nombre d’item reviews ;
- chaque issue appartient au bon field/item ;
- PASS => zéro issue ;
- FAIL => au moins une issue.

Toute anomalie donne :

```text
incomplete/error
```

et ne peut jamais devenir PASS.

La couverture n’est donc plus basée sur une simple déclaration du modèle.

---

## 10. Cross-field relationship review

Une deuxième passe conserve la vision globale afin d’éviter l’effet inverse d’une atomisation trop forte.

Ajout :

```text
SOURCE_FIDELITY_CROSS_FIELD_PROMPT
```

Cette passe ne rejuge pas les items individuellement.

Elle cherche uniquement des défauts relationnels :

- contradictions ;
- joint strengthening ;
- scope mismatch ;
- modality mismatch ;
- assumptions/prerequisites vs demonstrated behavior ;
- evidence_required visant une proposition différente ;
- combinaisons trigger/question/evidence impliquant un mécanisme non supporté ;
- combinaisons title/subtopic/routing déformant la source.

Si un item a déjà FAIL, la passe cross-field peut être court-circuitée.

---

## 11. Schémas stricts ajoutés

Ajout de schémas provider compatibles pour :

- issues itemisées avec `index` explicite ;
- verdicts item PASS / FAIL ;
- field review ;
- cross-field issue ;
- cross-field PASS / FAIL review.

Les provider schemas ne contiennent aucun champ de rewrite.

Les classifications restent :

```text
stronger_than_source
unsupported
```

Aucun nouvel enum sémantique n’a été nécessaire.

---

## 12. Agrégation fail-closed

Résultat application-owned :

```text
DecomposedSourceFidelityResult
```

Règles :

```text
provider/coverage error
→ incomplete/error
→ jamais PASS

un item FAIL
→ aggregate FAIL

tous les items PASS
→ cross-field review

cross-field FAIL
→ aggregate FAIL

all item PASS + cross-field PASS
→ aggregate PASS
```

Aucun vote, aucune majorité, aucun seuil de confiance, aucun rewrite automatique.

---

## 13. Nouveau CLI diagnostic

Commande :

```powershell
python forge.py fidelity-check-decomposed <card-id> --repeat N
```

avec :

```text
N = 1..5
```

Chaque répétition est indépendante.

Le JSON expose notamment :

- field/item reviews ;
- indices ;
- issues ;
- champs vides skippés ;
- cross-field result ;
- aggregate status/verdict ;
- provider response IDs ;
- per-call usage ;
- usage total ;
- incomplete/error details ;
- flags de mutation/persistence.

Sémantique :

```text
aggregation = independent observations; no automatic vote
```

---

## 14. Persistence / resumability

V0.6.5.6A n’ajoute volontairement aucune persistence production.

Pas de :

- migration DB ;
- nouvelle table de reviews décomposées ;
- modification de `knowledge_fidelity_reviews` ;
- changement de `fidelity_pending` ;
- resumability par field/item ;
- admission wiring.

Un run diagnostic interrompu peut repartir depuis le début.

---

## 15. Validation

Résultat final :

```text
239 tests passed
```

dont :

```text
52 nouveaux tests diagnostic
```

Validation complémentaire :

```text
compileall passed
import smoke passed
CLI parse repeat=1 passed
CLI parse repeat=5 passed
```

Corpus inchangé :

```text
56 total
54 measured
```

SHA-256 fixture :

```text
FEB295F88E5816C701094B7B23DAED2F8392A3990461317014324552A3ECB55E
```

Les comptes sémantiques restent inchangés.

---

## 16. Invariants confirmés

```text
KNOWLEDGE_CARD_FIELD_SEMANTICS
= unchanged

GENERATOR_PROMPT
= unchanged

CRITIC_PROMPT
= unchanged

SOURCE_FIDELITY_PROMPT
= unchanged byte-for-byte

existing SourceFidelityGate behavior
= unchanged

production admission flow
= unchanged

DB schema / migrations
= unchanged

existing fidelity persistence
= unchanged
```

Aucun appel OpenAI n’a été effectué pendant l’implémentation ou les tests.

`.env` et `data/warpstone.db` ont conservé leurs hashes de départ.

Aucun état production persistant n’a été muté.

---

## 17. GitHub checkpoint

Le commit V0.6.5.6A a été poussé sur `main` :

```text
890e22c7d398c07e19d0c1d8d7b9d28c6d2042c7
Implemented V0.6.5.6A
```

Le commit contient bien les changements attendus dans :

```text
README.md
forge.py
schemas.py
tests/test_decomposed_fidelity.py
```

Le README n’a reçu aujourd’hui qu’une petite mise à jour liée à la nouvelle commande diagnostique.

La **grosse passe README** reste volontairement à faire plus tard :

```text
README = état courant du repo
PATCHNOTES = historique de développement
```

---

## 18. État du projet à la fin de la journée

```text
Source Fidelity Gate production:
OFF

V0.6.5.6A:
IMPLEMENTED
DIAGNOSTIC ONLY
PUSHED

V0.6.5.6B:
NOT IMPLEMENTED

Fixtures:
56 total / 54 measured

Tests:
239 passed

SOURCE_FACTUAL:
stabilized on current calibration

SEMANTIC_LABEL:
stabilized

ROUTING_METADATA:
stabilized

DERIVED_OPERATIONAL / source licensing:
stabilized

DERIVED_OPERATIONAL / evidentiary sufficiency:
sufficiently stabilized atomically

Full-card salience / coverage:
OPEN
now directly testable with decomposed reviewer
```

---

## 19. Prochaine reprise

Le prochain test utile sera d’utiliser le nouveau CLI sur les **vraies cartes historiquement mal admises** et de comparer :

```text
monolithic SourceFidelityGate
vs
decomposed field/item + cross-field reviewer
```

Cibles prioritaires :

```text
SQLi / CSRF / XSS false approval
Stored XSS false approval
XSS PoC false approval
```

Si la décomposition améliore réellement la couverture sans générer trop de faux FAIL :

```text
→ V0.6.5.6B
→ production admission wiring
→ persistence
→ resumability
```

Sinon :

```text
→ corriger l’architecture diagnostique avant tout branchement production
```

---

## 20. Note de fin

La journée a fermé une question et construit l’outil pour la suivante :

```text
“Le rat comprend-il la logique ?”
→ suffisamment oui.

“Le rat voit-il chaque crotte dans une grosse copie ?”
→ maintenant on a enfin l’examen pour le mesurer.
```

🐀 **Thanquol n’est pas encore branché à la porte du terrier. Pour l’instant, on lui a juste donné une grille de correction où chaque ligne doit recevoir sa signature.**
