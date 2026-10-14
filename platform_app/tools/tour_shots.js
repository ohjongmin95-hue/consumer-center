// 제품 둘러보기 그림 찍기: tools/tour_server.py를 먼저 띄운 뒤 실행. static/tour/*.jpg 와 tour.json을 만든다.
// 각 단계: 화면을 열고, 짚을 요소를 화면 안으로 스크롤한 뒤 보이는 화면만 찍고, 그 요소 가운데 위치(%)를 기록한다.
const path=require('path'),fs=require('fs');
const { chromium } = require(process.env.PLAYWRIGHT_PATH||'playwright');
const BASE='http://127.0.0.1:8811',OUT=path.join(__dirname,'..','static','tour');
const STEPS=[ // [키, 주소(데모 기준), 짚을 요소]
  ['home','/biz/','.brief'],
  ['inbox','/biz/all','table.tbl2 tbody tr'],
  ['case','@case','#mkDraft'],
  ['rules','/biz/rules','[role=switch]'],
  ['chat','@to','.cs-chat'],
  ['returns','/biz/returns','table.tbl2 tbody tr, .panel'],
  ['assign','@case','select[name=assignee]'],
  ['stats','/biz/stats','.kpis, .sumrow'],
];
(async()=>{
  fs.mkdirSync(OUT,{recursive:true});
  const b=await chromium.launch(process.env.CHROME?{executablePath:process.env.CHROME}:{});
  const out={};
  for(const [tag,vp] of [['d',{width:1280,height:800}],['m',{width:390,height:780}]]){
    const ctx=await b.newContext({viewport:vp,deviceScaleFactor:tag==='m'?2:1});const p=await ctx.newPage();
    await p.goto(BASE+'/biz/login');await p.fill('input[name=login_id]','tour@example.com');await p.fill('input[name=password]','tourpassword1');
    await Promise.all([p.waitForNavigation(),p.click('form button.btn')]);
    const realHome=BASE+'/to/'+(await p.evaluate(()=>{const m=(document.body.innerHTML.match(/\/to\/(\d+)/)||[])[1];return m;}));
    await p.goto(BASE+'/biz/all');
    const caseUrl=BASE+await p.evaluate(()=>{const a=[...document.querySelectorAll('table.tbl2 a.ttl')].find(x=>x.textContent.includes('사이즈'));return a.getAttribute('href').replace(/^.*?(\/biz\/case\/\d+)/,'$1');});
    for(const [key,url,sel] of STEPS){
      const u=url==='@case'?caseUrl:url==='@to'?realHome:BASE+url;
      await p.goto(u);await p.waitForLoadState('networkidle');
      await p.evaluate(()=>{document.querySelectorAll('.flashes').forEach(e=>e.remove());});
      const el=await p.$(sel);let spot=null;
      if(el){await el.evaluate(e=>{const r=e.getBoundingClientRect();if(r.bottom>innerHeight-20)e.scrollIntoView({block:'center'});});const r=await el.boundingBox();
        if(r){const x=Math.min(r.x+Math.min(r.width/2,140),vp.width-24),y=r.y+Math.min(r.height/2,40);spot={x:+(x/vp.width*100).toFixed(1),y:+(Math.max(4,Math.min(96,y/vp.height*100))).toFixed(1)};}}
      const file=`${key}-${tag}.jpg`;await p.screenshot({path:path.join(OUT,file),type:'jpeg',quality:80});
      out[key]=out[key]||{};Object.assign(out[key],tag==='d'?{d:file,w:vp.width,h:vp.height,spot}:{m:file,mspot:spot});
    }
    await ctx.close();
  }
  await b.close();
  fs.writeFileSync(path.join(OUT,'tour.json'),JSON.stringify(out,null,1));
  console.log('saved',Object.keys(out).length,'steps');
})();
