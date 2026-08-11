import {
  Activity as ActivityIcon,
  AlertCircle,
  ArrowRight,
  BadgeCheck,
  Bot,
  Box,
  Check,
  ChevronRight,
  CircleDollarSign,
  CircleStop,
  ClipboardList,
  Copy,
  ExternalLink,
  FlaskConical,
  Gauge,
  Hash,
  Link2,
  LoaderCircle,
  LockKeyhole,
  Menu,
  PackageCheck,
  Play,
  Plus,
  RefreshCcw,
  Search,
  ShieldCheck,
  Star,
  Store,
  Unplug,
  Upload,
  Wallet,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  createContext,
  type FormEvent,
  type PropsWithChildren,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { z } from "zod";
import { api, ApiError } from "./api";
import {
  connectInjected,
  displayInj,
  executeWrite,
  loadActivities,
  MAINNET_ADDRESS,
  MAINNET_WRITES,
  MAX_TRANSACTION_INJ,
  networkConfig,
  publicClient,
  readListings,
  readOffers,
  readRequests,
  rememberRequest,
  recoverPending,
  saveActivities,
  TESTNET_ADDRESS,
  validateSpend,
  type ChainWrite,
} from "./chain";
import { copy } from "./strings";
import type {
  Activity,
  DemoMarket,
  Inspection,
  Listing,
  NetworkMode,
  Offer,
  RecipeSource,
  RunResult,
} from "./types";

const recipeSchema = z.object({
  intent: z.string().min(1),
  preconditions: z.array(z.string()).optional(),
  steps: z.array(z.object({ primitive: z.string().min(1), params: z.record(z.string(), z.unknown()).default({}) })).min(1),
  success_criteria: z.string().optional(),
  schema_version: z.number().int().default(1),
  payload: z.record(z.string(), z.unknown()).default({}),
});

type AppState = {
  mode: NetworkMode;
  setMode: (mode: NetworkMode) => void;
  inspection: Inspection | null;
  loadSource: (source: RecipeSource, expectedHash?: string) => Promise<Inspection>;
  runResult: RunResult | null;
  setRunResult: (result: RunResult | null) => void;
  activities: Activity[];
  addActivity: (activity: Omit<Activity, "id" | "createdAt">) => void;
  requestWrite: (write: ChainWrite, consequence: string, after?: () => void | Promise<void>) => void;
  walletAddress: string | null;
  connectWallet: () => Promise<void>;
  toast: ToastState | null;
  notify: (tone: ToastState["tone"], title: string, detail: string) => void;
};

type ToastState = { tone: "success" | "error" | "info"; title: string; detail: string };
type PendingWrite = { write: ChainWrite; consequence: string; after?: () => void | Promise<void> };

const AppContext = createContext<AppState | null>(null);

function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error("AppContext unavailable");
  return value;
}

function shorten(value: string, head = 7, tail = 5) {
  return value.length <= head + tail + 3 ? value : `${value.slice(0, head)}…${value.slice(-tail)}`;
}

function errorText(error: unknown) {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "操作未完成。请检查连接后重试；系统没有自动重复交易。";
}

function AppProvider({ children }: PropsWithChildren) {
  const [mode, setModeState] = useState<NetworkMode>(() => (localStorage.getItem("injenium.mode") as NetworkMode) || "demo");
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [activities, setActivities] = useState<Activity[]>(loadActivities);
  const [pendingWrite, setPendingWrite] = useState<PendingWrite | null>(null);
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    void recoverPending(activities).then(setActivities);
    // Pending recovery runs once. It never rebroadcasts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 5200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const setMode = (next: NetworkMode) => {
    if (activities.some((item) => item.status === "pending") && next !== mode) {
      setToast({ tone: "info", title: "仍有交易待确认", detail: "已保留待确认交易记录；切换网络不会自动重发。" });
    }
    setModeState(next);
    localStorage.setItem("injenium.mode", next);
    setRunResult(null);
  };

  const addActivity = (activity: Omit<Activity, "id" | "createdAt">) => {
    setActivities((current) => {
      const next = [{ ...activity, id: crypto.randomUUID(), createdAt: Date.now() }, ...current];
      saveActivities(next);
      return next;
    });
  };

  const notify = (tone: ToastState["tone"], title: string, detail: string) => setToast({ tone, title, detail });

  const loadSource = async (source: RecipeSource, expectedHash?: string) => {
    const loaded = await api.load(source, expectedHash);
    setInspection(loaded);
    setRunResult(null);
    addActivity({ mode, title: "Recipe 已装载", detail: `${loaded.recipe.intent} · 0x${shorten(loaded.hash)}`, status: "local" });
    notify("success", "验证通过并已装载", `${loaded.recipe.steps.length} 个动作均在 Go2 白名单内。`);
    return loaded;
  };

  const connectWallet = async () => {
    if (mode === "demo") {
      notify("info", "本地体验无需钱包", "切换到测试网或主网后再连接钱包。当前模拟不会签名或花费 INJ。");
      return;
    }
    try {
      const { account } = await connectInjected(mode);
      setWalletAddress(account);
      notify("success", "钱包已连接", `${shorten(account)} · Chain ID ${networkConfig(mode).chain.id}`);
    } catch (error) {
      notify("error", "钱包未连接", errorText(error));
    }
  };

  const confirmWrite = async () => {
    if (!pendingWrite || mode === "demo") return;
    const chainId = networkConfig(mode).chain.id;
    const createdId = crypto.randomUUID();
    try {
      const { hash, account } = await executeWrite(mode, pendingWrite.write);
      setWalletAddress(account);
      const pending: Activity = {
        id: createdId,
        mode,
        title: pendingWrite.write.title,
        detail: "交易已广播，正在等待链上回执；页面不会自动重发。",
        status: "pending",
        createdAt: Date.now(),
        hash,
        chainId,
      };
      setActivities((current) => {
        const next = [pending, ...current];
        saveActivities(next);
        return next;
      });
      setPendingWrite(null);
      notify("info", "交易已广播", `哈希 ${shorten(hash)}，等待链上确认。`);
      const receipt = await publicClient(mode).waitForTransactionReceipt({ hash, timeout: 180_000, pollingInterval: 2_000 });
      setActivities((current) => {
        const next = current.map((item) => item.id === createdId ? { ...item, status: receipt.status === "success" ? "confirmed" as const : "failed" as const, detail: receipt.status === "success" ? "链上回执已确认。" : "交易已回滚，未产生预期状态变更。" } : item);
        saveActivities(next);
        return next;
      });
      if (receipt.status !== "success") throw new Error("交易已回滚，未产生预期状态变更。");
      await pendingWrite.after?.();
      await queryClient.invalidateQueries({ queryKey: ["chain"] });
      notify("success", "链上确认完成", pendingWrite.write.title);
    } catch (error) {
      setActivities((current) => {
        const next = current.map((item) => item.id === createdId ? { ...item, status: "failed" as const, detail: errorText(error) } : item);
        saveActivities(next);
        return next;
      });
      setPendingWrite(null);
      notify("error", "交易未完成", errorText(error));
    }
  };

  return (
    <AppContext.Provider value={{ mode, setMode, inspection, loadSource, runResult, setRunResult, activities, addActivity, requestWrite: (write, consequence, after) => setPendingWrite({ write, consequence, after }), walletAddress, connectWallet, toast, notify }}>
      {children}
      {pendingWrite && <TransactionDialog pending={pendingWrite} mode={mode} onClose={() => setPendingWrite(null)} onConfirm={confirmWrite} />}
    </AppContext.Provider>
  );
}

