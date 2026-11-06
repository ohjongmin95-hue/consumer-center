// SODA 심벌: 네 방울(파랑·귤색·초록·보라, 은은한 그라데이션) + 가운데 흰 점. 웹 static/img/soda-mark.svg 와 같은 그림
import Svg, { Circle, Defs, G, LinearGradient, Stop } from 'react-native-svg';

const G4: [string, string, string, number, number, number, number][] = [
  ['d1', '#7FB8FF', '#2F6FF0', 0, 0, 1, 1],
  ['d2', '#FFD27A', '#F58A00', 1, 0, 0, 1],
  ['d3', '#0FB57A', '#7BE3B5', 0, 1, 1, 0],
  ['d4', '#7B5CF5', '#C3B5FF', 1, 1, 0, 0],
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
        {G4.map(([id, a, b, x1, y1, x2, y2]) => (
          <LinearGradient key={id} id={'soda' + id} x1={x1} y1={y1} x2={x2} y2={y2}>
            <Stop offset="0" stopColor={a} />
            <Stop offset="1" stopColor={b} />
          </LinearGradient>
        ))}
      </Defs>
      <G opacity={0.93}>
        {POS.map(([cx, cy], i) => (
          <Circle key={i} cx={cx} cy={cy} r={8.6} fill={`url(#soda${G4[i][0]})`} />
        ))}
      </G>
      <Circle cx={20} cy={20} r={4} fill="#fff" />
    </Svg>
  );
}
