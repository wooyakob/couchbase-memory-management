from pydantic import BaseModel
from typing import Optional, Any, Dict, List


class ConnectRequest(BaseModel):
    connection_string: str
    username: str
    password: str


class SelectCollectionRequest(BaseModel):
    bucket: str
    scope: str
    collection: str


class UpdateDocumentRequest(BaseModel):
    data: Dict[str, Any]


class BulkDeleteRequest(BaseModel):
    doc_ids: List[str]


class DocsByIdsRequest(BaseModel):
    ids: List[str]
