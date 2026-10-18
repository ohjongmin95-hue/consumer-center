// 상담이 들어온 곳 아이콘 (웹 platform_app/static/ch/*.svg와 같은 그림): 카페24 · 인스타그램 · 메일 · 네이버 · 쿠팡 · 상담창
import Svg, { Circle, Defs, LinearGradient, Path, Rect, Stop, Text as SvgText } from 'react-native-svg';

const BG: Record<string, string> = { c24: '#2F6BFF', mail: '#5F6B7A', nv: '#03C75A', cp: '#E52528', web: '#F89B00' };

export function ChannelIcon({ mark, size = 22 }: { mark: string; size?: number }) {
  const w = { stroke: '#fff', fill: 'none', strokeWidth: 1.8 };
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {mark === 'ig' ? (
        <Defs>
          <LinearGradient id="g" x1="0" y1="1" x2="1" y2="0">
            <Stop offset="0" stopColor="#F9A825" />
            <Stop offset="0.5" stopColor="#E91E63" />
            <Stop offset="1" stopColor="#8E24AA" />
          </LinearGradient>
        </Defs>
      ) : null}
      <Circle cx="12" cy="12" r="12" fill={mark === 'ig' ? 'url(#g)' : (BG[mark] ?? BG.web)} />
      {mark === 'ig' ? (
        <>
          <Rect x="6" y="6" width="12" height="12" rx="3.6" {...w} />
          <Circle cx="12" cy="12" r="2.9" {...w} />
          <Circle cx="15.4" cy="8.6" r="1" fill="#fff" />
        </>
      ) : mark === 'c24' ? (
        <SvgText x="12" y="15.6" textAnchor="middle" fontFamily="Arial" fontSize="10" fontWeight="700" fill="#fff">
          24
        </SvgText>
      ) : mark === 'mail' ? (
        <>
          <Rect x="6" y="7.5" width="12" height="9" rx="1.6" {...w} strokeWidth={1.7} />
          <Path d="M6.6 8.4l5.4 4.1 5.4-4.1" {...w} strokeWidth={1.7} strokeLinejoin="round" />
        </>
      ) : mark === 'nv' ? (
        <Path d="M8 7h3.1l2.3 3.6V7H16v10h-3.1l-2.3-3.6V17H8z" fill="#fff" />
      ) : mark === 'cp' ? (
        <>
          <Path d="M7.5 9.5h9l-.8 8h-7.4z" fill="#fff" />
          <Path d="M9.8 9.5V8.6a2.2 2.2 0 0 1 4.4 0v.9" {...w} strokeWidth={1.6} />
        </>
      ) : (
        <Path d="M6.5 9A2.5 2.5 0 0 1 9 6.5h6A2.5 2.5 0 0 1 17.5 9v3.6a2.5 2.5 0 0 1-2.5 2.5h-3.4l-3.3 2.6v-2.6A2.5 2.5 0 0 1 6.5 12.6z" fill="#fff" />
      )}
    </Svg>
  );
}
