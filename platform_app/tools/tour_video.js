// 제품 둘러보기 영상 만들기: tools/video_server.py를 먼저 띄운 뒤 실행 (개발용, 실제 서버에서 쓰지 않는다).
//   python tools/video_server.py &  node tools/tour_video.js
// 장면마다 Playwright recordVideo로 따로 찍고(화면 불러오는 부분은 잘라 냄), ffmpeg로 이어 붙여
// static/tour/tour.mp4·tour.webm(제품 둘러보기), hero.mp4·hero.webm(홈 첫 화면 반복 영상), 포스터 JPG를 만든다.
// 진짜 커서는 녹화되지 않으므로 둥근 커서·자막을 화면에 넣어 움직인다. 스마트스토어·쿠팡 글자는 화면에서 지운다.
const path=require('path'),fs=require('fs'),os=require('os'),http=require('http'),{execFileSync,spawn}=require('child_process');
const { chromium } = require(process.env.PLAYWRIGHT_PATH||'/opt/node-tools/node_modules/playwright');
// VIDEO_BASE를 주지 않으면 video_server.py를 직접 띄우고 끝나면 그 프로세스만 끈다 (승인을 실제로 누르므로 매번 새 DB로 찍는다).
const PORT=process.env.VIDEO_PORT||'8823',BASE=process.env.VIDEO_BASE||'http://127.0.0.1:'+PORT;
let server=null;
async function startServer(){
  if(process.env.VIDEO_BASE)return;
  server=spawn('python3',[path.join(__dirname,'video_server.py')],{env:{...process.env,VIDEO_PORT:PORT},stdio:'ignore'});
  for(let i=0;i<60;i++){const ok=await new Promise(r=>http.get(BASE+'/biz/login',res=>{res.resume();r(res.statusCode===200)}).on('error',()=>r(false)));if(ok)return;await new Promise(r=>setTimeout(r,500));}
  throw new Error('video_server.py가 뜨지 않았어요');
}
function stopServer(){if(server&&server.exitCode===null)server.kill('SIGTERM');}
const OUT=path.join(__dirname,'..','static','tour');
const TMP=fs.mkdtempSync(path.join(process.env.VIDEO_TMP||os.tmpdir(),'tourvid-'));
const FF='/usr/bin/ffmpeg',VP={width:1280,height:800},FPS=30,XF=0.45;
const CHAR='data:image/png;base64,'+fs.readFileSync(path.join(__dirname,'..','static','soboru-char.png')).toString('base64');

