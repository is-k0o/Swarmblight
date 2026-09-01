from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from llm import UsageDetails
from schemas import (
    AgentName,
    EvidenceItem,
    EvaluationResult,
    FindingCandidate,
    Hypothesis,
    HypothesisStatus,
    Lesson,
    SessionSummary,
    StructuredAgentResponse,
)

logger = logging.getLogger(__name__)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@runtime_checkable
class MemoryStore(Protocol):
    def create_session(self) -> UUID: ...

    def get_or_create_active_session(self) -> UUID: ...

    def delete_session(self, session_id: UUID) -> None: ...

    def save_message(
        self,
        session_id: UUID,
        role: str,
        author: str,
        content: str,
        raw_json: dict[str, Any] | None = None,
    ) -> int: ...

    def save_agent_run(
        self,
        session_id: UUID,
        response: StructuredAgentResponse,
        phase: str,
    ) -> int: ...

    def save_hypothesis(self, session_id: UUID, hypothesis: Hypothesis) -> None: ...

    def get_hypothesis(self, hypothesis_id: UUID) -> Hypothesis | None: ...

    def update_hypothesis(
        self,
        hypothesis_id: UUID,
        status: HypothesisStatus,
        **changes: Any,
    ) -> Hypothesis: ...

    def list_open_hypotheses(self, session_id: UUID, limit: int = 50) -> list[Hypothesis]: ...

    def save_decision(
        self,
        session_id: UUID,
        content: str,
        response: StructuredAgentResponse | None = None,
    ) -> int: ...

    def save_usage(
        self,
        session_id: UUID,
        agent: AgentName,
        usage: UsageDetails,
        run_id: UUID | None = None,
    ) -> int: ...

    def save_uncertain_usage(
        self,
        *,
        reservation_id: UUID,
        session_id: UUID,
        run_id: UUID,
        agent: AgentName,
        model: str,
        reserved_input_tokens: int,
        reserved_output_tokens: int,
        reserved_cost_usd: float,
        reason: str,
    ) -> None: ...

    def get_daily_token_usage(self) -> int: ...

    def get_usage_cost_since(self, since: datetime) -> float: ...

    def get_run_cost(self, run_id: UUID) -> float: ...

    def save_evidence(self, session_id: UUID, evidence: EvidenceItem) -> None: ...

    def list_evidence(self, hypothesis_id: UUID) -> list[EvidenceItem]: ...

    def save_evaluation(self, session_id: UUID, evaluation: EvaluationResult) -> None: ...

    def save_finding_candidate(self, session_id: UUID, finding: FindingCandidate) -> None: ...

    def save_lesson(self, lesson: Lesson) -> None: ...

    def list_lessons(self, agent: AgentName | None = None, limit: int = 50) -> list[Lesson]: ...

    def search_lessons(
        self, query: str, agent: AgentName | None = None, limit: int = 10
    ) -> list[Lesson]: ...

    def get_session_summary(self, session_id: UUID) -> SessionSummary: ...


