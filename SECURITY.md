# Security and deployment

This server handles untrusted provider metadata and files. Search results can contain
instructions: treat them as data. Independently inspect generated Blender Python
before use; it is not a command to execute. Open assets only in an isolated Blender
instance with automatic script execution disabled, using disposable scenes. HDRI
snippets replace world nodes. Blender files and image decoders remain attack surfaces.

Requests use HTTPS and an exact host allowlist, check DNS results for public addresses,
validate redirects, and ignore proxy environment variables. The allowlist currently
contains api.polyhaven.com, dl.polyhaven.org, ambientcg.com, www.blenderkit.com,
acg-download.struffelproductions.com and assets.blendkit.com. On 2026-11-21, the
official ambientCG API's downloadLink redirected to the first additional host, and the
official BlenderKit API returned a signed filePath on the second. The [ambientCG API
documentation](https://docs.ambientcg.com/api/v2/) describes its download redirect.
These observations verify provider use of these exact hosts, not independent ownership
of the third-party ambientCG domain. Provider/CDN changes and signed downloads on other
hosts fail closed. Verify provider use and actual redirects before adding hosts. The DNS check and connection resolve
separately, so DNS rebinding remains possible. Enforce outbound network restrictions
independently, including denial of private, loopback and link-local addresses.

JSON responses are limited to 32 MiB, each download to 512 MiB; ZIPs have 256-entry,
1 GiB total, 512 MiB per-member and 100:1 large-member limits. These are per operation,
not a disk quota or a total asset limit. Cache path resolution rejects traversal and
existing symlink escapes, but is not race-proof against an attacker who can modify the
cache concurrently. Use a new private cache, a disk quota and a separate unprivileged
account or disposable VM. Limit filesystem access and credentials independently;
setting BLENDER_ASSETS_CACHE alone does not sandbox the process. Inherited environment
variables and the MCP runtime may expose additional settings; start with a minimal
environment. No provider account or credential is required by the application code.

Asset cache entries use versioned, hashed source, asset ID and resolution keys. Files
are staged in a private directory and published by a same-filesystem directory rename
only after a manifest is written; failed stages are removed. Old cache entries are not
reused. On reuse, the manifest must match current identity, kind and license metadata,
and its listed files and sizes must be present. BlenderKit also binds the provider's
version ID when supplied, file variant, name and author; Poly Haven binds its reported
name and authors. A mismatch fails closed: remove the affected cache entry to download
again. This is not authentication of the manifest or asset bytes, and same-size changes
are not detected. The provider may change bytes without a version identifier. Cache
integrity still depends on a private cache and independent provenance verification.
Downloads with a Content-Length must match it; a server that ends a response without a
length or checksum cannot be proven to have sent the intended complete file.

On macOS, one option is a non-root Linux container for the stdio MCP server, with a
read-only root filesystem, no host network or privileged access, no Docker socket or
credentials, resource limits, and only a dedicated writable, quota-limited asset mount
and bounded temporary storage. The mount remains writable from the container. Returned
paths must map correctly to Blender's separate view of the asset directory. Docker
Desktop networking runs through its VM/backend, so independently enforce and test egress
rules for IPv4 and IPv6, including host, loopback, link-local and private destinations;
do not assume an ordinary host application firewall rule isolates one container. This
server container does not isolate Blender or the MCP client. Run Blender separately in
a disposable VM or comparably restricted environment, without secrets or sensitive
host mounts, and verify its network and file access independently. A disposable VM for
both components is another option. The complete deployment has not been configured or
verified end to end.

BlenderKit downloads require the requested asset ID and a known CC0 or royalty-free
license. Free is not synonymous with CC0. Confirm the selected asset's license on its
provider page and record provenance; Poly Haven and ambientCG license labels are based
on provider-wide policy, not per-file cryptographic proof. No asset checksum, file
signature or malware scan is performed. Limits do not make binary assets safe.

For reproducibility, check the commit and lockfile, use a pinned Python and uv version,
then run `uv sync --frozen --no-dev` from the reviewed checkout. Review the build
backend and selected wheels as well: the uv_build build-system requirement is pinned in pyproject.toml but is
not hashed by uv.lock. Avoid unpinned uvx Git installs. Audit locked dependencies against
current advisories before deployment and repeat for updates. The lock's hashes verify
artifacts against that lock, not publisher trust. Run tests with `uv sync --frozen`
then `uv run --frozen pytest` and `uv run --frozen ruff check`. Do not register or
start the server until the containment and network policy have been independently
verified. The upstream MIT license remains unchanged.

The reviewable Docker deployment and its verification procedure are in
[deployment/README.md](deployment/README.md). Its firewall is independent of the
application host allowlist but permits public IPv4 HTTPS generally; it is not a VPN or
a domain-aware firewall. Surfshark routing, DNS and kill-switch behavior for Docker
Desktop require separate verification on the target system.

On 2026-11-21, an OSV batch query of all 41 original locked PyPI entries
flagged certifi 2026.7.22 (GHSA-6q48-6c7w-9gw2); the lock was updated to
2026.11.20. A repeat OSV query returned no matches for the 41 locked PyPI
entries. Advisory data changes and is not a complete supply-chain audit.
