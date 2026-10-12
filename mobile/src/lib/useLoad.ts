// 화면에 들어올 때마다 서버에서 다시 불러온다. 토큰이 끊겼으면(401) 로그인 화면으로.
import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { ApiError } from './api';
import { useAuth } from './auth';

export function useLoad<T>(fn: (token: string) => Promise<T>) {
  const { session, logout } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState('');
  const token = session?.token ?? '';
  const reload = useCallback(async () => {
    if (!token) return;
    try {
      setData(await fn(token));
      setErr('');
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return logout();
      setErr((e as Error).message);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, logout]);
  useFocusEffect(
    useCallback(() => {
      reload();
    }, [reload]),
  );
  return { data, setData, err, setErr, reload, token };
}

// 저장 버튼용: 401이면 로그아웃, 아니면 문구를 돌려준다
export function errText(e: unknown, logout: () => void) {
  if (e instanceof ApiError && e.status === 401) {
    logout();
    return '';
  }
  return (e as Error).message;
}
