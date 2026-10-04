"""Coordination around service operations and ASGI backend cleanup."""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, Protocol, cast

from .store import PortalStateStore


class ServiceState(Protocol):
    store: PortalStateStore | None
    _operation_lock: threading.RLock
    _operation_depth: int

    def _load_state(self) -> None: ...
    def close(self) -> None: ...


def serialized_store_operation[**OperationArgs, OperationResult](
    method: Callable[OperationArgs, OperationResult],
) -> Callable[OperationArgs, OperationResult]:
    """Refresh once under cross-instance coordination, preserving nested calls."""

    @wraps(method)
    def operation(*args: OperationArgs.args, **kwargs: OperationArgs.kwargs) -> OperationResult:
        store = cast(ServiceState, args[0])
        with store._operation_lock:
            coordinator = getattr(store.store, "service_operation", None)
            if store._operation_depth or coordinator is None:
                return method(*args, **kwargs)
            with coordinator():
                store._operation_depth += 1
                try:
                    store._load_state()
                    return method(*args, **kwargs)
                finally:
                    store._operation_depth -= 1

    return operation


def portal_store_lifespan(store: ServiceState) -> Callable[..., Any]:
    @asynccontextmanager
    async def lifespan(_app: Any) -> AsyncIterator[None]:
        try:
            yield
        finally:
            store.close()

    return lifespan
