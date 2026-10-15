/* 켜 둔 화면 알림: 새 요청이나 고객의 새 메시지가 오면 오른쪽 아래에 카드가 올라오고, 소리와 탭 숫자로 알린다.
   창을 내려 두었거나 다른 탭을 보고 있으면 윈도우·맥 알림(브라우저 알림)으로 띄운다. 누르면 그 요청이 열린다.
   탭을 여러 개 열어도 한 탭만 서버에 묻는다(localStorage로 순번). */
(function(){
  var root=document.currentScript&&document.currentScript.dataset.url;if(!root||!window.fetch)return;
  var me=Math.random().toString(36).slice(2),cur=null,unseen=0,baseTitle=document.title,box,audio;
  function ls(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v);}catch(e){return null;}}
  function lead(){var l=(ls('nt:lead')||'').split('|');if(l[0]===me||!l[1]||Date.now()-(+l[1])>45000){ls('nt:lead',me+'|'+Date.now());return true;}return false;}
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
  window.addEventListener('pagehide',function(){if((ls('nt:lead')||'').split('|')[0]===me)ls('nt:lead','');});  // 다른 화면으로 옮길 때 순번을 내려놓아 다음 화면이 바로 이어받게
  function show(items){
    items=items.filter(function(it){return it.url!==location.pathname;});  // 지금 보고 있는 요청은 화면에 바로 보이니 빼고
    if(!items.length)return;
    var away=document.hidden||!document.hasFocus();
    items.slice().reverse().forEach(function(it){card(it);if(away)osNote(it);});
    if(away){unseen+=items.length;badge();}
    ding();
  }
  function poll(){
    if(!lead())return later();
    var q=cur?('?c='+cur.c+'&e='+cur.e):'';
    fetch(root+q,{credentials:'same-origin',headers:{'Accept':'application/json'}}).then(function(r){return r.ok?r.json():null;}).then(function(d){
      if(!d)return;var first=!cur;cur={c:d.c,e:d.e};if(!first)show(d.items||[]);
    }).catch(function(){}).then(later);
  }
  function later(){setTimeout(poll,document.hidden?20000:10000);}
  // 처음 한 번: 브라우저 알림 허락 받기 (닫으면 다시 묻지 않는다)
  function ask(){
    if(!('Notification' in window)||Notification.permission!=='default'||ls('nt:asked'))return;
    var a=el('div','ntcard ntask');var tx=el('span','nttx');
    tx.appendChild(el('b',null,'새 요청이 오면 알려 드릴까요?'));tx.appendChild(el('span',null,'다른 창을 보고 있어도 오른쪽 아래에 알림이 떠요.'));
    var ok=el('button','btn sm','알림 켜기');ok.type='button';var no=el('button','ntx','×');no.type='button';no.setAttribute('aria-label','닫기');
    function close(){ls('nt:asked','1');a.classList.remove('on');setTimeout(function(){a.remove();},300);}
    ok.addEventListener('click',function(){try{Notification.requestPermission().then(close,close);}catch(e){close();}});
    no.addEventListener('click',close);
    a.appendChild(tx);a.appendChild(ok);a.appendChild(no);stack().appendChild(a);requestAnimationFrame(function(){a.classList.add('on');});
  }
  document.addEventListener('pointerdown',function u(){try{audio=audio||new (window.AudioContext||window.webkitAudioContext)();audio.resume();}catch(e){}document.removeEventListener('pointerdown',u);});
  setTimeout(ask,1500);poll();
})();
