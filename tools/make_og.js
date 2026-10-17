// 소보루 공유 미리보기(og) 그림 만들기: node tools/make_og.js  → static/soboru-og*.png (1200x630)
// 귤색 바탕 + 흰 글자 로고 + 캐릭터 한 번. 이모지는 토스페이스(static/fonts/tossface-soboru.woff2)
const { chromium } = require(process.env.PW || '/opt/node22/lib/node_modules/playwright');
const fs = require('fs'), path = require('path'), root = path.resolve(__dirname, '..');
const u = p => `data:${p.endsWith('.png') ? 'image/png' : 'font/woff2'};base64,` + fs.readFileSync(path.join(root, p)).toString('base64');
const PAGES = [
  ['soboru-og', '', '<em>소</em>비자 권익 <em>보</em>호를<br>위한 <em>루</em>트', '제보 · 리뷰 · 생활정보, 소비자끼리 한곳에서'],
  ['soboru-og-report', '📣', '억울한 일 겪었다면<br><em>소보루에 제보</em>하세요', '기업에 전달하고 답변까지 챙겨 드려요'],
  ['soboru-og-pick', '⭐', '써 본 소비자가 고른<br><em>제품·업체 리뷰와 추천</em>', '광고 없이 소비자끼리 나누는 소보루 픽'],
  ['soboru-og-life', '💡', '알아 두면 돈 버는<br><em>소비 이야기</em>', '환불 · 해지 · 리콜, 쉽게 풀어 드려요'],
  ['soboru-og-ask', '💬', '소비자 권리,<br><em>AI 소비자 상담</em>', '법령 원문을 근거로 대응 방법을 안내해요'],
];
const html = (ic, h, s) => `<!doctype html><meta charset="utf-8"><style>
@font-face{font-family:TF;src:url(${u('static/fonts/tossface-soboru.woff2')})}
*{margin:0;box-sizing:border-box}body{width:1200px;height:630px;overflow:hidden;background:#ef7300;font-family:Pretendard,sans-serif;color:#fff;position:relative}
.ring{position:absolute;right:30px;top:50%;width:470px;height:470px;margin-top:-235px;border-radius:50%;background:#fff3e6}
.ch{position:absolute;right:62px;top:50%;width:400px;transform:translateY(-44%)}
.box{position:absolute;left:92px;top:0;bottom:0;width:620px;display:flex;flex-direction:column;justify-content:center}
.logo{height:46px;width:auto;filter:brightness(0) invert(1);margin-bottom:${ic ? 40 : 58}px;align-self:flex-start}
.ic{width:84px;height:84px;border-radius:22px;background:#fff;display:flex;align-items:center;justify-content:center;font:46px TF;margin-bottom:30px}
h1{font-weight:700;font-size:${ic ? 62 : 70}px;line-height:1.25;letter-spacing:-2px}h1 em{font-style:normal;color:#ffe2b8}
p{margin-top:26px;font-size:28px;font-weight:500;color:#fff;opacity:.88;letter-spacing:-.5px}
</style><div class="ring"></div><img class="ch" src="${u('static/img/soboru-character-hero.png')}">
<div class="box"><img class="logo" src="${u('static/img/soboru-wordmark.png')}">${ic ? `<div class="ic">${ic}</div>` : ''}<h1>${h}</h1><p>${s}</p></div>`;
(async () => {
  const b = await chromium.launch(), pg = await b.newPage({ viewport: { width: 1200, height: 630 } });
  for (const [name, ic, h, s] of PAGES) {
    await pg.setContent(html(ic, h, s), { waitUntil: 'load' }); await pg.evaluate(() => document.fonts.ready);
    await pg.screenshot({ path: path.join(process.env.OUT || path.join(root, 'static'), name + '.png') });
  }
  await b.close();
})();
