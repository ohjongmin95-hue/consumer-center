// 소보루 앱: 사이트(soboru.co.kr)를 웹뷰로 띄우고, 아래 탭·푸시 알림·Apple 로그인·공유·오프라인 화면은 앱이 직접 맡는다.
// 사이트와는 templates/app_bridge.html의 window.SoboruApp으로 주고받는다.
import * as AppleAuthentication from 'expo-apple-authentication';
import Constants from 'expo-constants';
import * as Linking from 'expo-linking';
import * as Notifications from 'expo-notifications';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BackHandler, Platform, Share, StyleSheet, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { WebView, type WebViewMessageEvent, type WebViewNavigation } from 'react-native-webview';
import { SITE, shouldLoadInside, sitePath, toSiteUrl, openOutside } from './links';
import Offline from './Offline';
import { getPushToken, linkOf, notAskedYet } from './push';
import TabBar, { activeTab, tabsFor, type Tab } from './TabBar';

SplashScreen.preventAutoHideAsync().catch(() => {});

const VERSION = Constants.expoConfig?.version ?? '1.0.0';
// 사이트가 앱인지 알아보는 표시 (appready.APP_UA_RE)
const UA_SUFFIX = `SoboruApp/${VERSION} (${Platform.OS === 'ios' ? 'ios' : 'android'})`;
// 사이트의 공유 버튼(navigator.share)을 기기 공유 창으로
const BEFORE_LOAD = `(function(){try{navigator.share=function(d){d=d||{};window.ReactNativeWebView.postMessage(JSON.stringify({type:'share',title:d.title||'',text:d.text||'',url:d.url||location.href}));return Promise.resolve();};}catch(e){}})();true;`;

type Msg = { type?: string; member?: boolean; path?: string; next?: string; link?: string; title?: string; text?: string; url?: string };