function App() {
  return (
    <AppProvider>
      <AppShell />
    </AppProvider>
  );
}

function AppShell() {
  const { mode, setMode, walletAddress, connectWallet, toast } = useApp();
  const [mobileOpen, setMobileOpen] = useState(false);
  const nav = [
    { to: "/market", label: copy.nav.market, icon: Store },
    { to: "/lab", label: copy.nav.lab, icon: FlaskConical },
    { to: "/requests", label: copy.nav.requests, icon: ClipboardList },
    { to: "/activity", label: copy.nav.activity, icon: ActivityIcon },
  ];
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup" aria-label="Injenium 灵枢">
          <span className="brand-mark"><Bot size={21} strokeWidth={2.2} /></span>
          <span><strong>{copy.brand}</strong><small>{copy.brandZh}</small></span>
        </div>
        <nav className={`primary-nav ${mobileOpen ? "is-open" : ""}`} aria-label="主要导航">
          {nav.map(({ to, label, icon: Icon }) => <NavItem key={to} to={to} label={label} icon={Icon} onClick={() => setMobileOpen(false)} />)}
        </nav>
        <div className="topbar-actions">
          <NetworkSelector value={mode} onChange={setMode} />
          <button className="wallet-button" aria-label={walletAddress ? `已连接钱包 ${shorten(walletAddress)}` : copy.connect} onClick={() => void connectWallet()}>
            <Wallet size={17} />
            <span>{walletAddress ? shorten(walletAddress) : copy.connect}</span>
          </button>
          <button className="icon-button mobile-menu" aria-label="打开导航" title="打开导航" onClick={() => setMobileOpen((value) => !value)}>
            {mobileOpen ? <X /> : <Menu />}
          </button>
        </div>
      </header>
      <main className="main-content">
        <NetworkNotice />
        <Routes>
          <Route path="/market" element={<MarketPage />} />
          <Route path="/lab" element={<LabPage />} />
          <Route path="/requests" element={<RequestsPage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/" element={<Navigate to="/market" replace />} />
          <Route path="*" element={<Navigate to="/market" replace />} />
        </Routes>
      </main>
      <nav className="bottom-nav" aria-label="移动端导航">
        {nav.map(({ to, label, icon: Icon }) => <NavItem key={to} to={to} label={label} icon={Icon} />)}
      </nav>
      {toast && <Toast {...toast} />}
    </div>
  );
}

function NavItem({ to, label, icon: Icon, onClick }: { to: string; label: string; icon: LucideIcon; onClick?: () => void }) {
  return <NavLink to={to} onClick={onClick} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><Icon size={18} /><span>{label}</span></NavLink>;
}

function NetworkSelector({ value, onChange }: { value: NetworkMode; onChange: (value: NetworkMode) => void }) {
  return (
    <div className="segmented" aria-label="网络模式">
      {(Object.keys(copy.modes) as NetworkMode[]).map((mode) => (
        <button key={mode} className={value === mode ? "selected" : ""} aria-pressed={value === mode} onClick={() => onChange(mode)}>{copy.modes[mode]}</button>
      ))}
    </div>
  );
}

function NetworkNotice() {
  const { mode } = useApp();
  if (mode === "demo") return <div className="network-notice demo"><FlaskConical size={16} /><span>本地体验使用隔离账本与模拟执行器，不连接钱包，不花费 INJ。</span></div>;
  if (mode === "mainnet" && !MAINNET_ADDRESS) return <div className="network-notice warning"><LockKeyhole size={16} /><span>主网合约尚未配置。当前仅展示安全预览，所有写入均被拒绝。</span></div>;
  if (mode === "mainnet" && !MAINNET_WRITES) return <div className="network-notice warning"><LockKeyhole size={16} /><span>主网只读保护已开启。需要部署地址和显式构建开关才能签名。</span></div>;
  return <div className="network-notice testnet"><BadgeCheck size={16} /><span>Injective 测试网 · Chain ID 1439 · 合约 {shorten(TESTNET_ADDRESS)}</span></div>;
}

function PageHeader({ title, detail, action }: { title: string; detail: string; action?: React.ReactNode }) {
  return <div className="page-header"><div><h1>{title}</h1><p>{detail}</p></div>{action}</div>;
}

