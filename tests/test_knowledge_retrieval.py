import json
from pathlib import Path
import sqlite3

from knowledge_store import SQLiteKnowledgeStore
from memory import SQLiteMemoryStore
from schemas import (
    AgentName,
    KnowledgeCard,
    KnowledgeCardStatus,
    KnowledgeSourceType,
    KnowledgeTopic,
)
from source_ingestion import SourceIngestor


def make_store(tmp_path: Path) -> tuple[SQLiteKnowledgeStore, object]:
    database_path = tmp_path / "knowledge.db"
    SQLiteMemoryStore(database_path)
    store = SQLiteKnowledgeStore(database_path, max_fragments=5)
    source_path = tmp_path / "source.md"
    source_path.write_text("# Context\n\nSynthetic reusable methodology.", encoding="utf-8")
    document, chunks = SourceIngestor(500).ingest_file(
        source_path,
        agent=AgentName.IKIT,
        source_type=KnowledgeSourceType.ACADEMY,
        topic=KnowledgeTopic.DOM,
    )
    store.save_document(document, chunks)
    return store, chunks[0]


def card(
    chunk,
    *,
    title: str,
    agent: AgentName = AgentName.IKIT,
    topic: KnowledgeTopic = KnowledgeTopic.DOM,
    status: KnowledgeCardStatus = KnowledgeCardStatus.APPROVED,
    source_type: KnowledgeSourceType = KnowledgeSourceType.ACADEMY,
    tags: list[str] | None = None,
    triggers: list[str] | None = None,
    principle: str = "Separate controllability from demonstrated execution.",
) -> KnowledgeCard:
    return KnowledgeCard(
        agent=agent,
        topic=topic,
        subtopic="context",
        title=title,
        source_type=source_type,
        source_title="Synthetic source",
        source_reference=chunk.source_reference,
        source_chunk_id=chunk.id,
        tags=tags or [topic.value],
        triggers=triggers or [topic.value],
        principle=principle,
        questions_to_ask=["What behavior is demonstrated?"],
        evidence_required=["A discriminating supplied result."],
        technique_assumptions=(
            ["The described parser is reachable."]
            if source_type == KnowledgeSourceType.RESEARCH
            else []
        ),
        prerequisites=(
            ["The input reaches the described transformation."]
            if source_type == KnowledgeSourceType.RESEARCH
            else []
        ),
        status=status,
    )


def test_only_ikit_cards_are_returned_for_ikit(tmp_path: Path) -> None:
    store, chunk = make_store(tmp_path)
    ikit = card(chunk, title="Ikit DOM context")
    queek = card(chunk, title="Queek DOM context", agent=AgentName.QUEEK)
    store.save_card(ikit)
    store.save_card(queek)

    results = store.get_relevant_knowledge(AgentName.IKIT, "dom context", limit=5)

    assert [item.id for item in results] == [ikit.id]


def test_rejected_cards_are_never_retrieved(tmp_path: Path) -> None:
    store, chunk = make_store(tmp_path)
    rejected = card(
        chunk,
        title="Rejected DOM idea",
        status=KnowledgeCardStatus.REJECTED,
    )
    store.save_card(rejected)

    assert store.get_relevant_knowledge(AgentName.IKIT, "dom", limit=5) == []


def test_max_knowledge_fragments_is_respected(tmp_path: Path) -> None:
    store, chunk = make_store(tmp_path)
    for index in range(8):
        store.save_card(card(chunk, title=f"DOM context {index}"))

    results = store.get_relevant_knowledge(AgentName.IKIT, "dom context", limit=99)

    assert len(results) == 5


