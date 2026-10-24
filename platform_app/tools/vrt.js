// 레이아웃 검증 + 시각적 회귀 시험 (소보루 CS).
// tools/tour_server.py를 먼저 띄운 뒤 실행해요.
//   node tools/vrt.js --base     지금 화면을 기준 그림으로 저장 (고치기 전에 한 번)
//   node tools/vrt.js            기준 그림과 비교하고 레이아웃 규칙을 검사
// 결과: $VRT_DIR(기본 /tmp/soboru-vrt)/report.json, 바뀐 화면은 diff/*.png (바뀐 곳 빨간색)
// 견본 서버는 띄울 때마다 견본 요청의 시각이 바뀌어서, 요청 목록의 날짜 칸은 늘 조금 달라져요. diff 그림으로 확인하세요.
// 레이아웃 규칙: 가로 넘침 없음, 본문 글이 왼쪽 메뉴(.bside)·머리글 밑에 가려지지 않음, 화면 밖으로 나간 제목 없음.
const fs=require('fs'),path=require('path');
const { chromium } = require(process.env.PLAYWRIGHT_PATH||'playwright');
const H=process.env.VRT_HOST||'http://127.0.0.1:8811';
const DIR=process.env.VRT_DIR||'/tmp/soboru-vrt';
const BASE_MODE=process.argv.includes('--base');
const ONLY=(process.argv.find(a=>a.startsWith('--only='))||'').slice(7);
const PUBLIC=['/biz/','/biz/tour','/biz/for','/biz/for/smartstore','/biz/industries','/biz/industries/fashion','/biz/contact',
  '/biz/blog','/biz/customers','/biz/help','/biz/help/start','/biz/partners','/biz/security','/biz/terms','/privacy','/biz/signup','/biz/login','/biz/partner/login','/biz/forgot'];
// 로그인한 기업 회원도 하단 메뉴로 공개 페이지를 열어요 (왼쪽 메뉴가 붙은 상태)
const ROLES={
  guest:PUBLIC,
  co:['/biz/','/biz/all','/biz/approvals','/biz/new','/biz/news','/biz/orders','/biz/pending','/biz/returns','/biz/rules','/biz/macros','/biz/automations','/biz/settings','/biz/start',
      '/biz/stats','/biz/stats/ai','/biz/team','/biz/connect','/biz/connect/widget','/biz/connect/email','/biz/connect/instagram','/biz/connect/cafe24','C24ORDER','/biz/import','/biz/report','/biz/guide','CASE',
      '/biz/tour','/biz/blog','/biz/customers','/biz/help','/biz/partners','/biz/security','/biz/terms','/biz/industries','/biz/contact'],
  ops:['/biz/ops','/biz/ops/all','/biz/ops/companies','/biz/ops/content','/biz/ops/copy','/biz/ops/keys','/biz/ops/leads','/biz/ops/marketing','/biz/ops/partners'],
};
const WIDTHS=[1920,1440,1280,1024,768,390];
const TOLERANCE=+(process.env.VRT_TOLERANCE||0.3); // 바뀐 픽셀이 이 % 넘으면 '바뀜'

