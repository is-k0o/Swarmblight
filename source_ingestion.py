from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import Field

from schemas import (
    AgentName,
    KnowledgeSchema,
    KnowledgeSourceType,
    KnowledgeTopic,
    utc_now,
)


HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*$")
FRONTMATTER_FIELD_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$")
LINK_ONLY_PATTERN = re.compile(
    r"^(?:(?:[-*+]\s+|\d+[.)]\s+))?\[[^\]]+\]\([^)]+\)\s*$"
)
SUPPORTED_FRONTMATTER_FIELDS = {
    "agent",
    "topic",
    "subtopic",
    "source_type",
    "source_title",
    "source_reference",
    "corpus",
}
NAVIGATION_ONLY_HEADINGS = {"read more", "further reading", "related links"}
SUPPORTED_SOURCE_SUFFIXES = {".md", ".markdown", ".txt"}


class SourceChunkStatus(str, Enum):
    PENDING = "pending"
    RETRYABLE = "retryable"
    PROCESSED = "processed"
    FAILED = "failed"


class SourceDocument(KnowledgeSchema):
    id: UUID
    title: str = Field(min_length=1, max_length=300)
    source_type: KnowledgeSourceType
    source_reference: str = Field(min_length=1, max_length=1000)
    source_path: str | None = Field(default=None, max_length=1000)
    corpus: str | None = Field(default=None, max_length=200)
    subtopic: str | None = Field(default=None, max_length=200)
    content: str = Field(min_length=1)
    agent: AgentName = AgentName.IKIT
    topic: KnowledgeTopic
    ingested_at: datetime = Field(default_factory=utc_now)


class SourceChunk(KnowledgeSchema):
    id: UUID
    document_id: UUID
    heading: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    source_reference: str = Field(min_length=1, max_length=1000)
    status: SourceChunkStatus = SourceChunkStatus.PENDING
    error: str | None = None