function MarketPage() {
  const { mode, inspection, loadSource, setRunResult, notify, requestWrite, walletAddress } = useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [ipfsOpen, setIpfsOpen] = useState(false);
  const [listingOpen, setListingOpen] = useState(false);
  const demo = useQuery({ queryKey: ["demo-market"], queryFn: api.market, enabled: mode === "demo" });
  const chainListings = useQuery({ queryKey: ["chain", mode, "listings"], queryFn: () => readListings(mode as Exclude<NetworkMode, "demo">), enabled: mode !== "demo" });

  const listings: Listing[] = mode === "demo" ? demo.data?.listings ?? [] : chainListings.data ?? [];
  const filtered = listings.filter((item) => `${item.description} ${item.tags.join(" ")}`.toLowerCase().includes(search.toLowerCase()));
  const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0] ?? null;
  const busy = demo.isLoading || chainListings.isLoading;
  const error = demo.error || chainListings.error;

  const sourceFor = (listing: Listing): RecipeSource => {
    if (listing.recipe_uri.startsWith("builtin://")) return { kind: "builtin", id: listing.recipe_uri.replace("builtin://", "") };
    return { kind: "ipfs", uri: listing.recipe_uri };
  };

  const loadListing = async (listing: Listing) => {
    try {
      await loadSource(sourceFor(listing), String(listing.recipe_hash));
    } catch (loadError) {
      notify("error", "Recipe 未装载", `${errorText(loadError)} 未执行动作，也未产生付款。`);
    }
  };

  const buy = async (listing: Listing) => {
    if (!inspection || inspection.hash !== String(listing.recipe_hash).replace(/^0x/, "")) {
      notify("error", "购买已阻止", "请先验证并装载该挂牌的 Recipe。未发起付款。");
      return;
    }
    if (mode === "demo") {
      try {
        const result = await api.buyRun(listing.id);
        setRunResult(result.run);
        await queryClient.invalidateQueries({ queryKey: ["demo-market"] });
        navigate("/lab");
        notify("success", "模拟购买与执行完成", `本地交易 ${shorten(result.tx)} 已记入隔离账本。`);
      } catch (buyError) {
        notify("error", "模拟购买未完成", errorText(buyError));
      }
      return;
    }
    const amount = validateSpend(displayInj(listing.price));
    requestWrite({ functionName: "buySkill", args: [BigInt(listing.id)], value: amount, title: `购买技能 #${listing.id}` }, `向卖方支付 ${displayInj(listing.price)} INJ。付款会直接结算，Recipe 已在付款前完成哈希与白名单验证。`);
  };

  const delist = async (listing: Listing) => {
    try {
      if (mode === "demo") {
        await api.delist(listing.id);
        await queryClient.invalidateQueries({ queryKey: ["demo-market"] });
        notify("success", "技能已下架", "挂牌不再接受新的模拟购买。" );
        return;
      }
      requestWrite({ functionName: "delistSkill", args: [BigInt(listing.id)], title: `下架技能 #${listing.id}` }, "下架后该技能不再出现在可购买列表中；已完成的购买不受影响。" );
    } catch (delistError) { notify("error", "技能未下架", errorText(delistError)); }
  };

  return (
    <section className="route-page">
      <PageHeader title="技能市场" detail="先验证能力，再决定是否运行或结算。" action={<div className="header-actions"><ImportButton /><button className="button secondary" onClick={() => setIpfsOpen(true)}><Link2 size={17} />装载 IPFS</button></div>} />
      <div className="market-workspace">
        <section className="market-list" aria-label="技能列表">
          <label className="search-field"><Search size={18} /><span className="sr-only">搜索技能</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索技能或标签" /></label>
          <div className="list-meta"><span>{filtered.length} 个可用技能</span><button className="text-button" onClick={() => { void queryClient.invalidateQueries(); }}><RefreshCcw size={15} />刷新</button></div>
          {busy && <LoadingState label="正在读取技能市场" />}
          {error && <ErrorState title="无法读取技能市场" detail={`${errorText(error)} 可以切换到本地体验继续。`} />}
          {!busy && !error && filtered.length === 0 && <EmptyState icon={Search} title="没有匹配的技能" detail="调整关键词，或装载自己的 Recipe。" />}
          <div className="skill-rows">
            {filtered.map((listing) => <button key={listing.id} className={`skill-row ${selected?.id === listing.id ? "selected" : ""}`} onClick={() => setSelectedId(listing.id)}><span className="skill-row-main"><strong>{listing.description}</strong><span>{listing.tags.join(" · ") || "未分类"}</span></span><span className="skill-row-price"><strong>{displayInj(listing.price)} INJ</strong><span>#{listing.id.slice(0, 8)}</span></span><ChevronRight size={18} /></button>)}
          </div>
        </section>
        <section className="skill-detail" aria-live="polite">
          {selected ? <>
            <div className="detail-heading"><div className="skill-symbol"><Box size={25} /></div><div><div className="status-line"><StatusBadge tone="verified" label={selected.active ? "可购买" : "已下架"} /><span>{selected.tags.join(" / ")}</span></div><h2>{selected.description}</h2><p>由 <Mono value={selected.seller} /> 提供，Recipe 正文存储在链下，合约保存 URI、哈希和价格。</p></div></div>
            <dl className="fact-list"><div><dt>价格</dt><dd>{displayInj(selected.price)} INJ</dd></div><div><dt>Recipe URI</dt><dd><Mono value={selected.recipe_uri} /></dd></div><div><dt>内容哈希</dt><dd><Mono value={`0x${String(selected.recipe_hash).replace(/^0x/, "")}`} /></dd></div><div><dt>网络</dt><dd>{copy.modes[mode]}</dd></div></dl>
            <div className="detail-actions"><button className="button primary" onClick={() => void loadListing(selected)}><ShieldCheck size={18} />{copy.load}</button><button className="button secondary" disabled={!inspection || inspection.hash !== String(selected.recipe_hash).replace(/^0x/, "")} onClick={() => void buy(selected)}><CircleDollarSign size={18} />{mode === "demo" ? "模拟购买并运行" : "购买技能"}</button>{(mode === "demo" || walletAddress?.toLowerCase() === selected.seller.toLowerCase()) && <button className="text-button danger-text" onClick={() => void delist(selected)}>下架技能</button>}</div>
            {inspection && inspection.hash === String(selected.recipe_hash).replace(/^0x/, "") && <SecuritySummary inspection={inspection} />}
          </> : <EmptyState icon={Store} title="市场暂时为空" detail={mode === "mainnet" && !MAINNET_ADDRESS ? "配置主网合约地址后可读取正式链挂牌。" : "刷新市场或切换到本地体验。"} />}
        </section>
        <aside className="security-rail"><SafetyRail inspection={inspection} /><button className="button tertiary full" disabled={!inspection} onClick={() => setListingOpen(true)}><Plus size={17} />挂牌已装载技能</button></aside>
      </div>
      <IpfsDialog open={ipfsOpen} onClose={() => setIpfsOpen(false)} />
      <ListingDialog open={listingOpen} onClose={() => setListingOpen(false)} />
    </section>
  );
}

function ImportButton() {
  const input = useRef<HTMLInputElement>(null);
  const { loadSource, notify } = useApp();
  const onFile = async (file?: File) => {
    if (!file) return;
    if (file.size > 256 * 1024) {
      notify("error", "文件未读取", "Recipe JSON 不能超过 256 KiB。");
      return;
    }
    try {
      const parsed = recipeSchema.parse(JSON.parse(await file.text()));
      await loadSource({ kind: "inline", recipe: parsed });
    } catch (error) {
      notify("error", "Recipe 未装载", `JSON 结构或内容无效：${errorText(error)} 未执行任何动作。`);
    } finally {
      if (input.current) input.current.value = "";
    }
  };
  return <><input ref={input} className="sr-only" type="file" accept="application/json,.json" onChange={(event) => void onFile(event.target.files?.[0])} /><button className="button secondary" onClick={() => input.current?.click()}><Upload size={17} />导入 JSON</button></>;
}

function IpfsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [uri, setUri] = useState("");
  const [busy, setBusy] = useState(false);
  const { loadSource, notify } = useApp();
  if (!open) return null;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await loadSource({ kind: "ipfs", uri });
      onClose();
    } catch (error) {
      notify("error", "IPFS Recipe 未装载", `${errorText(error)} 未执行动作，也未产生付款。`);
    } finally { setBusy(false); }
  };
  return <Modal title="从 IPFS 装载 Recipe" onClose={onClose}><form onSubmit={(event) => void submit(event)} className="form-stack"><label><span>IPFS URI</span><input required value={uri} onChange={(event) => setUri(event.target.value)} placeholder="ipfs://bafy..." /></label><p className="field-note">只允许读取 CID 根目录的 recipe.json；任意网页 URL 和本机路径会被拒绝。</p><div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>返回市场</button><button className="button primary" disabled={busy || !uri.startsWith("ipfs://")}><Link2 size={17} />{busy ? "正在验证" : "验证并装载"}</button></div></form></Modal>;
}

function ListingDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { mode, inspection, notify, requestWrite } = useApp();
  const queryClient = useQueryClient();
  const [description, setDescription] = useState(inspection?.recipe.intent ?? "");
  const [price, setPrice] = useState("0.02");
  if (!open) return null;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!inspection) return;
    try {
      validateSpend(price);
      if (mode === "demo") {
        await api.createListing(description, price, [], inspection.hash);
        await queryClient.invalidateQueries({ queryKey: ["demo-market"] });
        notify("success", "技能已挂牌", "本地挂牌可以重复购买，直到供给方主动下架。" );
        onClose();
        return;
      }
      const published = await api.publish(inspection.hash);
      requestWrite({ functionName: "listSkill", args: [description, [], published.uri, `0x${inspection.hash}`, validateSpend(price)], title: "挂牌技能" }, `将 Recipe URI、哈希和 ${price} INJ 价格写入 ${copy.modes[mode]}。`, onClose);
    } catch (error) {
      notify("error", "技能未挂牌", `${errorText(error)} 未发起链上交易。`);
    }
  };
  return <Modal title="挂牌已装载技能" onClose={onClose}><form className="form-stack" onSubmit={(event) => void submit(event)}><label><span>技能描述</span><input required value={description} onChange={(event) => setDescription(event.target.value)} maxLength={180} /></label><label><span>单次价格（INJ）</span><input required inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} /></label><p className="field-note">价格上限 {MAX_TRANSACTION_INJ} INJ。真实链挂牌前需要 companion 已配置 IPFS 发布。</p><div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>继续检查</button><button className="button primary"><PackageCheck size={17} />确认挂牌</button></div></form></Modal>;
}

