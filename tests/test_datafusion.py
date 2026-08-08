from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from the_compute_bazaar.prices.datafusion import DataFusionEngine


class DataFusionEngineTest(unittest.TestCase):
    def test_query_arrow_accepts_datafusion_physical_string_views(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parquet_path = Path(directory) / "market.parquet"
            pq.write_table(
                pa.table(
                    {
                        "source_role": ["aggregator", "direct"],
                        "matching_direct_source": [True, False],
                        "exclusion_reason": [None, "not_available"],
                    }
                ),
                parquet_path,
            )
            engine = DataFusionEngine({"market": str(parquet_path)})

            result = engine.query_arrow(
                """
                select case
                    when source_role = 'aggregator' and matching_direct_source
                        then 'matching_direct_provider_source'
                    else exclusion_reason
                end as exclusion_reason
                from market
                order by source_role
                """
            )

            self.assertEqual(
                result.column("exclusion_reason").to_pylist(),
                ["matching_direct_provider_source", "not_available"],
            )

    def test_empty_query_retains_logical_schema(self) -> None:
        engine = DataFusionEngine()

        result = engine.query_arrow(
            "select cast(null as varchar) as reason where false"
        )

        self.assertEqual(result.num_rows, 0)
        self.assertEqual(result.column_names, ["reason"])
        reason_type = result.schema.field("reason").type
        self.assertTrue(
            pa.types.is_string(reason_type) or pa.types.is_string_view(reason_type)
        )


if __name__ == "__main__":
    unittest.main()
