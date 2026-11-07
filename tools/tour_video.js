// 소개 영상 다시 찍기: node tools/tour_video.js <주소> <biz_session 쿠키 파일> [저장 폴더]
// 데모 데이터가 켜진 로그인 화면을 1280x800으로 녹화하고, ffmpeg로 static/tour/{tour,hero}.{mp4,webm} 와 포스터를 만든다.
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');const {execFileSync}=require('child_process');
const [,,BASE='http://127.0.0.1:8795',CK,OUT=path.join(__dirname,'../platform_app/static/tour')]=process.argv;
const ROOT=path.join(__dirname,'..');const TMP=fs.mkdtempSync('/tmp/tourvid-');
const F=ROOT+'/mobile/assets/fonts/Pretendard-';let font='';
for(const [n,w] of Object.entries({Regular:400,Medium:500,SemiBold:600,Bold:700})){try{font+=`@font-face{font-family:Pretendard;font-weight:${w};src:url(data:font/otf;base64,${fs.readFileSync(F+n+'.otf').toString('base64')})}`}catch(e){}}
const LOGO='data:image/png;base64,'+fs.readFileSync(ROOT+'/platform_app/static/cx-logo.png').toString('base64');
const W=1280,H=800;

// 화면 위에 얹는 것: 커서 점, 아래 자막, 데모 표시 지우기
function overlay(css){
  const add=()=>{if(document.getElementById('tv-cur'))return;
    const s=document.createElement('style');s.textContent=css+`*{font-family:Pretendard,sans-serif!important}html{scroll-behavior:smooth}
      #tv-cur{position:fixed;z-index:99999;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:rgba(25,31,40,.55);border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.25);pointer-events:none;transition:transform .15s;left:640px;top:400px}
      #tv-cur.dn{transform:scale(.7)}
      #tv-cap{position:fixed;z-index:99998;left:50%;bottom:36px;transform:translate(-50%,12px);opacity:0;transition:all .35s;background:#fff;color:#191F28;border-radius:999px;padding:14px 26px;font-size:20px;font-weight:700;box-shadow:0 8px 28px rgba(0,0,0,.14);white-space:nowrap;display:flex;align-items:center;gap:10px}
      #tv-cap.on{opacity:1;transform:translate(-50%,0)}#tv-cap i{width:9px;height:9px;border-radius:50%;background:#EF920E;display:block}`;
    document.head.appendChild(s);
    const c=document.createElement('div');c.id='tv-cur';document.body.appendChild(c);
    const p=document.createElement('div');p.id='tv-cap';p.innerHTML='<i></i><span></span>';document.body.appendChild(p);
    addEventListener('mousemove',e=>{c.style.left=e.clientX+'px';c.style.top=e.clientY+'px'});
    addEventListener('mousedown',()=>c.classList.add('dn'));addEventListener('mouseup',()=>c.classList.remove('dn'));
    document.querySelectorAll('*').forEach(e=>{if(e.children.length===0&&e.textContent.includes('데모 화면')){let x=e;while(x.parentElement&&!x.parentElement.matches('main,body,.pg'))x=x.parentElement;x.style.display='none'}});
    document.querySelectorAll('.mg').forEach(m=>{if(m.textContent.includes('데모 고객이 접수했어요'))m.style.display='none'});
    const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;
    while(n=w.nextNode()){n.nodeValue=n.nodeValue.replace(' (데모)','').replace(/^데모$/,'카카오톡').replace('데모 · ','카카오톡 · ')}};
  // 데모 표시를 지우기 전 화면이 녹화되지 않게, 다 지운 뒤에 보여 준다
  const hide=document.createElement('style');hide.textContent='html{visibility:hidden}';
  if(document.documentElement)document.documentElement.appendChild(hide);
  else new MutationObserver((_,o)=>{if(document.documentElement){document.documentElement.appendChild(hide);o.disconnect()}}).observe(document,{childList:true});
  const done=()=>{add();hide.remove()};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',done);else done();
}

async function rec(name,fn){
  const b=await chromium.launch();const ctx=await b.newContext({viewport:{width:W,height:H},recordVideo:{dir:TMP,size:{width:W,height:H}}});
  if(CK)await ctx.addCookies([{name:'biz_session',value:fs.readFileSync(CK,'utf8').trim(),url:BASE}]);
  await ctx.addInitScript(overlay,font);
  const p=await ctx.newPage();
  // 데모 데이터 켜기
  await p.goto(BASE+'/chat');
  if(!(await p.content()).includes('데모 화면')){const t=await p.evaluate(()=>{const i=document.querySelector('input[name=csrf]');return i&&i.value});
    await p.evaluate(t=>fetch('/demo',{method:'POST',body:new URLSearchParams({csrf:t,act:'on'}),credentials:'same-origin'}),t)}
  const t0=Date.now();await fn(p);const dur=(Date.now()-t0)/1000;
  const v=p.video();await ctx.close();await b.close();
  const raw=await v.path();return {raw,dur};
}
const wait=(p,ms)=>p.waitForTimeout(ms);
async function cap(p,txt){await p.evaluate(t=>{const c=document.getElementById('tv-cap');if(!c)return;c.classList.remove('on');setTimeout(()=>{c.querySelector('span').textContent=t;c.classList.add('on')},t?150:0)},txt)}
async function go(p,u){await p.goto(BASE+u);await p.waitForLoadState('networkidle').catch(()=>{});await wait(p,300)}
async function moveTo(p,sel,{click=false,steps=25}={}){const el=typeof sel==='string'?await p.$(sel):sel;if(!el)return false;const bx=await el.boundingBox();if(!bx)return false;
  await p.mouse.move(bx.x+bx.width/2,bx.y+Math.min(bx.height/2,30),{steps});await wait(p,250);if(click){await el.click().catch(()=>{})}return true}
