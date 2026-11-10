// 웹뷰 안에서 열 주소와 밖(브라우저·다른 앱)으로 보낼 주소를 가른다.
import Constants from 'expo-constants';
import * as Linking from 'expo-linking';
import * as WebBrowser from 'expo-web-browser';
import { Platform } from 'react-native';

// 첫 화면. 도메인을 연결하기 전엔 consumerjebo.co.kr/moabap, 연결한 뒤엔 서버가 새 주소로 넘김 (moabap/__init__.py mount)
export const SITE: string = (Constants.expoConfig?.extra?.site as string) || 'https://consumerjebo.co.kr/moabap';

function parts(url: string): [string, string] {
  const m = /^https?:\/\/([^/:?#]+)(?::\d+)?([^?#]*)/i.exec(url);
  return m ? [m[1].toLowerCase().replace(/^www\./, ''), m[2] || '/'] : ['', ''];
}

/** 모아밥 화면인지: moabap.com(운영자 11/11 구매)·moabap.co.kr·moabap.kr, 또는 임시 주소 consumerjebo.co.kr/moabap */
export function isOwn(url: string): boolean {
  const [h, p] = parts(url);
  if (['moabap.com', 'moabap.co.kr', 'moabap.kr'].includes(h)) return true;
  return h === 'consumerjebo.co.kr' && (p === '/moabap' || p.startsWith('/moabap/'));
}

export function openOutside(url: string) {
  WebBrowser.openBrowserAsync(url, { controlsColor: '#B57BFF', dismissButtonStyle: 'close' }).catch(() => Linking.openURL(url).catch(() => {}));
}

/** 웹뷰가 이 주소를 직접 열지(true) 아니면 밖으로 보낼지(false). tel: 같은 주소는 그 앱으로. */
export function shouldLoadInside(url: string, isTopFrame: boolean): boolean {
  if (/^(about:|data:|blob:)/i.test(url)) return true;
  if (/^https?:/i.test(url)) {
    if (!isTopFrame || isOwn(url)) return true;
    openOutside(url);
    return false;
  }
  if (Platform.OS === 'android' && /^intent:/i.test(url)) Linking.openURL(url).catch(() => {});
  else Linking.openURL(url).catch(() => {});
  return false;
}