def test_dom_query_ranks_dom_above_unrelated_sqli(tmp_path: Path) -> None:
    store, chunk = make_store(tmp_path)
    dom = card(
        chunk,
        title="DOM attribute context",
        tags=["dom", "attribute"],
        triggers=["setattribute", "attribute context"],
        principle="Trace controllable DOM data into its exact browser parsing context.",
    )
    sqli = card(
        chunk,
        title="SQL query behavior",
        topic=KnowledgeTopic.SQLI,
        tags=["sqli", "query"],
        triggers=["sql error"],
        principle="A server error does not demonstrate control of SQL query structure.",
    )
    store.save_card(sqli)
    store.save_card(dom)

    results = store.get_relevant_knowledge(
        AgentName.IKIT,
        "DOM setAttribute attribute context",
        limit=5,
    )

    assert results[0].id == dom.id
    result_ids = [item.id for item in results]
    if sqli.id in result_ids:
        assert result_ids.index(dom.id) < result_ids.index(sqli.id)


def test_research_does_not_swamp_core_for_ordinary_query(tmp_path: Path) -> None:
    store, chunk = make_store(tmp_path)
    for index in range(3):
        store.save_card(
            card(
                chunk,
                title=f"Core DOM context {index}",
                tags=["dom", "context"],
            )
        )
    for index in range(5):
        store.save_card(
            card(
                chunk,
                title=f"Research DOM technique {index}",
                source_type=KnowledgeSourceType.RESEARCH,
                tags=["dom", "context", "technique"],
            )
        )

    results = store.get_relevant_knowledge(
        AgentName.IKIT,
        "ordinary dom context analysis",
        limit=5,
    )

    assert sum(item.source_type == KnowledgeSourceType.RESEARCH for item in results) <= 1
    assert sum(item.source_type == KnowledgeSourceType.ACADEMY for item in results) >= 3


def test_cards_are_queryable_by_tags_and_triggers(tmp_path: Path) -> None:
    store, chunk = make_store(tmp_path)
    expected = card(
        chunk,
        title="Attribute parser context",
        tags=["dom", "attribute"],
        triggers=["setattribute", "attribute context"],
    )
    store.save_card(expected)
    store.save_card(card(chunk, title="Other DOM card", tags=["dom"], triggers=["innerhtml"]))

    by_tag = store.list_cards(tags={"attribute"})
    by_trigger = store.list_cards(triggers={"setattribute"})

    assert [item.id for item in by_tag] == [expected.id]
    assert [item.id for item in by_trigger] == [expected.id]


def test_v05_database_gets_additive_knowledge_tables(tmp_path: Path) -> None:
    path = tmp_path / "existing.db"
    SQLiteMemoryStore(path)

    SQLiteKnowledgeStore(path)

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "knowledge_documents",
        "knowledge_chunks",
        "knowledge_cards",
        "knowledge_card_sources",
        "knowledge_forge_runs",
        "knowledge_fidelity_reviews",
    } <= tables


def test_legacy_fidelity_pass_without_subtopic_coverage_is_requeued(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-fidelity.db"
    legacy_checked = {
        "title": True,
        "tags": True,
        "triggers": True,
        "principle": True,
        "questions_to_ask": True,
        "false_positive_traps": True,
        "evidence_required": True,
        "escalation_topics": True,
        "technique_assumptions": True,
        "prerequisites": True,
        "demonstrated_behavior": True,
    }
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE knowledge_fidelity_reviews (
                card_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                checked_fields TEXT NOT NULL DEFAULT '{}',
                issues TEXT NOT NULL DEFAULT '[]',
                response_id TEXT,
                checked_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO knowledge_fidelity_reviews(
                card_id, status, checked_fields, issues, response_id,
                checked_at, updated_at
            ) VALUES (?, 'pass', ?, '[]', 'resp_legacy', ?, ?)
            """,
            (
                "11111111-1111-1111-1111-111111111111",
                json.dumps(legacy_checked),
                "2026-08-29T00:00:00+00:00",
                "2026-08-29T00:00:00+00:00",
            ),
        )

    SQLiteKnowledgeStore(path)

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT status, checked_fields, issues, response_id, checked_at
            FROM knowledge_fidelity_reviews
            """
        ).fetchone()
    assert row == ("pending", "{}", "[]", None, None)
