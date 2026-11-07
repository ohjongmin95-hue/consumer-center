// SODA 심벌: 네 방울(민트·하늘). 방울마다 두 색이 부드럽게 섞이고, 겹치는 곳은 조금 진해지며 가운데는 흰 빛. 웹 static/soda-mark.svg 와 같은 그림
import Svg, { Circle, Defs, G, LinearGradient, RadialGradient, Stop } from 'react-native-svg';

// [id, x1, y1, x2, y2, 시작 색, 끝 색] — 방울마다 가운데 쪽으로 번지는 방향
const B: [string, number, number, number, number, string, string][] = [
  ['d1', 0, 0, 1, 1, '#8EE8C6', '#7FD0F0'],
  ['d2', 1, 0, 0, 1, '#9FD8FF', '#8FB8FF'],
  ['d3', 0, 1, 1, 0, '#B6F0D4', '#7FDDC0'],
  ['d4', 1, 1, 0, 0, '#86CFFF', '#9DE6E0'],
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
        {B.map(([id, x1, y1, x2, y2, a, z]) => (
          <LinearGradient key={id} id={'soda' + id} x1={x1} y1={y1} x2={x2} y2={y2}>
            <Stop offset="0" stopColor={a} />
            <Stop offset="1" stopColor={z} />
          </LinearGradient>
        ))}
        <RadialGradient id="sodadc" cx={0.5} cy={0.5} r={0.5}>
          <Stop offset="0" stopColor="#fff" />
          <Stop offset="0.6" stopColor="#fff" />
          <Stop offset="1" stopColor="#fff" stopOpacity={0} />
        </RadialGradient>
      </Defs>
      <G opacity={0.85}>
        {POS.map(([cx, cy], i) => (
          <Circle key={i} cx={cx} cy={cy} r={8.8} fill={`url(#soda${B[i][0]})`} />
        ))}
      </G>
      <Circle cx={20} cy={20} r={5.5} fill="url(#sodadc)" />
    </Svg>
  );
}
