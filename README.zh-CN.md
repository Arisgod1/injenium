# Injenium · 灵枢

[English](README.md) | [简体中文](README.zh-CN.md)

**Injenium（灵枢）** 是面向具身智能体的链上技能经济。它把录制经验转换为去隐私、参数化的 `Recipe` 数据，支持请求、报价、白名单沙箱验证、执行，并通过 Injective EVM 托管完成结算。

市场内核与具体形态无关。`injenium.core` 负责配方、存储、身份、沙箱、市场流程、链客户端和 blueprint 组装。各种具身形态以 `injenium.domains.<domain>` 领域插件接入；参考实现是 `injenium.domains.go2` 中的 Unitree Go2。新增机器狗、无人机、人形机器人或纯软件 agent 不需要修改核心逻辑，详见 [INTEGRATION.md](INTEGRATION.md)。

主要目标链是 Injective EVM 测试网，Chain ID 为 `1439`。仓库提供实现相同 `ChainClient` 协议的文件型 mock chain，因此可以在部署或为钱包充值前完成完整市场闭环。

## 浏览器体验台

`frontend/` 是面向没有 dimOS 或机器人的中文交互体验台，包含：

- 技能市场，以及一键验证和装载 Recipe；
- 白名单沙箱模拟器，Canvas 展示机器人路径和逐步执行结果；
- 悬赏双边市场，覆盖请求、报价、验收、执行、放款、评分和退款；
- 本地体验、Injective 测试网和只读主网模式；
- JSON 和受控 `ipfs://` Recipe 装载；
- 仅在浏览器中完成的 EIP-1193 钱包签名、待确认交易恢复和主网写入保护；
- 不接收私钥、助记词或签名权限的 FastAPI companion。

在仓库根目录运行：

```bash
uv venv --python 3.12 frontend/.venv
uv pip install --python frontend/.venv/bin/python -e . -r frontend/server/requirements.txt
cd frontend
npm install
npm run dev
```

打开 <http://127.0.0.1:5173>；companion API 在 <http://127.0.0.1:8000>。环境变量、Docker 部署、API 边界和 ABI 同步规则见 [frontend/README.md](frontend/README.md)，产品和视觉规范见 [PRODUCT.md](PRODUCT.md) 与 [DESIGN.md](DESIGN.md)。

## 市场技能

无头 dimOS 接口通过 `dimos mcp list-tools` 和 `dimos mcp call` 提供只读检查、悬赏结算、技能销售和执行控制：

| 技能 | 作用 |
| --- | --- |
| `chain_status()` | 只读检查钱包、余额、网络、RPC 和待确认交易。 |
| `list_requests()` | 浏览请求 ID、需求、预算和请求方。 |
| `list_offers(request_id)` | 浏览报价、应答方、价格和 Recipe 哈希。 |
| `search_skills(query)` | 在创建新悬赏前搜索在售技能。 |
| `set_auto_publish(enabled)` | 自动挂牌成功完成的技能。 |
| `publish_skill(description, price, query)` | 从已完成经验蒸馏并挂牌为可复用数据商品。 |
| `publish_request(need, budget)` | 创建困难请求，并把预算锁入托管。 |
| `distill_and_publish(request_id, query)` | 蒸馏去隐私 Recipe，并携带内容哈希提交报价。 |
| `fetch_and_run(offer_id)` | 在验收 URI、哈希和白名单权限后接受并执行。 |
| `buy_and_run(listing_id)` | 在付款前验证挂牌 Recipe，然后付款并执行。 |
| `pay(offer_id)` | 成功执行后释放托管并写入评分。 |
| `stop_run()` | 在 primitive 步骤之间协作式停止后台 Recipe 执行。 |

`fetch_and_run` 和 `buy_and_run` 会在哈希不匹配或 primitive 不安全时直接拒绝，不触碰链上状态。开放请求可以立即取消；已经接受但未结算的请求在合约超时后可以退款。`RequestListener` 会轮询请求和报价，在双方需要处理时提醒 agent。

## 目录结构

- `injenium/core/`：配方、沙箱、身份、存储、市场和链客户端。
- `injenium/domains/go2/`：Go2 primitive 白名单、provider、蒸馏器和 blueprint。
- `contracts/src/Market.sol`：Injective EVM 市场合约。
- `frontend/`：React/Vite 体验台与 FastAPI companion，不保存链私钥。
- `demo/`：M2-M5 手动端到端演示。
- `INTEGRATION.md`：机器及新具身形态接入指南。
- `TESTING.md`：mock、Anvil、测试网和接口级验收流程。
- `TESTNET_NOTES.md`：测试网部署和 RPC 记录。

Solidity 合约、Python `MARKET_ABI` 和 `frontend/src/chain.ts` 中的前端 ABI 必须保持同步。

## 安装和无头运行

使用提供 dimOS 的 Python 环境，支持 Python 3.10-3.12：

```bash
pip install -e '.[chain]'

# 完整 Go2 agentic 栈和市场技能：
dimos run injenium.agentic

# 无头市场服务，不需要机器人或 LLM key：
dimos run injenium.market
dimos mcp list-tools
```

