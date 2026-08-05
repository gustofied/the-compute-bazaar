Tests are small and hermetic: five checks protect the provider-to-Gold DataFusion path and public publication boundary without calling the live services. A production market-data platform would eventually need deterministic provider contract fixtures, bronze/silver/gold replay and schema-drift coverage, plus isolated integration tests for Kafka, S3, Windmill, and public delivery.

So tests are a weak point, but enough for this project.
pytests, terraform tests, even agent experience tests would be welcomed, something like raindrop.

Run the tests:

```bash
uv run python -m unittest discover -s tests -v
```
