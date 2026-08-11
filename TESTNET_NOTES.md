# Injective 测试网上链试错记录 · Testnet Bring-up Log

记录首次把 Injenium 部署到 Injective EVM 测试网(chain-id 1439)的完整试错过程、结论、可复用资产与遗留问题。配套运行手册见 `TESTING.md`。

## 第二次部署(含技能货架, 2026-07-25)
- 合约（含 listSkill/buySkill/delistSkill）：`Market` @ `0x641549D4c1ea67E16c84c996065629Df0AA34399`，部署者 = 运行时钱包 `0x9e2C16dA0877cb2445fd43c9bd861bEFe0E86C57`（`ROBOT_IP=192.168.12.1` 空盐派生，faucet 1 INJ）。
- 链上验证（状态读回，不依赖回执）：`listSkill` → `getListing`/`activeListingIds` 读回✓；`buySkill` eth_call 模拟通过 + 已广播（回执仍延迟，同遗留问题 #8）；`delistSkill` → active=false 读回✓；技能层 `chain_status`/`search_skills` 直连测试网✓。全程 gas ≈ 0.00006 INJ。
- 注：旧合约 `0x7Eab…104E` 无挂牌功能，已弃用；`-o …market_contract` 一律指向新地址。

## TL;DR
- ✅ **合约已真实部署到 Injective 测试网并可读**:`Market` @ `0x7Eab155DCae4Be8837678Af3ca96909b4141104E`(`eth_getCode` 返回字节码)。
- ✅ **写路径已验证**:`publishRequest` 成功落链 —— `getRequest(1)` 读到 request #1(requester=部署者、budget=0.1 INJ、status=Open、need/tags 正确)。
- ✅ **回执索引延迟已有客户端兜底**:交易管理器除查询 receipt 外,还会扫描区块中的
  sender+nonce、校验调用 payload,并从事件/合约状态恢复新 ID。

## 部署产物
| 项 | 值 |
|---|---|
| 网络 | Injective EVM 测试网,chain-id `1439` |
| RPC | `https://k8s.testnet.json-rpc.injective.network/` |
| 合约 `Market` | `0x7Eab155DCae4Be8837678Af3ca96909b4141104E` |
| 部署者 / 钱包 | `0xb4A52A6674a031f13EB96B575f6b51C4A0871FE5` |
| Blockscout | `https://testnet.blockscout.injective.network/address/0x7Eab155DCae4Be8837678Af3ca96909b4141104E` |
| 链上 request #1 | requester=部署者,budget=0.1 INJ,status=Open,need="climb the loading ramp",tags=[locomotion] |

## 试错时间线(问题 → 根因 → 处理)
1. **装错 Python 环境** — `pip install -e '.[chain]'` 在 base(3.13)报 `requires-python` 不符。根因:injenium 需 3.10–3.12 且依赖 dimos。→ 装进 dimos venv(3.12)。
2. **dimos 配置标志格式错误** — `--marketskillcontainer-…` 不生效。根因:dimos 用 `-o 模块.字段=值`(模块键=类名小写)。→ 全量修文档/脚本。
3. **market blueprint 缺 `McpServer`** — `dimos mcp` 连不上。→ `injenium_market` 加 `McpServer.blueprint()`,可无 LLM 用 `dimos mcp call` 驱动技能。
4. **部署者余额 0** — `insufficient funds`。→ 打印派生地址 → 水龙头领水(1 INJ)。
5. **`forge create` 全程 TLS 握手失败** — `tls handshake eof`(6/6),但 curl / web3(OpenSSL)能连同一端点。根因:forge 的 Rust TLS 栈与该 RPC 不兼容。→ **改用 web3.py 部署**(`contracts/deploy_web3.py`),读 forge 已编译的字节码发交易。
6. **web3 偶发 SSL EOF / 可能挂起** — 根因:端点握手偶发中断 + `HTTPProvider` 无超时。→ `InjectiveClient` 改用带 `timeout=30` + urllib3 `Retry(connect=6, read=0)` 的 session(**只重试连接层,已发出的交易绝不重发**)。
7. **沙箱只写工作区** — dimos logger 写 `projects/dimos/logs` 被拒(`Operation not permitted`)。根因:工作区外不可写。→ 该命令需在沙箱外(完整权限)运行。
8. **等回执超时但交易已上链** — 历史版本的 `wait_for_transaction_receipt`
   曾在 nonce 1→2、`getRequest(1)` 已可读时仍超时。现由 `TxManager` 的区块扫描和状态回读处理。

## 可复用资产
| 资产 | 用途 |
|---|---|
| `contracts/deploy_web3.py` | **forge TLS 连不上 RPC 时的部署兜底**:读 `out/Market.sol/Market.json` 字节码,web3.py 发部署交易,带连接重试。`INJECTIVE_PRIVATE_KEY=0x… python contracts/deploy_web3.py --network testnet` |
| `demo/demo_m5_onchain.py` | 两钱包(A/B)驱动真链闭环;默认打本地 anvil,传 `--rpc-url/--chain-id/--contract/--key-*` 打测试网 |
| `InjectiveClient` 连接层重试 session(`chain/client.py`) | 应对握手抖动的通用加固(timeout + connect-only retry) |
| `TESTING.md` + 本地 anvil 流程 | 上真网前的三层预验证:mock → anvil(真 EVM)→ testnet |
| 身份/领水一行命令 | `ROBOT_IP`+`WALLET_SALT` 派生地址与私钥 |

## Injective EVM 交易确认策略
`InjectiveClient` 通过 `TxManager` 串行管理本地 nonce,同一签名原文可有限次幂等广播。
确认顺序是 receipt → 新区块 sender+nonce 扫描 → payload 校验;创建类交易的 ID
按 receipt 日志 → 确认区块日志 → 计数器范围内的链状态匹配恢复。同 nonce 若出现不同
payload 会明确报替换错误,不会当成本次交易成功。

广播前,签名原文会原子写入 `pending_tx_path`(权限 `0600`)。进程重启后下一次写交易
会先恢复该 nonce:已入块则确认并清理,nonce 未前进则原样重播,nonce 已被未知交易占用
则停止并保留记录供人工核对。

## 复现要点
- 环境:dimos venv(Python 3.12),`pip install -e '.[chain]'`;Foundry(仅用其 `forge build` 编译,部署走 web3)。
- 部署:`forge build` → `contracts/deploy_web3.py --network testnet`(而非 `forge create`)。
- 验证:`eth_getCode` 看合约字节码;`eth_call getRequest(id)` / Blockscout 看写路径生效;`eth_getTransactionCount` 看 nonce 前进。