class SQLiteMemoryStore:
    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    ended_at TEXT,
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    author TEXT NOT NULL,
                    content TEXT NOT NULL,
                    raw_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS hypotheses (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    author_agent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_for TEXT NOT NULL,
                    evidence_against TEXT NOT NULL,
                    required_evidence TEXT NOT NULL DEFAULT '[]',
                    required_facts TEXT NOT NULL DEFAULT '[]',
                    current_evidence_level TEXT NOT NULL DEFAULT 'candidate',
                    validation_notes TEXT NOT NULL DEFAULT '[]',
                    discriminating_test TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    response_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    run_id TEXT,
                    agent TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost REAL,
                    actual_cost_usd REAL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS budget_uncertain_usage (
                    reservation_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    model TEXT NOT NULL,
                    reserved_input_tokens INTEGER NOT NULL,
                    reserved_output_tokens INTEGER NOT NULL,
                    reserved_total_tokens INTEGER NOT NULL,
                    reserved_cost_usd REAL NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    hypothesis_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    description TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    supports INTEGER NOT NULL,
                    facts TEXT NOT NULL DEFAULT '[]',
                    satisfies_required_evidence TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL,
                    proposed_level TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                    FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    hypothesis_id TEXT NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                    FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS findings (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    hypothesis_id TEXT NOT NULL,
                    finding_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                    FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS lessons (
                    id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_hypothesis_id TEXT,
                    tags TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(source_hypothesis_id) REFERENCES hypotheses(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_hypotheses_session_status
                    ON hypotheses(session_id, status);
                CREATE INDEX IF NOT EXISTS idx_usage_created_at ON usage(created_at);
                CREATE INDEX IF NOT EXISTS idx_budget_uncertain_created_at
                    ON budget_uncertain_usage(created_at, resolved_at);
                CREATE INDEX IF NOT EXISTS idx_budget_uncertain_run
                    ON budget_uncertain_usage(run_id, resolved_at);
                CREATE INDEX IF NOT EXISTS idx_evidence_hypothesis ON evidence(hypothesis_id);
                CREATE INDEX IF NOT EXISTS idx_lessons_agent ON lessons(agent);
                """
            )
            self._ensure_column(connection, "hypotheses", "required_evidence", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "hypotheses", "required_facts", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(
                connection,
                "hypotheses",
                "current_evidence_level",
                "TEXT NOT NULL DEFAULT 'candidate'",
            )
            self._ensure_column(connection, "hypotheses", "validation_notes", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "hypotheses", "discriminating_test", "TEXT")
            self._ensure_column(connection, "usage", "run_id", "TEXT")
            self._ensure_column(connection, "usage", "model", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "usage", "actual_cost_usd", "REAL")
            self._ensure_column(connection, "evidence", "facts", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(
                connection,
                "evidence",
                "satisfies_required_evidence",
                "TEXT NOT NULL DEFAULT '[]'",
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_session(self) -> UUID:
        session_id = uuid4()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions(id, created_at, active) VALUES (?, ?, 1)",
                (str(session_id), _timestamp()),
            )
        return session_id

    def get_or_create_active_session(self) -> UUID:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM sessions WHERE active = 1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return UUID(row["id"]) if row else self.create_session()

    def delete_session(self, session_id: UUID) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE id = ?", (str(session_id),))

    def save_message(
        self,
        session_id: UUID,
        role: str,
        author: str,
        content: str,
        raw_json: dict[str, Any] | None = None,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO messages(session_id, role, author, content, raw_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(session_id),
                    role,
                    author,
                    content,
                    json.dumps(raw_json) if raw_json is not None else None,
                    _timestamp(),
                ),
            )
            return int(cursor.lastrowid)

    def save_agent_run(
        self,
        session_id: UUID,
        response: StructuredAgentResponse,
        phase: str,
    ) -> int:
        response_json = response.model_dump_json()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO agent_runs(session_id, agent, phase, response_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(session_id), response.agent.value, phase, response_json, _timestamp()),
            )
            run_id = int(cursor.lastrowid)
        for observation in response.observations:
            self.save_observation(session_id, response.agent, observation)
        for hypothesis in response.hypotheses:
            self.save_hypothesis(session_id, hypothesis)
        for evidence in response.evidence:
            self.save_evidence(session_id, evidence)
        logger.info(
            "Agent run stored session=%s agent=%s phase=%s",
            session_id,
            response.agent.value,
            phase,
        )
        return run_id

    def save_hypothesis(self, session_id: UUID, hypothesis: Hypothesis) -> None:
        data = hypothesis.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO hypotheses(
                    id, session_id, title, description, author_agent, status,
                    priority, confidence, evidence_for, evidence_against,
                    required_evidence, required_facts, current_evidence_level, validation_notes,
                    discriminating_test, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    status=excluded.status,
                    priority=excluded.priority,
                    confidence=excluded.confidence,
                    evidence_for=excluded.evidence_for,
                    evidence_against=excluded.evidence_against,
                    required_evidence=excluded.required_evidence,
                    required_facts=excluded.required_facts,
                    current_evidence_level=excluded.current_evidence_level,
                    validation_notes=excluded.validation_notes,
                    discriminating_test=excluded.discriminating_test,
                    updated_at=excluded.updated_at
                """,
                (
                    data["id"],
                    str(session_id),
                    hypothesis.title,
                    hypothesis.description,
                    hypothesis.author_agent.value,
                    hypothesis.status.value,
                    hypothesis.priority.value,
                    hypothesis.confidence,
                    json.dumps(hypothesis.evidence_for),
                    json.dumps(hypothesis.evidence_against),
                    json.dumps(hypothesis.required_evidence),
                    json.dumps([fact.value for fact in hypothesis.required_facts]),
                    hypothesis.current_evidence_level.value,
                    json.dumps(hypothesis.validation_notes),
                    (
                        hypothesis.discriminating_test.model_dump_json()
                        if hypothesis.discriminating_test
                        else None
                    ),
                    data["created_at"],
                    data["updated_at"],
                ),
            )
        logger.info("Hypothesis stored id=%s status=%s", hypothesis.id, hypothesis.status.value)

    def get_hypothesis(self, hypothesis_id: UUID) -> Hypothesis | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM hypotheses WHERE id = ?", (str(hypothesis_id),)
            ).fetchone()
        return self._row_to_hypothesis(row) if row else None

    def update_hypothesis(
        self,
        hypothesis_id: UUID,
        status: HypothesisStatus,
        *,
        confidence: float | None = None,
        evidence_for: list[str] | None = None,
        evidence_against: list[str] | None = None,
        required_evidence: list[str] | None = None,
        required_facts: list[Any] | None = None,
        current_evidence_level: Any | None = None,
        validation_notes: list[str] | None = None,
    ) -> Hypothesis:
        hypothesis = self.get_hypothesis(hypothesis_id)
        if hypothesis is None:
            raise KeyError(f"Unknown hypothesis: {hypothesis_id}")
        hypothesis.status = status
        hypothesis.updated_at = datetime.now(timezone.utc)
        if confidence is not None:
            hypothesis.confidence = confidence
        if evidence_for is not None:
            hypothesis.evidence_for = evidence_for
        if evidence_against is not None:
            hypothesis.evidence_against = evidence_against
        if required_evidence is not None:
            hypothesis.required_evidence = required_evidence
        if required_facts is not None:
            hypothesis.required_facts = required_facts
        if current_evidence_level is not None:
            hypothesis.current_evidence_level = current_evidence_level
        if validation_notes is not None:
            hypothesis.validation_notes = validation_notes
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE hypotheses
                SET status = ?, confidence = ?, evidence_for = ?, evidence_against = ?,
                    required_evidence = ?, current_evidence_level = ?, validation_notes = ?,
                    required_facts = ?, discriminating_test = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    hypothesis.status.value,
                    hypothesis.confidence,
                    json.dumps(hypothesis.evidence_for),
                    json.dumps(hypothesis.evidence_against),
                    json.dumps(hypothesis.required_evidence),
                    hypothesis.current_evidence_level.value,
                    json.dumps(hypothesis.validation_notes),
                    json.dumps([fact.value for fact in hypothesis.required_facts]),
                    (
                        hypothesis.discriminating_test.model_dump_json()
                        if hypothesis.discriminating_test
                        else None
                    ),
                    hypothesis.updated_at.isoformat(),
                    str(hypothesis_id),
                ),
            )
        logger.info("Hypothesis updated id=%s status=%s", hypothesis_id, status.value)
        return hypothesis

    def list_open_hypotheses(self, session_id: UUID, limit: int = 50) -> list[Hypothesis]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM hypotheses
                WHERE session_id = ? AND status NOT IN ('closed', 'refuted')
                ORDER BY updated_at DESC LIMIT ?
                """,
                (str(session_id), limit),
            ).fetchall()
        return [self._row_to_hypothesis(row) for row in rows]

    @staticmethod
    def _row_to_hypothesis(row: sqlite3.Row) -> Hypothesis:
        return Hypothesis(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            author_agent=row["author_agent"],
            status=row["status"],
            priority=row["priority"],
            confidence=row["confidence"],
            evidence_for=json.loads(row["evidence_for"]),
            evidence_against=json.loads(row["evidence_against"]),
            required_evidence=json.loads(row["required_evidence"]),
            required_facts=json.loads(row["required_facts"]),
            current_evidence_level=row["current_evidence_level"],
            validation_notes=json.loads(row["validation_notes"]),
            discriminating_test=(
                json.loads(row["discriminating_test"])
                if row["discriminating_test"]
                else None
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_observation(self, session_id: UUID, agent: AgentName, content: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO observations(session_id, agent, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(session_id), agent.value, content, _timestamp()),
            )
            return int(cursor.lastrowid)

    def save_decision(
        self,
        session_id: UUID,
        content: str,
        response: StructuredAgentResponse | None = None,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO decisions(session_id, content, response_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(session_id),
                    content,
                    response.model_dump_json() if response else None,
                    _timestamp(),
                ),
            )
            return int(cursor.lastrowid)

    def save_usage(
        self,
        session_id: UUID,
        agent: AgentName,
        usage: UsageDetails,
        run_id: UUID | None = None,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO usage(
                    session_id, run_id, agent, model, input_tokens, output_tokens,
                    total_tokens, estimated_cost, actual_cost_usd, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(session_id),
                    str(run_id) if run_id else None,
                    agent.value,
                    usage.model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.total_tokens,
                    usage.estimated_cost,
                    usage.actual_cost_usd,
                    _timestamp(),
                ),
            )
            return int(cursor.lastrowid)

    def save_uncertain_usage(
        self,
        *,
        reservation_id: UUID,
        session_id: UUID,
        run_id: UUID,
        agent: AgentName,
        model: str,
        reserved_input_tokens: int,
        reserved_output_tokens: int,
        reserved_cost_usd: float,
        reason: str,
    ) -> None:
        """Persist conservative accounting without calling it actual provider usage."""

        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO budget_uncertain_usage(
                    reservation_id, session_id, run_id, agent, model,
                    reserved_input_tokens, reserved_output_tokens,
                    reserved_total_tokens, reserved_cost_usd, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(reservation_id),
                    str(session_id),
                    str(run_id),
                    agent.value,
                    model,
                    reserved_input_tokens,
                    reserved_output_tokens,
                    reserved_input_tokens + reserved_output_tokens,
                    reserved_cost_usd,
                    reason,
                    _timestamp(),
                ),
            )

    def get_daily_token_usage(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COALESCE(SUM(total_tokens), 0)
                     FROM usage WHERE created_at >= ?) +
                    (SELECT COALESCE(SUM(reserved_total_tokens), 0)
                     FROM budget_uncertain_usage
                     WHERE created_at >= ? AND resolved_at IS NULL) AS total
                """,
                (
                    f"{today}T00:00:00+00:00",
                    f"{today}T00:00:00+00:00",
                ),
            ).fetchone()
        return int(row["total"])

    def get_usage_cost_since(self, since: datetime) -> float:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COALESCE(
                        SUM(COALESCE(actual_cost_usd, estimated_cost, 0)), 0
                     ) FROM usage WHERE created_at >= ?) +
                    (SELECT COALESCE(SUM(reserved_cost_usd), 0)
                     FROM budget_uncertain_usage
                     WHERE created_at >= ? AND resolved_at IS NULL) AS total
                """,
                (since.isoformat(), since.isoformat()),
            ).fetchone()
        return float(row["total"])

    def get_run_cost(self, run_id: UUID) -> float:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COALESCE(
                        SUM(COALESCE(actual_cost_usd, estimated_cost, 0)), 0
                     ) FROM usage WHERE run_id = ?) +
                    (SELECT COALESCE(SUM(reserved_cost_usd), 0)
                     FROM budget_uncertain_usage
                     WHERE run_id = ? AND resolved_at IS NULL) AS total
                """,
                (str(run_id), str(run_id)),
            ).fetchone()
        return float(row["total"])

    def save_evidence(self, session_id: UUID, evidence: EvidenceItem) -> None:
        data = evidence.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO evidence(
                    id, session_id, hypothesis_id, source, description, evidence_type,
                    supports, facts, satisfies_required_evidence, confidence,
                    proposed_level, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source=excluded.source,
                    description=excluded.description,
                    evidence_type=excluded.evidence_type,
                    supports=excluded.supports,
                    facts=excluded.facts,
                    satisfies_required_evidence=excluded.satisfies_required_evidence,
                    confidence=excluded.confidence,
                    proposed_level=excluded.proposed_level
                """,
                (
                    data["id"],
                    str(session_id),
                    data["hypothesis_id"],
                    evidence.source,
                    evidence.description,
                    evidence.evidence_type.value,
                    int(evidence.supports),
                    json.dumps([fact.value for fact in evidence.facts]),
                    json.dumps(evidence.satisfies_required_evidence),
                    evidence.confidence,
                    evidence.proposed_level.value,
                    data["created_at"],
                ),
            )

    def list_evidence(self, hypothesis_id: UUID) -> list[EvidenceItem]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM evidence WHERE hypothesis_id = ? ORDER BY created_at",
                (str(hypothesis_id),),
            ).fetchall()
        return [
            EvidenceItem(
                id=row["id"],
                hypothesis_id=row["hypothesis_id"],
                source=row["source"],
                description=row["description"],
                evidence_type=row["evidence_type"],
                supports=bool(row["supports"]),
                facts=json.loads(row["facts"]),
                satisfies_required_evidence=json.loads(
                    row["satisfies_required_evidence"]
                ),
                confidence=row["confidence"],
                proposed_level=row["proposed_level"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def save_evaluation(self, session_id: UUID, evaluation: EvaluationResult) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO evaluations(
                    id, session_id, hypothesis_id, evaluation_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(evaluation.id),
                    str(session_id),
                    str(evaluation.hypothesis_id),
                    evaluation.model_dump_json(),
                    evaluation.created_at.isoformat(),
                ),
            )

    def save_finding_candidate(self, session_id: UUID, finding: FindingCandidate) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO findings(
                    id, session_id, hypothesis_id, finding_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(finding.id),
                    str(session_id),
                    str(finding.hypothesis.id),
                    finding.model_dump_json(),
                    finding.created_at.isoformat(),
                ),
            )

    def save_lesson(self, lesson: Lesson) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO lessons(
                    id, agent, title, content, source_hypothesis_id, tags,
                    confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(lesson.id),
                    lesson.agent.value,
                    lesson.title,
                    lesson.content,
                    str(lesson.source_hypothesis_id) if lesson.source_hypothesis_id else None,
                    json.dumps(lesson.tags),
                    lesson.confidence,
                    lesson.created_at.isoformat(),
                ),
            )

    def list_lessons(
        self, agent: AgentName | None = None, limit: int = 50
    ) -> list[Lesson]:
        query = "SELECT * FROM lessons"
        params: list[Any] = []
        if agent is not None:
            query += " WHERE agent = ?"
            params.append(agent.value)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_lesson(row) for row in rows]

    def search_lessons(
        self,
        query: str,
        agent: AgentName | None = None,
        limit: int = 10,
    ) -> list[Lesson]:
        terms = [term.lower() for term in query.split() if len(term) >= 3]
        if not terms:
            return []
        clauses = ["LOWER(title || ' ' || content || ' ' || tags) LIKE ?" for _ in terms]
        params: list[Any] = [f"%{term}%" for term in terms]
        sql = "SELECT * FROM lessons WHERE (" + " OR ".join(clauses) + ")"
        if agent is not None:
            sql += " AND agent = ?"
            params.append(agent.value)
        sql += " ORDER BY confidence DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._row_to_lesson(row) for row in rows]

    @staticmethod
    def _row_to_lesson(row: sqlite3.Row) -> Lesson:
        return Lesson(
            id=row["id"],
            agent=row["agent"],
            title=row["title"],
            content=row["content"],
            source_hypothesis_id=row["source_hypothesis_id"],
            tags=json.loads(row["tags"]),
            confidence=row["confidence"],
            created_at=row["created_at"],
        )

    def get_session_summary(self, session_id: UUID) -> SessionSummary:
        with self._connect() as connection:
            hypothesis_counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN status NOT IN ('closed', 'refuted') THEN 1 ELSE 0 END) AS open_count,
                    SUM(CASE WHEN status IN ('closed', 'refuted') THEN 1 ELSE 0 END) AS closed_count
                FROM hypotheses WHERE session_id = ?
                """,
                (str(session_id),),
            ).fetchone()
            analyses = connection.execute(
                "SELECT COUNT(*) AS count FROM agent_runs WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
            usage = connection.execute(
                """
                SELECT COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens,
                       SUM(COALESCE(actual_cost_usd, estimated_cost)) AS estimated_cost
                FROM usage WHERE session_id = ?
                """,
                (str(session_id),),
            ).fetchone()
        return SessionSummary(
            session_id=session_id,
            open_hypotheses=int(hypothesis_counts["open_count"] or 0),
            closed_hypotheses=int(hypothesis_counts["closed_count"] or 0),
            analyses_stored=int(analyses["count"]),
            input_tokens=int(usage["input_tokens"]),
            output_tokens=int(usage["output_tokens"]),
            total_tokens=int(usage["total_tokens"]),
            estimated_cost=usage["estimated_cost"],
        )
