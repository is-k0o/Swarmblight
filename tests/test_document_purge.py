from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import forge as forge_module
from config import Settings
from knowledge_store import SQLiteKnowledgeStore
from llm import UsageDetails
from memory import SQLiteMemoryStore
from schemas import (
    AgentName,
    CriticDecision,
    KnowledgeCard,
    KnowledgeCardStatus,
    KnowledgeSourceType,
    KnowledgeTopic,
)
from source_ingestion import SourceIngestor


def ingest_document(
    tmp_path: Path,
    store: SQLiteKnowledgeStore,
    name: str,
):
    path = tmp_path / name
    path.write_text(
        f"# {name}\n\nA reusable source-bounded method from {name}.",
        encoding="utf-8",
    )
    document, chunks = SourceIngestor(1000).ingest_file(
        path,
        agent=AgentName.IKIT,
        source_type=KnowledgeSourceType.ACADEMY,
        topic=KnowledgeTopic.DOM,
    )
    store.save_document(document, chunks)
    return document, chunks


def card_for(document, chunk, title: str) -> KnowledgeCard:
    return KnowledgeCard(
        agent=AgentName.IKIT,
        topic=KnowledgeTopic.DOM,
        subtopic="source-bounded",
        title=title,
        source_type=document.source_type,
        source_title=document.title,
        source_reference=document.source_reference,
        source_chunk_id=chunk.id,
        tags=["dom"],
        triggers=["source"],
        principle=f"Apply only the supported method from {title}.",
        status=KnowledgeCardStatus.APPROVED,
        confidence=0.8,
    )


