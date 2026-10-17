// 소보루 공유 미리보기(og) 그림 만들기: node tools/make_og.js  → static/soboru-og*.png (1200x630)
// 뉴닉처럼 귤색 바탕 가운데에 흰 SOBORU 글자 로고만. 카카오톡 등이 가장자리를 잘라도 로고는 남음. 모든 화면이 같은 그림
const { chromium } = require(process.env.PW || '/opt/node22/lib/node_modules/playwright');
const fs = require('fs'), path = require('path'), root = path.resolve(__dirname, '..');
const logo = 'data:image/png;base64,' + fs.readFileSync(path.join(root, 'static/img/soboru-wordmark.png')).toString('base64');
const NAMES = ['soboru-og', 'soboru-og-report', 'soboru-og-pick', 'soboru-og-life', 'soboru-og-ask'];
const html = `<!doctype html><style>*{margin:0}body{width:1200px;height:630px;background:#ef7300;display:flex;align-items:center;justify-content:center}
img{width:520px;height:auto;filter:brightness(0) invert(1)}</style><img src="${logo}">`;
(async () => {
  const b = await chromium.launch(), pg = await b.newPage({ viewport: { width: 1200, height: 630 } });
  await pg.setContent(html, { waitUntil: 'load' });
  for (const name of NAMES) await pg.screenshot({ path: path.join(process.env.OUT || path.join(root, 'static'), name + '.png') });
  await b.close();
})();
