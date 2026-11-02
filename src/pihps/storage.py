"""Akses Cloudflare R2 (S3-compatible)."""

from __future__ import annotations

import gzip
import json
from typing import Any

import boto3
from botocore.config import Config

from pihps.config import R2Config


class R2Storage:
    def __init__(self, cfg: R2Config) -> None:
        self.bucket = cfg.bucket
        self._s3 = boto3.client(
            "s3",
            endpoint_url=cfg.endpoint,
            aws_access_key_id=cfg.access_key_id,
            aws_secret_access_key=cfg.secret_access_key,
            region_name="auto",
            config=Config(
                retries={"max_attempts": 5, "mode": "standard"},
                max_pool_connections=32,  # unduh/unggah paralel di pihps.transform
            ),
        )

    def put_json(self, key: str, obj: Any, *, gzip_body: bool = False) -> int:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode()
        extra: dict[str, str] = {"ContentType": "application/json"}
        if gzip_body:
            body = gzip.compress(body)
            extra["ContentEncoding"] = "gzip"
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=body, **extra)
        return len(body)

    def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> int:
        """Tulis byte apa adanya (tanpa ContentEncoding, jadi tidak di-dekompres otomatis)."""
        self._s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            Metadata=metadata or {},
        )
        return len(body)

    def head(self, key: str) -> dict[str, Any]:
        return self._s3.head_object(Bucket=self.bucket, Key=key)

    def get_json(self, key: str) -> Any:
        obj = self._s3.get_object(Bucket=self.bucket, Key=key)
        body = obj["Body"].read()
        if obj.get("ContentEncoding") == "gzip" or key.endswith(".gz"):
            body = gzip.decompress(body)
        return json.loads(body)

    # ------------------------------------------------- dipakai pihps.transform
    def list_objects(self, prefix: str) -> list[dict[str, Any]]:
        """Semua objek di bawah prefix: [{'Key', 'Size', ...}]."""
        out: list[dict[str, Any]] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            out.extend(page.get("Contents", []))
        return out

    def download_file(self, key: str, path: str) -> None:
        self._s3.download_file(self.bucket, key, path)

    def upload_file(self, key: str, path: str, *, content_type: str) -> None:
        self._s3.upload_file(path, self.bucket, key, ExtraArgs={"ContentType": content_type})

    def delete_keys(self, keys: list[str]) -> None:
        for i in range(0, len(keys), 1000):  # batas DeleteObjects S3
            batch = [{"Key": k} for k in keys[i : i + 1000]]
            self._s3.delete_objects(Bucket=self.bucket, Delete={"Objects": batch, "Quiet": True})
