// 웹과 같은 선 아이콘(48칸): 검은 선 + 주황 포인트
import Svg, { Circle, Path, Rect } from 'react-native-svg';
import { C } from '../lib/theme';

type Shape = { t: 'p'; d: string; a?: 1 | 2 } | { t: 'c'; cx: number; cy: number; r: number; a?: 1 | 2 } | { t: 'r'; x: number; y: number; w: number; h: number; rx: number; a?: 1 | 2 };
// a: 1 = 주황 선, 2 = 주황 채움
const ICONS: Record<string, Shape[]> = {
  truck: [{ t: 'p', d: 'M6 14h22v18H6zM28 20h8l6 6v6H28z' }, { t: 'c', cx: 14, cy: 34, r: 3.5, a: 2 }, { t: 'c', cx: 34, cy: 34, r: 3.5, a: 2 }],
  exchange: [{ t: 'p', d: 'M10 18h26l-6-6M38 30H12l6 6' }, { t: 'p', d: 'M36 18l-6 6M12 30l6-6', a: 1 }],
  refund: [{ t: 'r', x: 7, y: 12, w: 34, h: 24, rx: 5 }, { t: 'c', cx: 24, cy: 24, r: 5, a: 1 }],
  defect: [{ t: 'p', d: 'M18 8h12v6l4 6v18a3 3 0 0 1-3 3H17a3 3 0 0 1-3-3V20l4-6z' }, { t: 'p', d: 'M22 24l3 4-3 4 3 3', a: 1 }],
  chat: [{ t: 'p', d: 'M7 10h26v18H17l-7 6v-6H7z' }, { t: 'p', d: 'M33 18h8v16h-3v5l-6-5H20v-3', a: 1 }],
  note: [{ t: 'p', d: 'M12 7h18l7 7v27H12z' }, { t: 'p', d: 'M30 7v7h7' }, { t: 'p', d: 'M17 22h14M17 28h14M17 34h8', a: 1 }],
  search: [{ t: 'c', cx: 21, cy: 21, r: 12 }, { t: 'p', d: 'M30 30l10 10' }, { t: 'p', d: 'M15 21l4 4 7-7', a: 1 }],
  phone: [{ t: 'r', x: 14, y: 6, w: 20, h: 36, rx: 4 }, { t: 'p', d: 'M21 36h6', a: 1 }],
  building: [{ t: 'p', d: 'M10 40V10h18v30M28 18h10v22M6 40h36' }, { t: 'p', d: 'M15 16h3M15 22h3M15 28h3M22 16h1M22 22h1M22 28h1M32 24h2M32 30h2', a: 1 }],
  list: [{ t: 'r', x: 8, y: 8, w: 32, h: 32, rx: 6 }, { t: 'p', d: 'M16 17h16M16 24h16M16 31h10' }, { t: 'c', cx: 12.5, cy: 17, r: 1.6, a: 2 }],
  shield: [{ t: 'p', d: 'M24 6l15 6v10c0 9-6 16-15 20-9-4-15-11-15-20V12z' }, { t: 'p', d: 'M17 24l5 5 9-10', a: 1 }],
  reply: [{ t: 'p', d: 'M8 11h32v20H22l-8 7v-7H8z' }, { t: 'p', d: 'M15 19h18M15 25h11', a: 1 }],
};
export const CAT_ICON: Record<string, string> = { '배송 조회': 'truck', 교환: 'exchange', '반품·환불': 'refund', '제품 불량': 'defect', '고객 응대': 'chat', 기타: 'note' };

export function Icon({ name, size = 28 }: { name: string; size?: number }) {
  const shapes = ICONS[name] ?? ICONS.note;
  return (
    <Svg width={size} height={size} viewBox="0 0 48 48" fill="none" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
      {shapes.map((s, i) => {
        const stroke = s.a === 1 ? C.accent : C.fg;
        const fill = s.a === 2 ? C.accent : 'none';
        if (s.t === 'p') return <Path key={i} d={s.d} stroke={stroke} fill={fill} />;
        if (s.t === 'c') return <Circle key={i} cx={s.cx} cy={s.cy} r={s.r} stroke={stroke} fill={fill} />;
        return <Rect key={i} x={s.x} y={s.y} width={s.w} height={s.h} rx={s.rx} stroke={stroke} fill={fill} />;
      })}
    </Svg>
  );
}
