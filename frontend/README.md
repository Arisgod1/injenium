# Injenium Web Experience

The browser experience runs a React workspace beside a Python companion that
reuses Injenium's Recipe model, Go2 whitelist, sandbox interpreter, and mock
chain. The companion cannot sign EVM transactions; real testnet or mainnet
writes are signed only by an injected browser wallet.

## Development

From the repository root:

```bash
uv venv --python 3.12 frontend/.venv
uv pip install --python frontend/.venv/bin/python -e . -r frontend/server/requirements.txt
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to the companion on port
8000. Copy `.env.example` to `.env` only when overriding public network or IPFS
configuration; never put a wallet key in either file.

`INJENIUM_DEMO_MAX_INJ` defaults to `0.1` and may be lowered for a deployment;
the companion rejects malformed, non-finite, zero, negative, and over-limit
amounts before changing the demo ledger.

## Production

```bash
docker build -f frontend/Dockerfile -t injenium-web .
docker run --rm -p 8000:8000 injenium-web
```

All `VITE_*` values are public build-time configuration. For example, an
audited mainnet deployment must pass both
`--build-arg VITE_MAINNET_MARKET_ADDRESS=0x...` and
`--build-arg VITE_ENABLE_MAINNET_WRITES=true`; runtime companion settings are
passed with `docker run -e`.

The production companion serves the built SPA and API from one origin. Mainnet
writes remain disabled unless both `VITE_MAINNET_MARKET_ADDRESS` and
`VITE_ENABLE_MAINNET_WRITES=true` are present at build time. Any change to the
market contract must keep `contracts/src/Market.sol`,
`injenium/core/chain/client.py::MARKET_ABI`, and
`frontend/src/chain.ts::marketAbi` in lockstep.

## Verification

No unit tests are added. The release checks are:

```bash
npm run lint
npm run build
npm run test:e2e
frontend/.venv/bin/python -m compileall -q frontend/server
frontend/.venv/bin/python frontend/server/smoke.py
python demo/demo_m4_mock_loop.py --db /nonexistent
```
