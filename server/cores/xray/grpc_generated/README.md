# Xray protobuf bindings

Generated from the official [Xray-core v26.3.27 source](https://github.com/XTLS/Xray-core/tree/v26.3.27).
Upstream license is included in LICENSE. Do not edit generated Python files manually.

Includes HandlerService, RoutingService, SOCKS, VLESS outbound, Shadowsocks, Shadowsocks 2022, Hysteria, freedom, blackhole,
and common transport settings. These are wire-format models, not JSON config models.

To regenerate from the repository root using Python 3.11+ (no venv or installed pip required):

```sh
python scripts/generate_grpc.py
```

The script downloads build dependencies and the pinned Xray source into a temporary
directory, which is removed on exit. Internet access is required. It does not install
packages into system Python. Runtime dependencies for the server remain in
`server/requirements.txt`.

To use an existing source checkout instead of downloading Xray:

```sh
python scripts/generate_grpc.py /path/to/Xray-core
```

Paths to output files are relative to the script, so the working directory does not matter.
The generator selects the required schemas and their imports, creates Python code
and type stubs, and qualifies Python imports under `server.cores.xray.grpc_generated`.
Protobuf package names and wire descriptors retain their original Xray names.
No sys.path changes or generation at application startup are required.

Update the schemas together with Xray binaries and rerun integration tests.