function LabPage() {
  const { inspection, runResult, setRunResult, addActivity, notify } = useApp();
  const [playing, setPlaying] = useState(false);
  const [visibleSteps, setVisibleSteps] = useState(0);
  const timer = useRef<number | null>(null);
  const navigate = useNavigate();
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);
  const play = async () => {
    if (!inspection) return;
    try {
      const result = await api.run(inspection.hash);
      setRunResult(result);
      setVisibleSteps(0);
      setPlaying(true);
      let current = 0;
      timer.current = window.setInterval(() => {
        current += 1;
        setVisibleSteps(current);
        if (current >= result.steps.length) {
          if (timer.current) window.clearInterval(timer.current);
          setPlaying(false);
        }
      }, window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 10 : 620);
      addActivity({ mode: "demo", title: "沙箱模拟完成", detail: `${result.steps.length} 个白名单动作已执行`, status: "local" });
    } catch (error) {
      notify("error", "模拟未运行", errorText(error));
    }
  };
  const stop = () => {
    if (timer.current) window.clearInterval(timer.current);
    setPlaying(false);
    notify("info", "播放已停止", "已停止剩余动作的可视化播放；没有链上状态被修改。" );
  };
  return <section className="route-page lab-page"><PageHeader title="模拟实验室" detail="同一份 Recipe，先在白名单执行器中观察，再决定是否上链。" action={<div className="header-actions">{playing ? <button className="button danger" onClick={stop}><CircleStop size={18} />停止播放</button> : <button className="button primary" disabled={!inspection} onClick={() => void play()}><Play size={18} />{copy.run}</button>}</div>} />
    {!inspection ? <EmptyState icon={FlaskConical} title="还没有装载技能" detail="先从技能市场验证并装载一个 Recipe。" action={<button className="button primary" onClick={() => navigate("/market")}><Store size={17} />前往技能市场</button>} /> : <div className="lab-workspace"><div className="simulation-stage"><RobotCanvas result={runResult} visibleSteps={visibleSteps} /><div className="stage-overlay"><span><Gauge size={16} />模拟执行器</span><strong>{playing ? `动作 ${Math.min(visibleSteps + 1, inspection.recipe.steps.length)} / ${inspection.recipe.steps.length}` : runResult ? "执行记录已就绪" : "等待运行"}</strong></div></div><section className="timeline"><div className="section-heading"><div><span className="section-icon"><ClipboardList size={18} /></span><h2>{inspection.recipe.intent}</h2></div><StatusBadge tone="verified" label="白名单通过" /></div><ol>{inspection.recipe.steps.map((step, index) => { const outcome = runResult?.steps[index]; const visible = Boolean(outcome) && (visibleSteps >= index + 1 || !playing); return <li key={`${step.primitive}-${index}`} className={visible ? "complete" : playing && visibleSteps === index ? "active" : ""}><span className="step-index">{visible ? <Check size={15} /> : index + 1}</span><div><strong><code>{step.primitive}</code></strong><p>{Object.entries(step.params).map(([key, value]) => `${key}=${JSON.stringify(value)}`).join(" · ") || "无参数"}</p>{visible && outcome && <small>{outcome.detail}</small>}</div></li>; })}</ol></section><aside className="lab-inspector"><SafetyRail inspection={inspection} /><div className="success-criteria"><span>成功标准</span><p>{inspection.recipe.success_criteria || "Recipe 未声明成功标准"}</p></div></aside></div>}
  </section>;
}

function RobotCanvas({ result, visibleSteps }: { result: RunResult | null; visibleSteps: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const ratio = window.devicePixelRatio || 1;
    const rect = element.getBoundingClientRect();
    element.width = rect.width * ratio;
    element.height = rect.height * ratio;
    const context = element.getContext("2d");
    if (!context) return;
    context.scale(ratio, ratio);
    const width = rect.width;
    const height = rect.height;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#f8f5f7";
    context.fillRect(0, 0, width, height);
    context.strokeStyle = "#e7dfe4";
    context.lineWidth = 1;
    for (let x = 28; x < width; x += 44) { context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke(); }
    for (let y = 20; y < height; y += 44) { context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke(); }
    let x = width * 0.28;
    let y = height * 0.62;
    let angle = -Math.PI / 2;
    const points = [{ x, y }];
    result?.calls.slice(0, visibleSteps || result.calls.length).forEach((call) => {
      if (call.primitive === "relative_move") {
        angle += (Number(call.args.degrees ?? 0) * Math.PI) / 180;
        const forward = Number(call.args.forward ?? 0) * 55;
        const left = Number(call.args.left ?? 0) * 55;
        x += Math.cos(angle) * forward + Math.cos(angle - Math.PI / 2) * left;
        y += Math.sin(angle) * forward + Math.sin(angle - Math.PI / 2) * left;
        points.push({ x, y });
      } else if (call.primitive === "navigate_with_text") {
        x = Math.min(width - 80, x + 110);
        y = Math.max(70, y - 65);
        points.push({ x, y });
      }
    });
    context.strokeStyle = "#b52673";
    context.lineWidth = 4;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.beginPath();
    points.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
    context.stroke();
    points.slice(0, -1).forEach((point) => { context.fillStyle = "#ffffff"; context.strokeStyle = "#b52673"; context.lineWidth = 2; context.beginPath(); context.arc(point.x, point.y, 5, 0, Math.PI * 2); context.fill(); context.stroke(); });
    context.save();
    context.translate(x, y);
    context.rotate(angle + Math.PI / 2);
    context.fillStyle = "#242027";
    context.fillRect(-18, -24, 36, 48);
    context.fillStyle = "#ffffff";
    context.fillRect(-9, -16, 18, 10);
    context.fillStyle = "#b52673";
    context.beginPath(); context.arc(0, -29, 6, 0, Math.PI * 2); context.fill();
    context.restore();
  }, [result, visibleSteps]);
  return <canvas ref={canvas} aria-label="机器人模拟路径画布" />;
}