class SourceIngestor:
    """Local-file-only ingestion with deterministic, provenance-preserving chunks."""

    def __init__(self, max_chunk_chars: int) -> None:
        if max_chunk_chars < 200:
            raise ValueError("max_chunk_chars must be at least 200")
        self.max_chunk_chars = max_chunk_chars

    def ingest_file(
        self,
        path: str | Path,
        *,
        agent: AgentName,
        source_type: KnowledgeSourceType,
        topic: KnowledgeTopic,
        title: str | None = None,
    ) -> tuple[SourceDocument, list[SourceChunk]]:
        source_path = Path(path)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        if source_path.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            raise ValueError("V0.6 accepts only local Markdown and text files")
        raw_content = (
            source_path.read_text(encoding="utf-8")
            .lstrip("\ufeff")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
        if not raw_content.strip():
            raise ValueError("Source document is empty")
        metadata, content = self._extract_frontmatter(
            raw_content,
            parse=source_path.suffix.lower() in {".md", ".markdown"},
        )
        self._validate_routing_metadata(
            metadata,
            agent=agent,
            source_type=source_type,
            topic=topic,
        )
        if agent != AgentName.IKIT:
            raise ValueError("V0.6 knowledge ingestion is restricted to Ikit")
        resolved_path = str(source_path.resolve())
        source_reference = metadata.get("source_reference", resolved_path)
        digest = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        document_id = uuid5(
            NAMESPACE_URL,
            f"swarmblight-source:{resolved_path}:{digest}",
        )
        document = SourceDocument(
            id=document_id,
            title=(title or metadata.get("source_title") or source_path.stem).strip(),
            source_type=source_type,
            source_reference=source_reference,
            source_path=resolved_path,
            corpus=metadata.get("corpus"),
            subtopic=metadata.get("subtopic"),
            content=content,
            agent=agent,
            topic=topic,
        )
        return document, self.chunk(document)

    def chunk(self, document: SourceDocument) -> list[SourceChunk]:
        sections = self._sections(document)
        chunks: list[SourceChunk] = []
        sequence = 0
        for heading, section_content in sections:
            if self._is_navigation_only_section(heading, section_content):
                continue
            for content in self._split_content(section_content):
                chunk_id = uuid5(
                    document.id,
                    f"{sequence}:{heading}:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
                )
                chunks.append(
                    SourceChunk(
                        id=chunk_id,
                        document_id=document.id,
                        heading=heading,
                        content=content,
                        sequence=sequence,
                        source_reference=document.source_reference,
                    )
                )
                sequence += 1
        if not chunks:
            raise ValueError("Source document produced no non-empty chunks")
        return chunks

    @classmethod
    def _extract_frontmatter(
        cls,
        content: str,
        *,
        parse: bool,
    ) -> tuple[dict[str, str], str]:
        lines = content.splitlines()
        if not parse or not lines or lines[0].strip() != "---":
            return {}, content
        try:
            closing_index = next(
                index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
            )
        except StopIteration as exc:
            raise ValueError("Malformed YAML frontmatter: missing closing '---'") from exc

        metadata: dict[str, str] = {}
        for line_number, line in enumerate(lines[1:closing_index], start=2):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = FRONTMATTER_FIELD_PATTERN.fullmatch(line)
            if match is None:
                raise ValueError(
                    f"Malformed YAML frontmatter line {line_number}: expected key: value"
                )
            key = match.group(1).replace("-", "_").casefold()
            if key not in SUPPORTED_FRONTMATTER_FIELDS:
                raise ValueError(f"Unsupported YAML frontmatter field: {key}")
            if key in metadata:
                raise ValueError(f"Contradictory YAML frontmatter: duplicate field {key}")
            metadata[key] = cls._parse_frontmatter_value(
                match.group(2),
                key=key,
                line_number=line_number,
            )

        body = "\n".join(lines[closing_index + 1 :]).lstrip("\n")
        if not body.strip():
            raise ValueError("Source document body is empty after YAML frontmatter")
        return metadata, body

    @staticmethod
    def _parse_frontmatter_value(value: str, *, key: str, line_number: int) -> str:
        if not value:
            raise ValueError(
                f"Malformed YAML frontmatter line {line_number}: {key} has no value"
            )
        if value.startswith('"'):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Malformed YAML frontmatter line {line_number}: invalid quoted value"
                ) from exc
            if not isinstance(parsed, str):
                raise ValueError(f"YAML frontmatter field {key} must be a string")
            result = parsed
        elif value.startswith("'"):
            if len(value) < 2 or not value.endswith("'"):
                raise ValueError(
                    f"Malformed YAML frontmatter line {line_number}: invalid quoted value"
                )
            result = value[1:-1].replace("''", "'")
        else:
            if value[0] in "[{&*!|>":
                raise ValueError(
                    f"Unsupported YAML frontmatter value for {key}: scalar strings only"
                )
            result = value
        if not result.strip():
            raise ValueError(f"YAML frontmatter field {key} must not be blank")
        return result.strip()

    @staticmethod
    def _validate_routing_metadata(
        metadata: dict[str, str],
        *,
        agent: AgentName,
        source_type: KnowledgeSourceType,
        topic: KnowledgeTopic,
    ) -> None:
        explicit_values = {
            "agent": agent.value,
            "source_type": source_type.value,
            "topic": topic.value,
        }
        enum_types = {
            "agent": AgentName,
            "source_type": KnowledgeSourceType,
            "topic": KnowledgeTopic,
        }
        for field, explicit_value in explicit_values.items():
            frontmatter_value = metadata.get(field)
            if frontmatter_value is None:
                continue
            try:
                normalized_value = enum_types[field](frontmatter_value).value
            except ValueError as exc:
                raise ValueError(
                    f"Invalid YAML frontmatter {field}: {frontmatter_value}"
                ) from exc
            if normalized_value != explicit_value:
                raise ValueError(
                    f"YAML frontmatter {field}={normalized_value!r} conflicts with "
                    f"explicit {field}={explicit_value!r}"
                )

    @staticmethod
    def _is_navigation_only_section(heading: str, content: str) -> bool:
        normalized_heading = heading.strip().casefold().rstrip(":")
        if normalized_heading not in NAVIGATION_ONLY_HEADINGS:
            return False
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        return bool(lines) and all(LINK_ONLY_PATTERN.fullmatch(line) for line in lines)

    @staticmethod
    def _sections(document: SourceDocument) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        heading = document.title
        lines: list[str] = []
        for line in document.content.splitlines():
            match = HEADING_PATTERN.match(line)
            if match:
                body = "\n".join(lines).strip()
                if body:
                    sections.append((heading, body))
                heading = match.group(1).strip()
                lines = []
            else:
                lines.append(line)
        body = "\n".join(lines).strip()
        if body:
            sections.append((heading, body))
        return sections

    def _split_content(self, content: str) -> list[str]:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", content) if item.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            parts = self._split_long_text(paragraph)
            for part in parts:
                candidate = part if not current else f"{current}\n\n{part}"
                if len(candidate) <= self.max_chunk_chars:
                    current = candidate
                else:
                    chunks.append(current)
                    current = part
        if current:
            chunks.append(current)
        return chunks

    def _split_long_text(self, text: str) -> list[str]:
        remaining = text.strip()
        parts: list[str] = []
        while len(remaining) > self.max_chunk_chars:
            split_at = remaining.rfind(" ", 0, self.max_chunk_chars + 1)
            if split_at < self.max_chunk_chars // 2:
                split_at = self.max_chunk_chars
            parts.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        if remaining:
            parts.append(remaining)
        return parts
