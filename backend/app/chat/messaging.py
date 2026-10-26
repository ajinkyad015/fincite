from typing import Dict, Any, Optional, List, Set
import asyncio
import logging
from uuid import uuid4
from anyio import BrokenResourceError, ClosedResourceError
from anyio.streams.memory import MemoryObjectSendStream

from llama_index.core.callbacks.base import BaseCallbackHandler
from llama_index.core.callbacks.schema import CBEventType, EventPayload
from llama_index.core.query_engine.sub_question_query_engine import SubQuestionAnswerPair
from llama_index.core.chat_engine.types import StreamingAgentChatResponse
from pydantic import BaseModel

from app import schema
from app.schema import SubProcessMetadataKeysEnum, SubProcessMetadataMap
from app.models.db import MessageSubProcessSourceEnum
from app.chat.engine import get_chat_engine

logger = logging.getLogger(__name__)


class StreamedMessage(BaseModel):
    content: str


class StreamedMessageSubProcess(BaseModel):
    source: MessageSubProcessSourceEnum
    has_ended: bool
    event_id: str
    metadata_map: Optional[SubProcessMetadataMap] = None


class ChatCallbackHandler(BaseCallbackHandler):
    """
    Turns LlamaIndex callback events into `StreamedMessageSubProcess` items on an
    anyio memory stream — the observability bus behind the research trail.

    The stream is owned by the SSE endpoint, never by this handler: it only
    sends, and treats a closed stream as "the client went away".
    """

    def __init__(
        self,
        send_chan: MemoryObjectSendStream,
    ):
        """Initialize the base callback handler."""
        ignored_events = [CBEventType.CHUNKING, CBEventType.NODE_PARSING]
        super().__init__(ignored_events, ignored_events)
        self._send_chan = send_chan
        # LlamaIndex fires callbacks synchronously, so sending has to be
        # scheduled. Track the tasks so the producer can drain them before the
        # channel closes (otherwise trailing trail events get dropped).
        self._tasks: Set["asyncio.Task[None]"] = set()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for in-flight callback sends to finish."""
        while self._tasks:
            pending = list(self._tasks)
            await asyncio.gather(*pending, return_exceptions=True)

    def on_event_start(
        self,
        event_type: CBEventType,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> str:
        """Create the MessageSubProcess row for the event that started."""
        self._spawn(
            self.async_on_event(
                event_type, payload, event_id, is_start_event=True, **kwargs
            )
        )

    def on_event_end(
        self,
        event_type: CBEventType,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        """Create the MessageSubProcess row for the event that completed."""
        self._spawn(
            self.async_on_event(
                event_type, payload, event_id, is_start_event=False, **kwargs
            )
        )

    def get_metadata_from_event(
        self,
        event_type: CBEventType,
        payload: Optional[Dict[str, Any]] = None,
        is_start_event: bool = False,
    ) -> SubProcessMetadataMap:
        metadata_map = {}

        if (
            event_type == CBEventType.SUB_QUESTION
            and EventPayload.SUB_QUESTION in payload
        ):
            sub_q: SubQuestionAnswerPair = payload[EventPayload.SUB_QUESTION]
            metadata_map[
                SubProcessMetadataKeysEnum.SUB_QUESTION.value
            ] = schema.QuestionAnswerPair.from_sub_question_answer_pair(sub_q).dict()
        return metadata_map

    async def async_on_event(
        self,
        event_type: CBEventType,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        is_start_event: bool = False,
        **kwargs: Any,
    ) -> None:
        metadata_map = self.get_metadata_from_event(
            event_type, payload=payload, is_start_event=is_start_event
        )
        metadata_map = metadata_map or None
        source = MessageSubProcessSourceEnum[event_type.name]
        try:
            await self._send_chan.send(
                StreamedMessageSubProcess(
                    source=source,
                    metadata_map=metadata_map,
                    event_id=event_id,
                    has_ended=not is_start_event,
                )
            )
        except (ClosedResourceError, BrokenResourceError):
            logger.debug(
                "Client disconnected before sub-process event %s could be sent", source
            )

    def start_trace(self, trace_id: Optional[str] = None) -> None:
        """No-op."""

    def end_trace(
        self,
        trace_id: Optional[str] = None,
        trace_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """No-op."""


async def handle_chat_message(
    conversation: schema.Conversation,
    user_message: schema.UserMessageCreate,
    send_chan: MemoryObjectSendStream,
    callback_handler: Optional[ChatCallbackHandler] = None,
) -> None:
    """
    Run one turn: build the engine, stream the answer onto `send_chan`.

    The channel is **owned by the caller** — this function never enters
    ``async with send_chan`` and never inspects private state, so the SSE
    endpoint can close it exactly once after the producer finishes. A client
    disconnect surfaces as `ClosedResourceError`, which ends the stream quietly.
    """
    handler = callback_handler or ChatCallbackHandler(send_chan)
    chat_engine = await get_chat_engine(handler, conversation)
    await send_chan.send(
        StreamedMessageSubProcess(
            event_id=str(uuid4()),
            has_ended=True,
            source=MessageSubProcessSourceEnum.CONSTRUCTED_QUERY_ENGINE,
        )
    )
    logger.debug("Engine received")
    templated_message = f"""
