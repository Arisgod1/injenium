# 把 Injenium 接入机器狗 Agent · Integration Guide

面向"在机器狗上跑起市场"的**逐步命令**。项目是外部 dimOS blueprint 包,`injenium.agentic`
即"完整 Go2 栈 + 市场模块"的接入形态。测试分层见 `TESTING.md`,踩坑记录见 `TESTNET_NOTES.md`。

## 架构:你在复用什么
项目分两层(重构后):
- **`injenium.core`** —— 域无关的经验能力市场内核:链/合约、市场技能(四个闭环技能 + 只读自检 `chain_status`)、内容寻址
  配方、**注册表驱动的沙箱**、身份、`build_market` 工厂。
- **`injenium.domains.go2`** —— 机器狗领域插件:原语白名单 + dispatch 适配器、mock/真机
  provider、记忆蒸馏;用内核工厂产出 `injenium.market`(无头)/ `injenium.agentic`(整机)。

**应用到你的狗有两条路:**
1. **Unitree Go2(或原语兼容的狗)** → 直接用 `go2` 域:走下面步骤 0–3 + 阶段 A/B。
2. **别的机器狗 / 别的能力** → 照 `go2` 写一个新域(见文末「适配你自己的机器狗」),
   **内核一行不改**。

> 约定
> - `$DPY` = 机器狗上 **dimOS 运行时的 Python**(Python 3.12 的 venv,dimos 就装在里面)。
>   例:`export DPY=/opt/dimos/.venv/bin/python`(路径按机器狗实际改)。相应 `dimos` = 同目录的 `bin/dimos`。
> - dimos 配置覆盖一律 `-o 模块.字段=值`(可重复)。市场相关模块键:`marketskillcontainer`、`requestlistener`。

---

## 步骤 0 · 前提
- 机器狗跑 dimOS,且其 dimos 含 Go2 栈(`unitree_go2_spatial`、Unitree/Navigation/PersonFollow 技能容器)——`agentic` 会 import 它们。
- 备好 LLM 凭证(`agentic` 内含 McpClient=LLM agent;按 dimOS 的 agent 配置设置对应 API key 环境变量)。
- 每台机器狗启动注入了固定的 `ROBOT_IP`。

## 步骤 1 · 安装 injenium 到机器狗的 dimos 运行时
```bash
# 把本仓库放到机器狗上(scp / git clone),进入目录后:
cd /path/to/injenium
$DPY -m pip install -e '.[chain]'          # 注册 dimos.blueprints entry point + 装 web3
# 验证:
$(dirname $DPY)/dimos list | grep injenium # 应打印 injenium.agentic / injenium.market
```

## 步骤 2 · 冒烟验证:技能能被发现、能调用(无真机、无链,风险最低先做)
```bash
cd /path/to/injenium
$(dirname $DPY)/dimos run injenium.market -d          # 无头:市场技能+监听+mock原语+McpServer
$(dirname $DPY)/dimos mcp list-tools                  # 应看到 chain_status/publish_request/distill_and_publish/fetch_and_run/pay
$(dirname $DPY)/dimos mcp call chain_status           # 只读自检:钱包/余额/链是否可达(不花钱)
$(dirname $DPY)/dimos mcp call publish_request --arg need="test" --arg budget=1.0
$(dirname $DPY)/dimos stop
```
能列出 5 个技能(含只读自检 chain_status)、调用返回 str,即"技能契约"打通。

## 步骤 3 · 配置身份 + 环境变量
在机器狗上准备 `.env`(参考仓库 `.env.example`),或直接 export:
```bash
export ROBOT_IP=10.88.15.25          # 每台固定(系统已注入,确认即可)
export WALLET_SALT='本队部署机密'      # 混入钱包派生,避免仅凭 IP 反推
# 打印本机派生钱包地址(测试网领水用):
ROBOT_IP=$ROBOT_IP WALLET_SALT=$WALLET_SALT $DPY -c "from injenium.core.identity import derive_address as a; import os; print(a(os.environ['ROBOT_IP']))"
```
说明:`agent_id` 默认空 → 由 `ROBOT_IP`+`WALLET_SALT` 确定性派生;每台狗 IP 不同 → 钱包不同,无需手配。

---

## 阶段 A · 真机 + mock 账本(dry-run,不上链,先跑通端到端)
两只狗共享一个账本文件(NFS/共享目录),或同机双 replay。`memory_db` 指向该狗**自己的 memory2 录制库**。

**狗 B(应答方,先起)**:
```bash
export ROBOT_IP=10.88.15.26           # B 的 IP
cd /path/to/injenium
$(dirname $DPY)/dimos run injenium.agentic -d \
  -o marketskillcontainer.chain_backend=mock \
  -o marketskillcontainer.market_state_path=/shared/market_state.json \
  -o marketskillcontainer.memory_db=/data/go2_recording.db \
  -o requestlistener.chain_backend=mock \
  -o requestlistener.market_state_path=/shared/market_state.json \
  -o requestlistener.poll_interval=5
```
**狗 A(请求方)**:同样命令,`ROBOT_IP=10.88.15.25`、同一个 `/shared/market_state.json`。

驱动与观察:
```bash
# 让 A 发布困难请求(可让 LLM 自主发起,或手动直接调技能):
$(dirname $DPY)/dimos mcp call publish_request --arg need="climb the ramp" --arg budget=1.0
# B 的 RequestListener 命中后会提示其 agent;或手动:
$(dirname $DPY)/dimos mcp call distill_and_publish --arg request_id=<id> --arg query="ramp"
$(dirname $DPY)/dimos mcp call fetch_and_run  --arg offer_id=<id>   # 沙箱驱动 Go2Primitives → 真机动作
$(dirname $DPY)/dimos mcp call pay --arg offer_id=<id>
$(dirname $DPY)/dimos stop
```
> `fetch_and_run` 在真机上通过 `Go2Primitives` 执行白名单原语(移动/导航/跟随/sport/wait);沙箱绝不 eval 对方代码。

