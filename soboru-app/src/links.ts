// 웹뷰 안에서 열 주소와 밖(브라우저·다른 앱)으로 보낼 주소를 가른다.
import Constants from 'expo-constants';
import * as Linking from 'expo-linking';
import * as WebBrowser from 'expo-web-browser';
import { Platform } from 'react-native';

export const SITE: string = (Constants.expoConfig?.extra?.site as string) || 'https://soboru.co.kr';
// 사이트 주소 (소보루·소비자제보센터는 같은 서버, 같은 회원)
const OWN = ['soboru.co.kr', 'consumerjebo.co.kr'];
// 로그인 화면: 웹뷰 안에서 이어져야 로그인 쿠키가 사이트에 붙음
const AUTH = ['kauth.kakao.com', 'accounts.kakao.com', 'logins.daum.net', 'appleid.apple.com', 'nid.naver.com'];

function host(url: string): string {
  const m = /^https?:\/\/([^/:?#]+)/i.exec(url);
  return m ? m[1].toLowerCase().replace(/^www\./, '') : '';
}
const matches = (h: string, list: string[]) => list.some((d) => h === d || h.endsWith('.' + d));

export const isOwn = (url: string) => matches(host(url), OWN);
export const sitePath = (url: string) => (isOwn(url) ? url.replace(/^https?:\/\/[^/]+/i, '') || '/' : '');

/** 사이트 안 주소(/me 같은)나 사이트 전체 주소를 웹뷰에 넣을 주소로. 다른 곳이면 '' */
export function toSiteUrl(link: string): string {
  if (!link) return '';
  if (link.startsWith('/') && !link.startsWith('//')) return SITE + link;
  return isOwn(link) ? link : '';
}

export function openOutside(url: string) {
  WebBrowser.openBrowserAsync(url, { controlsColor: '#EF7300', dismissButtonStyle: 'close' }).catch(() => Linking.openURL(url).catch(() => {}));
}

/** 안드로이드 intent:// (카카오톡 로그인 등): 앱을 열고, 없으면 browser_fallback_url → 스토어 */
function openIntent(url: string, load: (u: string) => void) {
  const fallback = /S\.browser_fallback_url=([^;]+)/.exec(url);
  const pkg = /;package=([^;]+)/.exec(url);
  Linking.openURL(url).catch(() => {
    if (fallback) load(decodeURIComponent(fallback[1]));
    else if (pkg) Linking.openURL('market://details?id=' + pkg[1]).catch(() => {});
  });
}

/**
 * 웹뷰가 이 주소를 직접 열지(true) 아니면 밖으로 보낼지(false).
 * 사이트·로그인 화면은 안에서, 다른 사이트는 앱 안 브라우저로, kakaotalk:// tel: 같은 주소는 그 앱으로.
 */
export function shouldLoadInside(url: string, isTopFrame: boolean, load: (u: string) => void): boolean {
  if (/^(about:|data:|blob:)/i.test(url)) return true;
  if (/^https?:/i.test(url)) {
    const h = host(url);
    if (!isTopFrame || matches(h, OWN) || matches(h, AUTH)) return true;  // 글 속 동영상·지도 같은 틀은 그대로
    openOutside(url);
    return false;
  }
  if (Platform.OS === 'android' && /^intent:/i.test(url)) openIntent(url, load);
  else Linking.openURL(url).catch(() => {});
  return false;
}
