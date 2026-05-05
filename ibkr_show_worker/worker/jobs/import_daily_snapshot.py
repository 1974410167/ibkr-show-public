from pathlib import Path

from worker.clients.cache_client import RedisCacheInvalidator
from worker.clients.es_client import ElasticsearchWriter
from worker.core.config import get_settings
from worker.parsers.flex_csv_parser import parse_flex_csv
from worker.parsers.transformers import transform_daily_statement


def import_daily_snapshot_file(es_writer: ElasticsearchWriter, file_path: str | Path) -> dict:
    statement = parse_flex_csv(file_path)
    transformed = transform_daily_statement(statement)

    results = {}
    for index_name, documents in transformed.documents_by_index().items():
        results[index_name] = es_writer.bulk_upsert(index_name, documents)

    RedisCacheInvalidator(get_settings()).clear_all()
    return results
