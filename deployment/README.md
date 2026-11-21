# Docker deployment review: Apple Silicon

The server is behind an explicit Compose profile so plain `docker compose up` does not
start it. Review the configuration and complete the checks below before an online run.

## Design and limits

`Dockerfile` copies the reviewed local source and installs runtime dependencies from
`uv.lock` with `uv sync --frozen --no-dev --no-install-project`. Python and uv base
images use immutable digests. The firewall base is also digest-pinned, and its direct
iptables package is version-pinned. Its transitive Alpine packages and repository are
not locked by `uv.lock`; review the built image, package provenance and advisories.
Builds need registry and package network access. A digest identifies an artifact; it
does not establish trust in its publisher. Rebuild after reviewing updates.

The server uses UID/GID 65532, a read-only root, no Linux capabilities, no privilege
escalation, bounded memory/CPU/PIDs, and a 768 MiB temporary filesystem. Its only host
mount is the dedicated asset directory. Docker Desktop still shares that directory with
the container; compromised container code can modify it. The firewall sidecar has
`NET_ADMIN` in its own network namespace but has no asset mount or Docker socket. The
server shares that namespace without receiving `NET_ADMIN`. Docker's default seccomp
profile remains enabled. No host networking or ports are configured.

The sidecar installs default-deny IPv4 and IPv6 rules before it becomes healthy. It
allows the Docker embedded DNS resolver, blocks private, loopback, link-local and other
listed special IPv4 ranges, allows remaining IPv4 TCP/443, and denies IPv6. This is an
independent IP/port boundary, **not a domain allowlist**. The application's HTTPS host
allowlist is a separate layer. DNS can disclose queried names to the configured resolver;
the firewall does not validate DNS answers. The list of special IPv4 ranges must be
maintained, and alternate Docker networking/DNS implementations may require changes.
The health check gates initial startup; it is not continuous external attestation. If the
sidecar stops or goes unhealthy, stop the server and investigate before restarting it.

This does not isolate the MCP client or Blender. Use a separately isolated Blender with
automatic script execution disabled and disposable scenes. Review generated code and
files before use, and keep credentials and sensitive mounts out of both environments.

### Provisioning Blender separately

This repository does not provision a Blender VM or a Blender MCP server. To prepare one:

1. Create a disposable GUI VM on Apple Silicon using an ARM64 guest OS and an updated
   Blender build compatible with that guest. Confirm that the VM's graphics support is
   adequate; software rendering may be required. Configure CPU, memory and disk limits.
2. Use a separate unprivileged guest account. Do not share the host home directory,
   credentials, Docker socket, SSH agent, clipboard or other unnecessary devices. Keep
   the VM offline during asset inspection, or independently deny its network access.
   Take a clean snapshot before importing untrusted files.
3. Transfer only the intended asset files into the guest, or expose just the required
   cache directory as a read-only share. Map it at the same absolute path used in the
   returned code, or independently review and adjust paths for the guest. A read-only
   share prevents guest writes but does not make the files safe.
4. Disable Blender's automatic Python execution, including trusted-file exceptions;
   launch with `--disable-autoexec` as an additional override. Use disposable scenes.
   Review any generated Python separately before running it: disabling auto-execution
   does not prevent a user or tool from manually executing code.
5. Verify isolation and path mapping before importing an asset. If automated Blender
   control is desired, separately design and review a narrowly scoped connection to
   the guest; do not expose an unrestricted Python execution endpoint on the host or
   LAN. Restore the clean snapshot when the trial is finished.

## Prepare storage and inspect

1. Provision a dedicated private, size-limited host filesystem for the cache, such as
   a quota-limited APFS volume or a fixed-capacity mounted disk image. Docker's tmpfs
   limit is separate; the bind mount itself has no quota. Limit Docker Desktop's VM disk
   and other resources as well. Choose a path under that volume, not `/app`, `/tmp`, a
   system path, or a directory containing other files. Create the directory with mode
   0700 and confirm Docker Desktop can share it. Do not reuse an untrusted old cache.
2. In a shell at the reviewed checkout, set an **absolute** path, for example:

   ```sh
   export ASSET_CACHE_DIR=/Volumes/BlenderAssets/cache
   ```

