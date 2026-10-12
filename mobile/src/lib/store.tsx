// 휴대폰에 두는 내 민원 토큰. 앱을 지우면 같이 사라지고, 휴대폰 번호와 조회 비밀번호로 다시 찾을 수 있다.
import * as SecureStore from 'expo-secure-store';
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Platform } from 'react-native';
import { api, Meta } from './api';
import { registerPush } from './push';

const KEY = 'soboru.cs.tokens';

async function load(): Promise<string[]> {
  try {
    const raw = Platform.OS === 'web' ? globalThis.localStorage?.getItem(KEY) : await SecureStore.getItemAsync(KEY);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.filter((t) => typeof t === 'string') : [];
  } catch {
    return [];
  }
}
async function save(tokens: string[]) {
  const raw = JSON.stringify(tokens);
  try {
    if (Platform.OS === 'web') globalThis.localStorage?.setItem(KEY, raw);
    else await SecureStore.setItemAsync(KEY, raw);
  } catch {}
}

type Store = {
  ready: boolean;
  tokens: string[];
  meta: Meta | null;
  addTokens: (t: string[]) => Promise<void>;
  forget: () => Promise<void>;
};
const Ctx = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [tokens, setTokens] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    load().then((t) => {
      setTokens(t);
      setReady(true);
    });
    api.meta().then(setMeta).catch(() => {});
  }, []);
  const addTokens = useCallback(async (t: string[]) => {
    const next = Array.from(new Set([...t, ...(await load())])).slice(0, 100);
    setTokens(next);
    await save(next);
    registerPush(next);
  }, []);
  const forget = useCallback(async () => {
    setTokens([]);
    await save([]);
  }, []);
  const value = useMemo(() => ({ ready, tokens, meta, addTokens, forget }), [ready, tokens, meta, addTokens, forget]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const s = useContext(Ctx);
  if (!s) throw new Error('StoreProvider 밖에서 썼어요');
  return s;
}
