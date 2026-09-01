from pathlib import Path
import sqlite3

from memory import SQLiteMemoryStore
from schemas import (
    AgentName,
    EvidenceFact,
    EvidenceItem,
    EvidenceLevel,
    EvidenceType,
    Hypothesis,
    HypothesisStatus,
    Lesson,
    Priority,
)


def test_memory_creates_session_and_updates_hypothesis(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "warpstone.db")
    session_id = store.create_session()
    hypothesis = Hypothesis(
        title="Client controls price",
        description="The submitted price may be trusted server-side.",
        author_agent=AgentName.QUEEK,
        priority=Priority.HIGH,
        confidence=0.4,
    )

    store.save_hypothesis(session_id, hypothesis)
    saved = store.get_hypothesis(hypothesis.id)

    assert saved is not None
    assert saved.title == hypothesis.title
    assert store.list_open_hypotheses(session_id)[0].id == hypothesis.id

    updated = store.update_hypothesis(
        hypothesis.id,
        HypothesisStatus.REFUTED,
        evidence_against=["Server recalculates price from product ID."],
    )

    assert updated.status == HypothesisStatus.REFUTED
    assert store.list_open_hypotheses(session_id) == []
    summary = store.get_session_summary(session_id)
    assert summary.closed_hypotheses == 1
    assert (tmp_path / "warpstone.db").exists()


def test_lessons_and_evidence_are_persisted(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "warpstone.db")
    session_id = store.create_session()
    hypothesis = Hypothesis(
        title="Ownership check candidate",
        description="The object may not be bound to the active identity.",
        author_agent=AgentName.SNIKCH,
    )
    store.save_hypothesis(session_id, hypothesis)
    evidence = EvidenceItem(
        hypothesis_id=hypothesis.id,
        source="manual account comparison",
        description="Account B was denied access to account A's object.",
        evidence_type=EvidenceType.MANUAL_TEST_RESULT,
        supports=False,
        facts=[EvidenceFact.HYPOTHESIS_CONTRADICTED],
        satisfies_required_evidence=["Account A/B authorization comparison"],
        confidence=0.9,
        proposed_level=EvidenceLevel.DEMONSTRATED,
    )
    store.save_evidence(session_id, evidence)
    lesson = Lesson(
        agent=AgentName.SNIKCH,
        title="Ownership denials are useful controls",
        content="Keep the denial response as evidence against authorization bypass.",
        source_hypothesis_id=hypothesis.id,
        tags=["ownership", "authorization"],
        confidence=0.8,
    )
    store.save_lesson(lesson)

    saved_evidence = store.list_evidence(hypothesis.id)[0]
    assert saved_evidence.id == evidence.id
    assert saved_evidence.facts == [EvidenceFact.HYPOTHESIS_CONTRADICTED]
    assert saved_evidence.satisfies_required_evidence == [
        "Account A/B authorization comparison"
    ]
    assert store.list_lessons(AgentName.SNIKCH)[0].id == lesson.id
    assert store.search_lessons("ownership", AgentName.SNIKCH)[0].id == lesson.id


def test_v0_database_is_migrated_in_place(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE hypotheses (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, title TEXT NOT NULL,
                description TEXT NOT NULL, author_agent TEXT NOT NULL, status TEXT NOT NULL,
                priority TEXT NOT NULL, confidence REAL NOT NULL, evidence_for TEXT NOT NULL,
                evidence_against TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                agent TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0, total_tokens INTEGER NOT NULL DEFAULT 0,
                estimated_cost REAL, created_at TEXT NOT NULL
            );
            """
        )

    SQLiteMemoryStore(path)

    with sqlite3.connect(path) as connection:
        hypothesis_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(hypotheses)")
        }
        usage_columns = {row[1] for row in connection.execute("PRAGMA table_info(usage)")}
        evidence_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(evidence)")
        }
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "required_evidence",
        "required_facts",
        "current_evidence_level",
        "validation_notes",
    } <= hypothesis_columns
    assert {"run_id", "model", "actual_cost_usd"} <= usage_columns
    assert {"facts", "satisfies_required_evidence"} <= evidence_columns
    assert "budget_uncertain_usage" in tables