测试网或 mock 部署可以使用固定的 `ROBOT_IP` 与机密 `WALLET_SALT` 派生稳定身份，但显式 `INJECTIVE_PRIVATE_KEY` 始终优先。主网必须使用显式私钥，禁止从机器人 IP 派生。绝不要提交这些机密或真实 `.env` 文件。

## 手动演示

以下脚本是手动演示，不会被自动测试发现：

```bash
python demo/demo_m2_distill.py     # 录制经验 -> 去隐私 Recipe
python demo/demo_m3_sandbox.py     # 白名单执行和危险步骤拒绝
python demo/demo_m4_mock_loop.py --db /nonexistent
```

M4 会在 mock chain 上完成发布、应答、接受、执行、放款、评分和退款。浏览器 companion 的接口级验收：

```bash
cd frontend
./.venv/bin/python -m compileall -q server
./.venv/bin/python server/smoke.py
npm run lint
npm run build
npm run test:e2e
```

按项目约定不添加单元测试；接口级 demo、API 冒烟和浏览器验收是发布门槛。

## 开发网络

### Anvil

```bash
export PATH="$HOME/.foundry/bin:$PATH"
cd contracts
forge build
anvil --silent
```

本地部署只能使用 Anvil 公共开发私钥：

```bash
forge create src/Market.sol:Market \
  --rpc-url http://127.0.0.1:8545 \
  --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
  --broadcast
```

### Injective 测试网

测试网 Chain ID 为 `1439`，使用 Injective 官方 EVM RPC。部署并为测试钱包充值后，使用部署地址运行链上演示：

```bash
cd "$INJENIUM_ROOT"
./contracts/script/deploy.sh testnet
python demo/demo_m5_onchain.py \
  --rpc-url https://k8s.testnet.json-rpc.injective.network/ \
  --chain-id 1439 \
  --contract 0x<部署地址> \
  --key-a "$INJECTIVE_PRIVATE_KEY" \
  --key-b "$INJECTIVE_PRIVATE_KEY"
```

在 [Injective EVM Testnet Blockscout](https://testnet.blockscout.injective.network/) 核对交易哈希。仓库曾验证的 [`0x6415...4399`](https://testnet.blockscout.injective.network/address/0x641549D4c1ea67E16c84c996065629Df0AA34399) 仅作历史参考。

### 主网

主网 Chain ID 为 `1776`。浏览器体验台只有在同时配置合约地址和 `VITE_ENABLE_MAINNET_WRITES=true` 时才开放写入。正式上线还必须完成：

- `Market.sol` 及所有 ABI、枚举映射的独立审计；
- 硬件或托管密钥与人工审批；
- 低余额热钱包、交易限额和 gas 保留；
- 固定 RPC、合约、IPFS、恢复文件和日志配置；
- 余额、RPC、nonce/pending、确认数、Blockscout 对账和 IPFS 可用性告警；
- 断网、超时、崩溃、重复调用、哈希篡改、执行失败和退款演练。

## 交易语义

### 悬赏请求

```text
publish_request -> distill_and_publish -> list_offers
-> fetch_and_run -> run_status(state=succeeded) -> pay
```

请求预算先进入托管；接受前校验 Recipe URI 和内容哈希；只有执行成功才放款。放款和评分是两笔交易，评分失败不会回滚已完成的放款。

### 技能挂牌

```text
publish_skill -> search_skills -> buy_and_run -> run_status
```

买方在付款前验证 Recipe。`buySkill` 付款给卖方后执行本地动作；本地执行失败不会自动逆转已经完成的销售。

### 交易恢复

每笔真实链写交易会在广播前写入权限为 `0600` 的 pending 文件。RPC 延迟或进程重启时，系统恢复原 sender、nonce、交易哈希和新 ID，不会盲目使用新 nonce 重发。浏览器将 pending 哈希、账户和 Chain ID 保存在本地，刷新后继续轮询回执。

## 安全边界

- Recipe 只能调用注册表中的 primitive；禁止 `eval`、shell、导入和动态代码加载。
- Recipe 在执行或付款前完成规范化、哈希和白名单沙箱检查。
- companion 使用 HttpOnly、SameSite 会话 cookie 和隔离临时 mock 账本，不能签名 EVM 交易。
- IPFS 只允许合法 `ipfs://` CID，通过固定网关、超时和响应大小限制读取；任意 URL 和本机路径会被拒绝。
- 浏览器写交易要求目标链、钱包网络、余额和 gas 保留检查，并显示交易预览；主网还要求输入 `MAINNET`。
- 不得提交 `INJECTIVE_PRIVATE_KEY`、`WALLET_SALT`、`.env` 或真实机器人数据。
- 真机动作必须先在 mock 和受控环境中验证；`stop_run` 是协作式停止，效果取决于底层 primitive。

机器参数见 [INTEGRATION.md](INTEGRATION.md)，完整验收矩阵见 [TESTING.md](TESTING.md)。
