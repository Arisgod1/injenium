# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Minimal IPFS (Kubo) HTTP-API client for off-chain recipe storage.

This moves a recipe off the local filesystem onto content-addressed storage so
two robots can share it (spec §链下产物存储 evolution). Only two operations are
needed: add the recipe *directory* (recipe.json + template images) and read a
file back by CID. Adding the whole directory keeps ``recipe.json`` byte-for-byte
identical — so its ``content_hash`` (the on-chain commitment) is unchanged — and
its relative ``image_path`` references resolve under the same CID.

The on-chain pointer becomes ``ipfs://<cid>``;
:func:`injenium.core.recipe.load_recipe` resolves it. We talk to the Kubo HTTP
API (default ``http://127.0.0.1:5001``, override with ``IPFS_API_URL``) using the
standard library only — no third-party IPFS package. A running IPFS daemon (or a
pinning service exposing the same API) is required for this path; the local-path
storage stays the zero-dependency PoC default.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import quote
import uuid

IPFS_URI_PREFIX = "ipfs://"
_DEFAULT_API_URL = "http://127.0.0.1:5001"


def is_ipfs_uri(uri: object) -> bool:
    """True if ``uri`` is an ``ipfs://`` pointer (accepts str or PathLike)."""
    return str(uri).startswith(IPFS_URI_PREFIX)


def cid_from_uri(uri: str) -> str:
    """``ipfs://<cid>[/path]`` -> ``<cid>[/path]``."""
    return str(uri)[len(IPFS_URI_PREFIX):]


def _api_url(api_url: str | None) -> str:
    return (api_url or os.environ.get("IPFS_API_URL") or _DEFAULT_API_URL).rstrip("/")


def publish_dir(local_dir: str | os.PathLike[str], *, api_url: str | None = None) -> str:
    """Pin ``local_dir`` recursively; return its ``ipfs://<cid>`` pointer."""
    return f"{IPFS_URI_PREFIX}{add_directory(local_dir, api_url=api_url)}"


def add_directory(local_dir: str | os.PathLike[str], *, api_url: str | None = None) -> str:
    """Add a directory (recursively) to IPFS and return the wrapping dir CID."""
    root = Path(os.fspath(local_dir))
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        raise ValueError(f"no files to add under {root}")

    boundary = f"----injenium{uuid.uuid4().hex}"
    body = _multipart_dir(root, files, boundary)
    url = f"{_api_url(api_url)}/api/v0/add?cid-version=1&pin=true"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    lines = _post(req, api_url, "add").decode("utf-8").splitlines()

    # NDJSON: the entry whose Name is the wrapping dir carries the dir CID.
    dirname = root.name
    cid = ""
    for line in lines:
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("Name") in (dirname, "", "."):
            cid = entry.get("Hash", cid)
    if not cid and lines:
        cid = json.loads(lines[-1]).get("Hash", "")
    if not cid:
        raise RuntimeError("IPFS add returned no directory CID")
    return cid


def cat(path: str, *, api_url: str | None = None) -> bytes:
    """Return the bytes of an IPFS path like ``<cid>/recipe.json``."""
    arg = quote(f"/ipfs/{path.lstrip('/')}", safe="")
    url = f"{_api_url(api_url)}/api/v0/cat?arg={arg}"
    req = urllib.request.Request(url, data=b"", method="POST")
    return _post(req, api_url, "cat")


def _post(req: urllib.request.Request, api_url: str | None, op: str) -> bytes:
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"IPFS {op} failed against {_api_url(api_url)} ({exc}); "
            f"is an IPFS (Kubo) daemon reachable? Set IPFS_API_URL to override."
        ) from exc


def _multipart_dir(root: Path, files: list[Path], boundary: str) -> bytes:
    parts: list[bytes] = []

    def _field(filename: str, ctype: str, content: bytes) -> None:
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode("utf-8")
        parts.append(head + content + b"\r\n")

    dirname = root.name
    _field(quote(dirname), "application/x-directory", b"")
    for f in files:
        rel = f.relative_to(root).as_posix()
        _field(quote(f"{dirname}/{rel}"), "application/octet-stream", f.read_bytes())
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts)
