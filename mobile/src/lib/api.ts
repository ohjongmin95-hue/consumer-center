// 소보루 CS 서버(/api/v1)와 주고받기. 앱은 쿠키 없이 민원마다 받은 토큰으로만 민원을 연다.
import Constants from 'expo-constants';
import { Platform } from 'react-native';

const configured = (Constants.expoConfig?.extra as { apiBase?: string } | undefined)?.apiBase ?? 'https://cs.soboru.co.kr';
// 웹 미리보기는 같은 주소의 서버를 쓴다
export const API_BASE = Platform.OS === 'web' ? '' : configured;

export type Cat = { name: string; hint: string };
export type Meta = {
  name: string;
  cats: Cat[];
  wants: string[];
  couriers: string[];
  banks: string[];
  reply_days: number;
  max_files: number;
  steps: string[];
  privacy_url: string;
  guide_url: string;
};
export type Company = { id: number; name: string; member: boolean; contact?: string; ret_guide?: string; reply_days?: number };
export type CaseSummary = {
  id: number;
  no: string;
  company_id: number;
  company_name: string;
  member: boolean;
  category: string;
  title: string;
  status: string;
  status_label: string;
  step: number;
  created: string;
  updated: string;
  token?: string;
};
export type FileRef = { id: number; name: string; url: string };
export type CaseEvent = { id: number; kind: 'me' | 'co' | 'sys' | string; text: string; reply: string; created: string; files: FileRef[] };
export type CaseDetail = CaseSummary & {
  body: string;
  want: string;
  order_no: string;
  product: string;
  received_on: string;
  due: string;
  info_ask: string;
  overdue: boolean;
  contact: string;
  ret_guide: string;
  ret: { status: string; courier: string; tracking: string; out_courier: string; out_tracking: string };
  refund: { possible: boolean; status: string; bank: string; account: string; holder: string };
  events: CaseEvent[];
  files: FileRef[];
  can: { rate: boolean; again: boolean; ship: boolean; cancel: boolean; refund: boolean; info: boolean; add: boolean };
  message?: string;
};
export type ChatAnswer = { category: string | null; faq?: string; auto?: boolean; cond?: string; member?: boolean; ask_days?: boolean; error?: string };
export type Photo = { uri: string; name: string; type: string };

export class ApiError extends Error {}

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
  if (!res.ok) throw new ApiError((data as { error?: string }).error || '잠시 후 다시 시도해 주세요.');
  return data as T;
}
const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function form(fields: Record<string, string | number | boolean | undefined>, photos: Photo[] = []): RequestInit {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== '') fd.append(k, String(v));
  for (const p of photos) {
    if (Platform.OS === 'web') continue; // 웹 미리보기에서는 사진을 보내지 않는다
    fd.append('files', { uri: p.uri, name: p.name, type: p.type } as unknown as Blob);
  }
  return { method: 'POST', body: fd };
}

export const api = {
  meta: () => call<Meta>('/api/v1/meta'),
  companies: (q: string) => call<Company[]>('/api/v1/companies?q=' + encodeURIComponent(q)),
  company: (id: number) => call<Company>('/api/v1/companies/' + id),
  chat: (companyId: number | null, body: Record<string, string>) => call<ChatAnswer>('/api/v1/chat' + (companyId ? '/' + companyId : ''), json(body)),
  submit: (fields: Record<string, string | number | boolean | undefined>, photos: Photo[]) =>
    call<{ id: number; no: string; token: string }>('/api/v1/cases', form(fields, photos)),
  lookup: (phone: string, password: string) => call<{ cases: CaseSummary[] }>('/api/v1/lookup', json({ phone, password })),
  mine: (tokens: string[]) => call<{ cases: CaseSummary[] }>('/api/v1/mine', json({ tokens })),
  case: (id: number, token: string) => call<CaseDetail>('/api/v1/cases/' + id, {}, token),
  act: (id: number, token: string, fields: Record<string, string>, photos: Photo[] = []) =>
    call<CaseDetail>('/api/v1/cases/' + id, photos.length ? form(fields, photos) : json(fields), token),
  push: (pushToken: string, tokens: string[]) => call<{ ok: boolean }>('/api/v1/push', json({ push_token: pushToken, tokens })),
};

export function fmtDate(iso: string) {
  const d = new Date(iso.replace(' ', 'T'));
  if (isNaN(d.getTime())) return iso.slice(0, 10);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
