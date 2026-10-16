/* 켜 둔 화면 알림: 새 요청이나 고객의 새 메시지가 오면 오른쪽 아래에 카드가 올라오고, 소리와 탭 숫자로 알린다.
   창을 내려 두었거나 다른 탭을 보고 있으면 윈도우·맥 알림(브라우저 알림)으로 띄운다. 누르면 그 요청이 열린다.
   탭마다 따로 묻는다. 카드는 보이는 탭에만, 윈도우 알림은 같은 tag라 탭이 여러 개여도 하나만 뜬다. */
(function(){
  var root=document.currentScript&&document.currentScript.dataset.url;if(!root||!window.fetch)return;
  var cur=null,unseen=0,baseTitle=document.title,box,audio;
  function ls(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v);}catch(e){return null;}}
  function el(t,c,txt){var e=document.createElement(t);if(c)e.className=c;if(txt)e.textContent=txt;return e;}
  function stack(){if(!box){box=el('div','ntbox');box.setAttribute('aria-live','polite');document.body.appendChild(box);}return box;}
  function ding(){try{audio=audio||new (window.AudioContext||window.webkitAudioContext)();var t=audio.currentTime;
    [[880,0],[1320,.12]].forEach(function(p){var o=audio.createOscillator(),g=audio.createGain();o.type='sine';o.frequency.value=p[0];
      g.gain.setValueAtTime(0,t+p[1]);g.gain.linearRampToValueAtTime(.18,t+p[1]+.02);g.gain.exponentialRampToValueAtTime(.001,t+p[1]+.35);
      o.connect(g);g.connect(audio.destination);o.start(t+p[1]);o.stop(t+p[1]+.4);});}catch(e){}}
  function card(it){
    var a=el('a','ntcard');a.href=it.url;
    var ic=el('span','ntic'+(it.kind==='new'?' new':''),it.kind==='new'?'N':'…');
    var tx=el('span','nttx');tx.appendChild(el('b',null,it.title));tx.appendChild(el('span',null,it.text||''));
    var x=el('button','ntx','×');x.type='button';x.setAttribute('aria-label','닫기');
    x.addEventListener('click',function(e){e.preventDefault();gone();});
    a.appendChild(ic);a.appendChild(tx);a.appendChild(x);
    var b=stack();b.appendChild(a);while(b.children.length>3)b.removeChild(b.firstChild);
    requestAnimationFrame(function(){a.classList.add('on');});
    var tm=setTimeout(gone,9000);a.addEventListener('mouseenter',function(){clearTimeout(tm);});a.addEventListener('mouseleave',function(){tm=setTimeout(gone,4000);});
    function gone(){a.classList.remove('on');setTimeout(function(){a.remove();},300);}
  }
  function osNote(it){
    if(!('Notification' in window)||Notification.permission!=='granted')return;
    try{var n=new Notification(it.title,{body:it.text||'',tag:'soboru-'+it.kind+'-'+it.case,icon:'/static/soboru-favicon.png'});
      n.onclick=function(){window.focus();location.href=it.url;n.close();};}catch(e){}
  }
  function badge(){document.title=(unseen?'('+unseen+') ':'')+baseTitle;}
  window.addEventListener('focus',function(){unseen=0;badge();});
  function show(items){
    items=items.filter(function(it){return it.url!==location.pathname;});  // 지금 보고 있는 요청은 화면에 바로 보이니 빼고
    if(!items.length)return;
    var seen=document.visibilityState==='visible',focus=document.hasFocus();
    if(seen){items.slice().reverse().forEach(card);ding();}
    if(!focus){items.forEach(osNote);unseen+=items.length;badge();}  // 다른 프로그램이나 다른 탭을 보고 있을 때
  }
  function poll(){
    var q=cur?('?c='+cur.c+'&e='+cur.e):'';
    fetch(root+q,{credentials:'same-origin',headers:{'Accept':'application/json'}}).then(function(r){return r.ok?r.json():null;}).then(function(d){
      if(!d)return;var first=!cur;cur={c:d.c,e:d.e};if(!first)show(d.items||[]);
    }).catch(function(){}).then(later);
  }
  function later(){setTimeout(poll,document.hidden?20000:10000);}
  // 처음 한 번: 브라우저 알림 허락 받기 (닫으면 다시 묻지 않는다)
  function ask(){
    if(!('Notification' in window)||Notification.permission!=='default'||Date.now()-(+ls('nt:asked')||0)<86400000)return;  // 닫았으면 하루 뒤에 다시 묻는다
    var a=el('div','ntcard ntask');var tx=el('span','nttx');
    tx.appendChild(el('b',null,'새 요청이 오면 알려 드릴까요?'));tx.appendChild(el('span',null,'다른 창을 보고 있어도 오른쪽 아래에 알림이 떠요.'));
    var ok=el('button','btn sm','알림 켜기');ok.type='button';var no=el('button','ntx','×');no.type='button';no.setAttribute('aria-label','닫기');
    function close(){ls('nt:asked',String(Date.now()));a.classList.remove('on');setTimeout(function(){a.remove();},300);}
    ok.addEventListener('click',function(){try{Notification.requestPermission().then(function(p){close();done(p);},close);}catch(e){close();}});
    no.addEventListener('click',close);
    a.appendChild(tx);a.appendChild(ok);a.appendChild(no);stack().appendChild(a);requestAnimationFrame(function(){a.classList.add('on');});
  }
  function done(p){  // 켰으면 시험 알림을 하나 띄워 바로 확인하게
    if(p==='granted'){osNote({kind:'test',case:0,title:'알림이 켜졌어요',text:'새 요청이 오면 이렇게 알려 드려요.',url:location.pathname});card({kind:'new',title:'알림이 켜졌어요',text:'다른 창을 보고 있어도 화면 오른쪽 아래에 떠요.',url:location.pathname});ding();}
    else if(p==='denied')card({kind:'msg',title:'알림이 막혀 있어요',text:'주소창 왼쪽 자물쇠 → 알림 → 허용으로 바꿔 주세요.',url:location.pathname});
  }
  document.addEventListener('pointerdown',function u(){try{audio=audio||new (window.AudioContext||window.webkitAudioContext)();audio.resume();}catch(e){}document.removeEventListener('pointerdown',u);});
  setTimeout(ask,1500);poll();
})();