async function login(p,role){
  if(role==='ops'){await p.goto(H+'/biz/ops/login');await p.fill('input[name=password]',process.env.TOUR_OPS_PW||'opsshotpw1');await Promise.all([p.waitForNavigation(),p.click('form button.btn')]);}
  if(role==='co'){await p.goto(H+'/biz/login');await p.fill('input[name=login_id]','tour@example.com');await p.fill('input[name=password]','tourpassword1');await Promise.all([p.waitForNavigation(),p.click('form button.btn')]);}
}
function layoutCheck(){
  const vw=innerWidth,bad=[];
  if(document.documentElement.scrollWidth>vw+1)bad.push('가로 넘침 '+(document.documentElement.scrollWidth-vw)+'px');
  const vis=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};
  const side=[...document.querySelectorAll('.bside')].find(vis);
  const sr=side&&side.getBoundingClientRect();
  const main=document.querySelector('main');
  if(main){
    const els=[...main.querySelectorAll('h1,h2,h3,p,a,button,input,select,textarea,label,li,td,th')].filter(vis).filter(e=>!e.closest('.bside,.gnb,[aria-hidden=true]'));
    let hidden=0,off=0,ex='';
    for(const e of els){const r=e.getBoundingClientRect();
      if(sr&&r.left<sr.right-1&&r.right>sr.left){hidden++;ex=ex||e.tagName+' "'+e.textContent.trim().slice(0,20)+'"';}
      if(r.right<=0||r.left>=vw){off++;}
    }
    if(hidden)bad.push('왼쪽 메뉴에 가려진 요소 '+hidden+'개 (예: '+ex+')');
    const h1=[...main.querySelectorAll('h1')].find(vis);
    if(h1){const r=h1.getBoundingClientRect();if(r.left<0||r.right>vw+1)bad.push('제목이 화면 밖');}
  }
  return bad;
}
async function diff(page,a,b,out){
  // 브라우저 캔버스로 두 그림의 픽셀을 비교 (따로 깔 프로그램 없이)
  const res=await page.evaluate(async([a,b])=>{
    const load=src=>new Promise((ok,no)=>{const i=new Image();i.onload=()=>ok(i);i.onerror=no;i.src=src});
    const [A,B]=await Promise.all([load(a),load(b)]);
    const w=Math.max(A.width,B.width),h=Math.max(A.height,B.height);
    const get=I=>{const c=document.createElement('canvas');c.width=w;c.height=h;const x=c.getContext('2d');x.fillStyle='#fff';x.fillRect(0,0,w,h);x.drawImage(I,0,0);return x.getImageData(0,0,w,h)};
    const da=get(A),db=get(B);const c=document.createElement('canvas');c.width=w;c.height=h;const x=c.getContext('2d');const o=x.createImageData(w,h);let n=0;
    for(let i=0;i<da.data.length;i+=4){const d=Math.abs(da.data[i]-db.data[i])+Math.abs(da.data[i+1]-db.data[i+1])+Math.abs(da.data[i+2]-db.data[i+2]);
      if(d>40){n++;o.data[i]=255;o.data[i+1]=0;o.data[i+2]=0;o.data[i+3]=255;}else{const g=(db.data[i]+db.data[i+1]+db.data[i+2])/3;o.data[i]=o.data[i+1]=o.data[i+2]=g*.35+165;o.data[i+3]=255;}}
    x.putImageData(o,0,0);
    return {pct:100*n/(w*h),sizeChanged:A.width!==B.width||A.height!==B.height,png:n?c.toDataURL('image/png'):''};
  },[a,b]);
  if(res.png)fs.writeFileSync(out,Buffer.from(res.png.split(',')[1],'base64'));
  return res;
}
(async()=>{
  const sub=BASE_MODE?'base':'now';
  for(const d of [sub,'diff'])fs.mkdirSync(path.join(DIR,d),{recursive:true});
  const b=await chromium.launch(process.env.CHROME?{executablePath:process.env.CHROME}:{});
  const report=[];
  for(const role of Object.keys(ROLES)){
    if(ONLY&&!ONLY.split(',').includes(role))continue;
    const ctx=await b.newContext({viewport:{width:1440,height:900}});const p=await ctx.newPage();
    await login(p,role);
    let paths=ROLES[role];
    if(paths.includes('C24ORDER')){await p.goto(H+'/biz/orders');const ls=await p.evaluate(()=>[...new Set([...document.querySelectorAll('a[href*="/biz/order/"]')].map(a=>a.getAttribute('href').replace(/^.*?(\/biz\/order\/\d+)/,'$1')))].slice(0,40));
      let hit=null;for(const l of ls){await p.goto(H+l);if(await p.evaluate(()=>!!document.querySelector('#c24'))){hit=l;break;}}
      paths=paths.map(x=>x==='C24ORDER'?hit:x).filter(Boolean);}
    if(paths.includes('CASE')){await p.goto(H+'/biz/all');const c=await p.evaluate(()=>{const a=document.querySelector('a[href*="/biz/case/"]');return a&&a.getAttribute('href').replace(/^.*?(\/biz\/case\/\d+)/,'$1')});paths=paths.map(x=>x==='CASE'?c:x).filter(Boolean);}
    for(const u of paths)for(const w of WIDTHS){
      await p.setViewportSize({width:w,height:900});
      const r=await p.goto(H+u);await p.waitForLoadState('networkidle').catch(()=>{});
      // 스크롤하면 나타나는 부분을 모두 띄우고 맨 위로 (기준 그림과 같은 상태로 찍기)
      await p.evaluate(async()=>{for(let y=0;y<document.body.scrollHeight;y+=600){scrollTo(0,y);await new Promise(r=>setTimeout(r,30));}scrollTo(0,0);});
      // 시각·애니메이션처럼 매번 달라지는 것은 멈춤
      await p.addStyleTag({content:'*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}'});
      const name=`${role}${u.replace(/[^a-z0-9]+/gi,'_')}_${w}.png`;
      const file=path.join(DIR,sub,name);
      await p.screenshot({path:file,fullPage:true});
      const row={role,path:u,width:w,status:r.status(),layout:await p.evaluate(layoutCheck)};
      if(!BASE_MODE){const base=path.join(DIR,'base',name);
        if(fs.existsSync(base)){const d=await diff(p,'data:image/png;base64,'+fs.readFileSync(base).toString('base64'),'data:image/png;base64,'+fs.readFileSync(file).toString('base64'),path.join(DIR,'diff',name));
          row.diff=+d.pct.toFixed(2);row.sizeChanged=d.sizeChanged;}
        else row.diff=null;}
      report.push(row);
    }
    await ctx.close();
  }
  await b.close();
  fs.writeFileSync(path.join(DIR,BASE_MODE?'base.json':'report.json'),JSON.stringify(report,null,1));
  const broken=report.filter(r=>r.layout.length||r.status>=500);
  const changed=report.filter(r=>r.diff>TOLERANCE||r.sizeChanged);
  console.log(`화면 ${report.length}개 · 레이아웃 문제 ${broken.length}개`+(BASE_MODE?' · 기준 그림 저장':` · 기준과 달라진 화면 ${changed.length}개 (${TOLERANCE}% 초과)`));
  for(const r of broken)console.log('  [레이아웃]',r.role,r.path,r.width,r.status,r.layout.join(', '));
  for(const r of changed)console.log('  [바뀜]',r.role,r.path,r.width,r.diff+'%',r.sizeChanged?'(높이 바뀜)':'');
  process.exitCode=broken.length?1:0;
})();
