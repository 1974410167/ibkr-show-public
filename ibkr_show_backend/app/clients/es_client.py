import logging

from elasticsearch import Elasticsearch
from elasticsearch import NotFoundError
from elasticsearch.exceptions import ConnectionError as ESConnectionError

from app.core.config import Settings

logger = logging.getLogger(__name__)


class ESClientError(RuntimeError):
    """Base Elasticsearch client error."""


class ESUnavailableError(ESClientError):
    """Raised when Elasticsearch is not reachable."""


class ESIndexNotFoundError(ESClientError):
    """Raised when a requested index does not exist."""


class ElasticsearchClient:
    def __init__(self, settings: Settings) -> None:
        basic_auth = None
        if settings.es_username:
            basic_auth = (settings.es_username, settings.es_password)

        self._client = Elasticsearch(
            settings.es_host,
            basic_auth=basic_auth,
            verify_certs=settings.es_verify_certs,
            request_timeout=30,
        )

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except ESConnectionError as exc:
            raise ESUnavailableError("Elasticsearch is not reachable.") from exc

    def search(self, index: str, body: dict) -> dict:
        try:
            return self._client.search(index=index, body=body)
        except NotFoundError as exc:
            raise ESIndexNotFoundError(f"Elasticsearch index not found: {index}") from exc
        except ESConnectionError as exc:
            raise ESUnavailableError("Elasticsearch is not reachable.") from exc

    def multi_search(self, searches: list[tuple[str, dict]]) -> list[dict]:
        payload: list[dict] = []
        for index, body in searches:
            payload.append({"index": index})
            payload.append(body)

        try:
            response = self._client.msearch(searches=payload)
        except NotFoundError as exc:
            raise ESIndexNotFoundError("Elasticsearch multi-search references a missing index.") from exc
        except ESConnectionError as exc:
            raise ESUnavailableError("Elasticsearch is not reachable.") from exc

        return list(response.get("responses", []))
