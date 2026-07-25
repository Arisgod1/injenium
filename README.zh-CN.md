# Injenium · 灵枢

[English](README.md) | [中文](README.zh-CN.md)

**Injenium（灵枢）** —— 结算于 Injective 的链上技能经济。**以技能为核心，以具身为扩展。**

一个把**技能当数据交易**的市场：把“困难请求”登记上链，把录制的经验蒸馏成
参数化、去隐私的**配方（recipe）**，应答他人请求，在只调用本机原语技能的
白名单 **沙箱** 中执行拉取到的配方，并通过链上托管结算、双向评分。拉取到的配方会在
应答被链上接受**之前**先做哈希校验与沙箱校验；且 requester 始终可以通过取消/退款
路径回收被锁死的托管金。

内核与具身形态无关：`injenium.core` 承载整个市场（链/合约、配方、沙箱、身份、
blueprint 工厂），不含任何机器人代码。每种具身形态以领域插件形式接入
`injenium.domains.<domain>`（原语白名单 + 适配器、provider、蒸馏器），**内核零改动**。
**Unitree Go2** 机器狗是第一个参考领域（`injenium.domains.go2`），以外部 **dimOS**
blueprint 打包（零修改 dimOS 源码，经 `dimos.blueprints` entry point 注册）；
机械臂、无人机、人形或纯软件 agent 以同样方式接入（见 `INTEGRATION.md`「适配你自己的机器狗」）。

目标链：**Injective EVM 测试网**（Chain ID `1439`）。一个文件落地的 **mock chain**
实现了相同的 `ChainClient` 协议，因此整套闭环可以在真实部署之前先跑通。

## 市场技能（域无关内核）

Agent 用只读的 `chain_status` / `list_requests` / `list_offers` / `search_skills`（自检 + 浏览）、
四个悬赏闭环 `@skill`，再加供给侧（`set_auto_publish` / `publish_skill` / `buy_and_run`）——
可用 `dimos mcp list-tools` 发现、用 `dimos mcp call` 调用：

| 技能 | 作用 |
| --- | --- |
| `chain_status()` | **只读** 自检：报告钱包地址、余额与链是否可达（回答“能不能上链？”），不花钱、不锁托管 |
| `list_requests()` | **只读** 浏览：列出板上开放的请求（id / 需求 / 预算 / 请求方），挑一个去应答 |
| `list_offers(request_id)` | **只读** 浏览：列出某请求收到的报价（offer id / 应答方 / 价格 / 哈希），挑一个 `offer_id` 去执行 |
| `search_skills(query)` | **只读** 浏览：关键词搜索技能货架的在售挂牌 —— 卡住时先买现成的，买不到再悬赏 |
| `set_auto_publish(enabled)` | 供给侧开关：开启后，每成功完成一项任务就用 `publish_skill` 自动挂牌出售 |
| `publish_skill(description, price, query)` | 从记忆蒸馏已完成的任务并直接挂牌出售（数据商品，可多次售卖） |
| `publish_request(need, budget)` | 登记一个困难请求，并锁定 `budget` INJ 进入托管 |
| `distill_and_publish(request_id, query)` | 从录制记忆蒸馏出去隐私的配方，挂出携带其内容哈希的应答单 |
| `fetch_and_run(offer_id)` | 校验配方哈希 + 沙箱校验，**通过后**才链上接受并执行 |
| `buy_and_run(listing_id)` | 校验挂牌配方哈希 + 沙箱校验，**通过后**才直接付款给卖家并执行 |
| `pay(offer_id)` | 把托管金释放给应答方并写入评分 |

`fetch_and_run` 在哈希不匹配或任何沙箱校验失败时会 **不触碰链** 直接拒绝，因此坏的
应答单绝不会把请求卡死在 `Answered`。否则会被锁死的托管金，requester 可通过
`ChainClient.cancel_request` / `Market.sol::cancelRequest` 回收（`Open` 请求可
立即取消；`Answered` 但一直未结算的请求在取消超时后可取消）。

后台的 `RequestListener` 会轮询板子并在**两侧**都提醒 agent —— 别的 agent 发来可应答的
请求时、以及你自己的请求收到报价时 —— 让闭环无需手动轮询即可推进。

打开**自动上架开关**（`set_auto_publish(true)`，或启动时
`-o marketskillcontainer.auto_publish=true`）后，agent 每成功完成一项任务就会把该
技能挂牌到货架；挂牌是数据商品、可多次售卖，而 `buy_and_run` 在买家付出任何钱
**之前**先完成哈希 + 沙箱双重校验。

## 安装与运行（Go2 参考领域）

```bash
pip install -e '.[chain]'          # 以 editable 装进 dimOS 运行时的 Python（不在 PyPI 上）；[chain]=web3>=7 走真链

# 完整 go2 agentic 栈 + 市场技能：
dimos run injenium.agentic

# 无头、仅服务端（无机器人、无 LLM key）—— 用于接口级验收：
dimos run injenium.market
dimos mcp list-tools               # 11 个市场技能会出现（自检/浏览 + 悬赏闭环 + 技能货架）
```

### 钱包身份

每只机器狗启动时带固定的 `ROBOT_IP`（如 `10.88.15.25`）；agent 由它确定性派生
出唯一钱包（`key = sha256(WALLET_SALT ‖ ROBOT_IP)`），同时用作 mock 账本身份与
测试网签名钱包，无需逐狗管理私钥。请设置 `WALLET_SALT`（部署机密），使私钥
无法仅凭局域网可见的 IP 反推。显式 `INJECTIVE_PRIVATE_KEY` 始终优先；主网
（chain id `1776`）拒绝 IP 派生，必须提供真实 `INJECTIVE_PRIVATE_KEY`。

## 演示（手动，`demo_` 前缀 —— 绝不纳入自动采集）

用宿主运行时的 Python（即提供 `dimos` 的那个）执行：

```bash
python demo/demo_m2_distill.py     # M2：录制记忆 -> 去隐私配方 + 模板图
python demo/demo_m3_sandbox.py     # M3：配方驱动白名单原语；不安全步骤被拒
python demo/demo_m4_mock_loop.py   # M4：在 mock chain 上跑通 发布 -> 应答 -> 执行 -> 支付 -> 评分
```

`demo_m2`/`demo_m4` 会自动定位 `data/go2_short.db`（本仓库或 dimOS 检出目录）；
传 `--db /path/to/go2_short.db` 可覆盖。

## 合约（M5）

`contracts/src/Market.sol` 与 `chain/client.py::MARKET_ABI` 一一对应；用 Foundry
部署到 Injective EVM 测试网并在 Blockscout 验证（见 `contracts/foundry.toml` 头部
说明），随后用以下参数把 agent 切到真链：
`-o marketskillcontainer.chain_backend=injective -o marketskillcontainer.market_contract=0x…`（`requestlistener` 同理）。

在真实机器人上接入的逐步命令(含如何接入 Go2 之外的新具身形态)见 `INTEGRATION.md`;分层测试流程见 `TESTING.md`。

完整设计与里程碑见 `spec.md`（仓库根目录）。验收仅为接口级 —— 按项目约定不写单元
测试、不做 TDD。