## 阶段 B · 真机 + Injective 测试网(真实上链)
**① 部署合约**(在任意一台开发机,`forge` 对该 RPC 有 TLS 兼容问题时用 web3 兜底):
```bash
cd /path/to/injenium && (cd contracts && forge build)
INJECTIVE_PRIVATE_KEY=0x<部署者KEY> $DPY contracts/deploy_web3.py --network testnet   # 打印合约地址
```
**② 每只狗领水**:把步骤 3 打印的地址拿到 https://testnet.faucet.injective.network/ 领 INJ(≥0.2)。

**③ 起 agentic 指向测试网**(两只狗都要,两个模块都配;`market_contract` 用①的地址):
```bash
$(dirname $DPY)/dimos run injenium.agentic -d \
  -o marketskillcontainer.chain_backend=injective \
  -o marketskillcontainer.market_contract=0x<合约地址> \
  -o marketskillcontainer.chain_id=1439 \
  -o marketskillcontainer.rpc_url=https://k8s.testnet.json-rpc.injective.network/ \
  -o marketskillcontainer.memory_db=/data/go2_recording.db \
  -o marketskillcontainer.recipe_storage=local \
  -o requestlistener.chain_backend=injective \
  -o requestlistener.market_contract=0x<合约地址> \
  -o requestlistener.chain_id=1439 \
  -o requestlistener.rpc_url=https://k8s.testnet.json-rpc.injective.network/
```
跨两台真机时把 `recipe_storage` 设为 `ipfs` 并各机设 `IPFS_API_URL`(否则请求方读不到应答方本地配方)。链上状态用 Blockscout 查证。

---

## `-o` 配置速查
| 键(marketskillcontainer / requestlistener 同名) | 说明 | 示例 |
|---|---|---|
| `chain_backend` | `mock` 或 `injective` | `injective` |
| `market_contract` | 部署的 Market 地址(injective 必填) | `0x7Eab…104E` |
| `chain_id` | 测试网 1439 / 主网 1776 | `1439` |
| `rpc_url` | EVM JSON-RPC | `https://k8s.testnet.json-rpc.injective.network/` |
| `market_state_path` | mock 账本文件(两狗共享) | `/shared/market_state.json` |
| `agent_id` | 身份覆盖;空=按 ROBOT_IP 派生 | 一般留空 |
| `marketskillcontainer.memory_db` | 蒸馏读取的录制库 | `/data/go2_recording.db` |
| `marketskillcontainer.recipe_storage` | `local` / `ipfs` | 跨机用 `ipfs` |
| `marketskillcontainer.ipfs_api_url` | Kubo API | `http://127.0.0.1:5001` |
| `requestlistener.poll_interval` | 轮询秒数 | `5` |

> `match_tags`/`match_keywords`(列表)留空=匹配所有开放请求;需过滤则用 `dimos run ... -c <config.json>` 传 JSON。

## 环境变量(代码直接读)
`ROBOT_IP`、`WALLET_SALT`、`INJECTIVE_PRIVATE_KEY`(显式则覆盖 IP 派生,主网必填)、`IPFS_API_URL`。私钥放 `.env`(已 gitignore)或内联,勿提交。

## 接坑速查
- **装错环境**:必须装进机器狗的 dimos venv(Python 3.12),非系统 base。
- **`agentic` 起不来**:机器狗 dimos 缺 Go2 blueprints;先用 `injenium.market` 排除市场侧问题。
- **`dimos mcp` 连不上**:确认所跑 blueprint 含 McpServer(`agentic`/`market` 都含)。
- **forge 部署 `tls handshake eof`**:改用 `contracts/deploy_web3.py`(见上)。
- **Injective 自动闭环卡在等回执**:`InjectiveClient` 依赖同步回执,在 Injective 上会超时(交易其实已上链)。真机测试网 demo 建议**先用 mock 账本**,或先改造 `_send`/`_decode_id` 为"轮询 nonce + 读状态取 id"(见 `TESTNET_NOTES.md` 遗留项)。

---

## 适配你自己的机器狗(非 Unitree Go2)
内核不含任何机器人代码;换机器人/换能力 = **新增一个域,内核零改动**。照
`injenium/domains/go2/` 依葫芦画瓢写 `injenium/domains/<yourbot>/`:

| 文件 | 职责 |
|---|---|
| `providers.py` | 你的原语 provider(mock + 真机),满足 `injenium.core.specs.PrimitiveSkillsSpec` |
| `primitives.py` | 每个原语的 `PrimitiveSpec`(参数校验)+ 显式适配器 `dispatch(provider, params)` + `register(registry)` |
| `distiller.py` | 把你的录制/经验蒸馏成 `Recipe`(实现 `injenium.core.distill.Distiller`) |
| `models.py`(可选) | 放进 `Recipe.payload` 的领域数据模型 |
| `blueprint.py` | 用 `injenium.core.blueprint.build_market(provider_blueprint=…, extra=[…])` 产出 market / agentic |
| `__init__.py` | 导入即 `register(default_registry)` + `set_default_distiller(...)` |

最后在 `pyproject.toml` 的 `[project.entry-points."dimos.blueprints"]` 注册你的 blueprint
(`dimos run <你的名字>.market|agentic` 即可)。沙箱只调用你注册的适配器、永不 `eval`
配方名——新域自动继承这条安全边界。
