// 레이아웃 검증 + 시각적 회귀 시험 (소비자제보센터).
// tools/site_vrt_server.py를 먼저 띄운 뒤 실행해요.
//   node tools/site_vrt.js --base     지금 화면을 기준 그림으로 저장 (고치기 전 코드로 한 번)
//   node tools/site_vrt.js            기준 그림과 비교하고 레이아웃 규칙을 검사
// 결과: $VRT_DIR(기본 /tmp/site-vrt)/report.json, 바뀐 화면은 diff/*.png (바뀐 곳 빨간색)
// 레이아웃 규칙: 가로 넘침 없음, 본문이 왼쪽 메뉴(.ad-side) 밑에 가려지지 않음, 화면 밖으로 나간 제목·버튼 없음, 버튼끼리 겹치지 않음.
const fs=require('fs'),path=require('path');
const { chromium } = require(process.env.PLAYWRIGHT_PATH||'playwright');
const H=process.env.VRT_HOST||'http://127.0.0.1:8822';
const DIR=process.env.VRT_DIR||'/tmp/site-vrt';
const BASE_MODE=process.argv.includes('--base');
const ONLY=(process.argv.find(a=>a.startsWith('--only='))||'').slice(7);
const ROLES={
  guest:['/','/reports','/reports/1','/reports/2','/reports/4','/companies','/companies/1','/lookup','/report','/terms','/biz/login','/biz/signup'],
  reporter:['/case'],
  admin:['/admin','/admin/reports','/admin/reports/1','/admin/reports/4','/admin/reports/5','/admin/companies'],
  biz:['/biz','/biz/case/4','/biz/statement'],
};
const WIDTHS=(process.env.VRT_WIDTHS||'1440,1024,768,390').split(',').map(Number);
const TOLERANCE=+(process.env.VRT_TOLERANCE||0.3);
async function submit(p){await Promise.all([p.waitForNavigation(),p.click('main form button[type=submit]')]);}
async function login(p,role){
  if(role==='admin'){await p.goto(H+'/admin/login');await p.fill('input[name=password]','adminshotpw1');await submit(p);}
  if(role==='reporter'){await p.goto(H+'/lookup');await p.fill('input[name=phone]','010-2222-3333');await p.fill('input[name=password]','1234');await submit(p);
    if(!p.url().endsWith('/case')){await Promise.all([p.waitForNavigation(),p.click('.lookup-list button')]);}}
  if(role==='biz'){await p.goto(H+'/biz/login');await p.fill('input[name=login_id]','sobo_cs');await p.fill('input[name=password]','bizshotpw1');await submit(p);}
}
function layoutCheck(){
  const vw=innerWidth,bad=[];
  if(document.documentElement.scrollWidth>vw+1)bad.push('가로 넘침 '+(document.documentElement.scrollWidth-vw)+'px');
  const vis=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.closest('details:not([open]) > :not(summary)')};
  const side=[...document.querySelectorAll('.ad-side')].find(vis);const sr=side&&side.getBoundingClientRect();
  const main=document.querySelector('main');
  if(main){
    const els=[...main.querySelectorAll('h1,h2,h3,p,a,button,input,select,textarea,label,li,td,th')].filter(vis).filter(e=>!e.closest('[aria-hidden=true],.cs-table-wrap'));
    let hidden=0,off=0,ex='',offEx='';
    for(const e of els){const r=e.getBoundingClientRect();
      if(sr&&r.left<sr.right-1&&r.right>sr.left&&r.bottom>sr.top&&r.top<sr.bottom){hidden++;ex=ex||e.tagName+' "'+e.textContent.trim().slice(0,20)+'"';}
      if(r.right>vw+1||r.left<-1){off++;offEx=offEx||e.tagName+' "'+e.textContent.trim().slice(0,20)+'"';}
    }
    if(hidden)bad.push('왼쪽 메뉴에 가려진 요소 '+hidden+'개 (예: '+ex+')');
    if(off)bad.push('화면 밖으로 나간 요소 '+off+'개 (예: '+offEx+')');
    const btns=[...main.querySelectorAll('button,.cs-btn,a.primary,a.secondary')].filter(vis).map(e=>[e,e.getBoundingClientRect()]);
    let overlap='';
    for(let i=0;i<btns.length&&!overlap;i++)for(let j=i+1;j<btns.length;j++){const [ea,a]=btns[i],[eb,b]=btns[j];
      if(ea.contains(eb)||eb.contains(ea))continue;
      const x=Math.min(a.right,b.right)-Math.max(a.left,b.left),y=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top);
      if(x>2&&y>2){overlap='"'+ea.textContent.trim().slice(0,12)+'" / "'+eb.textContent.trim().slice(0,12)+'"';break;}}
    if(overlap)bad.push('겹친 버튼 '+overlap);
  }
  return bad;
}
async function diff(page,a,b,out){
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
    for(const u of ROLES[role])for(const w of WIDTHS){
      await p.setViewportSize({width:w,height:900});
      const r=await p.goto(H+u);await p.waitForLoadState('networkidle').catch(()=>{});
      await p.evaluate(async()=>{for(let y=0;y<document.body.scrollHeight;y+=600){scrollTo(0,y);await new Promise(r=>setTimeout(r,30));}scrollTo(0,0);});
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
