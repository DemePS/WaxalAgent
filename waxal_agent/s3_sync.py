"""Documents kept in S3 (or any S3-compatible store), mirrored to local folders so the agent reads plain files.

    s3://<bucket>/<WAXAL_S3_SHARED_PREFIX>/...                 the library, the same for everybody (default documents/)
    s3://<bucket>/<WAXAL_S3_USERS_PREFIX>/<phone>/documents/   one person's own documents (default users/)

The shared library is mirrored once per server, every WAXAL_S3_INTERVAL seconds. A person's documents are fetched only when
that person writes (at most every WAXAL_S3_USER_TTL seconds), so the disk holds only the people who are active.
Credentials are boto3's usual chain (environment, profile, role); WAXAL_S3_ENDPOINT / WAXAL_S3_REGION for other stores.
A file is replaced when its size or date changes, and a local file that is no longer in S3 is removed.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("waxal.s3")


def s3_client():
    import boto3
    return boto3.client("s3", endpoint_url=os.environ.get("WAXAL_S3_ENDPOINT") or None,
                        region_name=os.environ.get("WAXAL_S3_REGION") or None)


def _prefix(value: str) -> str:
    value = value.strip("/")
    return value + "/" if value else ""


def mirror(client, bucket: str, prefix: str, folder: Path) -> int:
    """Make `folder` match the objects under `prefix`. Returns the number of files downloaded. Any S3 error changes nothing."""
    folder = Path(folder)
    wanted: dict[Path, dict] = {}
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            relative = item["Key"][len(prefix):]
            parts = relative.split("/")
            if not relative or relative.endswith("/") or any(p in ("", ".", "..") or p.startswith(".") for p in parts):
                continue
            wanted[folder.joinpath(*parts)] = item
    downloaded = 0
    for path, item in wanted.items():
        stamp = item["LastModified"].timestamp()
        if path.is_file() and path.stat().st_size == item["Size"] and abs(path.stat().st_mtime - stamp) < 1:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".part")
        client.download_file(bucket, item["Key"], str(partial))
        os.replace(partial, path)
        os.utime(path, (stamp, stamp))
        downloaded += 1
    if folder.is_dir():
        for path in sorted(folder.rglob("*"), reverse=True):
            if path.is_file() and path not in wanted:
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    return downloaded


class S3Documents:
    def __init__(self, client, bucket: str, shared_prefix: str = "documents/", users_prefix: str = "users/",
                 interval: float | None = None, user_ttl: float | None = None) -> None:
        self.client, self.bucket = client, bucket
        self.shared_prefix, self.users_prefix = _prefix(shared_prefix), _prefix(users_prefix)
        self.interval = interval if interval is not None else float(os.environ.get("WAXAL_S3_INTERVAL") or 600)
        self.user_ttl = user_ttl if user_ttl is not None else float(os.environ.get("WAXAL_S3_USER_TTL") or 60)
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def sync_shared(self, folder: Path) -> None:
        try:
            count = mirror(self.client, self.bucket, self.shared_prefix, folder)
            if count:
                log.info("Library: %d file(s) downloaded from s3://%s/%s", count, self.bucket, self.shared_prefix)
        except Exception as e:  # nothing is changed locally; the next round tries again
            log.warning("Library sync failed: %s", e)

    def start(self, folder: Path) -> None:
        """Mirror the library now, then every `interval` seconds in the background."""
        self.sync_shared(folder)

        def loop() -> None:
            while True:
                time.sleep(self.interval)
                self.sync_shared(folder)
        threading.Thread(target=loop, daemon=True, name="s3-library").start()

    def refresh_user(self, user_id: str, folder: Path) -> None:
        """Fetch one person's own documents into `folder` (at most once per user_ttl seconds)."""
        with self._lock:
            if time.monotonic() - self._seen.get(user_id, float("-inf")) < self.user_ttl:
                return
            self._seen[user_id] = time.monotonic()
        try:
            mirror(self.client, self.bucket, f"{self.users_prefix}{user_id}/documents/", folder)
        except Exception as e:
            log.warning("Documents of %s not refreshed: %s", user_id, e)
