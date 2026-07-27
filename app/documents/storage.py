"""Armazenamento de documentos fora do banco.

O banco guarda apenas metadados e hashes; os bytes dos documentos (texto
canônico e arquivo original) ficam em um object store. Isso reduz o raio de
exposição de material sensível, preserva o artefato original e mantém o banco
enxuto.

Backends:
- ``memory``: apenas para testes;
- ``local`` (padrão): disco local, adequado a desenvolvimento e a um volume
  persistente montado;
- ``s3``: qualquer serviço compatível com S3 (AWS, MinIO, R2), com ``boto3``
  importado sob demanda.

Configuração por variáveis de ambiente:
- ``DOCUMENT_STORAGE_BACKEND`` = memory | local | s3
- ``DOCUMENT_STORAGE_DIR`` (local; padrão ``./data/documents``)
- ``DOCUMENT_S3_BUCKET`` / ``DOCUMENT_S3_PREFIX`` / ``DOCUMENT_S3_ENDPOINT_URL``
  / ``DOCUMENT_S3_REGION`` (s3)
"""

import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Dict, Protocol


class StorageError(Exception):
    """Falha ao ler, gravar ou localizar um objeto no armazenamento."""


class DocumentStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str = ...) -> None: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...


def build_content_key(case_id: str, document_id: str) -> str:
    return f"{case_id}/{document_id}/content.txt"


def build_original_key(case_id: str, document_id: str, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower() or ".bin"
    return f"{case_id}/{document_id}/original{suffix}"


class InMemoryStorage:
    def __init__(self) -> None:
        self._data: Dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        with self._lock:
            self._data[key] = bytes(data)

    def get(self, key: str) -> bytes:
        with self._lock:
            if key not in self._data:
                raise StorageError(f"Objeto não encontrado: {key}")
            return self._data[key]

    def exists(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._data.clear()


class LocalDiskStorage:
    def __init__(self, base_dir: str) -> None:
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        target = (self.base / key).resolve()
        # Impede que uma chave manipulada escape do diretório base.
        if self.base != target and self.base not in target.parents:
            raise StorageError(f"Chave inválida: {key}")
        return target

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageError(f"Objeto não encontrado: {key}") from exc

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class EncryptedStorage:
    """Envelope que cifra/decifra transparentemente sobre qualquer backend."""

    def __init__(self, inner: "DocumentStorage", cipher) -> None:
        self.inner = inner
        self.cipher = cipher

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.inner.put(key, self.cipher.encrypt(data), content_type)

    def get(self, key: str) -> bytes:
        blob = self.inner.get(key)
        try:
            return self.cipher.decrypt(blob)
        except Exception as exc:  # noqa: BLE001 - inclui InvalidTag
            raise StorageError(f"Falha ao decifrar objeto: {key}") from exc

    def exists(self, key: str) -> bool:
        return self.inner.exists(key)

    def delete(self, key: str) -> None:
        self.inner.delete(key)


class S3Storage:  # pragma: no cover - depende de serviço externo
    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        try:
            import boto3  # importado sob demanda para não virar dependência dura
        except ImportError as exc:
            raise StorageError(
                "O backend s3 exige o pacote boto3 instalado."
            ) from exc
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = boto3.client(
            "s3", endpoint_url=endpoint_url, region_name=region
        )

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=self._key(key), Body=data, ContentType=content_type
        )

    def get(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
            return response["Body"].read()
        except Exception as exc:
            raise StorageError(f"Objeto não encontrado: {key}") from exc

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))


def _build_backend() -> DocumentStorage:
    backend = os.getenv("DOCUMENT_STORAGE_BACKEND", "local").strip().lower()
    if backend == "memory":
        return InMemoryStorage()
    if backend == "s3":
        bucket = os.getenv("DOCUMENT_S3_BUCKET", "").strip()
        if not bucket:
            raise StorageError(
                "DOCUMENT_S3_BUCKET é obrigatório quando DOCUMENT_STORAGE_BACKEND=s3"
            )
        return S3Storage(
            bucket=bucket,
            prefix=os.getenv("DOCUMENT_S3_PREFIX", "").strip(),
            endpoint_url=os.getenv("DOCUMENT_S3_ENDPOINT_URL", "").strip() or None,
            region=os.getenv("DOCUMENT_S3_REGION", "").strip() or None,
        )
    return LocalDiskStorage(os.getenv("DOCUMENT_STORAGE_DIR", "./data/documents"))


@lru_cache(maxsize=1)
def get_document_storage() -> DocumentStorage:
    backend = _build_backend()
    # Importado sob demanda para evitar acoplar o storage à criptografia.
    from app.core.encryption import get_document_cipher

    cipher = get_document_cipher()
    if cipher is not None:
        return EncryptedStorage(backend, cipher)
    return backend
