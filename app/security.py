import base64
import hashlib
import hmac
import ipaddress
import secrets
import socket
from urllib.parse import urlsplit


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
    return base64.b64encode(salt + digest).decode()


def password_valid(password, encoded):
    raw = base64.b64decode(encoded)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), raw[:16], 310000)
    return hmac.compare_digest(raw[16:], digest)


def validate_url(url, allow_local=False, allow_query=False):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("服务地址必须是无用户名和密码的 HTTP(S) 地址")
    if not allow_query and (parts.query or parts.fragment):
        raise ValueError("服务基础地址不能包含查询参数或片段")
    try:
        addresses = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("无法解析服务地址") from exc
    for addr in addresses:
        ip = ipaddress.ip_address(addr[4][0])
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise ValueError("服务地址指向不允许的网络地址")
        if not allow_local and not ip.is_global:
            raise ValueError("本地服务需要勾选“允许局域网服务”")
    if parts.scheme != "https" and not allow_local:
        raise ValueError("云端服务请使用 HTTPS；本地 HTTP 需要允许局域网服务")
    return url.rstrip("/")
