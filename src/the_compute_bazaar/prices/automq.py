"""Kafka-compatible publishing for AutoMQ."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

from .schemas import EventEnvelope, to_jsonable


class Publisher(Protocol):
    def publish(
        self, topic: str, event: EventEnvelope, *, key: str | None = None
    ) -> None: ...

    def flush(self) -> None: ...


class DryRunPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, str | None, str]] = []

    def publish(
        self, topic: str, event: EventEnvelope, *, key: str | None = None
    ) -> None:
        self.events.append((topic, key, event.event_id))

    def flush(self) -> None:
        return None


class KafkaPublisher:
    def __init__(
        self, *, bootstrap_servers: str, config: dict[str, str] | None = None
    ) -> None:
        try:
            from confluent_kafka import Producer
        except ImportError as exc:
            raise RuntimeError(
                "Publishing to AutoMQ/Kafka requires confluent-kafka. Run uv sync first."
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
        self._delivery_errors: list[str] = []

    def publish(
        self, topic: str, event: EventEnvelope, *, key: str | None = None
    ) -> None:
        payload = json.dumps(to_jsonable(event), sort_keys=True).encode("utf-8")
        while True:
            try:
                self._producer.produce(
                    topic,
                    key=key,
                    value=payload,
                    on_delivery=self._on_delivery,
                )
                break
            except BufferError:
                self._producer.poll(1)
        self._producer.poll(0)

    def flush(self) -> None:
        remaining = self._producer.flush(30)
        if remaining:
            raise RuntimeError(
                f"Kafka delivery timed out with {remaining} event(s) still queued"
            )
        if self._delivery_errors:
            details = "; ".join(self._delivery_errors[:3])
            raise RuntimeError(f"Kafka rejected event delivery: {details}")

    def _on_delivery(self, error: Any, _message: Any) -> None:
        if error is not None:
            self._delivery_errors.append(str(error))


def kafka_config_from_env() -> dict[str, str]:
    """Build confluent-kafka config from AutoMQ/Kafka environment variables."""
    mapping = {
        "COMPUTE_BAZAAR_KAFKA_SECURITY_PROTOCOL": "security.protocol",
        "COMPUTE_BAZAAR_KAFKA_SASL_MECHANISM": "sasl.mechanism",
        "COMPUTE_BAZAAR_KAFKA_USERNAME": "sasl.username",
        "COMPUTE_BAZAAR_KAFKA_PASSWORD": "sasl.password",
        "COMPUTE_BAZAAR_KAFKA_SSL_CA_LOCATION": "ssl.ca.location",
        "COMPUTE_BAZAAR_KAFKA_SSL_CERTIFICATE_LOCATION": "ssl.certificate.location",
        "COMPUTE_BAZAAR_KAFKA_SSL_KEY_LOCATION": "ssl.key.location",
    }
    return {
        config_key: value
        for env_key, config_key in mapping.items()
        if (value := os.getenv(env_key))
    }
