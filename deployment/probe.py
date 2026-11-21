"""Probe the firewall namespace without starting the MCP server."""
import socket


def blocked(host, family=socket.AF_INET):
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        sock.connect((host, 443))
    except OSError as exc:
        print(f"{host}: connection blocked or unreachable ({type(exc).__name__})")
    else:
        raise SystemExit(f"FAIL: connected to {host}:443")
    finally:
        sock.close()


for address in ("127.0.0.1", "10.0.0.1", "100.64.0.1", "169.254.169.254", "172.16.0.1", "192.168.0.1"):
    blocked(address)
blocked("::1", socket.AF_INET6)
print("DNS:", socket.getaddrinfo("example.com", 443, family=socket.AF_INET)[0][4][0])
with socket.create_connection(("1.1.1.1", 443), timeout=5):
    print("Public IPv4 TCP/443: connected")