function RequestsPage() {
  const { mode, inspection, notify, requestWrite, setRunResult } = useApp();
  const queryClient = useQueryClient();
  const [requestOpen, setRequestOpen] = useState(false);
  const [selectedRequest, setSelectedRequest] = useState<string | null>(null);
  const demo = useQuery({ queryKey: ["demo-market"], queryFn: api.market, enabled: mode === "demo" });
  const chainRequests = useQuery({ queryKey: ["chain", mode, "requests"], queryFn: () => readRequests(mode as Exclude<NetworkMode, "demo">), enabled: mode !== "demo" });
  const requests = mode === "demo" ? demo.data?.requests ?? [] : chainRequests.data ?? [];
  const selected = requests.find((item) => item.id === selectedRequest) ?? requests[0] ?? null;
  const chainOffers = useQuery({ queryKey: ["chain", mode, "offers", selected?.id], queryFn: () => readOffers(mode as Exclude<NetworkMode, "demo">, selected!.id), enabled: mode !== "demo" && Boolean(selected) });
  const offers = mode === "demo" ? demo.data?.offers.filter((item) => item.request_id === selected?.id) ?? [] : chainOffers.data ?? [];

  const answer = async () => {
    if (!selected || !inspection) { notify("error", "无法提交报价", "请先选择请求并装载一个通过验证的 Recipe。" ); return; }
    try {
      if (mode === "demo") {
        await api.createOffer(selected.id, inspection.hash);
        await queryClient.invalidateQueries({ queryKey: ["demo-market"] });
        notify("success", "模拟报价已提交", "Recipe 会在验收前再次校验哈希和白名单。" );
      } else {
        const published = await api.publish(inspection.hash);
        requestWrite({ functionName: "submitOffer", args: [BigInt(selected.id), published.uri, `0x${inspection.hash}`, BigInt(selected.budget)], title: `提交请求 #${selected.id} 的报价` }, "报价只写入 URI、哈希和价格；Recipe 正文不上链。" );
      }
    } catch (error) { notify("error", "报价未提交", `${errorText(error)} 未发起链上交易。`); }
  };

  const demoAction = async (operation: () => Promise<{ market: DemoMarket; run?: RunResult }>, success: string) => {
    try { const result = await operation(); if (result.run) setRunResult(result.run); await queryClient.invalidateQueries({ queryKey: ["demo-market"] }); notify("success", success, "隔离账本状态已更新。" ); }
    catch (error) { notify("error", "操作未完成", errorText(error)); }
  };

  return <section className="route-page"><PageHeader title="悬赏市场" detail="发布难题、验证报价、执行后再释放托管资金。" action={<button className="button primary" onClick={() => setRequestOpen(true)}><Plus size={18} />发布悬赏</button>} />
    <div className="requests-layout"><section className="request-board"><div className="section-heading"><div><span className="section-icon"><ClipboardList size={18} /></span><h2>市场请求</h2></div><span className="count-label">{requests.length} 条</span></div>{(demo.isLoading || chainRequests.isLoading) && <LoadingState label="正在读取请求" />}{requests.length === 0 && !demo.isLoading && !chainRequests.isLoading ? <EmptyState icon={ClipboardList} title="暂时没有请求" detail="发布一个难题，开始体验托管与报价流程。" /> : <div className="request-rows">{requests.map((item) => <button key={item.id} className={`request-row ${selected?.id === item.id ? "selected" : ""}`} onClick={() => setSelectedRequest(item.id)}><div><StatusBadge tone={item.status === "open" ? "pending" : "verified"} label={statusZh(item.status)} /><strong>{item.need}</strong><span>{item.tags.join(" · ") || "开放匹配"}</span></div><div><strong>{displayInj(item.budget)} INJ</strong><span>#{item.id.slice(0, 8)}</span></div></button>)}</div>}</section>
      <section className="offer-board">{selected ? <><div className="section-heading"><div><span className="section-icon"><CircleDollarSign size={18} /></span><h2>请求 #{selected.id.slice(0, 8)}</h2></div><button className="button secondary compact" disabled={!inspection || selected.status !== "open"} onClick={() => void answer()}><ArrowRight size={16} />用已装载技能报价</button></div><p className="request-need">{selected.need}</p><dl className="fact-list compact-facts"><div><dt>请求方</dt><dd><Mono value={selected.requester} /></dd></div><div><dt>托管金额</dt><dd>{displayInj(selected.budget)} INJ</dd></div></dl><div className="offer-list"><h3>收到的报价</h3>{offers.length === 0 ? <p className="muted-copy">还没有报价。装载一个 Recipe 后可模拟供给方应答。</p> : offers.map((offer) => <OfferRow key={offer.id} offer={offer} mode={mode} onDemoAction={demoAction} />)}</div>{selected.status === "open" && (mode === "demo" ? <button className="text-button danger-text" onClick={() => void demoAction(() => api.cancelRequest(selected.id), "悬赏已取消并退款")}>取消请求并退回托管</button> : <button className="text-button danger-text" onClick={() => requestWrite({ functionName: "cancelRequest", args: [BigInt(selected.id)], title: `取消请求 #${selected.id}` }, "开放请求将取消，剩余托管退回请求方钱包。")}>取消请求并退回托管</button>)}</> : <EmptyState icon={CircleDollarSign} title="选择一个请求" detail="查看预算、报价和执行状态。" />}</section>
      <aside className="security-rail"><SafetyRail inspection={inspection} /></aside></div>
    <RequestDialog open={requestOpen} onClose={() => setRequestOpen(false)} />
  </section>;
}

function OfferRow({ offer, mode, onDemoAction }: { offer: Offer; mode: NetworkMode; onDemoAction: (operation: () => Promise<{ market: DemoMarket; run?: RunResult }>, success: string) => Promise<void> }) {
  const { inspection, loadSource, notify, requestWrite, setRunResult } = useApp();
  const verified = inspection?.hash === offer.recipe_hash.replace(/^0x/, "");
  const verify = async () => { try { await loadSource({ kind: offer.recipe_uri.startsWith("builtin://") ? "builtin" : "ipfs", ...(offer.recipe_uri.startsWith("builtin://") ? { id: offer.recipe_uri.replace("builtin://", "") } : { uri: offer.recipe_uri }) } as RecipeSource, offer.recipe_hash); } catch (error) { notify("error", "报价验证失败", `${errorText(error)} 未接受报价，也未修改托管状态。`); } };
  const accept = () => {
    if (!verified) { notify("error", "验收已阻止", "请先验证该报价的 Recipe。" ); return; }
    if (mode === "demo") { void onDemoAction(() => api.acceptRun(offer.id), "报价已验收并完成模拟"); return; }
    rememberRequest(mode, offer.request_id);
    requestWrite({ functionName: "acceptOffer", args: [BigInt(offer.id)], title: `接受报价 #${offer.id}` }, "接受后请求进入 Answered。请确认本地执行成功后再释放托管。", async () => { if (inspection) setRunResult(await api.run(inspection.hash)); });
  };
  return <div className="offer-row"><div><div className="status-line"><StatusBadge tone={offer.status === "open" ? "pending" : "verified"} label={statusZh(offer.status)} /><Mono value={offer.responder} /></div><strong>{displayInj(offer.price)} INJ</strong><span><Mono value={`0x${offer.recipe_hash.replace(/^0x/, "")}`} /></span></div><div className="offer-actions">{!verified && <button className="button secondary compact" onClick={() => void verify()}><ShieldCheck size={16} />验证报价</button>}{offer.status === "open" && <button className="button primary compact" disabled={!verified} onClick={accept}><Play size={16} />验收并执行</button>}{offer.status === "accepted" && (mode === "demo" ? <button className="button primary compact" onClick={() => void onDemoAction(() => api.release(offer.id), "托管已释放")}>释放托管</button> : <button className="button primary compact" onClick={() => requestWrite({ functionName: "releasePayment", args: [BigInt(offer.id)], title: `释放报价 #${offer.id} 的托管` }, `将请求的托管金额支付给 ${shorten(offer.responder)}。`)}>释放托管</button>)}{offer.status === "paid" && (mode === "demo" ? <button className="button secondary compact" onClick={() => void onDemoAction(() => api.rate(offer.id, 5), "已写入五星评分")}><Star size={16} />评分 5</button> : <button className="button secondary compact" onClick={() => requestWrite({ functionName: "rate", args: [BigInt(offer.id), offer.responder, 5], title: `评价报价 #${offer.id}` }, "向合约写入对供给方的 5 分评价。") }><Star size={16} />评分 5</button>)}</div></div>;
}

function RequestDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { mode, notify, requestWrite } = useApp();
  const queryClient = useQueryClient();
  const [need, setNeed] = useState("通过狭窄的装卸坡道并保持稳定");
  const [budget, setBudget] = useState("0.05");
  if (!open) return null;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const value = validateSpend(budget);
      if (mode === "demo") {
        await api.createRequest(need, budget, ["locomotion"]);
        await queryClient.invalidateQueries({ queryKey: ["demo-market"] });
        notify("success", "悬赏已发布", `${budget} INJ 已锁入隔离账本的模拟托管。`);
        onClose();
      } else {
        requestWrite({ functionName: "publishRequest", args: [need, ["locomotion"]], value, title: "发布悬赏" }, `将 ${budget} INJ 锁入 ${copy.modes[mode]} Market 合约托管。`, onClose);
      }
    } catch (error) { notify("error", "悬赏未发布", `${errorText(error)} 未锁定任何资金。`); }
  };
  return <Modal title="发布技能悬赏" onClose={onClose}><form className="form-stack" onSubmit={(event) => void submit(event)}><label><span>需要解决的问题</span><textarea required value={need} onChange={(event) => setNeed(event.target.value)} maxLength={240} /></label><label><span>托管预算（INJ）</span><input required inputMode="decimal" value={budget} onChange={(event) => setBudget(event.target.value)} /></label><p className="field-note">单笔上限 {MAX_TRANSACTION_INJ} INJ。请求开放期间可取消并退回托管。</p><div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>继续浏览</button><button className="button primary"><CircleDollarSign size={17} />锁定预算并发布</button></div></form></Modal>;
}

function ActivityPage() {
  const { activities, mode, notify } = useApp();
  const pending = activities.filter((item) => item.status === "pending").length;
  const clearLocal = () => { const chainOnly = activities.filter((item) => item.status !== "local"); saveActivities(chainOnly); window.location.reload(); };
  return <section className="route-page"><PageHeader title="交易活动" detail="本地动作和链上交易分开记录；待确认交易不会被自动重发。" action={<button className="button secondary" onClick={() => { void recoverPending(activities).then(() => notify("info", "状态已核对", "已重新读取待确认交易的链上回执。")); }}><RefreshCcw size={17} />核对回执</button>} /><div className="activity-summary"><div><span className="summary-icon"><ActivityIcon /></span><div><strong>{activities.length}</strong><span>全部活动</span></div></div><div><span className="summary-icon pending"><LoaderCircle /></span><div><strong>{pending}</strong><span>等待链上确认</span></div></div><div><span className="summary-icon safe"><ShieldCheck /></span><div><strong>{copy.modes[mode]}</strong><span>当前网络模式</span></div></div></div><section className="activity-list"><div className="section-heading"><div><span className="section-icon"><ClipboardList size={18} /></span><h2>最近记录</h2></div><button className="text-button" onClick={clearLocal}>清除本地模拟记录</button></div>{activities.length === 0 ? <EmptyState icon={ActivityIcon} title="还没有活动记录" detail="装载并运行一个技能，或在测试网发起交易。" /> : activities.map((item) => <article className="activity-row" key={item.id}><StatusIcon status={item.status} /><div><div className="status-line"><strong>{item.title}</strong><StatusBadge tone={item.status === "failed" ? "danger" : item.status === "pending" ? "pending" : "verified"} label={activityStatus(item.status)} /></div><p>{item.detail}</p><span>{new Date(item.createdAt).toLocaleString("zh-CN")} · {copy.modes[item.mode]}</span></div>{item.hash && <a className="icon-button" title="在区块浏览器查看" aria-label="在区块浏览器查看" href={`${item.chainId === 1439 ? "https://testnet.blockscout.injective.network" : "https://explorer.injective.network"}/tx/${item.hash}`} target="_blank" rel="noreferrer"><ExternalLink /></a>}</article>)}</section></section>;
}

function SafetyRail({ inspection }: { inspection: Inspection | null }) {
  return <section className="safety-panel"><div className="section-heading"><div><span className="section-icon"><ShieldCheck size={18} /></span><h2>安全检查</h2></div>{inspection ? <StatusBadge tone={inspection.validation.ok ? "verified" : "danger"} label={inspection.validation.ok ? "已通过" : "已阻止"} /> : <StatusBadge tone="neutral" label="等待装载" />}</div>{inspection ? <><div className="hash-check"><span>内容承诺</span><Mono value={`0x${inspection.hash}`} /><div className={inspection.hashMatches ? "check-line ok" : "check-line bad"}>{inspection.hashMatches ? <Check size={16} /> : <AlertCircle size={16} />}{inspection.hashMatches ? "哈希一致" : "哈希不一致"}</div></div><div className="permission-list"><span>请求的能力</span>{inspection.permissions.map((permission) => <div key={permission.primitive}><code>{permission.primitive}</code><span>×{permission.count}</span></div>)}</div>{inspection.validation.problems.length > 0 && <ul className="problem-list">{inspection.validation.problems.map((problem) => <li key={problem}><AlertCircle size={15} />{problem}</li>)}</ul>}</> : <p className="muted-copy">装载 Recipe 后，这里会显示内容哈希、白名单权限和阻止原因。</p>}</section>;
}

function SecuritySummary({ inspection }: { inspection: Inspection }) {
  return <div className="security-summary"><div><ShieldCheck size={19} /><span><strong>沙箱检查通过</strong><small>未知动作与越界参数会在付款前被拒绝</small></span></div><div><Hash size={19} /><span><strong>内容哈希一致</strong><small><Mono value={`0x${inspection.hash}`} /></small></span></div></div>;
}

function TransactionDialog({ pending, mode, onClose, onConfirm }: { pending: PendingWrite | null; mode: NetworkMode; onClose: () => void; onConfirm: () => Promise<void> }) {
  const [phrase, setPhrase] = useState("");
  const [busy, setBusy] = useState(false);
  if (!pending || mode === "demo") return null;
  const config = networkConfig(mode);
  const mainnetLocked = mode === "mainnet" && (!MAINNET_ADDRESS || !MAINNET_WRITES);
  const phraseRequired = mode === "mainnet";
  return <Modal title="确认链上交易" onClose={onClose}><div className="transaction-preview"><div className="risk-banner"><LockKeyhole size={20} /><div><strong>{copy.modes[mode]} · Chain ID {config.chain.id}</strong><p>{pending.consequence}</p></div></div><dl className="fact-list"><div><dt>合约</dt><dd><Mono value={config.address ?? "尚未配置"} /></dd></div><div><dt>方法</dt><dd><code>{pending.write.functionName}</code></dd></div><div><dt>金额</dt><dd>{pending.write.value ? `${displayInj(pending.write.value)} INJ` : "仅支付 gas"}</dd></div><div><dt>签名位置</dt><dd>浏览器钱包</dd></div></dl>{phraseRequired && <label><span>输入 MAINNET 继续</span><input value={phrase} onChange={(event) => setPhrase(event.target.value)} autoComplete="off" /></label>}{mainnetLocked && <ErrorState title="主网写入已锁定" detail="需要同时配置主网合约地址和显式写入开关。" />}<div className="dialog-actions"><button className="button secondary" onClick={onClose}>返回检查</button><button className="button primary" disabled={busy || mainnetLocked || (phraseRequired && phrase !== "MAINNET")} onClick={() => { setBusy(true); void onConfirm().finally(() => setBusy(false)); }}><Wallet size={17} />{busy ? "等待钱包" : "在钱包中确认"}</button></div></div></Modal>;
}

function Modal({ title, onClose, children }: PropsWithChildren<{ title: string; onClose: () => void }>) {
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}><section className="modal" role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><button className="icon-button" aria-label="关闭" title="关闭" onClick={onClose}><X /></button></header>{children}</section></div>;
}

