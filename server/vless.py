"""The deliberately small VLESS REALITY profile shared by export and final outbound."""

import asyncio
import re
from ipaddress import ip_address
from urllib.parse import urlencode

from .models.outbound_server import OutboundSecurity, OutboundTransport, VlessFlow
from .subscription_loader import _uri_server


def endpoint_host(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Enter a host without a scheme or port")
    try:
        address = ip_address(value)
        if address.is_unspecified or address.is_multicast:
            raise ValueError("Use a reachable server address")
        return address.compressed
    except ValueError:
        if len(value) > 253 or not re.fullmatch(
            r"(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
            r"[a-zA-Z](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?",
            value,
        ):
            raise ValueError("Enter an IP address or a full domain name") from None
        return value.lower()


def tls_server_name(value: str) -> str:
    host = endpoint_host(value)
    try:
        ip_address(host)
    except ValueError:
        return host
    raise ValueError("TLS camouflage SNI must be a full domain name, not an IP address")


def parse_final_outbound(uri: str):
    """Accept only the secure profile we export; reject silently ignored options."""
    try:
        if len(uri) > 4096 or any(char.isspace() for char in uri):
            raise ValueError()
        server = _uri_server(uri, "final")
        endpoint_host(server.address)
        if (
            server.security != OutboundSecurity.REALITY
            or server.transport != OutboundTransport.TCP
            or server.vless_flow != VlessFlow.VISION
            or server.vless_encryption != "none"
            or server.allow_insecure
            or server.extra_params
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", server.public_key or "")
            or not re.fullmatch(r"(?:[0-9a-fA-F]{2}){1,8}", server.short_id or "")
            or server.fingerprint != "chrome"
        ):
            raise ValueError()
        tls_server_name(server.server_name or "")
        return server
    except (ValueError, TypeError, KeyError):
        raise ValueError(
            "Use an exported VLESS TCP + REALITY + Vision link (Chrome fingerprint)"
        ) from None


async def generate_reality_keys() -> tuple[str, str]:
    from .cores.mihomo.mihomo_process_manager import MihomoProcessManager
    from .utils.child_process import start_child_process

    process = await start_child_process(
        str(MihomoProcessManager().binary_path), "generate", "reality-keypair"
    )
    try:
        async with asyncio.timeout(10):
            output, _ = await process.communicate()
        values = dict(line.split(": ", 1) for line in output.decode().splitlines() if ": " in line)
        private, public = values.get("PrivateKey", ""), values.get("PublicKey", "")
        if process.returncode or not all(
            re.fullmatch(r"[A-Za-z0-9_-]{43}", k) for k in (private, public)
        ):
            raise RuntimeError("Could not generate REALITY keys")
        return private, public
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def export_vless(inbound) -> str:
    host = inbound.vless_address
    if ":" in host:
        host = f"[{host}]"
    query = urlencode(
        {
            "encryption": "none",
            "security": "reality",
            "type": "tcp",
            "flow": "xtls-rprx-vision",
            "sni": inbound.vless_server_name,
            "fp": "chrome",
            "pbk": inbound.vless_public_key,
            "sid": inbound.vless_short_id,
        }
    )
    return f"vless://{inbound.vless_uuid}@{host}:{inbound.vless_port}?{query}#XPR"