// ---------- 화면에 넣는 것: 자막·커서·글자 정리 ----------
const OVERLAY=`(()=>{
  const BAD=[[/스마트스토어\\s*·\\s*/g,''],[/\\s*·\\s*스마트스토어/g,''],[/쿠팡\\s*·\\s*/g,''],[/\\s*·\\s*쿠팡/g,''],[/(네이버\\s*)?스마트스토어|쿠팡/g,''],[/\\s*\\(?데모\\)?/g,'']];
  function scrub(root){const w=document.createTreeWalker(root||document.body,NodeFilter.SHOW_TEXT);let n;
    while((n=w.nextNode())){const t=n.nodeValue;if(!/스마트스토어|쿠팡|데모/.test(t))continue;let s=t;BAD.forEach(([re,r])=>s=s.replace(re,r));n.nodeValue=s}
    document.querySelectorAll('input[placeholder],textarea[placeholder]').forEach(e=>{if(/스마트스토어|쿠팡/.test(e.placeholder))e.placeholder=e.placeholder.replace(/스마트스토어·|쿠팡·|·스마트스토어|·쿠팡/g,'')});
    document.querySelectorAll('option').forEach(o=>{if(/스마트스토어|쿠팡/.test(o.textContent))o.remove()});}
  const css=\`.flashes,.nbar.demo,.cs-cta,.pilot,.ntcard,.toast{display:none!important}
  html{scroll-behavior:auto!important} *{caret-color:#ef920e}
  #vCap{position:fixed;left:50%;bottom:34px;transform:translate(-50%,14px);opacity:0;z-index:2147483646;pointer-events:none;
    background:#fff;color:#191f28;border-radius:22px;padding:17px 30px 17px 26px;display:flex;align-items:center;gap:12px;white-space:nowrap;
    font:700 23px/1.3 Pretendard,'Pretendard Variable',-apple-system,'Apple SD Gothic Neo',sans-serif;letter-spacing:-.02em;
    box-shadow:0 12px 40px rgba(17,24,39,.20),0 2px 8px rgba(17,24,39,.08);border:1px solid rgba(17,24,39,.06);
    transition:opacity .45s ease,transform .45s cubic-bezier(.2,.8,.2,1)}
  #vCap.on{opacity:1;transform:translate(-50%,0)}
  #vCap i{width:10px;height:10px;border-radius:50%;background:#ef920e;flex:none;box-shadow:0 0 0 5px rgba(239,146,14,.16)}
  #vCur{position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;z-index:2147483647;pointer-events:none;
    background:rgba(25,31,40,.82);border:3px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.28);transition:transform .12s ease,opacity .3s;opacity:0}
  #vCur.on{opacity:1} #vCur.dn{transform:scale(.78)}
  .vRip{position:fixed;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;border:3px solid #ef920e;z-index:2147483645;pointer-events:none;animation:vRip .6s ease-out forwards}
  @keyframes vRip{from{transform:scale(.6);opacity:.95}to{transform:scale(3.6);opacity:0}}
  .vHide{opacity:0!important}
  .vIn{animation:vIn .5s cubic-bezier(.2,.8,.2,1) both}
  @keyframes vIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
  .vOut{transition:opacity .45s ease,transform .45s ease;opacity:0!important;transform:translateY(-6px)}
  .vGlow{box-shadow:0 0 0 3px rgba(239,146,14,.55),0 8px 24px rgba(239,146,14,.18)!important;transition:box-shadow .4s ease}
  .vDots{display:inline-flex;align-items:center;gap:5px;padding:12px 16px;border-radius:18px;background:#e7efff;align-self:flex-end;color:#3b64c4;font:600 14px Pretendard,sans-serif}
  .vDots span{margin-left:6px}
  .vDots b{width:7px;height:7px;border-radius:50%;background:#6b8fd6;animation:vDot 1s infinite ease-in-out}
  .vDots b:nth-child(2){animation-delay:.15s}.vDots b:nth-child(3){animation-delay:.3s}
  @keyframes vDot{0%,80%,100%{opacity:.3;transform:translateY(0)}40%{opacity:1;transform:translateY(-3px)}}
  .vCard{position:absolute;inset:0;transition:all .55s cubic-bezier(.2,.8,.2,1)}\`;
  const ease=t=>t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2;
  function anim(ms,fn){return new Promise(r=>{const s=performance.now();(function f(n){const t=Math.min(1,(n-s)/ms);fn(ease(t));t<1?requestAnimationFrame(f):r()})(s)})}
  const V=window.__v={x:640,y:430,
    setup(){if(document.getElementById('vCur'))return;const st=document.createElement('style');st.textContent=css;document.head.appendChild(st);
      const c=document.createElement('div');c.id='vCur';document.body.appendChild(c);
      const p=document.createElement('div');p.id='vCap';p.innerHTML='<i></i><span></span>';document.body.appendChild(p);
      scrub();new MutationObserver(m=>m.forEach(x=>x.addedNodes.forEach(n=>{if(n.nodeType===1)scrub(n);else if(n.nodeType===3&&/스마트스토어|쿠팡|데모/.test(n.nodeValue))scrub(n.parentNode)}))).observe(document.body,{childList:true,subtree:true,characterData:false});
      document.querySelectorAll('.flashes').forEach(e=>e.remove());},
    cursor(x,y){V.x=x;V.y=y;const c=document.getElementById('vCur');c.style.transform='';c.style.left=x+'px';c.style.top=y+'px';c.classList.add('on')},
    hideCursor(){document.getElementById('vCur').classList.remove('on')},
    move(x,y,ms){const c=document.getElementById('vCur'),x0=V.x,y0=V.y;c.classList.add('on');ms=ms||Math.max(450,Math.min(1100,Math.hypot(x-x0,y-y0)*1.4));
      return anim(ms,t=>{V.x=x0+(x-x0)*t;V.y=y0+(y-y0)*t-Math.sin(t*Math.PI)*Math.min(40,Math.abs(x-x0)*.06);c.style.left=V.x+'px';c.style.top=V.y+'px'})},
    async click(){const c=document.getElementById('vCur');c.classList.add('dn');const r=document.createElement('div');r.className='vRip';r.style.left=V.x+'px';r.style.top=V.y+'px';document.body.appendChild(r);
      setTimeout(()=>r.remove(),700);await new Promise(r=>setTimeout(r,150));c.classList.remove('dn');},
    caption(t){const p=document.getElementById('vCap');if(p.classList.contains('on')&&p.dataset.t!==t){p.classList.remove('on');return new Promise(r=>setTimeout(()=>{V.caption(t).then(r)},420))}
      p.dataset.t=t;p.querySelector('span').textContent=t;p.classList.add('on');return new Promise(r=>setTimeout(r,450))},
    hideCaption(){document.getElementById('vCap').classList.remove('on')},
    scroll(y,ms,el){const s=el||document.scrollingElement,y0=s.scrollTop;y=Math.max(0,Math.min(y,s.scrollHeight-s.clientHeight));return anim(ms||900,t=>{s.scrollTop=y0+(y-y0)*t})},
    sleep(ms){return new Promise(r=>setTimeout(r,ms))},
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>V.setup());else V.setup();
})();`;

