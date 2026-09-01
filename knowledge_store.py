from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import Field

from schemas import (
    AgentName,
    CriticDecision,
    KnowledgeCard,
    KnowledgeCardStatus,
    KnowledgeSchema,
    KnowledgeSourceType,
    KnowledgeTopic,
    SourceFidelityCheckedFields,
    SourceFidelityIssue,
    utc_now,
)
from source_ingestion import SourceChunk, SourceChunkStatus, SourceDocument


SEARCH_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{1,}")


class ForgeRunStatus(str, Enum):
    RUNNING = "running"
    RETRYABLE = "retryable"
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"


class FidelityReviewStatus(str, Enum):
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"
    RETRYABLE = "retryable"
    ERROR = "error"


class ForgeRun(KnowledgeSchema):
    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    session_id: UUID
    status: ForgeRunStatus = ForgeRunStatus.RUNNING
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    error: str | None = None


class CardReviewMetadata(KnowledgeSchema):
    card_id: UUID
    critic_decision: CriticDecision | None = None
    validation_errors: list[str] = Field(default_factory=list)
    rejection_reason: str | None = None
    duplicate_of: UUID | None = None
    revision_count: int = Field(default=0, ge=0)


class FidelityReviewMetadata(KnowledgeSchema):
    card_id: UUID
    status: FidelityReviewStatus
    checked_fields: SourceFidelityCheckedFields | None = None
    issues: list[SourceFidelityIssue] = Field(default_factory=list, max_length=8)
    response_id: str | None = None
    checked_at: datetime | None = None
    updated_at: datetime


@dataclass(frozen=True)
class DocumentPurgeSummary:
    document_id: UUID
    documents_removed: int
    chunks_removed: int
    forge_runs_removed: int
    cards_removed: int
    card_review_states_removed: int
    card_source_associations_removed: int
    foreign_source_associations_removed: int
    duplicate_links_cleared: int


@runtime_checkable
class KnowledgeStore(Protocol):
    def save_document(
        self, document: SourceDocument, chunks: list[SourceChunk]
    ) -> None: ...

    def get_document(self, document_id: UUID) -> SourceDocument | None: ...

    def list_documents(self, limit: int = 100) -> list[SourceDocument]: ...

    def purge_document(self, document_id: UUID) -> DocumentPurgeSummary: ...

    def list_chunks(
        self,
        document_id: UUID,
        statuses: set[SourceChunkStatus] | None = None,
    ) -> list[SourceChunk]: ...

    def get_chunk(self, chunk_id: UUID) -> SourceChunk | None: ...

    def set_chunk_status(
        self,
        chunk_id: UUID,
        status: SourceChunkStatus,
        error: str | None = None,
    ) -> None: ...

    def requeue_failed_chunks(self, document_id: UUID) -> int: ...

    def create_forge_run(self, document_id: UUID, session_id: UUID) -> ForgeRun: ...

    def get_resumable_run(self, document_id: UUID) -> ForgeRun | None: ...

    def get_latest_run(self, document_id: UUID) -> ForgeRun | None: ...

    def update_forge_run(
        self,
        run_id: UUID,
        status: ForgeRunStatus,
        error: str | None = None,
    ) -> None: ...

    def save_card(self, card: KnowledgeCard, **metadata: Any) -> None: ...

    def get_card(self, card_id: UUID) -> KnowledgeCard | None: ...

    def get_card_review(self, card_id: UUID) -> CardReviewMetadata | None: ...

    def get_fidelity_review(self, card_id: UUID) -> FidelityReviewMetadata | None: ...

    def mark_fidelity_pending(self, card_ids: list[UUID]) -> None: ...

    def set_fidelity_review(
        self,
        card_id: UUID,
        status: FidelityReviewStatus,
        **metadata: Any,
    ) -> FidelityReviewMetadata: ...

    def list_fidelity_resumable_cards(self, source_chunk_id: UUID) -> list[KnowledgeCard]: ...

    def list_cards(self, **filters: Any) -> list[KnowledgeCard]: ...

    def list_card_ids(self, exclude: UUID | None = None) -> set[UUID]: ...

    def set_card_status(
        self,
        card_id: UUID,
        status: KnowledgeCardStatus,
        **metadata: Any,
    ) -> KnowledgeCard: ...

    def add_card_source(self, card_id: UUID, source_chunk_id: UUID) -> None: ...

    def get_card_sources(self, card_id: UUID) -> list[dict[str, str]]: ...

    def get_relevant_knowledge(
        self,
        agent: AgentName,
        query: str,
        limit: int,
    ) -> list[KnowledgeCard]: ...


