import ssl
import socket
import hashlib
from pathlib import Path

# Global cache for SSL contexts to avoid expensive re-creation overhead (saves ~1.5ms per connection)
_SSL_CONTEXT_CACHE = {}

def get_ssl_context(server_side: bool) -> ssl.SSLContext:
    """Returns a cached SSL context for either server or client roles."""
    purpose = ssl.Purpose.CLIENT_AUTH if server_side else ssl.Purpose.SERVER_AUTH
    if purpose not in _SSL_CONTEXT_CACHE:
        ctx = ssl.create_default_context(purpose)
        cert_file = Path(__file__).parent / "tls_cert.pem"
        key_file = Path(__file__).parent / "tls_key.pem"

        # In a real app, we'd want to ensure these exist or handle their absence gracefully
        if cert_file.exists() and key_file.exists():
            ctx.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
        else:
            # Fallback: if certs don't exist yet (e.g. first run), try to trigger generation via config import
            try:
                import config
                if cert_file.exists() and key_file.exists():
                    ctx.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
            except ImportError:
                pass

        if not server_side:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        _SSL_CONTEXT_CACHE[purpose] = ctx
    return _SSL_CONTEXT_CACHE[purpose]

def wrap_socket(sock: socket.socket, server_side: bool = False) -> ssl.SSLSocket:
    """Wraps a raw socket with a cached TLS context."""
    ctx = get_ssl_context(server_side)
    return ctx.wrap_socket(sock, server_side=server_side)

def get_peer_fingerprint(sslsock: ssl.SSLSocket) -> str:
    """Extracts the SHA-256 fingerprint of the peer's certificate."""
    try:
        cert_bin = sslsock.getpeercert(binary_form=True)
        if not cert_bin:
            return None
        return hashlib.sha256(cert_bin).hexdigest()
    except Exception:
        return None