3. Review `Dockerfile`, `compose.yaml`, `deployment/firewall.sh`, the image digests,
   source and lockfile. Review the rendered configuration with `docker compose config`.
   Run `docker compose build` only when registry/package access is acceptable. Building
   does not start the MCP server. The build context excludes unrelated files.

## Verify without starting the server

After reviewing the firewall configuration, the following starts **only** its sidecar:

```sh
docker compose up -d --no-build firewall
docker compose ps
docker compose exec firewall iptables -S OUTPUT
docker compose exec firewall ip6tables -S OUTPUT
```

The sidecar must be healthy, IPv4 OUTPUT must end in the intended TCP/443 accept with
all listed deny rules before it, and IPv6 OUTPUT must have a DROP policy. Run the
non-server probe in its namespace:

```sh
docker run --rm -i --network "container:$(docker compose ps -q firewall)" \
  --user 65532:65532 --cap-drop ALL --security-opt no-new-privileges \
  --read-only --entrypoint /app/.venv/bin/python blender-assets-server:local \
  - < deployment/probe.py
docker compose exec firewall iptables -L OUTPUT -n -v -x
docker compose exec firewall ip6tables -L OUTPUT -n -v -x
```

The probe contacts `example.com` for DNS and opens a TCP connection to `1.1.1.1:443`;
it does not contact asset providers. It attempts loopback, private, link-local, CGNAT and
IPv6 connections. A timeout alone does not prove firewall enforcement: confirm that the
corresponding DROP counters increment. DNS and the public connection must also work.
Test other relevant Docker host/gateway, LAN and IPv6 addresses and non-443 ports, and
repeat after Docker or network-policy changes. A public network outage can make the
positive check fail without proving the firewall is correct.

Check mount permissions separately, without running the server:

```sh
docker run --rm --network none --user 65532:65532 --cap-drop ALL \
  --security-opt no-new-privileges --read-only \
  --mount "type=bind,src=$ASSET_CACHE_DIR,dst=$ASSET_CACHE_DIR" \
  --env "ASSET_CACHE_DIR=$ASSET_CACHE_DIR" \
  --entrypoint /app/.venv/bin/python blender-assets-server:local \
  -c 'import os,tempfile; f=tempfile.NamedTemporaryFile(dir=os.environ["ASSET_CACHE_DIR"]); print("cache writable"); f.close()'
```

On Docker Desktop, host file sharing determines how container UIDs map to host access.
If the probe fails, fix the volume's ownership or sharing configuration; do not make a
sensitive directory world-writable. Inspect the created container configuration when
later authorized: verify read-only root, the sole bind mount, capabilities, resource
limits, no published ports, and the shared firewall network namespace.

## Surfshark and Docker Desktop

Docker Desktop routes container connections through its host backend. A working probe
does not establish that Surfshark tunnels that traffic, that DNS uses the intended
resolver, or that its kill switch covers Docker Desktop. Review Surfshark Bypasser and
Docker Desktop proxy settings for exclusions. If VPN routing is required, independently
compare the probe container's observed public egress and DNS behavior with the expected
VPN route, then test a VPN interruption and kill-switch behavior in a controlled window.
Do not disrupt an active VPN session merely to run this check. Repeat after VPN, Docker,
or macOS updates. If enforcement cannot be established, do not run the server online.

## Asset paths and eventual operation

The bind mount uses the same absolute `ASSET_CACHE_DIR` path on the host and in the
server, so generated paths refer to the host cache. For Blender in a separate VM or
container, expose only the specific reviewed asset directory at the **same absolute
path**, preferably read-only. If that mapping is unavailable, copy approved files into
the isolated Blender environment and update the reviewed snippet to its local paths;
do not expose the full host home directory. Mounting files does not make them safe.

After review and all checks, `deployment/launch.sh` starts an explicitly authorized
stdio session and its firewall dependency. Set `ASSET_CACHE_DIR` to the mounted
`/Volumes/<volume>/cache`; the launcher fails if the volume is not mounted. After a
reboot, attach the dedicated disk image again before launching. The launcher does not
register an MCP client. Stop the sidecar when finished with `docker compose -p
blender-assets-trial down`. Provider/CDN hosts and redirect chains still need independent
verification before allowing any additional hosts.
