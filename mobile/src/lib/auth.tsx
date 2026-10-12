// 로그인 상태. 토큰은 휴대폰 보안 저장소에 둔다(웹 미리보기는 localStorage). 비밀번호를 바꾸면 서버가 토큰을 끊어서 다시 로그인하게 된다.
import * as SecureStore from 'expo-secure-store';
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Platform } from 'react-native';
import { api, CompanyInfo, Meta } from './api';
import { pushToken, registerPush } from './push';

const KEY = 'soboru.biz.session';
type Session = { token: string; company: CompanyInfo };

async function load(): Promise<Session | null> {
  try {
    const raw = Platform.OS === 'web' ? globalThis.localStorage?.getItem(KEY) : await SecureStore.getItemAsync(KEY);
    const v = raw ? JSON.parse(raw) : null;
    return v && typeof v.token === 'string' ? v : null;
  } catch {
    return null;
  }
}
async function save(v: Session | null) {
  try {
    if (Platform.OS === 'web') v ? globalThis.localStorage?.setItem(KEY, JSON.stringify(v)) : globalThis.localStorage?.removeItem(KEY);
    else v ? await SecureStore.setItemAsync(KEY, JSON.stringify(v)) : await SecureStore.deleteItemAsync(KEY);
  } catch {}
}

type Auth = {
  ready: boolean;
  session: Session | null;
  meta: Meta | null;
  login: (id: string, pw: string) => Promise<void>;
  logout: () => Promise<void>;
};
const Ctx = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    load().then((s) => {
      setSession(s);
      setReady(true);
      if (s) registerPush(s.token);
    });
    api.meta().then(setMeta).catch(() => {});
  }, []);
  const login = useCallback(async (id: string, pw: string) => {
    const r = await api.login(id, pw);
    const s = { token: r.token, company: r.company };
    await save(s);
    setSession(s);
    registerPush(s.token);
  }, []);
  const logout = useCallback(async () => {
    const s = await load();
    const t = await pushToken();
    if (s && t) api.logout(s.token, t).catch(() => {});
    await save(null);
    setSession(null);
  }, []);
  const value = useMemo(() => ({ ready, session, meta, login, logout }), [ready, session, meta, login, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const s = useContext(Ctx);
  if (!s) throw new Error('AuthProvider 밖에서 썼어요');
  return s;
}
