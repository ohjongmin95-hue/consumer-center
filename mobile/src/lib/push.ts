// 기업 답변이 오면 휴대폰 알림. EAS 프로젝트(projectId)가 생긴 뒤 실제 휴대폰에서만 동작한다.
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

export async function registerPush(tokens: string[]) {
  if (!Notifications || !Device.isDevice || !tokens.length) return;
  try {
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', { name: '민원 진행 알림', importance: Notifications.AndroidImportance.HIGH });
    }
    let { status } = await Notifications.getPermissionsAsync();
    if (status !== 'granted') status = (await Notifications.requestPermissionsAsync()).status;
    if (status !== 'granted') return;
    const projectId = (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas?.projectId ?? Constants.easConfig?.projectId;
    if (!projectId) return;
    const { data } = await Notifications.getExpoPushTokenAsync({ projectId });
    await api.push(data, tokens);
  } catch {
    // 알림은 없어도 앱은 쓸 수 있다
  }
}
