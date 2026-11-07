// 브리핑 제목 앞 그림 (OH 11/07): 토스페이스 그대로가 아닌 소보루 것. 크림 종이 + 갈색 판 + 귤색 집게, 이모지처럼 평평하게.
import Svg, { Circle, Path, Rect } from 'react-native-svg';

export function BriefMark({ size = 24 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 32 32">
      <Rect x="5" y="4" width="22" height="26" rx="5" fill="#9A5A3C" />
      <Rect x="8" y="7.5" width="16" height="20" rx="3" fill="#FFF4E2" />
      <Rect x="11.5" y="2.5" width="9" height="6" rx="2.6" fill="#EF920E" />
      <Circle cx="16" cy="5.3" r="1.2" fill="#FFF4E2" />
      <Rect x="11" y="13" width="10" height="2.2" rx="1.1" fill="#E3B98F" />
      <Rect x="11" y="17.5" width="7.5" height="2.2" rx="1.1" fill="#E3B98F" />
      <Path d="M20.5 21.2l1.1 2.2 2.4.35-1.75 1.7.42 2.4-2.17-1.14-2.17 1.14.42-2.4-1.75-1.7 2.4-.35z" fill="#EF920E" />
    </Svg>
  );
}
