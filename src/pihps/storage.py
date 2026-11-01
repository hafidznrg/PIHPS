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
            config=Config(retries={"max_attempts": 5, "mode": "standard"}),
        )

    def put_json(self, key: str, obj: Any, *, gzip_body: bool = False) -> int:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode()
        extra: dict[str, str] = {"ContentType": "application/json"}
        if gzip_body:
            body = gzip.compress(body)
            extra["ContentEncoding"] = "gzip"
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=body, **extra)
        return len(body)

    def head(self, key: str) -> dict[str, Any]:
        return self._s3.head_object(Bucket=self.bucket, Key=key)

    def get_json(self, key: str) -> Any:
        obj = self._s3.get_object(Bucket=self.bucket, Key=key)
        body = obj["Body"].read()
        if obj.get("ContentEncoding") == "gzip" or key.endswith(".gz"):
            body = gzip.decompress(body)
        return json.loads(body)
