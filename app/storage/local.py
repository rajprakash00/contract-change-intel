"""Local filesystem storage for uploaded documents.

Layout is content-addressed: {data_dir}/{tenant_id}/{sha256}. Only these two
functions touch the filesystem; swapping in object storage (S3/GCS) later means
replacing this module, not the services that call it.
"""

import os
import tempfile
import uuid
from pathlib import Path


def save_document(data_dir: str | Path, tenant_id: uuid.UUID, sha256: str, content: bytes) -> Path:
    """Persist bytes at {data_dir}/{tenant_id}/{sha256}, atomically via os.replace.

    Content-addressed path means re-uploading identical bytes overwrites itself,
    so no orphan cleanup is needed on the duplicate-upload race path.
    """
    dest_dir = Path(data_dir) / str(tenant_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / sha256
    fd, tmp_path = tempfile.mkstemp(dir=dest_dir)
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(content)
        os.replace(tmp_path, dest)
    except BaseException:
        try:
            os.unlink(tmp_path)
        finally:
            raise
    return dest


def document_path(data_dir: str | Path, tenant_id: uuid.UUID, sha256: str) -> Path:
    """Resolve where a stored document lives; used by future download endpoints."""
    return Path(data_dir) / str(tenant_id) / sha256
