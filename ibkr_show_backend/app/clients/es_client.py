import logging

from elasticsearch import Elasticsearch
from elasticsearch import NotFoundError
from elasticsearch import ConflictError
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

    def get(self, index: str, id: str) -> dict | None:
        try:
            return self._client.get(index=index, id=id)
        except NotFoundError:
            return None
        except ESConnectionError as exc:
            raise ESUnavailableError("Elasticsearch is not reachable.") from exc

    def index_document(self, index: str, id: str, document: dict) -> dict:
        try:
            return self._client.index(index=index, id=id, document=document, refresh=True)
        except ESConnectionError as exc:
            raise ESUnavailableError("Elasticsearch is not reachable.") from exc

    def create_index_if_missing(self, index: str, body: dict) -> None:
        try:
            if self._client.indices.exists(index=index):
                return
            self._client.indices.create(index=index, **body)
        except ConflictError:
            return
        except ESConnectionError as exc:
            raise ESUnavailableError("Elasticsearch is not reachable.") from exc

    def put_index_settings(self, index: str, settings: dict) -> None:
        """Apply mutable settings (e.g. mapping limits) to an existing index."""
        try:
            if not self._client.indices.exists(index=index):
                return
            self._client.indices.put_settings(index=index, settings=settings)
        except ESConnectionError as exc:
            raise ESUnavailableError("Elasticsearch is not reachable.") from exc

    def update_by_query(self, index: str, body: dict) -> dict:
        try:
            return self._client.update_by_query(index=index, body=body, refresh=True)
        except NotFoundError:
            return {"updated": 0}
        except ESConnectionError as exc:
            raise ESUnavailableError("Elasticsearch is not reachable.") from exc

    def count(self, index: str) -> int:
        try:
            result = self._client.count(index=index)
            return result.get("count", 0)
        except NotFoundError:
            return 0
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
