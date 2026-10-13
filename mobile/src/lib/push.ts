// 새 요청이 오면 사장님 휴대폰에 알림. EAS 프로젝트(projectId)로 만든 실제 앱에서만 동작한다.
// Expo Go(미리보기)는 원격 알림을 지원하지 않아서 알림 모듈을 아예 불러오지 않는다.
import Constants, { ExecutionEnvironment } from 'expo-constants';
import * as Device from 'expo-device';
import { Platform } from 'react-native';
import { api } from './api';

type N = typeof import('expo-notifications');
const ENABLED = Platform.OS !== 'web' && Constants.executionEnvironment !== ExecutionEnvironment.StoreClient;
export const Notifications: N | null = ENABLED ? require('expo-notifications') : null;

Notifications?.setNotificationHandler({
  handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
});

let cached: string | null = null;
export async function pushToken(ask = false): Promise<string | null> {
  if (cached) return cached;
  if (!Notifications || !Device.isDevice) return null;
  try {
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', { name: '새 요청 알림', importance: Notifications.AndroidImportance.HIGH });
    }
    let { status } = await Notifications.getPermissionsAsync();
    if (status !== 'granted' && ask) status = (await Notifications.requestPermissionsAsync()).status;
    if (status !== 'granted') return null;
    const projectId = (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas?.projectId ?? Constants.easConfig?.projectId;
    if (!projectId) return null;
    cached = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
    return cached;
  } catch {
    return null;
  }
}

export async function registerPush(token: string) {
  const t = await pushToken(true);
  if (t) api.push(token, t).catch(() => {}); // 알림은 없어도 앱은 쓸 수 있다
}