function Main() {
  const web = useRef<WebView>(null);
  const [start] = useState(SITE + '/?src=app');
  const [path, setPath] = useState('/');
  const [member, setMember] = useState(false);
  const [canBack, setCanBack] = useState(false);
  const [offline, setOffline] = useState(false);
  const shown = useRef(false);
  const pushedFor = useRef('');  // 이번 실행에서 토큰을 저장한 회원 상태 (같은 토큰을 매 화면 보내지 않게)
  const pending = useRef('');  // 첫 화면이 뜨기 전에 온 링크(알림·유니버설 링크)는 뜬 뒤에 염

  const run = useCallback((js: string) => web.current?.injectJavaScript(`${js};true;`), []);
  const go = useCallback((url: string) => {
    if (!shown.current) { pending.current = url; return; }
    run(`location.href=${JSON.stringify(url)}`);
  }, [run]);

  // 알림을 눌러 열었으면 그 화면으로 (앱이 꺼져 있다가 열린 경우 포함)
  const lastResponse = Notifications.useLastNotificationResponse();
  useEffect(() => {
    const url = toSiteUrl(linkOf(lastResponse));
    if (url) go(url);
  }, [lastResponse, go]);

  // 유니버설 링크(soboru.co.kr/… 를 눌러 앱이 열림)
  const incoming = Linking.useLinkingURL();
  useEffect(() => {
    const url = incoming ? toSiteUrl(incoming) : '';
    if (url) go(url);
  }, [incoming, go]);

  // 안드로이드 뒤로 가기: 웹 화면부터 뒤로
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (canBack) { web.current?.goBack(); return true; }
      return false;
    });
    return () => sub.remove();
  }, [canBack]);

  const savePush = useCallback(async (ask: boolean, report: boolean) => {
    const r = await getPushToken(ask);
    if (r.state === 'on') run(`window.SoboruApp&&SoboruApp.registerPush(${JSON.stringify(r.token)})`);
    if (report) run(`window.SoboruApp&&SoboruApp.pushResult(${JSON.stringify(r.state)})`);
    return r.state;
  }, [run]);

  const appleLogin = useCallback(async (next: string, link: string) => {
    if (Platform.OS !== 'ios') return;
    try {
      const cred = await AppleAuthentication.signInAsync({
        requestedScopes: [AppleAuthentication.AppleAuthenticationScope.FULL_NAME, AppleAuthentication.AppleAuthenticationScope.EMAIL],
      });
      // 이름은 처음 동의할 때 한 번만 옴. 웹 로그인과 같은 모양으로 넘김 (members.apple_name)
      const name = cred.fullName && (cred.fullName.givenName || cred.fullName.familyName)
        ? JSON.stringify({ name: { firstName: cred.fullName.givenName || '', lastName: cred.fullName.familyName || '' } }) : '';
      run(`window.SoboruApp&&SoboruApp.appleDone(${JSON.stringify({ code: cred.authorizationCode || '', user: name, next, link })})`);
    } catch {
      // 사용자가 닫음(ERR_REQUEST_CANCELED) 등: 그대로 둠
    }
  }, [run]);

  const onMessage = useCallback((e: WebViewMessageEvent) => {
    let m: Msg;
    try { m = JSON.parse(e.nativeEvent.data); } catch { return; }
    if (m.type === 'page') {
      const isMember = !!m.member;
      setMember(isMember);
      if (isMember && pushedFor.current !== 'member') {
        pushedFor.current = 'member';
        // 로그인한 뒤 처음이면 알림을 받을지 물음 (댓글·답변·제보 소식), 이미 허락했으면 조용히 토큰만 저장
        notAskedYet().then((first) => savePush(first, false));
      }
      if (!isMember) pushedFor.current = '';
    } else if (m.type === 'push-enable') {
      savePush(true, true);
    } else if (m.type === 'apple-login') {
      appleLogin(m.next || '', m.link || '');
    } else if (m.type === 'share') {
      const url = m.url || '';
      const message = Platform.OS === 'ios' ? (m.text || m.title || '') : [m.title, m.text, url].filter(Boolean).join('\n');
      Share.share(Platform.OS === 'ios' ? { message, url } : { message, title: m.title }).catch(() => {});
    }
  }, [savePush, appleLogin]);

  const onNav = useCallback((nav: WebViewNavigation) => {
    setCanBack(nav.canGoBack);
    const p = sitePath(nav.url);
    if (p) setPath(p.split(/[?#]/)[0]);
  }, []);

  const onTab = useCallback((t: Tab) => {
    setOffline(false);
    if (activeTab(path) === t.key && path === t.path) run('window.scrollTo({top:0,behavior:"smooth"})');
    else go(SITE + t.path);
  }, [path, go, run]);

  const firstShown = useCallback(() => {
    if (shown.current) return;
    shown.current = true;
    SplashScreen.hideAsync().catch(() => {});
    if (pending.current) { go(pending.current); pending.current = ''; }
  }, [go]);

  return (
    <View style={s.root}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top']} style={s.top} />
      <View style={s.body}>
        <WebView
          ref={web}
          source={{ uri: start }}
          applicationNameForUserAgent={UA_SUFFIX}
          injectedJavaScriptBeforeContentLoaded={BEFORE_LOAD}
          onMessage={onMessage}
          onNavigationStateChange={onNav}
          onShouldStartLoadWithRequest={(req) => shouldLoadInside(req.url, req.isTopFrame ?? true, go)}
          onOpenWindow={(e) => { const u = e.nativeEvent.targetUrl; if (toSiteUrl(u)) go(u); else openOutside(u); }}
          onLoadEnd={firstShown}
          onError={() => { setOffline(true); firstShown(); }}
          onContentProcessDidTerminate={() => web.current?.reload()}
          onRenderProcessGone={() => web.current?.reload()}
          sharedCookiesEnabled
          thirdPartyCookiesEnabled
          domStorageEnabled
          allowsBackForwardNavigationGestures
          pullToRefreshEnabled
          allowsInlineMediaPlayback
          setSupportMultipleWindows={false}
          textZoom={100}
          style={s.web}
        />
        {offline && <Offline onRetry={() => { setOffline(false); web.current?.reload(); }} />}
      </View>
      <TabBar tabs={tabsFor(member)} active={activeTab(path)} onPress={onTab} />
    </View>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <Main />
    </SafeAreaProvider>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#FFFFFF' },
  top: { backgroundColor: '#FFFFFF' },
  body: { flex: 1 },
  web: { flex: 1, backgroundColor: '#FFFFFF' },
});