// ---------- 녹화 도우미 ----------
let browser,state;
async function login(){
  const ctx=await browser.newContext({viewport:VP});const p=await ctx.newPage();
  await p.goto(BASE+'/biz/login');await p.fill('input[name=login_id]','tour@example.com');await p.fill('input[name=password]','tourpassword1');
  await Promise.all([p.waitForNavigation(),p.click('form button.btn')]);
  state=await ctx.storageState();await ctx.close();
}
// 장면 하나: 새 녹화 창을 열고 url을 불러온 뒤 준비가 끝난 때부터 act가 끝날 때까지를 클립으로 남긴다.
async function scene(name,url,act,{prep}={}){
  const dir=path.join(TMP,name);fs.mkdirSync(dir,{recursive:true});
  const ctx=await browser.newContext({viewport:VP,deviceScaleFactor:1,storageState:state,recordVideo:{dir,size:VP}});
  await ctx.addInitScript(OVERLAY);
  const p=await ctx.newPage();const t0=Date.now();
  if(url.startsWith('html:'))await p.setContent(url.slice(5),{waitUntil:'load'});
  else{await p.goto(BASE+url);await p.waitForLoadState('networkidle');}
  await p.evaluate(()=>{window.__v.setup();document.querySelectorAll('.flashes').forEach(e=>e.remove())});
  await p.evaluate(()=>document.fonts&&document.fonts.ready);
  if(prep)await prep(p);
  await p.waitForTimeout(400);
  const start=(Date.now()-t0)/1000;
  await act(p);
  const bad=await p.evaluate(()=>(document.body.innerText.match(/.{0,20}(스마트스토어|쿠팡|데모).{0,20}/g)||[]).join(' / '));
  if(bad)console.warn('  WARNING 화면에 남은 글자:',bad);
  const end=(Date.now()-t0)/1000;
  const vid=p.video();await ctx.close();const raw=await vid.path();
  const clip=path.join(TMP,name+'.mp4');
  execFileSync(FF,['-y','-loglevel','error','-ss',start.toFixed(2),'-i',raw,'-t',(end-start).toFixed(2),'-vf',`fps=${FPS},format=yuv420p,setsar=1`,'-c:v','libx264','-crf','14','-preset','fast','-an',clip]);
  console.log('scene',name,(end-start).toFixed(1)+'s');
  return {clip,dur:end-start};
}
const v=(p,fn,...a)=>p.evaluate(fn,...a);
async function box(p,sel){const b=await p.locator(sel).first().boundingBox();if(!b)throw new Error('no element '+sel);return b}
async function moveTo(p,sel,{dx=.5,dy=.5,ms}={}){const b=await box(p,sel);await v(p,([x,y,ms])=>__v.move(x,y,ms),[b.x+b.width*dx,b.y+b.height*dy,ms]);return b}
const cap=(p,t)=>v(p,t=>__v.caption(t),t);
const wait=(p,ms)=>p.waitForTimeout(ms);

