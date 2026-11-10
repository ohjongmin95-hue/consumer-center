// 기본 프로필 (OH 11/07: 이름 첫 글자 동그라미 대신). 고객은 프로필을 등록하지 않으니
// 토스·채널톡 기본 프로필처럼 연한 색 동그라미 + 흰 사람 모양. 색은 id로 골라 사람마다 조금씩 달라요.
// kind="shop" 은 가게(사장님) 기본 모양: 차양이 있는 작은 가게.
import Svg, { Circle, Defs, LinearGradient, Path, Rect, Stop } from 'react-native-svg';

const TONES: [string, string][] = [
  ['#9FD8FF', '#7FB8F5'],
  ['#8EE8C6', '#62CFA8'],
  ['#FFD08C', '#FFAE5C'],
  ['#C3B8FF', '#9F90F5'],
  ['#FFB7C4', '#F58FA3'],
];

export function Avatar({ id = 0, size = 40, kind = 'person' }: { id?: number; size?: number; kind?: 'person' | 'shop' }) {
  const [a, b] = kind === 'shop' ? (['#FFD08C', '#F7A33B'] as [string, string]) : TONES[Math.abs(id) % TONES.length];
  const gid = `av${kind}${Math.abs(id) % TONES.length}`;
  return (
    <Svg width={size} height={size} viewBox="0 0 40 40">
      <Defs>
        <LinearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
          <Stop offset="0" stopColor={a} />
          <Stop offset="1" stopColor={b} />
        </LinearGradient>
      </Defs>
      <Circle cx={20} cy={20} r={20} fill={`url(#${gid})`} />
      {kind === 'shop' ? (
        <>
          <Rect x={12} y={18} width={16} height={11} rx={2} fill="#fff" />
          <Path d="M10.5 13.5 12.5 10h15l2 3.5v1.2a3.2 3.2 0 0 1-6.4 0 3.2 3.2 0 0 1-6.2 0 3.2 3.2 0 0 1-6.4 0z" fill="#fff" />
          <Rect x={17.5} y={22} width={5} height={7} rx={1} fill={b} opacity={0.55} />
        </>
      ) : (
        <>
          <Circle cx={20} cy={16} r={6} fill="#fff" />
          <Path d="M9.5 33c1.4-5.4 5.6-8.5 10.5-8.5S29.1 27.6 30.5 33a20 20 0 0 1-21 0z" fill="#fff" />
        </>
      )}
    </Svg>
  );
}