function Mono({ value }: { value: string }) {
  const { notify } = useApp();
  return <span className="mono-value" title={value}><code>{shorten(value, 10, 7)}</code><button aria-label="复制完整值" title="复制完整值" onClick={(event) => { event.stopPropagation(); void navigator.clipboard.writeText(value).then(() => notify("success", "已复制", shorten(value, 12, 8))); }}><Copy size={13} /></button></span>;
}

function StatusBadge({ tone, label }: { tone: "verified" | "pending" | "danger" | "neutral"; label: string }) {
  return <span className={`status-badge ${tone}`}>{tone === "verified" ? <Check /> : tone === "danger" ? <AlertCircle /> : tone === "pending" ? <LoaderCircle /> : <Unplug />}{label}</span>;
}

function StatusIcon({ status }: { status: Activity["status"] }) {
  const Icon = status === "failed" ? AlertCircle : status === "pending" ? LoaderCircle : status === "local" ? FlaskConical : Check;
  return <span className={`activity-status-icon ${status}`}><Icon /></span>;
}

function LoadingState({ label }: { label: string }) { return <div className="state-inline"><LoaderCircle className="spin" /><span>{label}</span></div>; }
function ErrorState({ title, detail }: { title: string; detail: string }) { return <div className="error-state"><AlertCircle /><div><strong>{title}</strong><p>{detail}</p></div></div>; }
function EmptyState({ icon: Icon, title, detail, action }: { icon: LucideIcon; title: string; detail: string; action?: React.ReactNode }) { return <div className="empty-state"><Icon /><h2>{title}</h2><p>{detail}</p>{action}</div>; }
function Toast({ tone, title, detail }: ToastState) { return <div className={`toast ${tone}`} role={tone === "error" ? "alert" : "status"}>{tone === "success" ? <Check /> : tone === "error" ? <AlertCircle /> : <ActivityIcon />}<div><strong>{title}</strong><span>{detail}</span></div></div>; }
function statusZh(status: string) { return ({ open: "开放", answered: "已接受", settled: "已结算", cancelled: "已取消", accepted: "已验收", paid: "已支付", rejected: "已拒绝" } as Record<string, string>)[status] ?? status; }
function activityStatus(status: Activity["status"]) { return ({ pending: "待确认", confirmed: "已确认", failed: "失败", local: "本地" } as const)[status]; }

export default App;
