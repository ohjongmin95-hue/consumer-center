// 소보루 CS 기업 서버(biz 주소의 /api/v1)와 주고받기. 로그인하면 받은 토큰으로만 우리 회사 민원을 연다.
import Constants from 'expo-constants';
import { Platform } from 'react-native';

const configured = (Constants.expoConfig?.extra as { apiBase?: string } | undefined)?.apiBase ?? 'https://biz.soboru.co.kr';
// 웹 미리보기는 같은 주소의 서버를 쓴다
export const API_BASE = Platform.OS === 'web' ? '' : configured;

export type Operator = { name: string; ceo: string; biz_no: string; address: string; manager: string };
export type Meta = { name: string; cats: string[]; couriers: string[]; operator: Operator; signup: string; forgot: string; privacy: string };
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
  can: { approve: boolean; hold: boolean; ask: boolean; reply: boolean; ret_received: boolean; out_ship: boolean; refund_done: boolean };
  message?: string;
};
export type Kpi = { n: number; auto: number; res: number | null; late: number };
export type Home = {
  company: CompanyInfo;
  kpi: Kpi;
  counts: { all: number; pending: number; open: number; late: number; auto_rules: number };
  pending: BizCase[];
  recent: BizCase[];
};

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
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError((data as { error?: string }).error || '잠시 후 다시 시도해 주세요.', res.status);
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
};

export function fmtDate(iso: string) {
  const d = new Date(iso.replace(' ', 'T'));
  if (isNaN(d.getTime())) return iso.slice(0, 10);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
