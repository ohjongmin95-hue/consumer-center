// 소보루 CS 기업 서버(biz 주소의 /api/v1)와 주고받기. 로그인하면 받은 토큰으로만 우리 회사 요청을 연다.
import Constants from 'expo-constants';
import { Platform } from 'react-native';

const configured = (Constants.expoConfig?.extra as { apiBase?: string } | undefined)?.apiBase ?? 'https://biz.soboru.co.kr';
// 웹 미리보기는 같은 주소의 서버를 쓴다
export const API_BASE = Platform.OS === 'web' ? '' : configured;
export const SITE_BASE = configured; // 약관처럼 브라우저로 여는 사장님 사이트 주소

export type Operator = { name: string; ceo: string; biz_no: string; address: string; manager: string };
export type Meta = { name: string; cats: string[]; industries?: string[]; couriers: string[]; operator: Operator; signup: string; forgot: string; privacy: string };
export type CompanyInfo = { id: number; name: string; login_id: string; link: string };
export type BizCase = {
  id: number;
  no: string;
  category: string;
  title: string;
  name: string;
  status: string;
  status_label: string;
  decision: string;
  decision_label: string;
  pending: boolean;
  overdue: boolean;
  due: string;
  created: string;
  updated: string;
};
export type FileRef = { id: number; name: string; url: string };
export type Track = { kind: string; label: string; courier: string; invoice: string; level: number; status: string; place: string; time: string; done: boolean; note: string; live: boolean; link: string };
export type CaseEvent = { id: number; kind: 'me' | 'co' | 'sys' | string; text: string; reply: string; created: string; files: FileRef[] };
export type BizDetail = BizCase & {
  body: string;
  want: string;
  order_no: string;
  product: string;
  received_on: string;
  info_ask: string;
  phone: string;
  email: string;
  plan: { title: string; steps: string[]; reply: string };
  ret: { status: string; courier: string; tracking: string; out_courier: string; out_tracking: string };
  refund: { possible: boolean; status: string; bank: string; account: string; holder: string };
  events: CaseEvent[];
  files: FileRef[];
  tracks?: Track[];
  can: { ship_track?: boolean; approve: boolean; hold: boolean; ask: boolean; reply: boolean; ret_received: boolean; out_ship: boolean; refund_done: boolean };
  message?: string;
};
export type Kpi = { n: number; auto: number; res: number | null; late: number };
export type Home = {
  company: CompanyInfo;
  kpi: Kpi;
  counts: { all: number; pending: number; open: number; late: number; auto_rules: number; ret?: number };
  pending: BizCase[];
  recent: BizCase[];
  alerts?: Alert[];
  news?: NewsItem[];
};

export type Alert = { kind: 'product' | 'category'; label: string; n: number; cats: string[] };
export type NewsItem = { id: number; title: string; body?: string; source_url?: string; created: string };
export type Rule = { category: string; auto: boolean; reply: string; faq: string; cond: string; cond_ok: boolean };
export type Rules = { rules: Rule[]; conds: { value: string; label: string }[]; chat: { asked: number; solved: number; filed: number }; link: string; message?: string };
export type Product = { id: number; name: string; price: string; stock: string; info: string };
export type Products = { products: Product[]; stocks: { value: string; label: string }[]; ai: boolean; message?: string };
export type Bar = { label: string; n: number; pct?: number };
export type Stats = {
  kpi: Kpi;
  reply_h: number | null;
  cats: Bar[];
  how: Bar[];
  weeks: Bar[];
  compare: null | { ready: false; have: number; need: number } | { ready: true; peers: number; mine: Record<string, number | null>; avg: Record<string, number | null> };
};
export type Report = { ym: string; months: string[]; n: number; prev_n: number; auto: number; res: number | null; reply_h: number | null; late: number; cats: Bar[]; top_products: Bar[]; by_channel: Bar[]; text: string };
export type Settings = {
  name: string; login_id: string; contact: string; notify_email: string; industry: string; tone: string;
  return_address: string; return_courier: string; return_memo: string; phone: string; kakao: boolean; report_mail: boolean; kakao_ready: boolean; return_guide: string;
  industries: string[]; tones: { value: string; label: string }[]; couriers: string[]; message?: string; token?: string;
};
export type LawItem = { label: string; title: string; source: string; text: string };
export type GuideItem = { id: string; title: string; points: { text: string; label: string }[]; sample: string; laws: LawItem[] };
export type NewForm = { channels: string[]; cats: string[]; wants: string[]; hints: Record<string, string> };