def table_count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_purge_removes_owned_forge_data_and_preserves_foreign_provenance(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "forge.db"
    memory = SQLiteMemoryStore(database_path)
    store = SQLiteKnowledgeStore(database_path)
    target, target_chunks = ingest_document(tmp_path, store, "target.md")
    foreign, foreign_chunks = ingest_document(tmp_path, store, "foreign.md")

    target_card = card_for(target, target_chunks[0], "Target-owned card")
    foreign_card = card_for(foreign, foreign_chunks[0], "Foreign approved card")
    store.save_card(
        target_card,
        critic_decision=CriticDecision.APPROVE,
        validation_errors=[],
        revision_count=1,
    )
    store.save_card(
        foreign_card,
        critic_decision=CriticDecision.APPROVE,
        validation_errors=[],
    )
    store.add_card_source(foreign_card.id, target_chunks[0].id)
    store.add_card_source(target_card.id, foreign_chunks[0].id)

    target_session = memory.create_session()
    foreign_session = memory.create_session()
    target_run = store.create_forge_run(target.id, target_session)
    foreign_run = store.create_forge_run(foreign.id, foreign_session)
    memory.save_usage(
        target_session,
        AgentName.IKIT,
        UsageDetails(
            model="mock-model",
            input_tokens=11,
            output_tokens=7,
            total_tokens=18,
            actual_cost_usd=0.01,
        ),
        run_id=target_run.id,
    )
    memory.save_uncertain_usage(
        reservation_id=uuid4(),
        session_id=target_session,
        run_id=target_run.id,
        agent=AgentName.IKIT,
        model="mock-model",
        reserved_input_tokens=20,
        reserved_output_tokens=30,
        reserved_cost_usd=0.02,
        reason="test uncertainty",
    )
    accounting_before = {
        table: table_count(database_path, table)
        for table in ("sessions", "usage", "budget_uncertain_usage")
    }

    summary = store.purge_document(target.id)

    assert summary.documents_removed == 1
    assert summary.chunks_removed == len(target_chunks)
    assert summary.forge_runs_removed == 1
    assert summary.cards_removed == 1
    assert summary.card_review_states_removed == 1
    assert summary.foreign_source_associations_removed == 1
    assert summary.card_source_associations_removed == 3
    assert store.get_document(target.id) is None
    assert store.list_chunks(target.id) == []
    assert store.get_card(target_card.id) is None
    assert store.get_card_review(target_card.id) is None

    assert store.get_document(foreign.id) is not None
    assert store.get_card(foreign_card.id) is not None
    assert store.get_card_review(foreign_card.id) is not None
    assert store.get_card_sources(foreign_card.id) == [
        {
            "source_chunk_id": str(foreign_chunks[0].id),
            "document_id": str(foreign.id),
            "source_reference": foreign.source_reference,
        }
    ]
    with sqlite3.connect(database_path) as connection:
        remaining_run_ids = {
            row[0] for row in connection.execute("SELECT id FROM knowledge_forge_runs")
        }
    assert str(target_run.id) not in remaining_run_ids
    assert str(foreign_run.id) in remaining_run_ids
    assert {
        table: table_count(database_path, table)
        for table in ("sessions", "usage", "budget_uncertain_usage")
    } == accounting_before


def test_unknown_document_purge_fails_without_mutation(tmp_path: Path) -> None:
    database_path = tmp_path / "forge.db"
    store = SQLiteKnowledgeStore(database_path)
    document, chunks = ingest_document(tmp_path, store, "kept.md")
    before = {
        "documents": table_count(database_path, "knowledge_documents"),
        "chunks": table_count(database_path, "knowledge_chunks"),
    }

    with pytest.raises(KeyError, match="Unknown source document"):
        store.purge_document(uuid4())

    assert store.get_document(document.id) is not None
    assert store.list_chunks(document.id) == chunks
    assert {
        "documents": table_count(database_path, "knowledge_documents"),
        "chunks": table_count(database_path, "knowledge_chunks"),
    } == before


def test_purge_rolls_back_every_mutation_on_persistence_failure(tmp_path: Path) -> None:
    database_path = tmp_path / "forge.db"
    store = SQLiteKnowledgeStore(database_path)
    target, chunks = ingest_document(tmp_path, store, "rollback.md")
    card = card_for(target, chunks[0], "Rollback card")
    store.save_card(card, critic_decision=CriticDecision.APPROVE)
    run = store.create_forge_run(target.id, uuid4())
    sources_before = store.get_card_sources(card.id)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            f"""
            CREATE TRIGGER inject_purge_failure
            BEFORE DELETE ON knowledge_documents
            WHEN OLD.id = '{target.id}'
            BEGIN
                SELECT RAISE(ABORT, 'injected purge persistence failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected purge persistence failure"):
        store.purge_document(target.id)

    assert store.get_document(target.id) is not None
    assert store.list_chunks(target.id) == chunks
    assert store.get_card(card.id) is not None
    assert store.get_card_review(card.id) is not None
    assert store.get_card_sources(card.id) == sources_before
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM knowledge_forge_runs WHERE id = ?",
            (str(run.id),),
        ).fetchone()[0] == 1


def test_purge_cli_prints_concise_json_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "forge.db"
    store = SQLiteKnowledgeStore(database_path)
    document, _ = ingest_document(tmp_path, store, "cli.md")
    settings = Settings(database_path=database_path, specialist_model="mock-model")
    monkeypatch.setattr(forge_module, "get_settings", lambda: settings)

    exit_code = forge_module.main(["purge-document", str(document.id)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["document_id"] == str(document.id)
    assert payload["documents_removed"] == 1
    assert SQLiteKnowledgeStore(database_path).get_document(document.id) is None


def test_legacy_knowledge_schema_is_migrated_additively(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    document_id = UUID("c0d85153-c326-5a4f-b6d2-0fe089458e5c")
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE knowledge_documents (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_reference TEXT NOT NULL,
                content TEXT NOT NULL,
                agent TEXT NOT NULL,
                topic TEXT NOT NULL,
                ingested_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO knowledge_documents(
                id, title, source_type, source_reference, content, agent, topic, ingested_at
            ) VALUES (?, ?, 'academy', ?, '# Kept\n\nContent.', 'ikit', 'xss', ?)
            """,
            (
                str(document_id),
                "Legacy source",
                "D:\\old\\source.md",
                "2026-08-27T00:00:00+00:00",
            ),
        )

    store = SQLiteKnowledgeStore(database_path)

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(knowledge_documents)")
        }
        row_count = connection.execute(
            "SELECT COUNT(*) FROM knowledge_documents WHERE id = ?",
            (str(document_id),),
        ).fetchone()[0]
    migrated = store.get_document(document_id)
    assert {"source_path", "corpus", "subtopic"} <= columns
    assert row_count == 1
    assert migrated is not None
    assert migrated.title == "Legacy source"
    assert migrated.source_reference == "D:\\old\\source.md"
    assert migrated.source_path is None
