// 앱 푸시: 기기 토큰(Expo)을 받아 사이트가 회원에게 저장 (서버 appready.py /me/push/app → Expo 푸시 → APNs·FCM)
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
});

export type PushResult = { state: 'on'; token: string } | { state: 'denied' | 'fail' };

/** ask=false면 이미 허락한 경우에만 토큰을 받음 (묻지 않음) */
export async function getPushToken(ask: boolean): Promise<PushResult> {
  if (!Device.isDevice) return { state: 'fail' };
  try {
    let perm = await Notifications.getPermissionsAsync();
    if (perm.status !== 'granted' && ask && perm.canAskAgain) perm = await Notifications.requestPermissionsAsync();
    if (perm.status !== 'granted') return { state: 'denied' };
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', { name: '소보루 알림', importance: Notifications.AndroidImportance.HIGH, lightColor: '#F89B00' });
    }
    const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
    const { data } = await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined);
    return { state: 'on', token: data };
  } catch {
    return { state: 'fail' };
  }
}

/** 처음 묻는 건지 (아직 허락도 거절도 안 함) */
export async function notAskedYet(): Promise<boolean> {
  try {
    const perm = await Notifications.getPermissionsAsync();
    return perm.status === 'undetermined';
  } catch {
    return false;
  }
}

/** 알림을 눌렀을 때 열 주소 (서버가 data.url에 넣음) */
export function linkOf(resp: Notifications.NotificationResponse | null | undefined): string {
  const url = resp?.notification.request.content.data?.url;
  return typeof url === 'string' ? url : '';
}