Remember - if I have asked a relevant financial question, use your tools.

{user_message.content}
    """.strip()

    try:
        streaming_chat_response: StreamingAgentChatResponse = (
            await chat_engine.astream_chat(templated_message)
        )
        response_str = ""
        async for text in streaming_chat_response.async_response_gen():
            response_str += text
            await send_chan.send(StreamedMessage(content=response_str))

        if response_str.strip() == "":
            await send_chan.send(
                StreamedMessage(
                    content="Sorry, I either wasn't able to understand your question or I don't have an answer for it."
                )
            )
    except (ClosedResourceError, BrokenResourceError):
        logger.info("Client disconnected mid-answer; stopping generation.")
        return


# ---------------------------------------------------------------------------
# Research-trail presentation helpers
# ---------------------------------------------------------------------------

#: Default labels for the LlamaIndex events that surface in the trail.
_SUB_PROCESS_LABELS: Dict[str, str] = {
    "CONSTRUCTED_QUERY_ENGINE": "Building the query engine",
    "SUB_QUESTION": "Researching a sub-question",
    "SUB_QUESTIONS": "Planning sub-questions",
    "RETRIEVE": "Retrieving passages",
    "SYNTHESIZE": "Synthesising the answer",
    "LLM": "Reasoning over the evidence",
    "QUERY": "Running a query",
    "TREE": "Walking the index",
    "EMBEDDING": "Embedding",
    "AGENT_STEP": "Agent step",
    "TEMPLATING": "Preparing the prompt",
    "FUNCTION_CALL": "Calling a tool",
    "RERANKING": "Re-ranking passages",
    "EXCEPTION": "Something went wrong",
}


def describe_sub_process(
    source: MessageSubProcessSourceEnum,
    metadata_map: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Human label for a trail step.

    Preference order: the sub-question text (the most informative thing we have),
    then a per-event default, then a de-slugged event name. Never raises — a
    label is presentation, not control flow.
    """
    source_name = getattr(source, "name", str(source))
    sub_question = (metadata_map or {}).get(SubProcessMetadataKeysEnum.SUB_QUESTION.value)
    if isinstance(sub_question, dict):
        question = (sub_question.get("question") or "").strip()
        if question:
            compact = " ".join(question.split())
            if len(compact) > 140:
                compact = compact[:137] + "…"
            return compact
    label = _SUB_PROCESS_LABELS.get(source_name)
    if label:
        return label
    return source_name.replace("_", " ").capitalize()


def citations_from_sub_processes(
    sub_processes: List[schema.MessageSubProcess],
) -> List[schema.Citation]:
    """
    Collect every citation the research trail produced, in trail order.

    The SUB_QUESTION events carry `QuestionAnswerPair` metadata
    (question / answer / citations); that is where page-level evidence lives.
    """
    citations: List[schema.Citation] = []
    for sub_process in sub_processes:
        metadata = sub_process.metadata_map or {}
        pair = metadata.get(SubProcessMetadataKeysEnum.SUB_QUESTION.value)
        if not isinstance(pair, dict):
            continue
        for raw in pair.get("citations") or []:
            try:
                citations.append(schema.Citation.model_validate(raw))
            except Exception:  # noqa: BLE001 — a malformed citation must not kill the answer
                logger.warning("Skipping malformed citation: %s", raw)
    return citations
