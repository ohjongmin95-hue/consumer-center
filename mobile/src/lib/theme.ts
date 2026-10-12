// 소보루 CS 색과 간격. 웹(platform_app/static/hanq.css)과 같은 값을 쓴다.
export const C = {
  accent: '#F89B00',
  accentPress: '#E88F00',
  accentSoft: '#FFF4E0',
  accentInk: '#B36B00',
  fg: '#191F28',
  fg2: '#4E5968',
  fg3: '#8B95A1',
  fg4: '#B0B8C1',
  line: '#E5E8EB',
  fill: '#F2F4F6',
  band: '#F6F7F9',
  card: '#FFFFFF',
  green: '#12A26A',
  greenSoft: '#E5F6EE',
  red: '#F04452',
  redSoft: '#FDECEE',
};

export const R = { sm: 12, md: 16, lg: 20, xl: 26 };

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
