/* 실시간 채팅: 몇 초마다 새 말을 가져오고, 보낸 말은 바로 붙인다. 고객 화면과 사장님 화면이 같이 쓴다.
   #chat[data-url][data-csrf][data-after][data-me] 안에 #lMsgs, #lForm, #lText, #lOn, #lErr */
(function(){
  var box=document.getElementById('chat');if(!box)return;
  var url=box.dataset.url,csrf=box.dataset.csrf,after=+box.dataset.after||0,mine=box.dataset.me||'me';
  var list=document.getElementById('lMsgs'),form=document.getElementById('lForm'),text=document.getElementById('lText'),on=document.getElementById('lOn'),err=document.getElementById('lErr');
  var seen={},busy=false,closed=false;
  function bottom(){list.scrollTop=list.scrollHeight;}
  function add(m){if(seen[m.id])return;seen[m.id]=1;after=Math.max(after,m.id);
    var d=document.createElement('div');d.className='lm '+(m.who===mine?'me':'co');var p=document.createElement('p');p.textContent=m.text;var s=document.createElement('small');s.textContent=m.at;d.appendChild(p);d.appendChild(s);list.appendChild(d);}
  function show(j){(j.msgs||[]).forEach(add);if(j.msgs&&j.msgs.length)bottom();
    var o=mine==='me'?j.co_online:j.me_online;if(on)on.hidden=!o;
    if(j.open===false&&!closed){closed=true;form.hidden=true;err.hidden=false;err.textContent='대화가 끝났어요.';}}
  function poll(){if(busy||document.hidden)return;busy=true;
    fetch(url+'?after='+after,{credentials:'same-origin',headers:{'Accept':'application/json'}}).then(function(r){return r.json();}).then(show).catch(function(){}).then(function(){busy=false;});}
  form.addEventListener('submit',function(e){e.preventDefault();var v=text.value.trim();if(!v)return;
    var fd=new FormData();fd.append('csrf',csrf);fd.append('text',v);fd.append('after',after);
    form.querySelector('button').disabled=true;err.hidden=true;
    fetch(url,{method:'POST',body:fd,credentials:'same-origin',headers:{'Accept':'application/json'}}).then(function(r){return r.json().then(function(j){return [r.ok,j];});})
      .then(function(x){if(!x[0]){err.hidden=false;err.textContent=x[1].error||'보내지 못했어요';return;}text.value='';show(x[1]);})
      .catch(function(){err.hidden=false;err.textContent='보내지 못했어요. 다시 눌러 주세요.';})
      .then(function(){form.querySelector('button').disabled=false;text.focus();});});
  text.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();form.requestSubmit?form.requestSubmit():form.dispatchEvent(new Event('submit'));}});
  list.querySelectorAll('.lm').forEach(function(){});bottom();poll();setInterval(poll,3000);
})();
