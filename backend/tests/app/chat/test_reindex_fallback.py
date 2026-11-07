"""Chat-path re-index fallback: offloaded off the event loop, and serialised.

The fallback in build_doc_id_to_index_map downloads + parses + embeds a PDF
when a document has no usable index. Three properties matter:

* it must not run on the event loop (blocking work starves every other
  request the process is serving, including SSE streams),
* concurrent questions must not fan out into unbounded parallel embedding
  (memory + provider rate limits) — a process-local lock serialises it, and
* a cancelled caller must NOT release the lock while its worker thread is
  still running, or repeated cancelled requests stack parallel jobs anyway.
"""
import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from app.chat import engine as chat_engine


class _FakeIndex:
    def set_index_id(self, _index_id) -> None:
        pass


class _FakeStorageContext:
    @staticmethod
    def from_defaults(**_kwargs):
        return object()


class _ForceFallbackVectorStoreIndex:
    """from_vector_store always misses, so the fallback path runs."""

    @staticmethod
    def from_vector_store(**_kwargs):
        raise RuntimeError("no index for this document")


@pytest.fixture
def fallback_patches(monkeypatch):
    monkeypatch.setattr(
        chat_engine, "VectorStoreIndex", _ForceFallbackVectorStoreIndex
    )
    monkeypatch.setattr(chat_engine, "StorageContext", _FakeStorageContext)
    monkeypatch.setattr(chat_engine, "_REINDEX_LOCK", None)  # fresh lock

    async def fake_vector_store():
        return object()

    monkeypatch.setattr(chat_engine, "get_vector_store_singleton", fake_vector_store)
    return monkeypatch


@pytest.mark.asyncio
async def test_fallback_runs_off_event_loop_and_serialised(fallback_patches):
    loop_thread = threading.get_ident()
    used_threads = set()
    in_flight = 0
    max_in_flight = 0

    def fake_fetch_and_index(*_args, **_kwargs):
        nonlocal in_flight, max_in_flight
        used_threads.add(threading.get_ident())
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)  # stand-in for download + parse + embed work
        in_flight -= 1
        return _FakeIndex()

    fallback_patches.setattr(chat_engine, "_fetch_and_index", fake_fetch_and_index)

    doc = SimpleNamespace(id="d1")
    results = await asyncio.gather(
        chat_engine.build_doc_id_to_index_map(None, [doc]),
        chat_engine.build_doc_id_to_index_map(None, [doc]),
    )

    assert all("d1" in result for result in results)
    # Offloaded: the blocking work ran in worker threads, not the loop thread.
    assert used_threads
    assert loop_thread not in used_threads
    # Serialised: two concurrent fallbacks never embedded at the same time.
    assert max_in_flight == 1


@pytest.mark.asyncio
async def test_fallback_errors_propagate_and_release_lock(fallback_patches):
    """A failed re-index must surface to the caller and not wedge the lock."""

    def fake_fetch_and_index(*_args, **_kwargs):
        raise ValueError("embedding endpoint blew up")

    fallback_patches.setattr(chat_engine, "_fetch_and_index", fake_fetch_and_index)

    doc = SimpleNamespace(id="d1")
    with pytest.raises(ValueError, match="embedding endpoint blew up"):
        await chat_engine.build_doc_id_to_index_map(None, [doc])

    # The lock was released: a second attempt enters the fallback again
    # instead of hanging on a poisoned lock.
    with pytest.raises(ValueError):
        await asyncio.wait_for(
            chat_engine.build_doc_id_to_index_map(None, [doc]), timeout=2
        )


@pytest.mark.asyncio
async def test_cancelled_caller_holds_lock_until_thread_finishes(fallback_patches):
    """Cancellation must not free the lock while the thread is still running.

    Regression: `async with lock: await to_thread(...)` releases the lock on
    CancelledError while the thread keeps working, so each cancelled request
    would free the next one to start a parallel embedding job.
    """
    first_started = threading.Event()
    first_may_finish = threading.Event()
    second_entered = threading.Event()
    calls = 0
    in_flight = 0
    max_in_flight = 0

    def fake_fetch_and_index(*_args, **_kwargs):
        nonlocal calls, in_flight, max_in_flight
        calls += 1
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        if calls == 1:
            first_started.set()
            first_may_finish.wait(5)
        else:
            second_entered.set()
        in_flight -= 1
        return _FakeIndex()

    fallback_patches.setattr(chat_engine, "_fetch_and_index", fake_fetch_and_index)

    doc = SimpleNamespace(id="d1")
    first = asyncio.create_task(chat_engine.build_doc_id_to_index_map(None, [doc]))
    await asyncio.to_thread(first_started.wait, 5)

    # Cancel the caller mid-re-index. Do NOT await it yet: the caller drains
    # the orphaned thread before its CancelledError becomes visible, so
    # awaiting here would block until the thread finishes.
    first.cancel()
    await asyncio.sleep(0.2)  # let the cancellation land

    # The first caller's thread is still running, so the next caller must
    # wait on the lock instead of starting a parallel embedding job.
    second = asyncio.create_task(chat_engine.build_doc_id_to_index_map(None, [doc]))
    await asyncio.sleep(0.3)
    assert not second.done()
    assert not second_entered.is_set()

    # Once the orphaned thread finishes, the cancellation surfaces, the lock
    # is released, and the queued caller proceeds — at no point did two
    # embedding jobs run in parallel.
    first_may_finish.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(first, timeout=5)
    result = await asyncio.wait_for(second, timeout=5)
    assert "d1" in result
    assert max_in_flight == 1
