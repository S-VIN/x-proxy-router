"""Export/import, persistence, real REALITY traffic and fail-closed chaining."""

import asyncio
import json
import secrets
import socket
import ssl
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from server.cores.mihomo.mihomo_client import MihomoClient, inbound_config
from server.models import InboundServer, InboundType, RoutingAction, RoutingRule
from server.models.serialization import serialize
from server.models.server_settings import ServerSettings
from server.settings_store import SettingsStore
from server.vless import export_vless, generate_reality_keys, parse_final_outbound


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def vless(**kwargs):
    private, public = await generate_reality_keys()
    return InboundServer(
        type=InboundType.VLESS,
        vless_port=free_port(),
        vless_listen="127.0.0.1",
        vless_address="127.0.0.1",
        vless_server_name="camouflage.example.com",
        vless_uuid=str(uuid4()),
        vless_private_key=private,
        vless_public_key=public,
        vless_short_id=secrets.token_hex(8),
        **kwargs,
    )


class VlessTests(unittest.IsolatedAsyncioTestCase):
    async def test_roundtrip_secrets_and_persistence(self):
        inbound = await vless()
        uri = export_vless(inbound)
        parsed = parse_final_outbound(uri)
        self.assertEqual(str(parsed.vless_uuid), inbound.vless_uuid)
        self.assertEqual(parsed.public_key, inbound.vless_public_key)
        self.assertEqual(parsed.short_id, inbound.vless_short_id)
        self.assertNotIn(inbound.vless_private_key, uri)
        self.assertNotIn(inbound.vless_uuid, json.dumps(serialize(inbound)))
        settings = ServerSettings(final_outbound_uri=uri, final_outbound_enabled=True)
        self.assertNotIn(uri, json.dumps(serialize(settings)))
        self.assertNotIn(uri, repr(settings))
        with TemporaryDirectory() as directory:
            with SettingsStore(Path(directory)) as store:
                store.inbound_server.save(inbound)
                store.server_settings.save(settings)
            with SettingsStore(Path(directory)) as store:
                self.assertEqual(store.inbound_server.get_by_id(inbound.id), inbound)
                self.assertEqual(store.server_settings.get(), settings)
        ipv6 = replace(inbound, vless_address="2001:db8::1")
        self.assertEqual(parse_final_outbound(export_vless(ipv6)).address, "2001:db8::1")
        for bad in (
            uri.replace("security=reality", "security=none"),
            uri + "&unknown=1",
            uri.replace("fp=chrome", "fp=invalid"),
            uri.replace("type=tcp", "type=ws"),
        ):
            # Query must go before the fragment.
            bad = bad.replace("#XPR&unknown=1", "&unknown=1#XPR")
            with self.assertRaises(ValueError):
                parse_final_outbound(bad)
        with self.assertRaises(ValueError):
            ServerSettings(
                outbound_mode="server", final_outbound_enabled=True, final_outbound_uri=uri
            )

    async def test_egress_rollback(self):
        client = MihomoClient()
        old = client._egress
        with (
            patch.object(client, "_require_started"),
            patch.object(client, "_apply", AsyncMock(side_effect=RuntimeError)),
            self.assertRaises(RuntimeError),
        ):
            await client.egress_set(ServerSettings(outbound_mode="server"))
        self.assertEqual(client._egress, old)

    async def test_real_two_hops_rotation_and_no_bypass(self):
        # A local TLS 1.3 camouflage site makes this test independent of public websites.
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()

        def handle_exception(loop, context):
            if isinstance(context.get("exception"), ConnectionResetError):
                return
            if previous_handler:
                previous_handler(loop, context)
            else:
                loop.default_exception_handler(context)

        loop.set_exception_handler(handle_exception)
        self.addCleanup(loop.set_exception_handler, previous_handler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_3
        tls.load_cert_chain(Path(__file__).with_name("localhost.pem"))
        writers = []

        async def camouflage(reader, writer):
            writers.append(writer)
            await reader.read(4096)
            writer.close()

        cover = await asyncio.start_server(camouflage, "127.0.0.1", 0, ssl=tls)
        self.addAsyncCleanup(cover.wait_closed)
        self.addCleanup(cover.close)
        cover_port = cover.sockets[0].getsockname()[1]

        def local_config(inbound):
            config = inbound_config(inbound)
            if inbound.type == InboundType.VLESS:
                config["reality-config"]["dest"] = f"127.0.0.1:{cover_port}"
            return config

        self.enterContext(
            patch("server.cores.mihomo.mihomo_client.inbound_config", side_effect=local_config)
        )

        async def echo(reader, writer):
            writers.append(writer)
            try:
                while data := await reader.read(1024):
                    writer.write(b"exit:" + data)
                    await writer.drain()
            finally:
                writer.close()

        target = await asyncio.start_server(echo, "127.0.0.1", 0)
        self.addAsyncCleanup(target.wait_closed)
        self.addCleanup(target.close)
        target_port = target.sockets[0].getsockname()[1]
        client, first, final = MihomoClient(), MihomoClient(), MihomoClient()
        for core in (client, first, final):
            await core.service_start()
            self.addAsyncCleanup(core.service_stop)
        first_in = await vless()
        second_first_in = await vless()
        final_in = await vless()
        await first.egress_set(ServerSettings(outbound_mode="server"))
        await first.inbound_set(first_in)
        await first.inbound_set(second_first_in)
        await final.egress_set(ServerSettings(outbound_mode="server"))
        await final.inbound_set(final_in)
        hop1 = parse_final_outbound(export_vless(first_in))
        hop2 = parse_final_outbound(export_vless(second_first_in))
        await client.outbound_register([hop1, hop2])
        local = InboundServer(type=InboundType.PROXY, proxy_port=free_port())
        await client.inbound_set(local)
        await client.routing_set([RoutingRule(priority=1, reg="*", action=RoutingAction.DIRECT)])
        settings = ServerSettings(
            final_outbound_enabled=True, final_outbound_uri=export_vless(final_in)
        )
        await client.egress_set(settings)

        async def exchange(expect_success):
            async with asyncio.timeout(8):
                reader, writer = await asyncio.open_connection("127.0.0.1", local.proxy_port)
                writers.append(writer)
                writer.write(b"\x05\x01\x00")
                await writer.drain()
                self.assertEqual(await reader.readexactly(2), b"\x05\x00")
                writer.write(b"\x05\x01\x00\x01\x7f\x00\x00\x01" + target_port.to_bytes(2, "big"))
                await writer.drain()
                reply = await reader.readexactly(4)
                await reader.readexactly(6 if reply[3] == 1 else 18)
                writer.write(b"ping")
                await writer.drain()
                try:
                    result = await reader.read(9)
                except ConnectionResetError:
                    result = b""
                self.assertEqual(result, b"exit:ping" if expect_success else b"")
                writer.close()

        await exchange(False)  # No first hop, despite a MATCH,DIRECT rule.
        await client.outbound_connect(hop1.id)
        await exchange(True)

        # UDP must follow the same two-hop chain, not escape through DIRECT.
        class EchoDatagram(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, addr):
                self.transport.sendto(b"udp:" + data, addr)

        udp_transport, _ = await loop.create_datagram_endpoint(
            EchoDatagram, local_addr=("127.0.0.1", 0)
        )
        self.addCleanup(udp_transport.close)
        udp_target_port = udp_transport.get_extra_info("sockname")[1]
        async with asyncio.timeout(8):
            udp_reader, udp_writer = await asyncio.open_connection("127.0.0.1", local.proxy_port)
            writers.append(udp_writer)
            udp_writer.write(b"\x05\x01\x00")
            await udp_writer.drain()
            self.assertEqual(await udp_reader.readexactly(2), b"\x05\x00")
            udp_writer.write(b"\x05\x03\x00\x01" + bytes(6))
            await udp_writer.drain()
            reply = await udp_reader.readexactly(10)
            self.assertEqual(reply[:2], b"\x05\x00")
            udp_port = int.from_bytes(reply[-2:], "big")
            with socket.socket(type=socket.SOCK_DGRAM) as sock:
                sock.setblocking(False)
                packet = (
                    b"\x00\x00\x00\x01\x7f\x00\x00\x01"
                    + udp_target_port.to_bytes(2, "big")
                    + b"ping"
                )
                await loop.sock_sendto(sock, packet, ("127.0.0.1", udp_port))
                data, _ = await loop.sock_recvfrom(sock, 1024)
                self.assertEqual(data[10:], b"udp:ping")
            udp_writer.close()
        await client.outbound_connect(hop2.id)
        await exchange(True)  # Rotating first hops retains the final hop.
        await final.inbound_delete(final_in.id)
        await exchange(False)  # No silent fallback when final is down.
        await client.egress_set(replace(settings, final_outbound_enabled=False))
        await exchange(True)  # Original direct routing restored.
        await client.egress_set(ServerSettings(outbound_mode="server"))
        await client.outbound_disconnect()
        await exchange(True)  # Server needs neither subscriptions nor first hop.
        for writer in writers:
            writer.close()