// 대화방의 AI 답을 감춰 두었다가 'AI 확인 중' → 답 순서로 보여 준다 (장면 3·홈 영상)
const HIDE_AI=()=>{const ai=document.querySelector('#cxMsgs .mg.ai');ai.classList.add('vHide');ai.style.display='none';
  const row=document.querySelector('.cx-row.on');if(row){row.dataset.txt=row.querySelector('.cx-r2').textContent;row.querySelector('.cx-r2').textContent='월요일에 주문한 리넨 셔츠 언제 받을 수 있을까요? 주문번호 20261020-0001…';
    const bd=row.querySelector('.bdg.ai');if(bd){bd.dataset.t=bd.textContent;bd.textContent='AI 확인 중'}}
  const st=[...document.querySelectorAll('.cx-mh span,.cx-card dd')];st.forEach(e=>{e.dataset.t=e.textContent;e.textContent=e.textContent.replace('답변·조치 완료 · AI 답함','AI 확인 중').replace('답변·조치 완료','AI 확인 중')})};
const SHOW_DOTS=()=>{const ai=document.querySelector('#cxMsgs .mg.ai');const d=document.createElement('div');d.className='vDots vIn';d.id='vDots';d.innerHTML='<b></b><b></b><b></b><span>AI가 카페24 주문을 찾고 있어요</span>';ai.before(d)};
const GLOW_ORDER=on=>{const c=[...document.querySelectorAll('.cx-card')].find(e=>e.querySelector('h2')&&e.querySelector('h2').textContent.trim()==='주문');if(c)c.classList.toggle('vGlow',on)};
const SHOW_AI=()=>{document.getElementById('vDots')?.remove();const ai=document.querySelector('#cxMsgs .mg.ai');ai.style.display='';ai.classList.remove('vHide');ai.classList.add('vIn');
  const row=document.querySelector('.cx-row.on');if(row&&row.dataset.txt){row.querySelector('.cx-r2').textContent=row.dataset.txt;const bd=row.querySelector('.bdg.ai');if(bd)bd.textContent=bd.dataset.t}
  document.querySelectorAll('[data-t]').forEach(e=>{if(e.matches('.cx-mh span,.cx-card dd'))e.textContent=e.dataset.t})};

const END_CARD=`<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#fff;font-family:Pretendard,-apple-system,'Apple SD Gothic Neo',sans-serif;color:#191f28;letter-spacing:-.02em}
.w{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0;text-align:center}
.w>*{opacity:0;animation:in .7s cubic-bezier(.2,.8,.2,1) forwards}
img{width:150px;height:auto;animation-delay:.05s!important}
.brand{font-size:30px;font-weight:800;color:#5a3416;margin-top:14px;animation-delay:.2s!important}
h1{font-size:50px;font-weight:800;margin:34px 0 0;line-height:1.25;animation-delay:.45s!important}
h1 em{font-style:normal;color:#ef920e}
.price{margin-top:32px;display:inline-flex;gap:12px;align-items:center;background:#fff6e8;color:#b8660a;border-radius:999px;padding:14px 28px;font-size:24px;font-weight:700;animation-delay:.75s!important}
.price i{width:6px;height:6px;border-radius:50%;background:#ef920e}
@keyframes in{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
</style></head><body><div class="w"><img src="${CHAR}" alt=""><div class="brand">소보루 CS</div>
<h1>쇼핑몰 문의, <em>AI가 먼저</em> 답해요</h1><div class="price">월 19,900원<i></i>5일 무료 체험</div></div></body></html>`;

