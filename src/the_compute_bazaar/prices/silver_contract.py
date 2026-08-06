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


GPU_OFFER_COLUMNS = (
    SilverColumn("provider", "Utf8", _text("provider"), "Offer provider."),
    SilverColumn(
        "source_offer_id",
        "Utf8",
        _text("source_offer_id"),
        "Provider or connector identifier for the observed offer.",
    ),
    SilverColumn(
        "observed_at",
        UTC_TIMESTAMP_DATA_TYPE,
        _utc_timestamp("observed_at"),
        "UTC time represented by the source observation; collection time when the source supplies no market timestamp.",
    ),
    SilverColumn(
        "gpu_raw_name",
        "Utf8",
        _text("gpu_raw_name"),
        "GPU name as reported by the source.",
    ),
    SilverColumn(
        "gpu_model",
        "Utf8",
        _text("gpu_model"),
        "Canonical GPU product and memory variant.",
    ),
    SilverColumn(
        "source_connector",
        "Utf8",
        _text("coalesce(source_connector, provider)"),
        "Connector that observed the offer; differs from provider for aggregators.",
    ),
    SilverColumn(
        "gpu_count",
        "Int64",
        "cast(gpu_count as bigint)",
        "GPU units in the offered machine or configuration.",
    ),
    SilverColumn(
        "available_gpu_count_lower_bound",
        "Int64",
        "cast(available_gpu_count as bigint)",
        "Nullable row-level lower bound on GPU units reported or demonstrated available; never total fleet capacity.",
    ),
    SilverColumn(
        "vram_gb",
        "Float64",
        "cast(vram_gb as double)",
        "Memory in GiB per GPU, represented with the historical field name.",
    ),
    SilverColumn(
        "price_usd_instance_hr",
        "Float64",
        "cast(price_usd_hr as double)",
        "Observed USD hourly price for the complete offered machine or configuration.",
    ),
    SilverColumn(
        "price_usd_gpu_hr",
        "Float64",
        "case when cast(gpu_count as bigint) > 0 "
        "then cast(price_usd_hr as double) / cast(gpu_count as double) "
        "else cast(null as double) end",
        "Mechanical instance-hour price divided by GPU count; not a benchmark or transaction price.",
    ),
    SilverColumn(
        "currency",
        "Utf8",
        _text("currency"),
        "Currency of the normalized price; currently USD.",
    ),
    SilverColumn("country", "Utf8", _text("country"), "Source country."),
    SilverColumn("region", "Utf8", _text("region"), "Source region."),
    SilverColumn(
        "is_spot",
        "Boolean",
        "cast(is_spot as boolean)",
        "Whether the source describes the price as spot or interruptible.",
    ),
    SilverColumn(
        "is_secure",
        "Boolean",
        "cast(is_secure as boolean)",
        "Source-reported secure-cloud status when available.",
    ),
    SilverColumn(
        "is_available",
        "Boolean",
        "case "
        "when lower(arrow_cast(availability_status, 'Utf8')) in "
        "('available', 'spot_available', 'available_component_rate') then true "
        "when lower(arrow_cast(availability_status, 'Utf8')) in "
        "('unavailable', 'spot_unavailable') then false "
        "else cast(null as boolean) end",
        "Tri-state availability assertion. Null means the source exposed a price without asserting deployable capacity.",
    ),
    SilverColumn(
        "source_availability_status",
        "Utf8",
        _text("availability_status"),
        "Normalized source status retained for pricing-basis and eligibility rules.",
    ),
    SilverColumn(
        "gpu_socket",
        "Utf8",
        _text("gpu_socket"),
        "Source-reported GPU interconnect or socket label.",
    ),
    SilverColumn(
        "source_stock_status",
        "Utf8",
        _text("stock_status"),
        "Uninterpreted stock label supplied by the source.",
    ),
    SilverColumn(
        "price_is_variable",
        "Boolean",
        "cast(price_is_variable as boolean)",
        "Whether the source says the quoted price can vary.",
    ),
    SilverColumn(
        "minimum_executable_price_usd_instance_hr",
        "Float64",
        "cast(minimum_executable_price_usd_hr as double)",
        "Minimum instance-hour price after mandatory priced resources, when known.",
    ),
    SilverColumn(
        "required_resource_price_usd_instance_hr",
        "Float64",
        "cast(required_resource_price_usd_hr as double)",
        "Mandatory non-GPU resource component of the instance-hour price, when known.",
    ),
    SilverColumn(
        "price_basis",
        "Utf8",
        _text("price_basis"),
        "Source-specific basis for the observed price when explicitly known.",
    ),
    SilverColumn(
        "raw_ref",
        "Utf8",
        _text("raw_ref"),
        "Bronze evidence reference for audit and replay.",
    ),
)

GPU_OFFER_LINEAGE_COLUMNS = (
    SilverColumn(
        "source_run_id",
        "Utf8",
        "",
        "Ingestion run that produced this provider observation.",
    ),
    SilverColumn(
        "source_manifest_ref",
        "Utf8",
        "",
        "Manifest for the ingestion run that produced this observation.",
    ),
    SilverColumn(
        "source_normalized_ref",
        "Utf8",
        "",
        "Silver Parquet object containing this observation.",
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
    "gpu_offers": GPU_OFFER_COLUMNS + GPU_OFFER_LINEAGE_COLUMNS,
    "compute_market_state": MARKET_STATE_COLUMNS,
}


def select_contract(table_name: str, columns: tuple[SilverColumn, ...]) -> str:
    projection = ",\n      ".join(
        f"{column.expression} as {column.name}" for column in columns
    )
    return f"select\n      {projection}\n    from {table_name}"


def silver_offer_select(
    table_name: str,
    *,
    source_run_id: str,
    source_manifest_ref: str | None,
    source_normalized_ref: str,
) -> str:
    projection = ",\n      ".join(
        f"{column.expression} as {column.name}" for column in GPU_OFFER_COLUMNS
    )
    lineage = ",\n      ".join(
        (
            f"{_sql_text(source_run_id)} as source_run_id",
            f"{_sql_text(source_manifest_ref)} as source_manifest_ref",
            f"{_sql_text(source_normalized_ref)} as source_normalized_ref",
        )
    )
    return f"select\n      {projection},\n      {lineage}\n    from {table_name}"


def silver_market_state_select(table_name: str) -> str:
    return select_contract(table_name, MARKET_STATE_COLUMNS)


def silver_contract(table_name: str) -> tuple[SilverColumn, ...] | None:
    return SILVER_TABLE_CONTRACTS.get(table_name)


def _sql_text(value: str | None) -> str:
    if value is None:
        return "cast(null as varchar)"
    return "'" + value.replace("'", "''") + "'"
