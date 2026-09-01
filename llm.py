from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from config import Settings
from schemas import AgentName, StructuredAgentResponse

logger = logging.getLogger(__name__)
JSON_WHITESPACE = frozenset(" \t\r\n")


@dataclass(frozen=True)
class ProviderErrorDiagnostics:
    status_code: int | None
    error_type: str | None
    error_code: str | None
    param: str | None
    message: str | None
    request_id: str | None


class LLMError(RuntimeError):
    """Base error exposed to the application layer."""


class LLMTransportError(LLMError):
    """Definite pre-response/API rejection with no provider token usage."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: ProviderErrorDiagnostics | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class LLMAmbiguousRequestError(LLMError):
    """The request outcome is unknown and must be accounted conservatively."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: ProviderErrorDiagnostics | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class LLMAmbiguousInterruption(asyncio.CancelledError):
    """Cancellation while a provider request may still have consumed tokens."""


@dataclass(frozen=True)
class UsageDetails:
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float | None = None
    actual_cost_usd: float | None = None


@dataclass(frozen=True)
class LLMResponseMetadata:
    response_id: str | None = None
    response_status: str | None = None
    incomplete_reason: str | None = None
    request_id: str | None = None
    model: str = ""
    output_character_length: int | None = None


@dataclass(frozen=True)
class StructuredValidationIssue:
    location: tuple[str | int, ...]
    error_type: str
    message: str


@dataclass(frozen=True)
class StructuredValidationDiagnostics:
    response_id: str | None
    provider_status: str | None
    schema_name: str
    output_character_length: int
    error_count: int
    issues: tuple[StructuredValidationIssue, ...]


@dataclass(frozen=True)
class IncompleteOutputDiagnostics:
    response_id: str | None
    schema_name: str
    output_character_length: int
    raw_decode_succeeded: bool
    decoded_end: int | None
    post_document_suffix_length: int | None
    post_document_suffix_only_json_whitespace: bool | None
    schema_validation_succeeded: bool | None
    semantically_complete: bool
    trailing_whitespace_start: int
    trailing_whitespace_length: int
    trailing_spaces: int
    trailing_tabs: int
    trailing_cr: int
    trailing_lf: int
    lexically_inside_string: bool
    unclosed_structure_depth: int | None


