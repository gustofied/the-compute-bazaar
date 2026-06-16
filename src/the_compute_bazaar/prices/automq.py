"""Kafka-compatible publishing for AutoMQ."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Protocol

from .schemas import EventEnvelope, to_jsonable


class Publisher(Protocol):
    def publish(self, topic: str, event: EventEnvelope, *, key: str | None = None) -> None: ...

    def flush(self) -> None: ...


class DryRunPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, str | None, str]] = []

    def publish(self, topic: str, event: EventEnvelope, *, key: str | None = None) -> None:
        self.events.append((topic, key, event.event_id))

    def flush(self) -> None:
        return None


class KafkaPublisher:
    def __init__(self, *, bootstrap_servers: str, config: dict[str, str] | None = None) -> None:
        try:
            from confluent_kafka import Producer
        except ImportError as exc:
            raise RuntimeError(
                "Publishing to AutoMQ/Kafka requires the 'platform' extra: uv sync --extra platform"
            ) from exc

        producer_config = {
            "bootstrap.servers": bootstrap_servers,
            "client.id": "compute-bazaar",
            "acks": "all",
            "enable.idempotence": "true",
        }
        if config:
            producer_config.update(config)
        self._producer = Producer(producer_config)

    def publish(self, topic: str, event: EventEnvelope, *, key: str | None = None) -> None:
        self._producer.produce(
            topic,
            key=key,
            value=json.dumps(to_jsonable(event), sort_keys=True).encode("utf-8"),
        )
        self._producer.poll(0)

    def flush(self) -> None:
        self._producer.flush()


def publish_all(
    publisher: Publisher,
    topic: str,
    events: Iterable[EventEnvelope],
    *,
    key_prefix: str | None = None,
) -> int:
    count = 0
    for event in events:
        key = f"{key_prefix}:{event.event_id}" if key_prefix else event.event_id
        publisher.publish(topic, event, key=key)
        count += 1
    publisher.flush()
    return count

