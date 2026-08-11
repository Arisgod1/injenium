# Injenium 测试流程 · Testing Guide

三层递进验证:**L1 虚拟(mock)→ L2 本地真 EVM(anvil)→ L3 Injective 测试网**。
前两层零私钥、零资金、可随时跑;第三层才需要你已领水的私钥。项目遵循「仅接口级验收、不写单元测试」,以下均为手动/端到端验证。

> 关键约定
> - **运行环境**:必须用 dimOS 的 venv(Python 3.12),`injenium` 已 `pip install -e '.[chain]'` 装入其中。
>   例如 `source /path/to/dimos/.venv/bin/activate`(下文 `python` 均指该 venv)。
> - **dimOS 配置格式**:使用 blueprint 长选项，例如 `--marketskillcontainer.chain-backend mock`。
>   运行 `dimos run injenium.market --help` 可查看当前版本的完整参数。
> - **身份**:每台机器 `ROBOT_IP` + `WALLET_SALT` 确定性派生钱包;显式 `INJECTIVE_PRIVATE_KEY` 优先;主网(1439→1776)拒绝 IP 派生。

---

## L1 — 虚拟闭环(mock,无链无私钥)

纯本地内存/文件账本,验证市场逻辑与沙箱。

```bash
source /path/to/dimos/.venv/bin/activate
cd /path/to/injenium

# M2 蒸馏:录制记忆 -> 去隐私配方 + 模板图(用 HF 离线避免联网噪声)
HF_HUB_OFFLINE=1 python demo/demo_m2_distill.py

# M3 沙箱:白名单原语执行;越界/不安全步骤被拒
python demo/demo_m3_sandbox.py

# M4 全闭环:发布 -> 应答 -> 执行 -> 支付 -> 评分 + 取消退款
HF_HUB_OFFLINE=1 python demo/demo_m4_mock_loop.py          # 真实蒸馏 33 步
# 或快速版(手搓 3 步配方,跳过 CLIP):
python demo/demo_m4_mock_loop.py --db /nonexistent
```

**预期**:M4 打印 `publish_request → distill_and_publish → fetch_and_run(ok=True) → pay(rated 5/5)`,请求 `status=settled`,B 余额 +budget,并有一条 `cancel_request` 退款成功。

---

## L2 — 本地真 EVM(anvil,无资金无私钥)

用 Foundry 内置的本地 EVM 节点,跑**真实合约字节码 + 真实 web3.py 交易**,覆盖 mock 覆盖不到的路径:交易签名、gas、事件取 id、bytes32、原生币托管转账。anvil 的 dev 账户是**公开预充值**的(非秘密,仅本地)。

```bash
export PATH="$HOME/.foundry/bin:$PATH"      # forge/anvil 在 PATH 即可(homebrew 亦可)
cd /path/to/injenium

# 1) 编译合约
forge build --root contracts                # Solc 0.8.24,应 "compilation successful"

# 2) 起本地节点(后台,chain-id 31337)
anvil --silent &

# 3) 部署(anvil account0 的公开 key);首次部署确定性地址如下
forge create contracts/src/Market.sol:Market \
  --rpc-url http://127.0.0.1:8545 \
  --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
  --broadcast
#   Deployed to: 0x5FbDB2315678afecb367f032d93F642f64180aa3

# 4) 两钱包(A/B)驱动真链闭环(默认即 anvil 参数)
python demo/demo_m5_onchain.py --contract 0x5FbDB2315678afecb367f032d93F642f64180aa3

# 5) 收尾
pkill -f "anvil"
```

**预期**:`publish → submit → accept → run → pay → rate` 全部真实上链;`request 1 status=settled`;A 余额 −(托管+gas),B 余额 +(托管−自身 gas)。

---

## L3 — Injective 测试网(需资助 key + 领水)

代码在 L2 已被真实 EVM 全量验证;测试网只是换网络参数 + 真实资金。**写操作必须用你已领水的私钥,自行本机执行。**

### 3.1 只读预检(无需私钥)
```bash
curl -s -X POST https://k8s.testnet.json-rpc.injective.network/ \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}'
# 期望 {"result":"0x59f"}  (0x59f = 1439)
```

### 3.2 打印身份 + 领水(浏览器)
```bash
ROBOT_IP=10.88.15.25 WALLET_SALT='你的部署机密' python -c "import os;from injenium.core.identity import derive_address,derive_private_key as k;ip=os.environ['ROBOT_IP'];print('ADDR',derive_address(ip));print('KEY',k(ip))"
```
把打印的 `ADDR` 拿到 https://testnet.faucet.injective.network/ 领测试 INJ;`KEY` 即「资助 key」。
(简单起见 A、B 可用同一地址;要真·双钱包则领两个。)

