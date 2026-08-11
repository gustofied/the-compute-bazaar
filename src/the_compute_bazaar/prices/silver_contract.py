"""Stable typed views over provider-normalized Silver Parquet."""

from __future__ import annotations

from dataclasses import dataclass


UTC_TIMESTAMP_ARROW_TYPE = 'Timestamp(Nanosecond, Some("UTC"))'
UTC_TIMESTAMP_DATA_TYPE = 'Timestamp(ns, "UTC")'


def _text(expression: str) -> str:
    return f"arrow_cast({expression}, 'Utf8')"


def _utc_timestamp(expression: str) -> str:
    return f"arrow_cast({expression}, '{UTC_TIMESTAMP_ARROW_TYPE}')"


@dataclass(frozen=True)
class SilverColumn:
    """One public column in a logical Silver table."""

    name: str
    data_type: str
    expression: str
    meaning: str


OFFER_OBSERVATION_COLUMNS = (
    SilverColumn(
        "observation_id", "Utf8", _text("observation_id"), "Stable row identifier."
    ),
    SilverColumn(
        "batch_id",
        "Utf8",
        _text("batch_id"),
        "Provider read that produced the row.",
    ),
    SilverColumn(
        "market_run_id",
        "Utf8",
        _text("market_run_id"),
        "Hourly market run, when present.",
    ),
    SilverColumn(
        "observation_purpose",
        "Utf8",
        _text("observation_purpose"),
        "Scheduled, interactive, or preflight.",
    ),
    SilverColumn(
        "observation_resolution",
        "Utf8",
        _text("observation_resolution"),
        "Market summary, deployment option, or exact offer.",
    ),
    SilverColumn(
        "selection_resolution",
        "Utf8",
        _text("selection_resolution"),
        "Provider selection specificity.",
    ),
    SilverColumn(
        "observed_at",
        UTC_TIMESTAMP_DATA_TYPE,
        _utc_timestamp("observed_at"),
        "UTC observation time.",
    ),
    SilverColumn("provider", "Utf8", _text("provider"), "Capacity provider."),
    SilverColumn(
        "source_connector",
        "Utf8",
        _text("source_connector"),
        "Connector that observed the offer.",
    ),
    SilverColumn(
        "source_offer_id",
        "Utf8",
        _text("source_offer_id"),
        "Provider-scoped offer key.",
    ),
    SilverColumn("gpu_raw_name", "Utf8", _text("gpu_raw_name"), "Source GPU name."),
    SilverColumn("gpu_model", "Utf8", _text("gpu_model"), "Canonical GPU model."),
    SilverColumn("gpu_count", "Int64", "cast(gpu_count as bigint)", "GPU count."),
    SilverColumn(
        "vram_gb", "Float64", "cast(vram_gb as double)", "Memory per GPU in GiB."
    ),
    SilverColumn(
        "price_usd_instance_hr",
        "Float64",
        "cast(price_usd_instance_hr as double)",
        "USD per offered configuration-hour.",
    ),
    SilverColumn(
        "price_usd_gpu_hr",
        "Float64",
        "cast(price_usd_gpu_hr as double)",
        "USD per GPU-hour.",
    ),
    SilverColumn("currency", "Utf8", _text("currency"), "Normalized currency."),
    SilverColumn(
        "available_gpu_count_lower_bound",
        "Int64",
        "cast(available_gpu_count_lower_bound as bigint)",
        "Observed lower bound, not total fleet capacity.",
    ),
    SilverColumn(
        "is_available",
        "Boolean",
        "cast(is_available as boolean)",
        "Source availability assertion.",
    ),
    SilverColumn(
        "source_availability_status",
        "Utf8",
        _text("source_availability_status"),
        "Normalized source status.",
    ),
    SilverColumn(
        "source_stock_status",
        "Utf8",
        _text("source_stock_status"),
        "Source stock label.",
    ),
    SilverColumn("country", "Utf8", _text("country"), "Source country."),
    SilverColumn("region", "Utf8", _text("region"), "Source region."),
    SilverColumn(
        "cloud_type",
        "Utf8",
        _text("cloud_type"),
        "Provider cloud or security class.",
    ),
    SilverColumn(
        "location_ids_json",
        "Utf8",
        _text("location_ids_json"),
        "Eligible provider locations.",
    ),
    SilverColumn(
        "selection_fingerprint",
        "Utf8",
        _text("selection_fingerprint"),
        "Stable provider selection key.",
    ),
    SilverColumn(
        "native_selection_json",
        "Utf8",
        _text("native_selection_json"),
        "Provider-native selection fields.",
    ),
    SilverColumn(
        "query_scope_json",
        "Utf8",
        _text("query_scope_json"),
        "Scope requested from the provider.",
    ),
    SilverColumn(
        "response_complete",
        "Boolean",
        "cast(response_complete as boolean)",
        "Whether the requested provider response completed.",
    ),
    SilverColumn(
        "is_spot", "Boolean", "cast(is_spot as boolean)", "Spot or interruptible price."
    ),
    SilverColumn(
        "is_secure", "Boolean", "cast(is_secure as boolean)", "Source security class."
    ),
    SilverColumn(
        "gpu_socket",
        "Utf8",
        _text("gpu_socket"),
        "Source GPU socket or interconnect label.",
    ),
    SilverColumn(
        "price_is_variable",
        "Boolean",
        "cast(price_is_variable as boolean)",
        "Source says the price may vary.",
    ),
    SilverColumn(
        "minimum_executable_price_usd_instance_hr",
        "Float64",
        "cast(minimum_executable_price_usd_instance_hr as double)",
        "Known minimum executable configuration price.",
    ),
    SilverColumn(
        "required_resource_price_usd_instance_hr",
        "Float64",
        "cast(required_resource_price_usd_instance_hr as double)",
        "Known mandatory resource price.",
    ),
    SilverColumn("price_basis", "Utf8", _text("price_basis"), "Source price basis."),
    SilverColumn("raw_ref", "Utf8", _text("raw_ref"), "Bronze evidence reference."),
    SilverColumn(
        "raw_hash", "Utf8", _text("raw_hash"), "Hash of the provider response."
    ),
    SilverColumn(
        "source_run_id",
        "Utf8",
        _text("source_run_id"),
        "Ingestion run identifier.",
    ),
    SilverColumn(
        "source_manifest_ref",
        "Utf8",
        _text("source_manifest_ref"),
        "Ingestion manifest reference.",
    ),
    SilverColumn(
        "source_normalized_ref",
        "Utf8",
        _text("source_normalized_ref"),
        "Physical Silver object.",
    ),
    SilverColumn(
        "methodology_version",
        "Utf8",
        _text("methodology_version"),
        "Observation methodology.",
    ),
    SilverColumn(
        "schema_version",
        "Utf8",
        _text("schema_version"),
        "Observation schema.",
    ),
)


