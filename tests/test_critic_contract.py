from __future__ import annotations

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from schemas import (
    CriticDecision,
    GeneratedKnowledgeCards,
    KnowledgeCardCritique,
    KnowledgeCardDraft,
)


def revised_draft() -> KnowledgeCardDraft:
    return KnowledgeCardDraft(
        title="Source-bounded revision",
        principle="Retain only the mechanism supported by the current chunk.",
    )


@pytest.mark.parametrize("decision", [CriticDecision.APPROVE, CriticDecision.REJECT])
def test_non_revision_critique_variants_are_valid(decision: CriticDecision) -> None:
    critique = KnowledgeCardCritique.model_validate(
        {
            "critique": {
                "decision": decision.value,
                "reasons": ["The candidate is source-bounded."],
            }
        }
    )

    assert critique.decision == decision
    assert critique.reasons == ["The candidate is source-bounded."]
    assert critique.revised_card is None


def test_revision_critique_requires_and_exposes_revised_card() -> None:
    draft = revised_draft()
    critique = KnowledgeCardCritique.model_validate(
        {
            "critique": {
                "decision": "revise",
                "reasons": ["Remove unsupported detail."],
                "revised_card": draft.model_dump(mode="json"),
            }
        }
    )

    assert critique.decision == CriticDecision.REVISE
    assert critique.revised_card == draft


@pytest.mark.parametrize(
    "variant",
    [
        {
            "decision": "revise",
            "reasons": ["A card is required."],
        },
        {
            "decision": "approve",
            "reasons": ["Approval cannot revise."],
            "revised_card": revised_draft().model_dump(mode="json"),
        },
        {
            "decision": "reject",
            "reasons": ["Rejection cannot revise."],
            "revised_card": revised_draft().model_dump(mode="json"),
        },
    ],
)
def test_invalid_decision_revision_combinations_are_rejected_locally(
    variant: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        KnowledgeCardCritique.model_validate({"critique": variant})


@pytest.mark.parametrize(
    ("payload", "model"),
    [
        (
            {
                "critique": {
                    "decision": "approve",
                    "reasons": ["x" * 401],
                }
            },
            KnowledgeCardCritique,
        ),
        (
            {"title": "Bounded", "principle": "x" * 801},
            KnowledgeCardDraft,
        ),
        (
            {
                "title": "Bounded",
                "principle": "Supported.",
                "triggers": ["x" * 401],
            },
            KnowledgeCardDraft,
        ),
        (
            {
                "title": "Bounded",
                "principle": "Supported.",
                "demonstrated_behavior": "x" * 801,
            },
            KnowledgeCardDraft,
        ),
    ],
)
def test_critic_and_revised_card_text_bounds_are_enforced_locally(
    payload: dict[str, object],
    model: type[KnowledgeCardCritique] | type[KnowledgeCardDraft],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_knowledge_card_confidence_range_remains_enforced(confidence: float) -> None:
    with pytest.raises(ValidationError):
        KnowledgeCardDraft(
            title="Source-bounded card",
            principle="Retain only the source-supported mechanism.",
            confidence=confidence,
        )


def test_sdk_provider_schema_encodes_the_same_critique_variants() -> None:
    # This is the strict schema transformation used by the installed OpenAI SDK.
    schema = to_strict_json_schema(KnowledgeCardCritique)

    assert schema["type"] == "object"
    assert "anyOf" not in schema
    assert schema["required"] == ["critique"]
    assert schema["additionalProperties"] is False
    variants = schema["properties"]["critique"]["anyOf"]
    assert len(variants) == 3

    by_decision: dict[str, dict[str, object]] = {}
    for variant in variants:
        reference = variant["$ref"]
        branch = schema["$defs"][reference.rsplit("/", 1)[-1]]
        decision = branch["properties"]["decision"]["const"]
        by_decision[decision] = branch

    assert set(by_decision) == {"approve", "reject", "revise"}
    for decision in ("approve", "reject"):
        branch = by_decision[decision]
        assert set(branch["properties"]) == {"decision", "reasons"}
        assert set(branch["required"]) == {"decision", "reasons"}
        assert branch["additionalProperties"] is False
        assert branch["properties"]["reasons"]["maxItems"] == 4
        assert branch["properties"]["reasons"]["items"]["maxLength"] == 400

    revise = by_decision["revise"]
    assert set(revise["properties"]) == {"decision", "reasons", "revised_card"}
    assert set(revise["required"]) == {"decision", "reasons", "revised_card"}
    assert revise["additionalProperties"] is False
    assert revise["properties"]["reasons"]["maxItems"] == 4
    assert revise["properties"]["reasons"]["items"]["maxLength"] == 400

    draft = schema["$defs"]["KnowledgeCardDraft"]["properties"]
    assert draft["tags"]["items"]["maxLength"] == 40
    for field in (
        "triggers",
        "questions_to_ask",
        "false_positive_traps",
        "evidence_required",
        "technique_assumptions",
        "prerequisites",
        "speculative_extensions",
    ):
        assert draft[field]["items"]["maxLength"] == 400
    assert draft["principle"]["maxLength"] == 800
    assert draft["demonstrated_behavior"]["maxLength"] == 800
    assert draft["confidence"]["minimum"] == 0.0
    assert draft["confidence"]["maximum"] == 1.0
    assert "not a source-derived claim" in draft["confidence"]["description"]


def test_generator_and_critic_provider_schemas_share_the_draft_contract() -> None:
    generator = to_strict_json_schema(GeneratedKnowledgeCards)
    critic = to_strict_json_schema(KnowledgeCardCritique)

    assert generator["$defs"]["KnowledgeCardDraft"] == critic["$defs"][
        "KnowledgeCardDraft"
    ]
    assert "anyOf" not in generator
    assert "anyOf" not in critic
    variants = critic["properties"]["critique"]["anyOf"]
    assert len(variants) == 3
    assert all(set(variant) == {"$ref"} for variant in variants)