### 3.3 部署 + 验证
```bash
cd /path/to/injenium
# 首选 Foundry:
INJECTIVE_PRIVATE_KEY=0x<你的KEY> ./contracts/script/deploy.sh testnet
# ⬇ 若 forge 报 `tls handshake eof`（它的 Rust TLS 与该 RPC 不兼容），改用 web3.py 兜底：
(cd contracts && forge build) && INJECTIVE_PRIVATE_KEY=0x<你的KEY> python contracts/deploy_web3.py --network testnet   # 打印合约地址
```
> ℹ️ Injective EVM 回执按 eth-hash 查询可能延迟。客户端会用区块 sender+nonce
> 和链状态兜底确认；若仍超时，用 `eth_call getRequest(id)` / nonce / Blockscout 核实。

### 3.4 跑真链闭环
```bash
python demo/demo_m5_onchain.py \
  --rpc-url https://k8s.testnet.json-rpc.injective.network/ --chain-id 1439 \
  --contract 0x<部署地址> --key-a 0x<你的KEY> --key-b 0x<你的KEY>
```
**验收**:在 `https://testnet.blockscout.injective.network/address/<部署地址>` 看到
`publishRequest / submitOffer / acceptOffer / releasePayment / rate`(可加 `cancelRequest`)逐笔交易。

---

## 接口级验收(dimos mcp,无 LLM 驱动技能)

`injenium.market` 已挂 `McpServer`,可用命令直接驱动 13 个 `@skill`(只读自检/浏览 + 悬赏闭环 + 技能货架 + 运行状态/中止;可指向 mock 或测试网)。

```bash
# 起 headless 市场服务(后台);指向测试网需给两个模块都配链
dimos run injenium.market -d \
  --marketskillcontainer.chain-backend injective \
  --marketskillcontainer.market-contract 0x<部署地址> \
  --marketskillcontainer.chain-id 1439 \
  --marketskillcontainer.rpc-url https://k8s.testnet.json-rpc.injective.network/ \
  --marketskillcontainer.memory-db /path/to/dimos/data/go2_short.db \
  --requestlistener.chain-backend injective \
  --requestlistener.market-contract 0x<部署地址> \
  --requestlistener.chain-id 1439 \
  --requestlistener.rpc-url https://k8s.testnet.json-rpc.injective.network/

dimos mcp list-tools                                       # 列出 13 个市场技能(含运行状态/中止)
dimos mcp call chain_status                                # 只读自检:钱包/余额/链是否可达(不花钱)
dimos mcp call list_requests                               # 只读浏览:板上开放请求(不花钱)
dimos mcp call publish_request --json-args '{"need":"climb the ramp","budget":"0.1"}'
dimos mcp call distill_and_publish --arg request_id=1 --arg query="ramp"
dimos mcp call list_offers --arg request_id=1              # 拿到 offer_id 再 fetch_and_run
dimos mcp call fetch_and_run --arg offer_id=1
dimos mcp call run_status --arg run_id=offer:1             # state=succeeded 后才能付款
dimos mcp call pay --arg offer_id=1
# 技能货架(供给侧):
dimos mcp call set_auto_publish --arg enabled=true         # 开关:完成任务后自动挂牌
dimos mcp call publish_skill --json-args '{"description":"climb the ramp","price":"0.05","query":"ramp"}'
dimos mcp call search_skills --arg query="ramp"            # 拿到 listing_id
dimos mcp call buy_and_run --arg listing_id=1              # 先验证后付款并执行
dimos stop
```
(不带链参数则跑 mock 账本;`ROBOT_IP`/`WALLET_SALT` 从环境继承派生钱包。)

---

## 参考

### 测试网参数
| 项 | 值 |
|---|---|
| Chain ID | `1439` (`0x59f`);主网 `1776` |
| JSON-RPC | `https://k8s.testnet.json-rpc.injective.network/` |
| Blockscout | `https://testnet.blockscout.injective.network/` |
| 水龙头 | `https://testnet.faucet.injective.network/` |
| gasPrice | ~0.16 Gwei(兼容 legacy gasPrice) |

### 关键环境变量
`ROBOT_IP`、`WALLET_SALT`、`INJECTIVE_PRIVATE_KEY`、`IPFS_API_URL`(见 `.env.example`)。跨机取配方才需 `recipe_storage=ipfs` + 各机 IPFS 守护进程;单机用默认 `local`。

### 常见坑
- **必须装进 dimos venv**(Python 3.12),base(3.13)不满足 `requires-python` 且无 dimos。
- **web3 连测试网**偶发 SSL/超时(环境出口抖动);`InjectiveClient` 已可用,若不稳定加 `request_kwargs={'timeout':20}` 并重试。
- dimOS 配置使用 blueprint 长选项;字段中的下划线转换为短横线。
- 私钥仅在你本机(`.env` 已 gitignore 或命令行内联),切勿提交。

### 分层对照
| 层 | 命令 | 需私钥/资金 | 覆盖 |
|---|---|---|---|
| L1 mock | `demo_m4_mock_loop.py` | 否 | 市场逻辑 + 沙箱 |
| L2 anvil | `demo_m5_onchain.py`(默认) | 否 | + 真合约/交易/托管转账 |
| L3 测试网 | `deploy.sh testnet` + `demo_m5_onchain.py --rpc-url…` | 是 | + 真网络/Blockscout 可查证 |
