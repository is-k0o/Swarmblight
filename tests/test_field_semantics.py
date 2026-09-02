from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from forge import KNOWLEDGE_CARD_FIELD_SEMANTIC_CLASSES
from schemas import KnowledgeCardDraft


FIXTURE_PATH = Path(__file__).parent / "corpus" / "knowledge_card_field_semantics_cases.json"


def load_cases() -> list[dict[str, object]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_manual_semantics_matrix_has_required_class_balance() -> None:
    cases = load_cases()
    measured = [case for case in cases if case["expected"] in {"pass", "fail"}]
    counts = Counter(
        (str(case["semantic_class"]), str(case["expected"])) for case in measured
    )

    assert len(measured) == 47
    assert counts == {
        ("SOURCE_FACTUAL", "pass"): 3,
        ("SOURCE_FACTUAL", "fail"): 3,
        ("DERIVED_OPERATIONAL", "pass"): 15,
        ("DERIVED_OPERATIONAL", "fail"): 18,
        ("SEMANTIC_LABEL", "pass"): 2,
        ("SEMANTIC_LABEL", "fail"): 2,
        ("ROUTING_METADATA", "pass"): 2,
        ("ROUTING_METADATA", "fail"): 2,
    }


def test_semantics_fixture_covers_requested_boundary_examples() -> None:
    cases = {str(case["id"]): case for case in load_cases()}
    expected = {
        "source_factual_fail_sqli_queries": "fail",
        "derived-php-faithful": "pass",
        "derived-sqli-faithful": "pass",
        "derived-sqli-mechanism": "fail",
        "derived-csrf-faithful": "pass",
        "derived-csrf-mechanism": "fail",
        "derived-php-csp": "fail",
        "derived-php-availability-guarantee": "fail",
        "derived-php-safety-guarantee": "fail",
        "derived-prohibition-compliance": "pass",
        "derived-stored-xss-later-response-faithful": "pass",
        "derived-stored-xss-verbatim": "fail",
        "derived-stored-xss-unsafe-inclusion-faithful": "pass",
        "derived-stored-xss-same-payload": "fail",
        "derived-stored-xss-workflow-faithful": "pass",
        "derived-stored-xss-exact-bytes": "fail",
        "derived-stored-xss-browser-html-context": "fail",
        "derived-stored-xss-example-no-processing-scoped": "pass",
        "derived-stored-xss-no-processing-generalized": "fail",
        "derived-stored-xss-html-example-scoped": "pass",
        "derived-stored-xss-browser-inference-example-scoped": "fail",
        "derived-stored-xss-html-generalized": "fail",
        "derived-entailment-q-coreference": "pass",
        "derived-completion-q-html-context": "fail",
        "derived-entailment-comment-visible": "pass",
        "derived-completion-comment-browser-html": "fail",
        "derived-entailment-stored-nickname": "pass",
        "derived-completion-nickname-sql-storage": "fail",
        "derived-entailment-literal-response": "pass",
        "derived-completion-literal-response-browser": "fail",
        "derived_pass_persistence_question": "pass",
        "derived_fail_httponly_question": "fail",
        "label_pass_taxonomy": "pass",
        "label_fail_oauth": "fail",
        "routing_pass_sqli": "pass",
        "routing_fail_kerberos": "fail",
        "source_factual_fail_encoder_availability": "fail",
        "metadata_confidence_excluded": "excluded",
        "speculation_isolated_excluded": "excluded",
    }

    assert {case_id: cases[case_id]["expected"] for case_id in expected} == expected


def test_derived_fixture_covers_descriptive_and_normative_modality_matrix() -> None:
    cases = {str(case["id"]): case for case in load_cases()}
    matrix = {
        "derived-sqli-faithful": (
            "descriptive",
            "pass",
            "operational_wrapper",
        ),
        "derived-sqli-mechanism": (
            "descriptive",
            "fail",
            "factual_payload",
        ),
        "derived-php-faithful": (
            "normative",
            "pass",
            "operational_wrapper",
        ),
        "derived-php-csp": ("normative", "fail", "factual_payload"),
        "derived-php-availability-guarantee": (
            "normative",
            "fail",
            "factual_payload",
        ),
        "derived-php-safety-guarantee": (
            "normative",
            "fail",
            "factual_payload",
        ),
        "derived-prohibition-compliance": (
            "normative",
            "pass",
            "operational_wrapper",
        ),
    }

    assert {
        case_id: (
            cases[case_id]["source_modality"],
            cases[case_id]["expected"],
            cases[case_id]["derived_boundary"],
        )
        for case_id in matrix
    } == matrix
    assert cases["derived-php-faithful"]["value"] == (
        "Confirm the relevant HTML output path uses htmlentities with ENT_QUOTES."
    )
    assert cases["derived-php-csp"]["value"] == (
        "Confirm CSP blocks JavaScript execution."
    )
    assert cases["derived-prohibition-compliance"]["source"] == (
        "Do not insert untrusted data into executable JavaScript contexts."
    )
    assert cases["derived-prohibition-compliance"]["value"] == (
        "Check whether untrusted data is inserted into executable JavaScript contexts."
    )


def test_stored_xss_counterexamples_share_one_exact_source_and_atomic_boundaries() -> None:
    cases = {str(case["id"]): case for case in load_cases()}
    case_ids = (
        "derived-stored-xss-later-response-faithful",
        "derived-stored-xss-verbatim",
        "derived-stored-xss-unsafe-inclusion-faithful",
        "derived-stored-xss-same-payload",
        "derived-stored-xss-workflow-faithful",
        "derived-stored-xss-exact-bytes",
        "derived-stored-xss-browser-html-context",
        "derived-stored-xss-example-no-processing-scoped",
        "derived-stored-xss-no-processing-generalized",
        "derived-stored-xss-html-example-scoped",
        "derived-stored-xss-browser-inference-example-scoped",
        "derived-stored-xss-html-generalized",
    )
    source = str(cases[case_ids[0]]["source"])

    assert len({cases[case_id]["source"] for case_id in case_ids}) == 1
    assert "within its later HTTP responses in an unsafe way" in source
    assert "The application doesn't perform any other processing of the data" in source
    assert {
        case_id: (
            cases[case_id]["field"],
            cases[case_id]["value"],
            cases[case_id]["expected"],
            cases[case_id]["derived_boundary"],
        )
        for case_id in case_ids
    } == {
        "derived-stored-xss-later-response-faithful": (
            "questions_to_ask",
            "Which later HTTP responses include the persisted data?",
            "pass",
            "operational_wrapper",
        ),
        "derived-stored-xss-verbatim": (
            "questions_to_ask",
            "Is the persisted data included verbatim in later HTTP responses?",
            "fail",
            "factual_payload",
        ),
        "derived-stored-xss-unsafe-inclusion-faithful": (
            "evidence_required",
            "Confirm that data received from an untrusted source is later included in an HTTP response in an unsafe way.",
            "pass",
            "operational_wrapper",
        ),
        "derived-stored-xss-same-payload": (
            "evidence_required",
            "Submit a payload via an input path that the application persists, and show the same payload is later present in an HTTP response where a browser would parse it.",
            "fail",
            "factual_payload",
        ),
        "derived-stored-xss-workflow-faithful": (
            "evidence_required",
            "First identify data received from an untrusted source, then inspect a later HTTP response to determine whether that data is included in an unsafe way.",
            "pass",
            "operational_wrapper",
        ),
        "derived-stored-xss-exact-bytes": (
            "evidence_required",
            "Confirm that the exact byte-for-byte value received from the untrusted source is reproduced unchanged in a later HTTP response.",
            "fail",
            "factual_payload",
        ),
        "derived-stored-xss-browser-html-context": (
            "evidence_required",
            "Confirm that the browser parses the persisted data as HTML in the later response.",
            "fail",
            "factual_payload",
        ),
        "derived-stored-xss-example-no-processing-scoped": (
            "questions_to_ask",
            "In the simple message-board example, are submitted messages displayed without any other processing?",
            "pass",
            "operational_wrapper",
        ),
        "derived-stored-xss-no-processing-generalized": (
            "evidence_required",
            "Confirm that Stored XSS data is always included in later HTTP responses without any other processing.",
            "fail",
            "factual_payload",
        ),
        "derived-stored-xss-html-example-scoped": (
            "questions_to_ask",
            "In the simple message-board example, is the submitted message included in the HTML displayed to other users?",
            "pass",
            "operational_wrapper",
        ),
        "derived-stored-xss-browser-inference-example-scoped": (
            "evidence_required",
            "In the simple message-board example, confirm that a browser parses the submitted message as HTML.",
            "fail",
            "factual_payload",
        ),
        "derived-stored-xss-html-generalized": (
            "evidence_required",
            "Confirm that every Stored XSS vulnerability requires persisted data to be included in an HTML context in a later HTTP response.",
            "fail",
            "factual_payload",
        ),
    }


def test_entailment_holdout_pairs_share_sources_and_exact_atomic_boundaries() -> None:
    cases = {str(case["id"]): case for case in load_cases()}
    pairs = (
        (
            "derived-entailment-q-coreference",
            "derived-completion-q-html-context",
        ),
        (
            "derived-entailment-comment-visible",
            "derived-completion-comment-browser-html",
        ),
        (
            "derived-entailment-stored-nickname",
            "derived-completion-nickname-sql-storage",
        ),
        (
            "derived-entailment-literal-response",
            "derived-completion-literal-response-browser",
        ),
    )

    assert all(cases[left]["source"] == cases[right]["source"] for left, right in pairs)
    assert {
        case_id: (
            cases[case_id]["source_modality"],
            cases[case_id]["field"],
            cases[case_id]["value"],
            cases[case_id]["expected"],
            cases[case_id]["derived_boundary"],
        )
        for pair in pairs
        for case_id in pair
    } == {
        "derived-entailment-q-coreference": (
            "descriptive",
            "evidence_required",
            "Confirm that the later HTTP response includes the value previously received in the q parameter.",
            "pass",
            "operational_wrapper",
        ),
        "derived-completion-q-html-context": (
            "descriptive",
            "evidence_required",
            "Confirm that the later HTTP response places the q value in an HTML context.",
            "fail",
            "factual_payload",
        ),
        "derived-entailment-comment-visible": (
            "descriptive",
            "questions_to_ask",
            "Determine whether another user is shown the comment that was submitted.",
            "pass",
            "operational_wrapper",
        ),
        "derived-completion-comment-browser-html": (
            "descriptive",
            "evidence_required",
            "Confirm that another user's browser renders the submitted comment as HTML.",
            "fail",
            "factual_payload",
        ),
        "derived-entailment-stored-nickname": (
            "descriptive",
            "evidence_required",
            "Confirm that the nickname displayed on the profile page is the nickname the application previously stored.",
            "pass",
            "operational_wrapper",
        ),
        "derived-completion-nickname-sql-storage": (
            "descriptive",
            "evidence_required",
            "Confirm that the nickname is stored in a SQL database before it is displayed on the profile page.",
            "fail",
            "factual_payload",
        ),
        "derived-entailment-literal-response": (
            "descriptive",
            "evidence_required",
            "Confirm that the HTTP response body contains the exact string '<b>Hello</b>'.",
            "pass",
            "operational_wrapper",
        ),
        "derived-completion-literal-response-browser": (
            "descriptive",
            "evidence_required",
            "Confirm that a browser interprets the response body as HTML.",
            "fail",
            "factual_payload",
        ),
    }


def test_fixture_fields_follow_the_authoritative_semantic_classes() -> None:
    for case in load_cases():
        field = str(case["field"])
        assert KNOWLEDGE_CARD_FIELD_SEMANTIC_CLASSES[field] == case["semantic_class"]


def test_derived_fixture_distinguishes_wrapper_from_factual_payload() -> None:
    derived = [
        case
        for case in load_cases()
        if case["semantic_class"] == "DERIVED_OPERATIONAL"
    ]

    assert all(
        case["derived_boundary"] == "operational_wrapper"
        for case in derived
        if case["expected"] == "pass"
    )
    assert all(
        case["derived_boundary"] == "factual_payload"
        for case in derived
        if case["expected"] == "fail"
    )


def test_out_of_ontology_routing_topic_is_rejected_before_fidelity_review() -> None:
    with pytest.raises(ValidationError):
        KnowledgeCardDraft(
            title="Comparison",
            principle="The source compares XSS with SQL injection.",
            escalation_topics=["kerberos"],
        )