async function scroll(p,y){await p.evaluate(y=>scrollTo({top:y,behavior:'smooth'}),y);await wait(p,900)}

async function chatScene(p,hero){
  await go(p,'/chat');await p.mouse.move(400,300);
  if(!hero){await cap(p,'카카오톡·네이버 톡톡·쇼핑몰 상담창 문의가 한곳에');await wait(p,2600)}
  await openRow(p,'김하늘');
  // 배송 문의에 SODA가 주문을 보고 답하는 장면 (실제 기능과 같은 말풍선 모양)
  await p.evaluate(()=>{const last=[...document.querySelectorAll('.mg')].pop();if(!last)return;const box={appendChild:n=>last.after(n)};
    const d=document.createElement('div');d.className='mg ai';d.style.cssText='opacity:0;transform:translateY(8px);transition:all .45s';
    d.innerHTML='<div class="mb"><span class="mby"><img class="mbm" src="/static/soda-mark.svg" alt="" width="16" height="16">SODA</span><div class="mr"><div class="mt">주문하신 리넨 셔츠(아이보리, M)는 지금 출고 준비 중이에요. 내일 CJ대한통운으로 출발하면 송장 번호를 바로 알려 드릴게요.</div><time>지금</time></div></div>';
    box.appendChild(d);setTimeout(()=>{d.style.opacity=1;d.style.transform='none';d.scrollIntoView({block:'end',behavior:'smooth'})},700)});
  await cap(p,'배송 문의는 SODA가 주문을 찾아 먼저 답해요');await wait(p,1400);
  await moveTo(p,'.cx-side, aside',{steps:30});await wait(p,hero?2200:2000);
  await openRow(p,'이도윤');
  await cap(p,'교환·환불은 SODA가 정리하고, 사장님은 승인만');await wait(p,900);
  await moveTo(p,'#cxDec button[value=approve], #cxDec .btn',{steps:30});await wait(p,hero?2600:2200);
}
async function openRow(p,name){
  const rows=await p.$$('.cx-row');let el=rows[0];for(const r of rows){if((await r.textContent()).includes(name)){el=r;break}}
  await moveTo(p,el,{click:true});await p.waitForLoadState('networkidle').catch(()=>{});await wait(p,700);
}
async function endCard(p){
  await p.setContent(`<style>${font}body{margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:26px;background:linear-gradient(160deg,#FFF4E9,#FFFFFF 55%,#EFEBFF);font-family:Pretendard,sans-serif;color:#191F28}
    img{height:54px}h1{font-size:46px;font-weight:700;margin:0;letter-spacing:-1px}h1 b{color:#EF920E}p{margin:0;font-size:22px;font-weight:600;color:#4E5968;background:#fff;border-radius:999px;padding:12px 26px;box-shadow:0 6px 20px rgba(0,0,0,.06)}
    .a{opacity:0;transform:translateY(14px);animation:u .6s forwards}.a:nth-child(2){animation-delay:.25s}.a:nth-child(3){animation-delay:.5s}@keyframes u{to{opacity:1;transform:none}}</style>
    <img class="a" src="${LOGO}" alt=""><h1 class="a">쇼핑몰 문의, <b>SODA</b>가 먼저 답해요</h1><p class="a">무료로 시작 · 스타터 월 9,900원</p>`);
  await wait(p,3200);
}

async function tour(p){
  await go(p,'/');await p.mouse.move(640,420,{steps:10});
  await cap(p,'오늘 확인할 일이 먼저 보여요');await wait(p,2400);await scroll(p,420);await wait(p,1400);
  await chatScene(p,false);
  await go(p,'/approvals');await p.mouse.move(500,300);
  await cap(p,'승인할 일은 한곳에 모여요');await wait(p,1200);
  await moveTo(p,'button.btn, .btn-primary, button[type=submit]',{steps:30});await wait(p,2400);
  await go(p,'/soda');await p.mouse.move(600,300);
  await cap(p,'우리 가게 정보를 SODA에게 가르쳐요');await wait(p,2200);await scroll(p,380);await wait(p,1600);
  await cap(p,'');await wait(p,300);await endCard(p);
}

function enc(raw,name,skip,dur){
  const mp4=path.join(OUT,name+'.mp4'),webm=path.join(OUT,name+'.webm'),poster=path.join(OUT,name+'-poster.jpg');
  const cut=['-ss',String(skip),'-t',String(dur)];
  execFileSync('ffmpeg',['-v','error','-y',...cut,'-i',raw,'-an','-c:v','libx264','-pix_fmt','yuv420p','-crf','26','-preset','slow','-movflags','+faststart',mp4]);
  execFileSync('ffmpeg',['-v','error','-y',...cut,'-i',raw,'-an','-c:v','libvpx-vp9','-b:v','0','-crf','40','-row-mt','1',webm]);
  execFileSync('ffmpeg',['-v','error','-y','-ss',String(Math.min(3,dur/3)),'-i',mp4,'-frames:v','1','-q:v','4',poster]);
  console.log(name,dur.toFixed(1)+'s',fs.statSync(mp4).size,fs.statSync(webm).size);
}

(async()=>{
  for(const [name,fn] of [['tour',tour],['hero',p=>chatScene(p,true)]]){
    const t=Date.now();const {raw,dur}=await rec(name,fn);
    // 앞부분(데모 켜기·첫 로딩)은 잘라낸다
    const total=parseFloat(execFileSync('ffprobe',['-v','error','-show_entries','format=duration','-of','csv=p=0',raw]).toString());
    enc(raw,name,Math.max(0,total-dur),dur);
  }
})();
