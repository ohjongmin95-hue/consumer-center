// 소보루 CS 색과 간격. 웹(platform_app/static/hanq.css)과 같은 값을 쓴다.
export const C = {
  accent: '#F89B00',
  brand: '#652D1C', // 소보루 CS 로고 글자 (로고 이미지의 갈색)
  accentPress: '#E88F00',
  accentSoft: '#FFF4E0',
  accentInk: '#B36B00',
  fg: '#191F28',
  fg2: '#4E5968',
  fg3: '#8B95A1',
  fg4: '#B0B8C1',
  line: '#E5E8EB',
  fill: '#F2F4F6',
  band: '#F2F4F6', // 토스처럼 바탕은 연회색, 그 위에 흰 카드
  card: '#FFFFFF',
  green: '#12A26A',
  greenSoft: '#E5F6EE',
  red: '#F04452',
  redSoft: '#FDECEE',
};

export const R = { sm: 12, md: 16, lg: 24, xl: 28 };

export const STATUS_TONE: Record<string, { bg: string; fg: string }> = {
  received: { bg: C.fill, fg: C.fg2 },
  forwarded: { bg: C.accentSoft, fg: C.accentInk },
  seen: { bg: C.accentSoft, fg: C.accentInk },
  info: { bg: C.accentSoft, fg: C.accentInk },
  answered: { bg: C.greenSoft, fg: C.green },
  resolved: { bg: C.greenSoft, fg: C.green },
  closed: { bg: C.greenSoft, fg: C.green },
  unresolved: { bg: C.redSoft, fg: C.red },
  withdrawn: { bg: C.fill, fg: C.fg3 },
};

// 글꼴: 프리텐다드 (assets/fonts, SIL OFL). 굵기는 fontWeight로 고른다 (안드로이드는 expo-font 설정으로 한 가족으로 묶음)
export const FONT = 'Pretendard';