class SQLiteKnowledgeStore:
    """Local SQLite store for forge provenance, state, and approved cards."""

    def __init__(
        self,
        database_path: str | Path,
        max_fragments: int = 5,
        *,
        initialize: bool = True,
        read_only: bool = False,
    ) -> None:
        self.path = Path(database_path)
        self.read_only = read_only
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_fragments = max(0, max_fragments)
        if initialize:
            self._initialize()

    @classmethod
    def open_read_only(
        cls,
        database_path: str | Path,
        max_fragments: int = 5,
    ) -> "SQLiteKnowledgeStore":
        return cls(
            database_path,
            max_fragments,
            initialize=False,
            read_only=True,
        )

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            uri = f"{self.path.resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
        else:
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_reference TEXT NOT NULL,
                    source_path TEXT,
                    corpus TEXT,
                    subtopic TEXT,
                    content TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    ingested_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    heading TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    source_reference TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT,
                    processed_at TEXT,
                    UNIQUE(document_id, sequence),
                    FOREIGN KEY(document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS knowledge_cards (
                    id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    subtopic TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    source_reference TEXT NOT NULL,
                    source_chunk_id TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    triggers TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    card_json TEXT NOT NULL,
                    critic_decision TEXT,
                    validation_errors TEXT NOT NULL DEFAULT '[]',
                    rejection_reason TEXT,
                    duplicate_of TEXT,
                    revision_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(source_chunk_id) REFERENCES knowledge_chunks(id) ON DELETE RESTRICT,
                    FOREIGN KEY(duplicate_of) REFERENCES knowledge_cards(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_card_sources (
                    card_id TEXT NOT NULL,
                    source_chunk_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    source_reference TEXT NOT NULL,
                    PRIMARY KEY(card_id, source_chunk_id),
                    FOREIGN KEY(card_id) REFERENCES knowledge_cards(id) ON DELETE CASCADE,
                    FOREIGN KEY(source_chunk_id) REFERENCES knowledge_chunks(id) ON DELETE RESTRICT,
                    FOREIGN KEY(document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS knowledge_forge_runs (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    error TEXT,
                    FOREIGN KEY(document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS knowledge_fidelity_reviews (
                    card_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    checked_fields TEXT NOT NULL DEFAULT '{}',
                    issues TEXT NOT NULL DEFAULT '[]',
                    response_id TEXT,
                    checked_at TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(card_id) REFERENCES knowledge_cards(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_status
                    ON knowledge_chunks(document_id, status, sequence);
                CREATE INDEX IF NOT EXISTS idx_knowledge_cards_lookup
                    ON knowledge_cards(agent, status, topic, source_type);
                CREATE INDEX IF NOT EXISTS idx_knowledge_forge_runs_document
                    ON knowledge_forge_runs(document_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_knowledge_fidelity_status
                    ON knowledge_fidelity_reviews(status, updated_at);
                """
            )
            self._ensure_column(connection, "knowledge_documents", "source_path", "TEXT")
            self._ensure_column(connection, "knowledge_documents", "corpus", "TEXT")
            self._ensure_column(connection, "knowledge_documents", "subtopic", "TEXT")
            self._invalidate_legacy_fidelity_passes(connection)

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _invalidate_legacy_fidelity_passes(connection: sqlite3.Connection) -> None:
        """Recheck old PASS reviews that predate mandatory subtopic coverage."""

        connection.execute(
            """
            UPDATE knowledge_fidelity_reviews
            SET status = 'pending', checked_fields = '{}', issues = '[]',
                response_id = NULL, checked_at = NULL, updated_at = ?
            WHERE status = 'pass'
              AND checked_fields NOT LIKE '%"subtopic"%'
            """,
            (utc_now().isoformat(),),
        )

    def save_document(
        self, document: SourceDocument, chunks: list[SourceChunk]
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_documents(
                    id, title, source_type, source_reference, source_path, corpus,
                    subtopic, content, agent, topic, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    source_type=excluded.source_type,
                    source_reference=excluded.source_reference,
                    source_path=excluded.source_path,
                    corpus=excluded.corpus,
                    subtopic=excluded.subtopic,
                    content=excluded.content,
                    agent=excluded.agent,
                    topic=excluded.topic
                """,
                (
                    str(document.id),
                    document.title,
                    document.source_type.value,
                    document.source_reference,
                    document.source_path,
                    document.corpus,
                    document.subtopic,
                    document.content,
                    document.agent.value,
                    document.topic.value,
                    document.ingested_at.isoformat(),
                ),
            )
            for chunk in chunks:
                connection.execute(
                    """
                    INSERT INTO knowledge_chunks(
                        id, document_id, heading, content, sequence,
                        source_reference, status, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (
                        str(chunk.id),
                        str(chunk.document_id),
                        chunk.heading,
                        chunk.content,
                        chunk.sequence,
                        chunk.source_reference,
                        chunk.status.value,
                        chunk.error,
                    ),
                )

    def get_document(self, document_id: UUID) -> SourceDocument | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_documents WHERE id = ?",
                (str(document_id),),
            ).fetchone()
        if row is None:
            return None
        return SourceDocument(
            id=UUID(row["id"]),
            title=row["title"],
            source_type=row["source_type"],
            source_reference=row["source_reference"],
            source_path=row["source_path"],
            corpus=row["corpus"],
            subtopic=row["subtopic"],
            content=row["content"],
            agent=row["agent"],
            topic=row["topic"],
            ingested_at=row["ingested_at"],
        )

    def list_documents(self, limit: int = 100) -> list[SourceDocument]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM knowledge_documents ORDER BY ingested_at DESC LIMIT ?",
                (max(0, limit),),
            ).fetchall()
        return [document for row in rows if (document := self.get_document(UUID(row["id"]))) is not None]

    def purge_document(self, document_id: UUID) -> DocumentPurgeSummary:
        """Transactionally remove one document and only knowledge it causally owns."""

        document_key = str(document_id)
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM knowledge_documents WHERE id = ?",
                (document_key,),
            ).fetchone()
            if exists is None:
                raise KeyError(f"Unknown source document: {document_id}")

            chunks_removed = int(
                connection.execute(
                    "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id = ?",
                    (document_key,),
                ).fetchone()[0]
            )
            forge_runs_removed = int(
                connection.execute(
                    "SELECT COUNT(*) FROM knowledge_forge_runs WHERE document_id = ?",
                    (document_key,),
                ).fetchone()[0]
            )
            cards_removed = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM knowledge_cards
                    WHERE source_chunk_id IN (
                        SELECT id FROM knowledge_chunks WHERE document_id = ?
                    )
                    """,
                    (document_key,),
                ).fetchone()[0]
            )
            foreign_source_associations_removed = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM knowledge_card_sources
                    WHERE document_id = ?
                      AND card_id NOT IN (
                          SELECT id FROM knowledge_cards
                          WHERE source_chunk_id IN (
                              SELECT id FROM knowledge_chunks WHERE document_id = ?
                          )
                      )
                    """,
                    (document_key, document_key),
                ).fetchone()[0]
            )
            card_source_associations_removed = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM knowledge_card_sources
                    WHERE document_id = ?
                       OR card_id IN (
                           SELECT id FROM knowledge_cards
                           WHERE source_chunk_id IN (
                               SELECT id FROM knowledge_chunks WHERE document_id = ?
                           )
                       )
                    """,
                    (document_key, document_key),
                ).fetchone()[0]
            )
            duplicate_links_cleared = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM knowledge_cards
                    WHERE duplicate_of IN (
                        SELECT id FROM knowledge_cards
                        WHERE source_chunk_id IN (
                            SELECT id FROM knowledge_chunks WHERE document_id = ?
                        )
                    )
                      AND source_chunk_id NOT IN (
                          SELECT id FROM knowledge_chunks WHERE document_id = ?
                      )
                    """,
                    (document_key, document_key),
                ).fetchone()[0]
            )

            connection.execute(
                """
                DELETE FROM knowledge_card_sources
                WHERE document_id = ?
                  AND card_id NOT IN (
                      SELECT id FROM knowledge_cards
                      WHERE source_chunk_id IN (
                          SELECT id FROM knowledge_chunks WHERE document_id = ?
                      )
                  )
                """,
                (document_key, document_key),
            )
            connection.execute(
                """
                DELETE FROM knowledge_cards
                WHERE source_chunk_id IN (
                    SELECT id FROM knowledge_chunks WHERE document_id = ?
                )
                """,
                (document_key,),
            )
            connection.execute(
                "DELETE FROM knowledge_forge_runs WHERE document_id = ?",
                (document_key,),
            )
            connection.execute(
                "DELETE FROM knowledge_chunks WHERE document_id = ?",
                (document_key,),
            )
            documents_removed = int(
                connection.execute(
                    "DELETE FROM knowledge_documents WHERE id = ?",
                    (document_key,),
                ).rowcount
            )

        return DocumentPurgeSummary(
            document_id=document_id,
            documents_removed=documents_removed,
            chunks_removed=chunks_removed,
            forge_runs_removed=forge_runs_removed,
            cards_removed=cards_removed,
            card_review_states_removed=cards_removed,
            card_source_associations_removed=card_source_associations_removed,
            foreign_source_associations_removed=foreign_source_associations_removed,
            duplicate_links_cleared=duplicate_links_cleared,
        )

    def list_chunks(
        self,
        document_id: UUID,
        statuses: set[SourceChunkStatus] | None = None,
    ) -> list[SourceChunk]:
        sql = "SELECT * FROM knowledge_chunks WHERE document_id = ?"
        params: list[Any] = [str(document_id)]
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            sql += f" AND status IN ({placeholders})"
            params.extend(sorted(status.value for status in statuses))
        sql += " ORDER BY sequence"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            SourceChunk(
                id=UUID(row["id"]),
                document_id=UUID(row["document_id"]),
                heading=row["heading"],
                content=row["content"],
                sequence=row["sequence"],
                source_reference=row["source_reference"],
                status=row["status"],
                error=row["error"],
            )
            for row in rows
        ]

    def get_chunk(self, chunk_id: UUID) -> SourceChunk | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_chunks WHERE id = ?",
                (str(chunk_id),),
            ).fetchone()
        if row is None:
            return None
        return SourceChunk(
            id=UUID(row["id"]),
            document_id=UUID(row["document_id"]),
            heading=row["heading"],
            content=row["content"],
            sequence=row["sequence"],
            source_reference=row["source_reference"],
            status=row["status"],
            error=row["error"],
        )

    def set_chunk_status(
        self,
        chunk_id: UUID,
        status: SourceChunkStatus,
        error: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE knowledge_chunks
                SET status = ?, error = ?, processed_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    error,
                    utc_now().isoformat() if status == SourceChunkStatus.PROCESSED else None,
                    str(chunk_id),
                ),
            )

    def requeue_failed_chunks(self, document_id: UUID) -> int:
        """Explicitly make permanent failures eligible for one future build pass."""

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE knowledge_chunks
                SET status = 'retryable', error = NULL, processed_at = NULL
                WHERE document_id = ? AND status = 'failed'
                """,
                (str(document_id),),
            )
            return int(cursor.rowcount)

    def create_forge_run(self, document_id: UUID, session_id: UUID) -> ForgeRun:
        run = ForgeRun(document_id=document_id, session_id=session_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_forge_runs(
                    id, document_id, session_id, status, started_at, updated_at,
                    completed_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run.id),
                    str(run.document_id),
                    str(run.session_id),
                    run.status.value,
                    run.started_at.isoformat(),
                    run.updated_at.isoformat(),
                    None,
                    None,
                ),
            )
        return run

    def get_resumable_run(self, document_id: UUID) -> ForgeRun | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_forge_runs
                WHERE document_id = ?
                  AND status IN ('running', 'retryable', 'budget_exhausted')
                ORDER BY updated_at DESC LIMIT 1
                """,
                (str(document_id),),
            ).fetchone()
        return self._row_to_run(row) if row else None

    def get_latest_run(self, document_id: UUID) -> ForgeRun | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_forge_runs
                WHERE document_id = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (str(document_id),),
            ).fetchone()
        return self._row_to_run(row) if row else None

    def update_forge_run(
        self,
        run_id: UUID,
        status: ForgeRunStatus,
        error: str | None = None,
    ) -> None:
        now = utc_now().isoformat()
        completed_at = now if status in {ForgeRunStatus.COMPLETED, ForgeRunStatus.FAILED} else None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE knowledge_forge_runs
                SET status = ?, updated_at = ?, completed_at = ?, error = ?
                WHERE id = ?
                """,
                (status.value, now, completed_at, error, str(run_id)),
            )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> ForgeRun:
        return ForgeRun(
            id=UUID(row["id"]),
            document_id=UUID(row["document_id"]),
            session_id=UUID(row["session_id"]),
            status=row["status"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            error=row["error"],
        )

    def save_card(
        self,
        card: KnowledgeCard,
        *,
        critic_decision: CriticDecision | None = None,
        validation_errors: list[str] | None = None,
        rejection_reason: str | None = None,
        duplicate_of: UUID | None = None,
        revision_count: int = 0,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_cards(
                    id, agent, topic, subtopic, title, source_type, source_title,
                    source_reference, source_chunk_id, tags, triggers, confidence,
                    status, card_json, critic_decision, validation_errors,
                    rejection_reason, duplicate_of, revision_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    agent=excluded.agent,
                    topic=excluded.topic,
                    subtopic=excluded.subtopic,
                    title=excluded.title,
                    source_type=excluded.source_type,
                    source_title=excluded.source_title,
                    source_reference=excluded.source_reference,
                    source_chunk_id=excluded.source_chunk_id,
                    tags=excluded.tags,
                    triggers=excluded.triggers,
                    confidence=excluded.confidence,
                    status=excluded.status,
                    card_json=excluded.card_json,
                    critic_decision=excluded.critic_decision,
                    validation_errors=excluded.validation_errors,
                    rejection_reason=excluded.rejection_reason,
                    duplicate_of=excluded.duplicate_of,
                    revision_count=excluded.revision_count,
                    updated_at=excluded.updated_at
                """,
                (
                    str(card.id),
                    card.agent.value,
                    card.topic.value,
                    card.subtopic,
                    card.title,
                    card.source_type.value,
                    card.source_title,
                    card.source_reference,
                    str(card.source_chunk_id),
                    json.dumps(card.tags),
                    json.dumps(card.triggers),
                    card.confidence,
                    card.status.value,
                    card.model_dump_json(),
                    critic_decision.value if critic_decision else None,
                    json.dumps(validation_errors or []),
                    rejection_reason,
                    str(duplicate_of) if duplicate_of else None,
                    revision_count,
                    card.created_at.isoformat(),
                    card.updated_at.isoformat(),
                ),
            )
            self._add_card_source(connection, card.id, card.source_chunk_id)

    def get_card(self, card_id: UUID) -> KnowledgeCard | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT card_json FROM knowledge_cards WHERE id = ?",
                (str(card_id),),
            ).fetchone()
        return KnowledgeCard.model_validate_json(row["card_json"]) if row else None

    def get_card_review(self, card_id: UUID) -> CardReviewMetadata | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, critic_decision, validation_errors, rejection_reason,
                       duplicate_of, revision_count
                FROM knowledge_cards WHERE id = ?
                """,
                (str(card_id),),
            ).fetchone()
        if row is None:
            return None
        return CardReviewMetadata(
            card_id=UUID(row["id"]),
            critic_decision=row["critic_decision"],
            validation_errors=json.loads(row["validation_errors"]),
            rejection_reason=row["rejection_reason"],
            duplicate_of=UUID(row["duplicate_of"]) if row["duplicate_of"] else None,
            revision_count=row["revision_count"],
        )

    def get_fidelity_review(self, card_id: UUID) -> FidelityReviewMetadata | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_fidelity_reviews WHERE card_id = ?",
                (str(card_id),),
            ).fetchone()
        if row is None:
            return None
        checked_payload = json.loads(row["checked_fields"])
        checked_fields_complete = set(SourceFidelityCheckedFields.model_fields).issubset(
            checked_payload
        )
        status = FidelityReviewStatus(row["status"])
        if status == FidelityReviewStatus.PASS and not checked_fields_complete:
            status = FidelityReviewStatus.PENDING
        return FidelityReviewMetadata(
            card_id=UUID(row["card_id"]),
            status=status,
            checked_fields=(
                SourceFidelityCheckedFields.model_validate(checked_payload)
                if checked_payload and checked_fields_complete
                else None
            ),
            issues=[
                SourceFidelityIssue.model_validate(issue)
                for issue in json.loads(row["issues"])
            ],
            response_id=row["response_id"],
            checked_at=row["checked_at"],
            updated_at=row["updated_at"],
        )

    def mark_fidelity_pending(self, card_ids: list[UUID]) -> None:
        if not card_ids:
            return
        now = utc_now().isoformat()
        with self._connect() as connection:
            for card_id in card_ids:
                connection.execute(
                    """
                    INSERT INTO knowledge_fidelity_reviews(
                        card_id, status, checked_fields, issues, response_id,
                        checked_at, updated_at
                    ) VALUES (?, 'pending', '{}', '[]', NULL, NULL, ?)
                    ON CONFLICT(card_id) DO UPDATE SET
                        status='pending',
                        checked_fields='{}',
                        issues='[]',
                        response_id=NULL,
                        checked_at=NULL,
                        updated_at=excluded.updated_at
                    """,
                    (str(card_id), now),
                )

    def set_fidelity_review(
        self,
        card_id: UUID,
        status: FidelityReviewStatus,
        *,
        checked_fields: SourceFidelityCheckedFields | None = None,
        issues: list[SourceFidelityIssue] | None = None,
        response_id: str | None = None,
    ) -> FidelityReviewMetadata:
        issue_list = [SourceFidelityIssue.model_validate(issue) for issue in issues or []]
        checked = (
            SourceFidelityCheckedFields.model_validate(checked_fields)
            if checked_fields is not None
            else None
        )
        if status == FidelityReviewStatus.PASS and (checked is None or issue_list):
            raise ValueError("A fidelity pass requires all checked fields and zero issues")
        if status == FidelityReviewStatus.FAIL and (checked is None or not issue_list):
            raise ValueError("A fidelity fail requires all checked fields and at least one issue")
        now = utc_now()
        checked_at = None if status == FidelityReviewStatus.PENDING else now
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_fidelity_reviews(
                    card_id, status, checked_fields, issues, response_id,
                    checked_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(card_id) DO UPDATE SET
                    status=excluded.status,
                    checked_fields=excluded.checked_fields,
                    issues=excluded.issues,
                    response_id=excluded.response_id,
                    checked_at=excluded.checked_at,
                    updated_at=excluded.updated_at
                """,
                (
                    str(card_id),
                    status.value,
                    json.dumps(checked.model_dump(mode="json") if checked else {}),
                    json.dumps([issue.model_dump(mode="json") for issue in issue_list]),
                    response_id,
                    checked_at.isoformat() if checked_at else None,
                    now.isoformat(),
                ),
            )
        review = self.get_fidelity_review(card_id)
        if review is None:
            raise RuntimeError(f"Fidelity review was not persisted for card {card_id}")
        return review

    def list_fidelity_resumable_cards(
        self,
        source_chunk_id: UUID,
    ) -> list[KnowledgeCard]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.card_json
                FROM knowledge_cards AS c
                JOIN knowledge_fidelity_reviews AS f ON f.card_id = c.id
                WHERE c.source_chunk_id = ?
                  AND c.status = 'candidate'
                  AND f.status IN ('pending', 'retryable', 'error')
                ORDER BY c.created_at, c.id
                """,
                (str(source_chunk_id),),
            ).fetchall()
        return [KnowledgeCard.model_validate_json(row["card_json"]) for row in rows]

    def list_cards(
        self,
        *,
        agent: AgentName | None = None,
        status: KnowledgeCardStatus | None = None,
        topic: KnowledgeTopic | None = None,
        source_type: KnowledgeSourceType | None = None,
        source_chunk_id: UUID | None = None,
        document_id: UUID | None = None,
        tags: set[str] | None = None,
        triggers: set[str] | None = None,
        limit: int = 500,
    ) -> list[KnowledgeCard]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("agent", agent.value if agent else None),
            ("status", status.value if status else None),
            ("topic", topic.value if topic else None),
            ("source_type", source_type.value if source_type else None),
            ("source_chunk_id", str(source_chunk_id) if source_chunk_id else None),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if document_id is not None:
            clauses.append(
                "source_chunk_id IN (SELECT id FROM knowledge_chunks WHERE document_id = ?)"
            )
            params.append(str(document_id))
        for tag in sorted(tags or set()):
            clauses.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        for trigger in sorted(triggers or set()):
            clauses.append("triggers LIKE ?")
            params.append(f'%"{trigger}"%')
        sql = "SELECT card_json FROM knowledge_cards"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC, id LIMIT ?"
        params.append(max(0, limit))
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [KnowledgeCard.model_validate_json(row["card_json"]) for row in rows]

    def list_card_ids(self, exclude: UUID | None = None) -> set[UUID]:
        sql = "SELECT id FROM knowledge_cards"
        params: tuple[str, ...] = ()
        if exclude is not None:
            sql += " WHERE id != ?"
            params = (str(exclude),)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return {UUID(row["id"]) for row in rows}

    def set_card_status(
        self,
        card_id: UUID,
        status: KnowledgeCardStatus,
        *,
        critic_decision: CriticDecision | None = None,
        validation_errors: list[str] | None = None,
        rejection_reason: str | None = None,
        duplicate_of: UUID | None = None,
        revision_count: int | None = None,
    ) -> KnowledgeCard:
        card = self.get_card(card_id)
        if card is None:
            raise KeyError(f"Unknown knowledge card: {card_id}")
        updated = card.model_copy(
            update={"status": status, "updated_at": utc_now()}
        )
        existing = self.get_card_review(card_id)
        self.save_card(
            updated,
            critic_decision=(
                critic_decision
                if critic_decision is not None
                else existing.critic_decision if existing else None
            ),
            validation_errors=(
                validation_errors
                if validation_errors is not None
                else existing.validation_errors if existing else []
            ),
            rejection_reason=rejection_reason,
            duplicate_of=duplicate_of,
            revision_count=(
                revision_count
                if revision_count is not None
                else existing.revision_count if existing else 0
            ),
        )
        return updated

    def add_card_source(self, card_id: UUID, source_chunk_id: UUID) -> None:
        with self._connect() as connection:
            self._add_card_source(connection, card_id, source_chunk_id)

    @staticmethod
    def _add_card_source(
        connection: sqlite3.Connection,
        card_id: UUID,
        source_chunk_id: UUID,
    ) -> None:
        row = connection.execute(
            "SELECT document_id, source_reference FROM knowledge_chunks WHERE id = ?",
            (str(source_chunk_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown source chunk: {source_chunk_id}")
        connection.execute(
            """
            INSERT OR IGNORE INTO knowledge_card_sources(
                card_id, source_chunk_id, document_id, source_reference
            ) VALUES (?, ?, ?, ?)
            """,
            (str(card_id), str(source_chunk_id), row["document_id"], row["source_reference"]),
        )

    def get_card_sources(self, card_id: UUID) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT source_chunk_id, document_id, source_reference
                FROM knowledge_card_sources WHERE card_id = ?
                ORDER BY source_chunk_id
                """,
                (str(card_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_relevant_knowledge(
        self,
        agent: AgentName,
        query: str,
        limit: int | None = None,
    ) -> list[KnowledgeCard]:
        capped_limit = min(
            self.max_fragments,
            self.max_fragments if limit is None else max(0, limit),
        )
        if capped_limit == 0:
            return []
        candidates = self.list_cards(
            agent=agent,
            status=KnowledgeCardStatus.APPROVED,
        )
        normalized_query = self._normalize(query)
        query_tokens = set(SEARCH_TOKEN_PATTERN.findall(normalized_query))
        scored: list[tuple[int, KnowledgeCard]] = []
        for card in candidates:
            score = self._score(card, normalized_query, query_tokens)
            if score > 0:
                scored.append((score, card))
        scored.sort(
            key=lambda item: (
                -item[0],
                item[1].source_type == KnowledgeSourceType.RESEARCH,
                -item[1].confidence,
                str(item[1].id),
            )
        )

        research_query = bool(
            {"research", "advanced", "novel", "paper", "technique"} & query_tokens
        )
        selected: list[KnowledgeCard] = []
        research_count = 0
        for _, card in scored:
            if (
                card.source_type == KnowledgeSourceType.RESEARCH
                and not research_query
                and research_count >= 1
            ):
                continue
            selected.append(card)
            if card.source_type == KnowledgeSourceType.RESEARCH:
                research_count += 1
            if len(selected) >= capped_limit:
                break
        return selected

    @classmethod
    def _score(
        cls,
        card: KnowledgeCard,
        normalized_query: str,
        query_tokens: set[str],
    ) -> int:
        score = 0
        if card.topic.value in query_tokens:
            score += 12
        for trigger in card.triggers:
            normalized_trigger = cls._normalize(trigger)
            if normalized_trigger and normalized_trigger in normalized_query:
                score += 10
        tag_matches = query_tokens & {cls._normalize(tag) for tag in card.tags}
        score += 5 * len(tag_matches)
        searchable_tokens = set(
            SEARCH_TOKEN_PATTERN.findall(
                cls._normalize(f"{card.title} {card.subtopic} {card.principle}")
            )
        )
        score += min(6, len(query_tokens & searchable_tokens))
        if score > 0 and card.source_type in {
            KnowledgeSourceType.ACADEMY,
            KnowledgeSourceType.INTERNAL,
        }:
            score += 2
        return score

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.casefold().split())
