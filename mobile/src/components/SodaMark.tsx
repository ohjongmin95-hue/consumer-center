// SODA 심벌: 네 방울(파랑·귤색·초록·보라). 방울마다 안쪽이 밝게 빛나는 둥근 그라데이션 + 가운데 부드러운 흰 빛. 웹 static/soda-mark.svg 와 같은 그림
import Svg, { Circle, Defs, G, RadialGradient, Stop } from 'react-native-svg';

const B: [string, number, number, string, string, string][] = [
  ['d1', 0.35, 0.3, '#BFDDFF', '#5C9BFF', '#2459E0'],
  ['d2', 0.65, 0.3, '#FFF0C2', '#FFB94A', '#F07C00'],
  ['d3', 0.35, 0.7, '#C8F5DF', '#3FD394', '#0A9A5E'],
  ['d4', 0.65, 0.7, '#E6DEFF', '#9A82FF', '#6440E8'],
];
const POS = [
  [13.5, 13.5],
  [26.5, 13.5],
  [13.5, 26.5],
  [26.5, 26.5],
];

export function SodaMark({ size = 24 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 40 40">
      <Defs>
        {B.map(([id, cx, cy, a, m, z]) => (
          <RadialGradient key={id} id={'soda' + id} cx={cx} cy={cy} r={0.8}>
            <Stop offset="0" stopColor={a} />
            <Stop offset="0.45" stopColor={m} />
            <Stop offset="1" stopColor={z} />
          </RadialGradient>
        ))}
        <RadialGradient id="sodadc" cx={0.5} cy={0.5} r={0.5}>
          <Stop offset="0" stopColor="#fff" />
          <Stop offset="0.6" stopColor="#fff" />
          <Stop offset="1" stopColor="#fff" stopOpacity={0} />
        </RadialGradient>
      </Defs>
      <G opacity={0.9}>
        {POS.map(([cx, cy], i) => (
          <Circle key={i} cx={cx} cy={cy} r={8.8} fill={`url(#soda${B[i][0]})`} />
        ))}
      </G>
      <Circle cx={20} cy={20} r={6} fill="url(#sodadc)" />
    </Svg>
  );
}