(async()=>{
  fs.mkdirSync(OUT,{recursive:true});
  await startServer();
  browser=await chromium.launch({executablePath:process.env.CHROME||'/opt/pw-browsers/chromium'});
  await login();
  const only=process.env.ONLY?process.env.ONLY.split(','):null,want=k=>!only||only.includes(k);
  const clips=[];

  if(want('hero')){
  // 홈 첫 화면용 (둘러보기의 승인 장면이 DB를 바꾸기 전에 먼저 찍는다)
  // 홈 첫 화면용 반복 영상: 카페24 배송 문의에 AI가 답하는 모습 (자막·커서 없음). 끝에 처음 상태로 돌아가 이어진다.
  const h=await scene('hero','/biz/chat/7',async p=>{
    await v(p,()=>__v.hideCursor());await wait(p,1500);
    await v(p,SHOW_DOTS);await wait(p,1000);
    await v(p,GLOW_ORDER,true);await wait(p,1600);
    await v(p,SHOW_AI);await v(p,GLOW_ORDER,false);await wait(p,6500);
    // 처음 모습으로 되돌리기
    await v(p,()=>{const ai=document.querySelector('#cxMsgs .mg.ai');ai.classList.remove('vIn');ai.classList.add('vOut')});await wait(p,500);
    await v(p,()=>{const ai=document.querySelector('#cxMsgs .mg.ai');ai.classList.remove('vOut');window.__hideAgain()});await wait(p,1100);
  },{prep:p=>v(p,HIDE_AI).then(()=>p.evaluate(`window.__hideAgain=${HIDE_AI.toString()}`)).then(()=>v(p,()=>__v.scroll(0,1,document.getElementById('cxRows'))))});
  encode(h.clip,'hero',h.dur,true);
  execFileSync(FF,['-y','-loglevel','error','-ss','0.1','-i',h.clip,'-frames:v','1','-q:v','3',path.join(OUT,'hero-poster.jpg')]);
  console.log('hero',h.dur.toFixed(1)+'s');
  }
  if(want('tour')){
  // 1. 홈
  clips.push(await scene('s1_home','/biz/',async p=>{
    await v(p,()=>__v.cursor(900,560));
    await cap(p,'오늘 확인할 일만 먼저 보여요');await wait(p,500);
    await moveTo(p,'.sumrow > *:nth-child(2)',{dy:.6}).catch(()=>v(p,()=>__v.move(540,300)));await wait(p,700);
    await moveTo(p,'.sumrow > *:nth-child(3)',{dy:.6}).catch(()=>v(p,()=>__v.move(790,300)));await wait(p,500);
    await v(p,()=>__v.scroll(260,1200));
    await v(p,()=>__v.move(560,330,800));await wait(p,1300);
  }));
  // 2. 상담 모아 보기
  clips.push(await scene('s2_inbox','/biz/chat',async p=>{
    await v(p,()=>__v.cursor(820,420));
    await cap(p,'카페24 게시판·인스타 DM·메일 문의가 한곳에');
    const rows=await p.$$eval('.cx-row',rs=>rs.map(r=>{const b=r.querySelector('.chm').getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2,ch:r.querySelector('.chm').className}}));
    const pick=['c24','ig','mail'].map(k=>rows.find(r=>r.ch.includes(k))).filter(Boolean);
    for(const r of pick){await v(p,([x,y])=>__v.move(x+6,y+4,800),[r.x,r.y]);await wait(p,650);}
    await v(p,()=>__v.scroll(140,900,document.getElementById('cxRows')));await wait(p,300);
    await v(p,()=>__v.scroll(0,800,document.getElementById('cxRows')));
    await moveTo(p,'.cx-row >> nth=0',{dx:.45,dy:.35});await wait(p,250);await v(p,()=>__v.click());await wait(p,350);
  }));
  // 3. 카페24 배송 문의: AI가 주문을 찾아 답한다
  clips.push(await scene('s3_case','/biz/chat/7',async p=>{
    await v(p,()=>__v.scroll(0,1,document.getElementById('cxRows')));
    await wait(p,300);
    await cap(p,'배송 문의는 AI가 주문을 찾아 바로 답해요');
    await moveTo(p,'#cxMsgs .mg.me .mb',{dx:.7,dy:.6});await wait(p,300);
    await v(p,SHOW_DOTS);await wait(p,500);
    await v(p,()=>__v.move(1110,600,900));await v(p,GLOW_ORDER,true);await wait(p,900);
    await v(p,SHOW_AI);await v(p,GLOW_ORDER,false);await wait(p,300);
    await moveTo(p,'#cxMsgs .mg.ai .mb',{dx:.55,dy:.7});await wait(p,2000);
  },{prep:p=>v(p,HIDE_AI)}));
  // 4. 승인할 일: 반품·환불 승인
  clips.push(await scene('s4_approve','/biz/approvals',async p=>{
    await v(p,()=>__v.cursor(760,300));
    await cap(p,'환불·교환 결정만 사장님이 승인해요');
    const card=p.locator('.cgrid > *').first();
    await moveTo(p,'.cgrid > * >> nth=0',{dx:.5,dy:.38});await wait(p,900);
    const btn=card.locator('button',{hasText:'승인'}).first();const b=await btn.boundingBox();
    await v(p,([x,y])=>__v.move(x,y,800),[b.x+b.width/2,b.y+b.height/2]);await wait(p,250);
    await v(p,()=>__v.click());
    // 실제로 승인 (뒤에서 보내고 화면은 부드럽게 바꾼다)
    const res=await card.evaluate(async c=>{const f=[...c.querySelectorAll('form')].find(f=>[...f.querySelectorAll('button')].some(b=>b.textContent.trim()==='승인'));
      const bt=[...f.querySelectorAll('button')].find(b=>b.textContent.trim()==='승인');const fd=new FormData(f);if(bt.name)fd.append(bt.name,bt.value);
      const r=await fetch(f.action||location.href,{method:'POST',body:fd,credentials:'same-origin'});return r.status});
    console.log('  approve status',res);
    await card.evaluate(c=>{c.style.transition='opacity .45s ease, transform .45s ease';c.style.opacity='0';c.style.transform='scale(.96)'});await wait(p,480);
    await card.evaluate(c=>{const w=c.offsetWidth;c.style.transition='all .5s cubic-bezier(.2,.8,.2,1)';c.style.width=w+'px';c.style.minWidth='0';c.style.overflow='hidden';requestAnimationFrame(()=>{c.style.width='0px';c.style.padding='0';c.style.margin='0';c.style.marginRight='-24px'})});
    await v(p,()=>{const em=document.querySelector('.phead h1 em');if(em)em.textContent='2건';document.querySelectorAll('.cnt').forEach(e=>{if(e.textContent.trim()==='3')e.textContent='2'})});
    await wait(p,600);await card.evaluate(c=>c.remove());
    await v(p,()=>__v.move(700,420,900));await wait(p,1400);
  }));
  // 5. 고객 상담창: AI 상담
  clips.push(await scene('s5_widget','/to/1',async p=>{
    await v(p,()=>__v.cursor(640,520));
    await cap(p,'쇼핑몰 상담창에서도 AI가 먼저 안내해요');
    const y=await p.$eval('.cs-chat',e=>e.getBoundingClientRect().top+scrollY-110);
    await v(p,y=>__v.scroll(y,1300),y);await wait(p,250);
    await moveTo(p,'#cbText',{dx:.35});await v(p,()=>__v.click());await p.focus('#cbText');await wait(p,200);
    await v(p,()=>__v.move(__v.x+120,__v.y+70,500));
    await p.keyboard.type('배송은 언제 와요?',{delay:95});await wait(p,350);
    await p.keyboard.press('Enter');await wait(p,600);
    // 답이 보이게 상담창 아래쪽까지 천천히 내린다
    await p.waitForFunction(()=>document.querySelectorAll('#cbLog .cb-m.bot').length>=2&&!document.querySelector('#cbLog .dots'),null,{timeout:8000});
    const y2=await p.$eval('.cs-chat',e=>e.getBoundingClientRect().bottom+scrollY-innerHeight+130);
    await v(p,y=>{if(y>scrollY)return __v.scroll(y,700)},y2);
    await moveTo(p,'#cbLog .cb-m.bot >> nth=-1',{dx:.6,dy:.7,ms:900});await wait(p,2300);
  }));
  // 6. 자동 처리·AI 설정
  clips.push(await scene('s6_rules','/biz/rules',async p=>{
    await v(p,()=>__v.cursor(700,460));
    await cap(p,'어떤 문의를 맡길지 사장님이 정해요');
    // 스위치는 화면에서만 켠다 (눌러도 저장하지 않음)
    await v(p,()=>document.querySelectorAll('[role=switch]').forEach(s=>s.addEventListener('click',e=>{e.preventDefault();s.classList.toggle('on');s.setAttribute('aria-checked',s.classList.contains('on'))},true)));
    await moveTo(p,'[role=switch] >> nth=0');await wait(p,200);await v(p,()=>__v.click());await p.locator('[role=switch]').first().click();await wait(p,600);
    await moveTo(p,'select[name=ai_ok] >> nth=0',{dx:.4});await wait(p,700);
    const y=await p.$eval('#ai',e=>e.getBoundingClientRect().top+scrollY-110);
    await v(p,y=>__v.scroll(y,1500),y);
    {const b=await p.getByText('켜짐',{exact:true}).first().boundingBox().catch(()=>null);if(b)await v(p,([x,y])=>__v.move(x,y,900),[b.x+b.width+18,b.y+b.height*.8]);}await wait(p,1800);
  }));
  // 7. 끝 화면
  clips.push(await scene('s7_end','html:'+END_CARD,async p=>{await wait(p,3600)}));

  // 이어 붙이기 (짧은 크로스페이드)
  const inputs=[],fc=[];let off=0,last='[0:v]';
  clips.forEach(c=>inputs.push('-i',c.clip));
  for(let i=1;i<clips.length;i++){off+=clips[i-1].dur-XF;const o=i===clips.length-1?'[vout]':`[x${i}]`;fc.push(`${last}[${i}:v]xfade=transition=fade:duration=${XF}:offset=${off.toFixed(3)}${o}`);last=o;}
  const total=clips.reduce((a,c)=>a+c.dur,0)-XF*(clips.length-1);
  fs.writeFileSync(path.join(TMP,'fc.txt'),fc.join(';'));
  const master=path.join(TMP,'tour_master.mp4');
  execFileSync(FF,['-y','-loglevel','error',...inputs,'-filter_complex_script',path.join(TMP,'fc.txt'),'-map','[vout]','-c:v','libx264','-crf','12','-preset','fast','-pix_fmt','yuv420p',master]);
  encode(master,'tour',total);
  execFileSync(FF,['-y','-loglevel','error','-ss',(0.9).toFixed(2),'-i',master,'-frames:v','1','-q:v','3',path.join(OUT,'tour-poster.jpg')]);
  console.log('tour',total.toFixed(1)+'s');
  }

  await browser.close();stopServer();
})().catch(e=>{console.error(e);stopServer();process.exit(1)});

function encode(src,name,dur,hero){
  const mp4=path.join(OUT,name+'.mp4'),webm=path.join(OUT,name+'.webm');
  // 크기 목표: 둘러보기 < 6MB, 홈 영상 < 2.5MB. 화면 글자가 많아 CRF로 맞추고 최대 비트레이트로 막는다.
  const max=hero?'1400k':'1100k';
  execFileSync(FF,['-y','-loglevel','error','-i',src,'-an','-c:v','libx264','-preset','slow','-crf',hero?'21':'22','-maxrate',max,'-bufsize','2400k','-pix_fmt','yuv420p','-profile:v','high','-tune','stillimage','-movflags','+faststart',mp4]);
  execFileSync(FF,['-y','-loglevel','error','-i',src,'-an','-c:v','libvpx-vp9','-b:v',max,'-crf',hero?'31':'33','-row-mt','1','-deadline','good','-cpu-used','2','-pix_fmt','yuv420p',webm]);
  for(const f of [mp4,webm])console.log('  ',path.basename(f),(fs.statSync(f).size/1048576).toFixed(2)+'MB');
}
