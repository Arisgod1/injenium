FROM node:22-alpine AS web
WORKDIR /app/frontend
ARG VITE_TESTNET_RPC_URL=https://k8s.testnet.json-rpc.injective.network/
ARG VITE_TESTNET_MARKET_ADDRESS=0x641549D4c1ea67E16c84c996065629Df0AA34399
ARG VITE_MAINNET_RPC_URL=https://sentry.evm-rpc.injective.network/
ARG VITE_MAINNET_MARKET_ADDRESS=
ARG VITE_ENABLE_MAINNET_WRITES=false
ARG VITE_MAX_TRANSACTION_INJ=0.1
ARG VITE_MIN_GAS_RESERVE_INJ=0.01
ENV VITE_TESTNET_RPC_URL=$VITE_TESTNET_RPC_URL \
    VITE_TESTNET_MARKET_ADDRESS=$VITE_TESTNET_MARKET_ADDRESS \
    VITE_MAINNET_RPC_URL=$VITE_MAINNET_RPC_URL \
    VITE_MAINNET_MARKET_ADDRESS=$VITE_MAINNET_MARKET_ADDRESS \
    VITE_ENABLE_MAINNET_WRITES=$VITE_ENABLE_MAINNET_WRITES \
    VITE_MAX_TRANSACTION_INJ=$VITE_MAX_TRANSACTION_INJ \
    VITE_MIN_GAS_RESERVE_INJ=$VITE_MIN_GAS_RESERVE_INJ
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY injenium/ ./injenium/
COPY frontend/server/ ./frontend/server/
COPY frontend/server/requirements.txt ./frontend/server/requirements.txt
COPY --from=web /app/frontend/dist ./frontend/dist
RUN pip install --no-cache-dir . -r frontend/server/requirements.txt
RUN groupadd --system injenium && useradd --system --gid injenium --home-dir /nonexistent injenium
USER injenium
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/status', timeout=3)"
CMD ["python", "-m", "uvicorn", "server.app:app", "--app-dir", "frontend", "--host", "0.0.0.0", "--port", "8000"]
