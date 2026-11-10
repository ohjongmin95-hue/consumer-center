// 모아밥 앱 (운영자 2026-11-11): 모아밥 사이트(app.json extra.site)를 웹뷰로 띄우고, 뒤로 가기·공유·전화·오프라인 화면은 앱이 맡는다.
// 사이트의 아래 탭(홈·주문 내역)을 그대로 쓴다.
import Constants from 'expo-constants';
import * as Linking from 'expo-linking';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BackHandler, Platform, Share, StyleSheet, ToastAndroid, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { WebView, type WebViewMessageEvent, type WebViewNavigation } from 'react-native-webview';
import { SITE, isOwn, openOutside, shouldLoadInside } from './links';
import Offline from './Offline';

SplashScreen.preventAutoHideAsync().catch(() => {});

const VERSION = Constants.expoConfig?.version ?? '1.0.0';
const UA_SUFFIX = `MoabapApp/${VERSION} (${Platform.OS === 'ios' ? 'ios' : 'android'})`;
// 사이트의 공유(navigator.share)를 기기 공유 창으로
const BEFORE_LOAD = `(function(){try{navigator.share=function(d){d=d||{};window.ReactNativeWebView.postMessage(JSON.stringify({type:'share',title:d.title||'',text:d.text||'',url:d.url||location.href}));return Promise.resolve();};}catch(e){}})();true;`;

function Main() {
  const web = useRef<WebView>(null);
  const [start, setStart] = useState(SITE + '/?src=app');
  const [canBack, setCanBack] = useState(false);
  const [offline, setOffline] = useState(false);
  const backAt = useRef(0);
  const shown = useRef(false);

  // moabap://o/코드 또는 https://moabap.co.kr/… 로 앱이 열리면 그 화면으로
  const incoming = Linking.useLinkingURL();
  useEffect(() => {
    if (!incoming) return;
    const url = isOwn(incoming) ? incoming : incoming.startsWith('moabap://') ? SITE + '/' + incoming.slice('moabap://'.length) : '';
    if (url) { if (shown.current) web.current?.injectJavaScript(`location.href=${JSON.stringify(url)};true;`); else setStart(url); }
  }, [incoming]);

  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (canBack) { web.current?.goBack(); return true; }
      if (Date.now() - backAt.current < 2000) return false;
      backAt.current = Date.now();
      ToastAndroid.show('한 번 더 누르면 앱이 닫혀요', ToastAndroid.SHORT);
      return true;
    });
    return () => sub.remove();
  }, [canBack]);

  const onMessage = useCallback((e: WebViewMessageEvent) => {
    let m: { type?: string; title?: string; text?: string; url?: string };
    try { m = JSON.parse(e.nativeEvent.data); } catch { return; }
    if (m.type === 'share') {
      const url = m.url || '';
      const message = Platform.OS === 'ios' ? (m.text || m.title || '') : [m.title, m.text, url].filter(Boolean).join('\n');
      Share.share(Platform.OS === 'ios' ? { message, url } : { message, title: m.title }).catch(() => {});
    }
  }, []);

  const onNav = useCallback((nav: WebViewNavigation) => setCanBack(nav.canGoBack), []);

  const firstShown = useCallback(() => {
    if (shown.current) return;
    shown.current = true;
    SplashScreen.hideAsync().catch(() => {});
  }, []);

  return (
    <View style={s.root}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top']} style={s.top} />
      <View style={s.body}>
        <WebView
          ref={web}
          source={{ uri: start }}
          applicationNameForUserAgent={UA_SUFFIX}
          geolocationEnabled
          injectedJavaScriptBeforeContentLoaded={BEFORE_LOAD}
          onMessage={onMessage}
          onNavigationStateChange={onNav}
          onShouldStartLoadWithRequest={(req) => shouldLoadInside(req.url, req.isTopFrame ?? true)}
          onOpenWindow={(e) => openOutside(e.nativeEvent.targetUrl)}
          onLoadEnd={firstShown}
          onError={() => { setOffline(true); firstShown(); }}
          onContentProcessDidTerminate={() => web.current?.reload()}
          onRenderProcessGone={() => web.current?.reload()}
          sharedCookiesEnabled
          domStorageEnabled
          allowsBackForwardNavigationGestures
          pullToRefreshEnabled
          setSupportMultipleWindows={false}
          textZoom={100}
          style={s.web}
        />
        {offline && <Offline onRetry={() => { setOffline(false); web.current?.reload(); }} />}
      </View>
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
  root: { flex: 1, backgroundColor: '#F7F5FA' },
  top: { backgroundColor: '#F7F5FA' },
  body: { flex: 1 },
  web: { flex: 1, backgroundColor: '#F7F5FA' },
});
