"""HTTP, cache and path helpers shared by the asset sources."""
import errno
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__

USER_AGENT = f"blender-assets-mcp/{__version__} (+https://github.com/TimotheFCN/blender-assets-mcp)"
KINDS = ("model", "material", "hdri")
CC0 = "CC0 1.0 (public domain, no attribution required)"


def cache_dir() -> Path:
    if override := os.environ.get("BLENDER_ASSETS_CACHE"):
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "blender-assets"


# Exact hosts only; unknown provider/CDN changes fail closed.
ALLOWED_HOSTS = {
    "api.polyhaven.com", "dl.polyhaven.org", "ambientcg.com", "www.blenderkit.com",
    "acg-download.struffelproductions.com", "assets.blendkit.com",
}
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024


def validate_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS
            or parts.username is not None or parts.password is not None
            or parts.port not in (None, 443)):
        raise ValueError("refusing unapproved network destination")
    addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("refusing non-public network destination")


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url: str, timeout: int):
    validate_url(url)
    # Ignore inherited proxy configuration; redirects go through the same policy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RestrictedRedirect())
    return opener.open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


def copy_limited(src, dst, limit: int) -> int:
    total = 0
    while chunk := src.read(min(1024 * 1024, limit + 1 - total)):
        total += len(chunk)
        if total > limit:
            raise ValueError("response exceeds size limit")
        dst.write(chunk)
    return total


def get_json(url: str, params: dict | None = None) -> dict:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with open_url(url, 30) as resp:
        data = resp.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            raise ValueError("JSON response exceeds size limit")
        return json.loads(data)


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with open_url(url, 120) as resp, tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            size = copy_limited(resp, tmp, MAX_DOWNLOAD_BYTES)
            length = getattr(resp, "headers", {}).get("Content-Length")
            if length is not None and size != int(length):
                raise ValueError("incomplete download")
        tmp_path.replace(dest)
        return dest
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def inside(root: Path, rel: str) -> Path:
    """Resolve a server-supplied relative path, refusing anything outside root."""
    path = (root / rel).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"refusing path outside the asset folder: {rel}")
    return path


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._") or "asset"


def url_filename(url: str) -> str:
    return safe_name(Path(urllib.parse.urlparse(url).path).name)


def asset_dir(source: str, asset_id: str, resolution: str) -> Path:
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    return inside(cache_dir(), f"{safe_name(source)}/v2/{digest(source)}/{digest(asset_id)}/{digest(resolution)}")


def cached_asset(source: str, asset_id: str, resolution: str, metadata: dict, populate,
                 *, allow_directory: bool = False) -> tuple[Path, str]:
    """Publish a complete asset directory once, then verify its identity and contents on reuse."""
    root = asset_dir(source, asset_id, resolution)
    expected = {"source": source, "id": asset_id, "resolution": resolution, **metadata}

    def read_entry() -> tuple[Path, str]:
        try:
            manifest = json.loads((root / "manifest.json").read_text())
            if manifest["identity"] != expected:
                raise ValueError("cached asset identity or license mismatch")
            data = root / "data"
            files = manifest["files"]
            if not isinstance(files, dict) or not files:
                raise ValueError("cached asset has no files")
            for rel, size in files.items():
                path = inside(data, rel)
                if not path.is_file() or path.stat().st_size != size:
                    raise ValueError("cached asset is incomplete")
            if {str(p.relative_to(data)) for p in data.rglob("*") if p.is_file()} != set(files):
                raise ValueError("cached asset contents changed")
            main = manifest["main"]
            if not isinstance(main, str) or (not main and not allow_directory) or (main and main not in files):
                raise ValueError("cached asset main file is missing")
            return data, main
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid or incomplete cached asset") from exc

    if root.exists():
        return read_entry()
    root.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".asset-", dir=root.parent))
    try:
        data = stage / "data"
        data.mkdir()
        main = populate(data)
        files = {str(p.relative_to(data)): p.stat().st_size for p in data.rglob("*") if p.is_file()}
        if not files or not isinstance(main, str) or (not main and not allow_directory) or (main and main not in files):
            raise ValueError("asset download is incomplete")
        (stage / "manifest.json").write_text(json.dumps({"identity": expected, "main": main, "files": files}))
        try:
            stage.rename(root)
        except OSError as exc:
            if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
        return read_entry()
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def words_matched(words: list[str], text: str) -> int:
    """Count query words found in a word of text, or sharing its stem ("wooden" matches "wood")."""
    tokens = {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 3}
    return sum(any(w in t or w.startswith(t) for t in tokens) for w in words)