export class ApiError extends Error {
  constructor(message: string, public status = 0) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...(init.headers as Record<string, string>) };
  if (token) headers.Authorization = 'Bearer ' + token;
  let res: Response;
  try {
    res = await fetch(API_BASE + path, { ...init, headers });
  } catch {
    throw new ApiError('인터넷 연결을 확인해 주세요.');
  }
  const data = await res.json().catch(() => null);
  // JSON이 아니면 서버가 아직 앱 기능으로 업데이트되지 않은 것 (홈페이지 화면이 대신 온다)
  if (data === null) throw new ApiError(res.ok || res.status === 404 ? `서버가 아직 앱용으로 업데이트되지 않았어요. 잠시 후 다시 시도해 주세요. (${res.status})` : `서버에 문제가 있어요. 잠시 후 다시 시도해 주세요. (${res.status})`, res.status);
  if (!res.ok) throw new ApiError((data as { error?: string }).error || `잠시 후 다시 시도해 주세요. (${res.status})`, res.status);
  return data as T;
}
const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export const api = {
  meta: () => call<Meta>('/api/v1/meta'),
  login: (login_id: string, password: string) => call<{ token: string; company: CompanyInfo }>('/api/v1/login', json({ login_id, password })),
  home: (t: string) => call<Home>('/api/v1/home', {}, t),
  cases: (t: string, f: string, q = '') => call<{ cases: BizCase[]; counts: Record<string, number> }>(`/api/v1/cases?f=${f}&q=${encodeURIComponent(q)}`, {}, t),
  case: (t: string, id: number) => call<BizDetail>('/api/v1/cases/' + id, {}, t),
  act: (t: string, id: number, fields: Record<string, string>) => call<BizDetail>('/api/v1/cases/' + id, json(fields), t),
  draft: (t: string, id: number) => call<{ text?: string; error?: string }>(`/api/v1/cases/${id}/draft`, json({}), t),
  approveMany: (t: string, category: string) => call<{ approved: number; message: string }>('/api/v1/approve_many', json({ category }), t),
  push: (t: string, push_token: string) => call<{ ok: boolean }>('/api/v1/push', json({ push_token }), t),
  logout: (t: string, push_token: string) => call<{ ok: boolean }>('/api/v1/logout', json({ push_token }), t),
  signup: (f: Record<string, string>) => call<{ ok: boolean; name: string; message: string }>('/api/v1/signup', json(f)),
  forgot: (login_id: string) => call<{ ok: boolean; message: string }>('/api/v1/forgot', json({ login_id })),
  rules: (t: string) => call<Rules>('/api/v1/rules', {}, t),
  saveRule: (t: string, f: Partial<Rule> & { category: string }) => call<Rules>('/api/v1/rules', json(f), t),
  products: (t: string) => call<Products>('/api/v1/products', {}, t),
  saveProduct: (t: string, f: Partial<Product> & { act?: 'delete' }) => call<Products>('/api/v1/products', json(f), t),
  stats: (t: string) => call<Stats>('/api/v1/stats', {}, t),
  report: (t: string, ym = '') => call<Report>('/api/v1/report?ym=' + ym, {}, t),
  settings: (t: string) => call<Settings>('/api/v1/settings', {}, t),
  saveSettings: (t: string, f: Record<string, string | boolean>) => call<Settings>('/api/v1/settings', json(f), t),
  guide: (t: string) => call<{ guide: GuideItem[]; kca: string }>('/api/v1/guide', {}, t),
  news: (t: string) => call<{ news: NewsItem[] }>('/api/v1/news', {}, t),
  newForm: (t: string) => call<NewForm>('/api/v1/new', {}, t),
  newCase: (t: string, f: Record<string, string>) => call<{ ok: boolean; id: number; message: string }>('/api/v1/new', json(f), t),
  record: (t: string, id: number) => call<{ no: string; html: string }>(`/api/v1/cases/${id}/record`, {}, t),
  leave: (t: string, password: string) => call<{ ok: boolean; message: string }>('/api/v1/leave', json({ password }), t),
};

export function fmtDate(iso: string) {
  const d = new Date(iso.replace(' ', 'T'));
  if (isNaN(d.getTime())) return iso.slice(0, 10);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