class LLMResponseError(LLMError):
    """A provider response was received but is not usable as structured output."""

    def __init__(
        self,
        message: str,
        *,
        usage: UsageDetails | None,
        metadata: LLMResponseMetadata,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.usage = usage
        self.metadata = metadata
        self.retryable = retryable


class InvalidLLMResponse(LLMResponseError):
    """Provider response completed but structured content is invalid."""

    def __init__(
        self,
        message: str,
        *,
        usage: UsageDetails | None,
        metadata: LLMResponseMetadata,
        retryable: bool,
        validation_diagnostics: StructuredValidationDiagnostics | None = None,
    ) -> None:
        super().__init__(
            message,
            usage=usage,
            metadata=metadata,
            retryable=retryable,
        )
        self.validation_diagnostics = validation_diagnostics


class IncompleteLLMResponse(LLMResponseError):
    """Provider explicitly marked the response incomplete."""

    def __init__(
        self,
        message: str,
        *,
        usage: UsageDetails | None,
        metadata: LLMResponseMetadata,
        retryable: bool,
        incomplete_diagnostics: IncompleteOutputDiagnostics | None = None,
    ) -> None:
        super().__init__(
            message,
            usage=usage,
            metadata=metadata,
            retryable=retryable,
        )
        self.incomplete_diagnostics = incomplete_diagnostics


class LLMRefusalError(LLMResponseError):
    """Provider returned a refusal or no usable structured output."""


@dataclass(frozen=True)
class LLMResult:
    response: StructuredAgentResponse
    usage: UsageDetails = UsageDetails()
    metadata: LLMResponseMetadata | None = None


@dataclass(frozen=True)
class StructuredLLMResult:
    output: BaseModel
    usage: UsageDetails = UsageDetails()
    metadata: LLMResponseMetadata | None = None


class LLMBackend(Protocol):
    async def ask_agent(
        self,
        agent: AgentName,
        system_prompt: str,
        user_input: str,
        context: str = "",
    ) -> LLMResult:
        ...

    async def ask_structured(
        self,
        agent: AgentName,
        system_prompt: str,
        user_input: str,
        response_model: type[BaseModel],
        context: str = "",
        max_output_tokens: int | None = None,
        verbosity: Literal["low", "medium", "high"] | None = None,
    ) -> StructuredLLMResult:
        ...


class LLMClient:
    """Replaceable adapter that validates Structured Outputs after raw accounting."""

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None) -> None:
        self.settings = settings
        if client is None and not settings.openai_api_key:
            raise LLMTransportError(
                "OPENAI_API_KEY must be configured before creating the LLM client"
            )
        self._client = client or AsyncOpenAI(api_key=settings.openai_api_key)

    def _model_for(self, agent: AgentName) -> str:
        model = (
            self.settings.coordinator_model
            if agent == AgentName.HORNED_RAT
            else self.settings.specialist_model
        )
        if not model:
            variable = (
                "COORDINATOR_MODEL"
                if agent == AgentName.HORNED_RAT
                else "SPECIALIST_MODEL"
            )
            raise LLMTransportError(
                f"{variable} must be configured before calling the LLM"
            )
        return model

    async def ask_agent(
        self,
        agent: AgentName,
        system_prompt: str,
        user_input: str,
        context: str = "",
    ) -> LLMResult:
        model = self._model_for(agent)
        validated, usage, metadata = await self._request_structured(
            agent=agent,
            model=model,
            system_prompt=system_prompt,
            user_input=user_input,
            context=context,
            response_model=StructuredAgentResponse,
            max_output_tokens=self.settings.max_output_tokens,
            verbosity=None,
        )
        return LLMResult(
            response=StructuredAgentResponse.model_validate(validated),
            usage=usage,
            metadata=metadata,
        )

    async def ask_structured(
        self,
        agent: AgentName,
        system_prompt: str,
        user_input: str,
        response_model: type[BaseModel],
        context: str = "",
        max_output_tokens: int | None = None,
        verbosity: Literal["low", "medium", "high"] | None = None,
    ) -> StructuredLLMResult:
        model = self._model_for(agent)
        validated, usage, metadata = await self._request_structured(
            agent=agent,
            model=model,
            system_prompt=system_prompt,
            user_input=user_input,
            context=context,
            response_model=response_model,
            max_output_tokens=(
                self.settings.max_output_tokens
                if max_output_tokens is None
                else max_output_tokens
            ),
            verbosity=verbosity,
        )
        return StructuredLLMResult(
            output=validated,
            usage=usage,
            metadata=metadata,
        )

    async def _request_structured(
        self,
        *,
        agent: AgentName,
        model: str,
        system_prompt: str,
        user_input: str,
        context: str,
        response_model: type[BaseModel],
        max_output_tokens: int,
        verbosity: Literal["low", "medium", "high"] | None,
    ) -> tuple[BaseModel, UsageDetails, LLMResponseMetadata]:
        prompt = user_input if not context else f"{user_input}\n\nCONTEXT:\n{context}"
        logger.info(
            "LLM call started agent=%s schema=%s",
            agent.value,
            response_model.__name__,
        )
        try:
            request: dict[str, Any] = {
                "model": model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "text_format": response_model,
                "max_output_tokens": max_output_tokens,
            }
            if verbosity is not None:
                # The Responses wire contract nests verbosity under `text`.
                # The SDK merges this with the format generated by `text_format`.
                request["text"] = {"verbosity": verbosity}
            raw_response = await self._client.responses.with_raw_response.parse(**request)
        except LLMAmbiguousInterruption:
            raise
        except asyncio.CancelledError as exc:
            raise LLMAmbiguousInterruption(
                "LLM request cancelled while provider outcome was unknown"
            ) from exc
        except LLMError:
            raise
        except APIStatusError as exc:
            diagnostics = self._provider_error_diagnostics(exc)
            status_code = diagnostics.status_code or 0
            message = self._provider_error_summary(diagnostics)
            logger.warning(
                "OpenAI API status error status=%s type=%s code=%s param=%s "
                "request_id=%s message=%s",
                diagnostics.status_code,
                diagnostics.error_type,
                diagnostics.error_code,
                diagnostics.param,
                diagnostics.request_id,
                diagnostics.message,
            )
            if 400 <= status_code < 500:
                raise LLMTransportError(message, diagnostics=diagnostics) from exc
            raise LLMAmbiguousRequestError(
                message,
                diagnostics=diagnostics,
            ) from exc
        except (APITimeoutError, APIConnectionError) as exc:
            raise LLMAmbiguousRequestError(
                "OpenAI request outcome is unknown after a connection failure"
            ) from exc
        except Exception as exc:
            raise LLMAmbiguousRequestError(
                "OpenAI request failed before a raw response became available"
            ) from exc

        request_id = self._request_id(raw_response)
        try:
            payload = self._raw_json(raw_response)
        except Exception as exc:
            metadata = LLMResponseMetadata(request_id=request_id, model=model)
            logger.warning("Provider response body invalid request_id=%s", request_id)
            raise InvalidLLMResponse(
                "Provider response body was not valid JSON",
                usage=None,
                metadata=metadata,
                retryable=True,
            ) from exc
        if not isinstance(payload, Mapping):
            metadata = LLMResponseMetadata(request_id=request_id, model=model)
            raise InvalidLLMResponse(
                "Provider response body was not a JSON object",
                usage=None,
                metadata=metadata,
                retryable=True,
            )

        output_text, refusal = self._extract_output(payload)
        metadata = self._metadata_from_payload(
            payload,
            request_id,
            model,
            output_character_length=len(output_text),
        )
        usage = self._usage_from_payload(payload, metadata.model)
        logger.info(
            "Provider response received id=%s status=%s reason=%s request_id=%s "
            "output_chars=%d reasoning_tokens=%d",
            metadata.response_id,
            metadata.response_status,
            metadata.incomplete_reason,
            metadata.request_id,
            metadata.output_character_length,
            usage.reasoning_tokens if usage is not None else 0,
        )

        if metadata.response_status == "incomplete":
            reason = metadata.incomplete_reason or "unknown"
            incomplete_diagnostics = (
                self._incomplete_output_diagnostics(
                    output_text,
                    response_model=response_model,
                    metadata=metadata,
                )
                if reason == "max_output_tokens"
                else None
            )
            if incomplete_diagnostics is not None:
                logger.warning(
                    "Incomplete structured output id=%s schema=%s raw_decode=%s "
                    "semantic_complete=%s decoded_end=%s output_chars=%d "
                    "trailing_whitespace_start=%d trailing_whitespace_chars=%d "
                    "unclosed_depth=%s inside_string=%s",
                    incomplete_diagnostics.response_id,
                    incomplete_diagnostics.schema_name,
                    incomplete_diagnostics.raw_decode_succeeded,
                    incomplete_diagnostics.semantically_complete,
                    incomplete_diagnostics.decoded_end,
                    incomplete_diagnostics.output_character_length,
                    incomplete_diagnostics.trailing_whitespace_start,
                    incomplete_diagnostics.trailing_whitespace_length,
                    incomplete_diagnostics.unclosed_structure_depth,
                    incomplete_diagnostics.lexically_inside_string,
                )
            raise IncompleteLLMResponse(
                f"Provider response incomplete: {reason}",
                usage=usage,
                metadata=metadata,
                retryable=reason == "max_output_tokens",
                incomplete_diagnostics=incomplete_diagnostics,
            )
        if metadata.response_status in {"failed", "cancelled"}:
            raise LLMResponseError(
                f"Provider response status is {metadata.response_status}",
                usage=usage,
                metadata=metadata,
                retryable=metadata.response_status == "failed",
            )
        if usage is None:
            raise LLMResponseError(
                "Provider response did not include usage accounting",
                usage=None,
                metadata=metadata,
                retryable=True,
            )

        if refusal and not output_text:
            raise LLMRefusalError(
                "Provider refused to produce structured output",
                usage=usage,
                metadata=metadata,
                retryable=False,
            )
        if not output_text:
            raise LLMRefusalError(
                "Provider response contained no usable structured output",
                usage=usage,
                metadata=metadata,
                retryable=False,
            )

        try:
            validated = response_model.model_validate_json(output_text)
        except (ValidationError, ValueError, TypeError) as exc:
            diagnostics = self._validation_diagnostics(
                exc,
                metadata=metadata,
                schema_name=response_model.__name__,
                output_character_length=len(output_text),
            )
            logger.warning(
                "Structured output invalid id=%s status=%s schema=%s "
                "validation_errors=%d output_chars=%d issues=%s",
                metadata.response_id,
                metadata.response_status,
                response_model.__name__,
                diagnostics.error_count,
                diagnostics.output_character_length,
                [
                    {
                        "loc": list(issue.location),
                        "type": issue.error_type,
                        "message": issue.message,
                    }
                    for issue in diagnostics.issues
                ],
            )
            raise InvalidLLMResponse(
                f"Provider output did not match {response_model.__name__}",
                usage=usage,
                metadata=metadata,
                retryable=True,
                validation_diagnostics=diagnostics,
            ) from exc

        logger.info(
            "LLM JSON validated agent=%s schema=%s response_id=%s total_tokens=%d",
            agent.value,
            response_model.__name__,
            metadata.response_id,
            usage.total_tokens,
        )
        return validated, usage, metadata

    @classmethod
    def _incomplete_output_diagnostics(
        cls,
        output_text: str,
        *,
        response_model: type[BaseModel],
        metadata: LLMResponseMetadata,
    ) -> IncompleteOutputDiagnostics:
        trailing_start = len(output_text)
        while (
            trailing_start > 0
            and output_text[trailing_start - 1] in JSON_WHITESPACE
        ):
            trailing_start -= 1
        trailing = output_text[trailing_start:]

        start = 0
        while start < len(output_text) and output_text[start] in JSON_WHITESPACE:
            start += 1
        decoded_end: int | None = None
        post_suffix_length: int | None = None
        post_suffix_only_whitespace: bool | None = None
        schema_valid: bool | None = None
        try:
            decoded, decoded_end = json.JSONDecoder().raw_decode(
                output_text,
                idx=start,
            )
        except json.JSONDecodeError:
            raw_decode_succeeded = False
        else:
            raw_decode_succeeded = True
            post_suffix = output_text[decoded_end:]
            post_suffix_length = len(post_suffix)
            post_suffix_only_whitespace = all(
                character in JSON_WHITESPACE for character in post_suffix
            )
            try:
                response_model.model_validate(decoded)
            except (ValidationError, ValueError, TypeError):
                schema_valid = False
            else:
                schema_valid = True

        inside_string, unclosed_depth = cls._json_lexical_state(
            output_text[:trailing_start]
        )
        return IncompleteOutputDiagnostics(
            response_id=metadata.response_id,
            schema_name=response_model.__name__,
            output_character_length=len(output_text),
            raw_decode_succeeded=raw_decode_succeeded,
            decoded_end=decoded_end,
            post_document_suffix_length=post_suffix_length,
            post_document_suffix_only_json_whitespace=post_suffix_only_whitespace,
            schema_validation_succeeded=schema_valid,
            semantically_complete=(
                raw_decode_succeeded
                and post_suffix_only_whitespace is True
                and schema_valid is True
            ),
            trailing_whitespace_start=trailing_start,
            trailing_whitespace_length=len(trailing),
            trailing_spaces=trailing.count(" "),
            trailing_tabs=trailing.count("\t"),
            trailing_cr=trailing.count("\r"),
            trailing_lf=trailing.count("\n"),
            lexically_inside_string=inside_string,
            unclosed_structure_depth=unclosed_depth,
        )

    @staticmethod
    def _json_lexical_state(value: str) -> tuple[bool, int | None]:
        stack: list[str] = []
        expected_opener = {"}": "{", "]": "["}
        in_string = False
        escaped = False
        for character in value:
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character in "{[":
                stack.append(character)
            elif character in expected_opener:
                if not stack or stack[-1] != expected_opener[character]:
                    return in_string, None
                stack.pop()
        return in_string, len(stack)

    @classmethod
    def _validation_diagnostics(
        cls,
        error: ValidationError | ValueError | TypeError,
        *,
        metadata: LLMResponseMetadata,
        schema_name: str,
        output_character_length: int,
    ) -> StructuredValidationDiagnostics:
        if isinstance(error, ValidationError):
            raw_issues = error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
            issues = tuple(
                StructuredValidationIssue(
                    location=tuple(
                        part if isinstance(part, int) else str(part)[:80]
                        for part in issue.get("loc", ())
                    ),
                    error_type=str(issue.get("type", "validation_error"))[:80],
                    message=cls._concise_validation_message(issue.get("msg")),
                )
                for issue in raw_issues
            )
        else:
            issues = (
                StructuredValidationIssue(
                    location=(),
                    error_type=type(error).__name__,
                    message="Structured validation failed",
                ),
            )
        return StructuredValidationDiagnostics(
            response_id=metadata.response_id,
            provider_status=metadata.response_status,
            schema_name=schema_name,
            output_character_length=output_character_length,
            error_count=len(issues),
            issues=issues,
        )

    @staticmethod
    def _concise_validation_message(message: object) -> str:
        concise = " ".join(str(message or "Validation failed").split())
        return concise[:240]

    @classmethod
    def _provider_error_diagnostics(
        cls,
        error: APIStatusError,
    ) -> ProviderErrorDiagnostics:
        status = int(getattr(error, "status_code", 0) or 0) or None
        error_type = cls._bounded_provider_field(getattr(error, "type", None))
        error_code = cls._bounded_provider_field(getattr(error, "code", None))
        param = cls._bounded_provider_field(getattr(error, "param", None), limit=160)
        request_id = cls._bounded_provider_field(
            getattr(error, "request_id", None),
            limit=160,
        )

        provider_message: object | None = None
        body = getattr(error, "body", None)
        if isinstance(body, Mapping):
            provider_message = body.get("message")
        message = cls._safe_provider_message(
            provider_message,
            error_code=error_code,
            param=param,
        )
        return ProviderErrorDiagnostics(
            status_code=status,
            error_type=error_type,
            error_code=error_code,
            param=param,
            message=message,
            request_id=request_id,
        )

    @staticmethod
    def _bounded_provider_field(value: object, *, limit: int = 80) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = " ".join(value.split())
        if not normalized:
            return None
        return normalized[:limit]

    @staticmethod
    def _safe_provider_message(
        value: object,
        *,
        error_code: str | None,
        param: str | None,
    ) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = " ".join(value.split())
        if not normalized:
            return None

        # Parameter errors have a small fixed shape and cannot contain prompts.
        # Schema diagnostics are also request-structure-only. Other provider
        # messages may echo input, so omit them rather than risk source logs.
        if error_code in {"unknown_parameter", "unsupported_parameter"} and re.fullmatch(
            r"(?:Unknown|Unsupported) parameter: '[A-Za-z0-9_.\[\]-]+'"
            r"(?: is not supported with this model)?\.?",
            normalized,
        ):
            return normalized
        if error_code == "invalid_json_schema" and param in {
            "response_format",
            "text.format",
            "text.format.schema",
        }:
            return normalized[:500]
        return None

    @staticmethod
    def _provider_error_summary(diagnostics: ProviderErrorDiagnostics) -> str:
        status = diagnostics.status_code or "unknown"
        details = []
        if diagnostics.error_code:
            details.append(f"code={diagnostics.error_code}")
        if diagnostics.param:
            details.append(f"param={diagnostics.param}")
        suffix = f" ({', '.join(details)})" if details else ""
        message = f"OpenAI API rejected the request with HTTP {status}{suffix}"
        if diagnostics.message:
            message = f"{message}: {diagnostics.message}"
        return message

    @staticmethod
    def _raw_json(raw_response: object) -> Any:
        json_method = getattr(raw_response, "json", None)
        if callable(json_method):
            return json_method()
        http_response = getattr(raw_response, "http_response", None)
        if http_response is None:
            raise TypeError("Raw SDK response exposes no JSON reader")
        return http_response.json()

    @staticmethod
    def _request_id(raw_response: object) -> str | None:
        request_id = getattr(raw_response, "request_id", None)
        if request_id:
            return str(request_id)
        headers = getattr(raw_response, "headers", None)
        if headers is not None:
            return headers.get("x-request-id")
        return None

    @staticmethod
    def _metadata_from_payload(
        payload: Mapping[str, Any],
        request_id: str | None,
        requested_model: str,
        *,
        output_character_length: int,
    ) -> LLMResponseMetadata:
        incomplete = payload.get("incomplete_details")
        reason = incomplete.get("reason") if isinstance(incomplete, Mapping) else None
        return LLMResponseMetadata(
            response_id=str(payload["id"]) if payload.get("id") else None,
            response_status=str(payload["status"]) if payload.get("status") else None,
            incomplete_reason=str(reason) if reason else None,
            request_id=request_id,
            model=str(payload.get("model") or requested_model),
            output_character_length=output_character_length,
        )

    @staticmethod
    def _usage_from_payload(
        payload: Mapping[str, Any], model: str
    ) -> UsageDetails | None:
        usage = payload.get("usage")
        if not isinstance(usage, Mapping):
            return None
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        output_details = usage.get("output_tokens_details")
        reasoning_tokens = (
            int(output_details.get("reasoning_tokens", 0) or 0)
            if isinstance(output_details, Mapping)
            else 0
        )
        return UsageDetails(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=int(
                usage.get("total_tokens", input_tokens + output_tokens) or 0
            ),
        )

    @staticmethod
    def _extract_output(payload: Mapping[str, Any]) -> tuple[str, str | None]:
        text_parts: list[str] = []
        refusal: str | None = None
        output = payload.get("output")
        if not isinstance(output, list):
            return "", None
        for item in output:
            if not isinstance(item, Mapping) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    text_parts.append(str(part["text"]))
                elif part.get("type") == "refusal" and isinstance(part.get("refusal"), str):
                    refusal = str(part["refusal"])
        return "".join(text_parts), refusal
