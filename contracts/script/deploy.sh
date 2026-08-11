#!/usr/bin/env bash
# Deploy Market.sol to Injective EVM and verify on Blockscout.
#
# Prerequisites:
#   - Foundry (forge) installed
#   - A funded deployer key exported (NEVER commit it):
#       export INJECTIVE_PRIVATE_KEY=0x...
#   - Network access to the Injective EVM RPC
#
# Usage:
#   contracts/script/deploy.sh testnet     # chain id 1439 (default)
#   contracts/script/deploy.sh mainnet     # chain id 1776
#
# RPC + verifier endpoints come from contracts/foundry.toml
# ([rpc_endpoints] / [etherscan]); this script only selects the network.
set -euo pipefail

NET="${1:-testnet}"
case "$NET" in
  testnet)
    RPC_ALIAS="injectiveTestnet"
    RPC_URL="https://k8s.testnet.json-rpc.injective.network/"
    CHAIN_ID="1439"
    EXPLORER="https://testnet.blockscout.injective.network"
    VERIFIER_URL="https://testnet.blockscout-api.injective.network/api"
    ;;
  mainnet)
    RPC_ALIAS="injectiveMainnet"
    RPC_URL="https://sentry.evm-rpc.injective.network/"
    CHAIN_ID="1776"
    EXPLORER="https://blockscout.injective.network"
    VERIFIER_URL="https://blockscout-api.injective.network/api"
    ;;
  *) echo "usage: $0 [testnet|mainnet]" >&2; exit 2 ;;
esac

: "${INJECTIVE_PRIVATE_KEY:?set INJECTIVE_PRIVATE_KEY to a funded deployer key}"

# Run from the contracts/ root (where foundry.toml lives).
cd "$(cd "$(dirname "$0")/.." && pwd)"

echo "== forge build =="
forge build

echo "== deploying src/Market.sol:Market to ${NET} (${RPC_ALIAS}) =="
forge create src/Market.sol:Market \
  --rpc-url "$RPC_ALIAS" \
  --private-key "$INJECTIVE_PRIVATE_KEY" \
  --broadcast \
  --verify --verifier blockscout \
  --verifier-url "$VERIFIER_URL"

cat <<EOF

Done. Wire the agent to the deployed address (both modules need it):

  dimos run injenium.market \\
    --marketskillcontainer.chain-backend injective \\
    --marketskillcontainer.market-contract <ADDRESS> \\
    --marketskillcontainer.chain-id ${CHAIN_ID} \\
    --marketskillcontainer.rpc-url ${RPC_URL} \\
    --requestlistener.chain-backend injective \\
    --requestlistener.market-contract <ADDRESS> \\
    --requestlistener.chain-id ${CHAIN_ID} \\
    --requestlistener.rpc-url ${RPC_URL}

Verify on Blockscout: ${EXPLORER}/address/<ADDRESS>
EOF