MARKET_STATE_COLUMNS = (
    SilverColumn(
        "observation_id",
        "Utf8",
        _text("observation_id"),
        "Stable observation identifier.",
    ),
    SilverColumn(
        "observed_at",
        UTC_TIMESTAMP_DATA_TYPE,
        _utc_timestamp("observed_at"),
        "UTC market observation time.",
    ),
    SilverColumn(
        "resource_market", "Utf8", _text("resource_market"), "Resource market."
    ),
    SilverColumn(
        "resource_type", "Utf8", _text("resource_type"), "Measured resource type."
    ),
    SilverColumn("provider", "Utf8", _text("provider"), "Measured provider."),
    SilverColumn(
        "source_connector",
        "Utf8",
        _text("source_connector"),
        "Connector that made the observation.",
    ),
    SilverColumn(
        "source_role", "Utf8", _text("source_role"), "Direct or aggregator source role."
    ),
    SilverColumn(
        "measurement_kind", "Utf8", _text("measurement_kind"), "Named measurement."
    ),
    SilverColumn(
        "measurement_scope",
        "Utf8",
        _text("measurement_scope"),
        "Population covered by the measurement.",
    ),
    SilverColumn("unit", "Utf8", _text("unit"), "Measurement unit."),
    SilverColumn(
        "total_units",
        "Float64",
        "cast(total_units as double)",
        "Source-defined denominator.",
    ),
    SilverColumn(
        "rented_units",
        "Float64",
        "cast(rented_units as double)",
        "Source-defined rented units.",
    ),
    SilverColumn(
        "available_units",
        "Float64",
        "cast(available_units as double)",
        "Source-defined available units.",
    ),
    SilverColumn(
        "pending_units",
        "Float64",
        "cast(pending_units as double)",
        "Source-defined pending units.",
    ),
    SilverColumn(
        "rented_share",
        "Float64",
        "cast(rented_share as double)",
        "Rented units divided by the stated denominator.",
    ),
    SilverColumn(
        "available_share",
        "Float64",
        "cast(available_share as double)",
        "Available units divided by the stated denominator.",
    ),
    SilverColumn("stock_status", "Utf8", _text("stock_status"), "Source stock label."),
    SilverColumn(
        "count_precision", "Utf8", _text("count_precision"), "Exactness of the count."
    ),
    SilverColumn(
        "numerator_definition",
        "Utf8",
        _text("numerator_definition"),
        "Definition of the numerator.",
    ),
    SilverColumn(
        "denominator_definition",
        "Utf8",
        _text("denominator_definition"),
        "Definition of the denominator.",
    ),
    SilverColumn(
        "aggregation_eligible",
        "Boolean",
        "cast(aggregation_eligible as boolean)",
        "Whether this observation may be aggregated.",
    ),
    SilverColumn(
        "aggregation_exclusion_reason",
        "Utf8",
        _text("aggregation_exclusion_reason"),
        "Reason the observation is excluded.",
    ),
    SilverColumn("source_url", "Utf8", _text("source_url"), "Public source URL."),
    SilverColumn("raw_ref", "Utf8", _text("raw_ref"), "Bronze evidence reference."),
    SilverColumn(
        "methodology_version",
        "Utf8",
        _text("methodology_version"),
        "Measurement methodology version.",
    ),
    SilverColumn("notes", "Utf8", _text("notes"), "Measurement caveat."),
    SilverColumn(
        "source_run_id", "Utf8", _text("source_run_id"), "Ingestion run identifier."
    ),
    SilverColumn(
        "source_manifest_ref",
        "Utf8",
        _text("source_manifest_ref"),
        "Ingestion manifest reference.",
    ),
    SilverColumn(
        "source_normalized_ref",
        "Utf8",
        _text("source_normalized_ref"),
        "Normalized offer reference.",
    ),
    SilverColumn(
        "source_market_state_ref",
        "Utf8",
        _text("source_market_state_ref"),
        "Normalized market-state reference.",
    ),
)


SILVER_TABLE_CONTRACTS = {
    "offer_observations": OFFER_OBSERVATION_COLUMNS,
    "compute_market_state": MARKET_STATE_COLUMNS,
}


def select_contract(table_name: str, columns: tuple[SilverColumn, ...]) -> str:
    projection = ",\n      ".join(
        f"{column.expression} as {column.name}" for column in columns
    )
    return f"select\n      {projection}\n    from {table_name}"


def silver_observation_select(table_name: str) -> str:
    return select_contract(table_name, OFFER_OBSERVATION_COLUMNS)


def silver_market_state_select(table_name: str) -> str:
    return select_contract(table_name, MARKET_STATE_COLUMNS)


def silver_contract(table_name: str) -> tuple[SilverColumn, ...] | None:
    return SILVER_TABLE_CONTRACTS.get(table_name)
