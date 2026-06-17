"""Kafka-compatible publishing for AutoMQ."""

from __future__ import annotations

import json
import os
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


def kafka_bootstrap_servers_from_env() -> str | None:
    """Return Kafka bootstrap servers from project or legacy AutoMQ env vars."""
    return _first_env("COMPUTE_BAZAAR_KAFKA_BOOTSTRAP_SERVERS", "AUTOMQ_BOOTSTRAP_SERVERS")


def kafka_config_from_env() -> dict[str, str]:
    """Build confluent-kafka config from AutoMQ/Kafka environment variables."""
    mapping = {
        ("COMPUTE_BAZAAR_KAFKA_SECURITY_PROTOCOL", "AUTOMQ_SECURITY_PROTOCOL"): "security.protocol",
        ("COMPUTE_BAZAAR_KAFKA_SASL_MECHANISM", "AUTOMQ_SASL_MECHANISM"): "sasl.mechanism",
        ("COMPUTE_BAZAAR_KAFKA_USERNAME", "AUTOMQ_SASL_USERNAME"): "sasl.username",
        ("COMPUTE_BAZAAR_KAFKA_PASSWORD", "AUTOMQ_SASL_PASSWORD"): "sasl.password",
        ("AUTOMQ_SSL_CA_LOCATION",): "ssl.ca.location",
        ("AUTOMQ_SSL_CERTIFICATE_LOCATION",): "ssl.certificate.location",
        ("AUTOMQ_SSL_KEY_LOCATION",): "ssl.key.location",
    }
    return {
        config_key: value
        for env_keys, config_key in mapping.items()
        if (value := _first_env(*env_keys))
    }


def _first_env(*keys: str) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return None


def check_cluster(*, bootstrap_servers: str, config: dict[str, str] | None = None) -> list[str]:
    """Return visible topic names to verify broker connectivity."""
    try:
        from confluent_kafka.admin import AdminClient
    except ImportError as exc:
        raise RuntimeError(
            "Connecting to AutoMQ/Kafka requires confluent-kafka. Run uv sync first."
        ) from exc

    admin_config = {"bootstrap.servers": bootstrap_servers}
    if config:
        admin_config.update(config)
    metadata = AdminClient(admin_config).list_topics(timeout=15)
    return sorted(metadata.topics)
