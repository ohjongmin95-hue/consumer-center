// 운영자 2026-11-05: 얼굴 모자이크는 따로 쓰는 도구가 아니라, 기사에 사진·영상을 올릴 때 바로 거치는 단계.
// window.soboruMosaic(file, {logo}) → 창을 띄워 얼굴을 찾아 가리고, {file} (가린 파일) 또는 null (취소)을 돌려줌.
// 사진·영상은 이 브라우저 안에서만 다룸. 브라우저가 못 읽는 영상(아이폰 HEVC)만 서버에서 MP4로 바꿈.
const CFG = window.MOSAIC_CFG || {};
const BASE = CFG.base, CSRF = CFG.csrf;
let detImg = null, detVid = null, loading = null;
const logo = new Image(); logo.src = CFG.logo;

function loadDetector() {
  if (!loading) loading = (async () => {
    const {FaceDetector} = await import(BASE + 'vision_bundle.mjs');
    const fileset = {wasmLoaderPath: BASE + 'vision_wasm_internal.js', wasmBinaryPath: BASE + 'vision_wasm_internal.wasm'};
    const opt = m => ({baseOptions: {modelAssetPath: BASE + 'blaze_face_short_range.tflite', delegate: 'CPU'}, runningMode: m, minDetectionConfidence: 0.4});
    detImg = await FaceDetector.createFromOptions(fileset, opt('IMAGE'));
    detVid = await FaceDetector.createFromOptions(fileset, opt('VIDEO'));
  })();
  return loading;
}

// ---- 창 ----------------------------------------------------------------------
const box = document.createElement('div');
box.className = 'mo-modal'; box.hidden = true; box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.setAttribute('aria-labelledby', 'mo-h');
box.innerHTML = `<div class="mo-sheet">
  <div class="mo-head"><h2 id="mo-h">얼굴 가리기</h2><button type="button" class="mo-x" aria-label="닫기">×</button></div>
  <p class="mo-status" role="status"></p>
  <div class="mo-stage"><canvas></canvas></div>
  <div class="mo-bar" hidden><i></i></div>
  <div class="mo-opts">
    <label class="mo-range">모자이크 세기<input type="range" min="5" max="18" value="9"><span>보통</span></label>
    <label class="mo-check"><input type="checkbox" class="mo-logo"> 오른쪽 아래에 소보루 로고 넣기</label>
    <label class="mo-audio" hidden>영상 소리<select>
      <option value="keep">원래 소리 그대로</option>
      <option value="low">목소리 변조 (낮게)</option>
      <option value="high">목소리 변조 (높게)</option>
      <option value="mute">소리 없애기 (음소거)</option>
    </select></label>
  </div>
  <div class="mo-act"><button type="button" class="mo-run">가리고 넣기</button><button type="button" class="mo-skip">가리지 않고 그대로 넣기</button></div>
</div>`;
document.body.appendChild(box);
const q = s => box.querySelector(s);
const st = q('.mo-status'), cv = q('canvas'), cx = cv.getContext('2d'), rng = q('.mo-range input'), lg = q('.mo-logo'), au = q('.mo-audio select'), runB = q('.mo-run'), skipB = q('.mo-skip');
const say = t => { st.textContent = t; };
let file, kind, img, video, boxes = [], finish = null, busy = false;

const tmp = document.createElement('canvas'), tx = tmp.getContext('2d');
const strength = () => +rng.value;
rng.oninput = () => { const v = strength(); q('.mo-range span').textContent = v <= 7 ? '세게' : v >= 14 ? '약하게' : '보통'; redraw(); };
lg.onchange = () => redraw();
function redraw() { if (kind === 'image' && img) drawImage(true); else if (kind === 'video' && video && video.dataset.ready) drawPoster(); }
function grow(b, W, H) {  // 머리카락·턱까지 가리게 칸을 넓힘 (손으로 그린 칸은 그대로)
  if (b.hand) return b;
  const w = b.w * 1.4, h = b.h * 1.55, x = b.x + b.w / 2 - w / 2, y = b.y + b.h * 0.36 - h / 2;
  const x0 = Math.max(0, x), y0 = Math.max(0, y);
  return {x: x0, y: y0, w: Math.min(W, x + w) - x0, h: Math.min(H, y + h) - y0};
}
function pixelate(ctx, b) {
  const n = strength(), bs = Math.max(4, b.w / n);
  const sw = Math.max(1, Math.round(b.w / bs)), sh = Math.max(1, Math.round(b.h / bs));
  tmp.width = sw; tmp.height = sh; tx.imageSmoothingEnabled = true;
  tx.drawImage(ctx.canvas, b.x, b.y, b.w, b.h, 0, 0, sw, sh);
  ctx.imageSmoothingEnabled = false; ctx.drawImage(tmp, 0, 0, sw, sh, b.x, b.y, b.w, b.h); ctx.imageSmoothingEnabled = true;
}
function stamp(ctx, W, H) {
  if (!lg.checked || !logo.complete || !logo.naturalWidth) return;
  const w = Math.round(Math.max(90, Math.min(W * 0.14, 420))), h = Math.round(w * logo.naturalHeight / logo.naturalWidth), m = Math.round(Math.max(12, W * 0.025));
  ctx.save(); ctx.shadowColor = 'rgba(0,0,0,.35)'; ctx.shadowBlur = Math.max(4, w * 0.04);
  ctx.drawImage(logo, W - w - m, H - h - m, w, h); ctx.restore();
}
function iou(a, b) {
  const x = Math.max(a.x, b.x), y = Math.max(a.y, b.y), r = Math.min(a.x + a.w, b.x + b.w), d = Math.min(a.y + a.h, b.y + b.h);
  const i = Math.max(0, r - x) * Math.max(0, d - y); return i / Math.min(a.w * a.h, b.w * b.h);
}
const toBox = d => ({x: d.boundingBox.originX, y: d.boundingBox.originY, w: d.boundingBox.width, h: d.boundingBox.height});

// ---- 열기·닫기 -----------------------------------------------------------------
function close(result) {
  if (busy && result === null) return;  // 영상 만드는 중에는 닫지 않음
  box.hidden = true; document.documentElement.classList.remove('mo-open');
  if (video) { video.pause(); video = null; }
  const f = finish; finish = null; if (f) f(result);
}
q('.mo-x').onclick = () => close(null);
box.addEventListener('keydown', e => { if (e.key === 'Escape') close(null); });
skipB.onclick = () => close({file, masked: false});
runB.onclick = () => kind === 'video' ? runVideo() : saveImage();

window.soboruMosaic = function (f, opt) {
  opt = opt || {};
  return new Promise(resolve => {
    finish = resolve; file = f; kind = f.type.startsWith('video/') ? 'video' : 'image'; boxes = []; img = null; video = null; busy = false;
    lg.checked = opt.logo !== false;
    q('.mo-audio').hidden = kind !== 'video'; q('.mo-bar').hidden = true; q('.mo-bar i').style.width = '0';
    q('#mo-h').textContent = kind === 'video' ? '영상 속 얼굴 가리기' : '사진 속 얼굴 가리기';
    runB.textContent = kind === 'video' ? '얼굴 가린 영상 만들어 넣기' : '가리고 넣기'; runB.disabled = true; skipB.disabled = false;
    cx.clearRect(0, 0, cv.width, cv.height);
    box.hidden = false; document.documentElement.classList.add('mo-open'); runB.focus();
    say('얼굴 찾는 도구를 준비하고 있어요');
    loadDetector().then(() => kind === 'video' ? openVideo() : openImage())
      .catch(e => { console.error(e); say('얼굴 찾는 도구를 불러오지 못했어요. 크롬이나 엣지 최신판에서 다시 해 주세요. 그대로 넣을 수는 있어요.'); if (kind === 'image') openImage(true); });
  });
};

// ---- 사진 ---------------------------------------------------------------------
function openImage(noDetect) {
  img = new Image();
  img.onload = () => {
    const W = img.naturalWidth, H = img.naturalHeight; cv.width = W; cv.height = H;
    boxes = noDetect || !detImg ? [] : findFaces(img, W, H).map(b => ({...b, on: true}));
    drawImage(true); runB.disabled = false;
    if (!noDetect) say(boxes.length ? `얼굴 ${boxes.length}개를 찾아 가렸어요. 빠진 곳은 끌어서 칸을 그리고, 잘못 잡힌 칸은 눌러서 빼 주세요.` : '얼굴을 찾지 못했어요. 가릴 곳이 있으면 끌어서 칸을 그려 주세요.');
  };
  img.onerror = () => say('사진을 열지 못했어요. JPG·PNG·WEBP 사진을 골라 주세요.');
  img.src = URL.createObjectURL(file);
}
function findFaces(src, W, H) {
  // 사진 전체 + 겹치게 나눈 칸(작은 얼굴도 찾게)에서 찾고 겹친 것은 하나로
  const found = [];
  const add = (list, ox, oy, s, min) => list.forEach(d => { if (d.categories[0].score < min) return; const b = toBox(d); found.push({x: ox + b.x * s, y: oy + b.y * s, w: b.w * s, h: b.h * s}); });
  add(detImg.detect(src).detections, 0, 0, 1, 0.4);
  const c = document.createElement('canvas'), g = c.getContext('2d');
  const m = Math.min(W, H);
  for (const T of [m, m / 2, m / 3.5]) {
    if (T < 140) continue;
    const xs = [], ys = [], step = T * 0.6;
    for (let x = 0; x + T < W; x += step) xs.push(x); xs.push(Math.max(0, W - T));
    for (let y = 0; y + T < H; y += step) ys.push(y); ys.push(Math.max(0, H - T));
    const s = Math.min(1, 640 / T); c.width = c.height = Math.round(T * s);
    for (const x of xs) for (const y of ys) {
      g.drawImage(src, x, y, T, T, 0, 0, c.width, c.height);
      add(detImg.detect(c).detections, x, y, 1 / s, 0.62);  // 잘게 나눈 칸은 헛잡기 쉬워서 더 확실한 것만
    }
  }
  const out = [];
  found.sort((a, b) => b.w * b.h - a.w * a.h).forEach(b => { if (!out.some(o => iou(o, b) > 0.35)) out.push(b); });
  return out;
}
let drag = null, start = null;
function drawImage(guides) {
  const W = cv.width, H = cv.height;
  cx.drawImage(img, 0, 0, W, H);
  boxes.filter(b => b.on).forEach(b => pixelate(cx, grow(b, W, H)));
  stamp(cx, W, H);
  if (!guides) return;
  cx.save(); cx.lineWidth = Math.max(2, W / 400);
  boxes.forEach(b => { const g = grow(b, W, H); cx.setLineDash(b.on ? [] : [10, 8]); cx.strokeStyle = b.on ? '#EF920E' : 'rgba(255,255,255,.8)'; cx.strokeRect(g.x, g.y, g.w, g.h); });
  if (drag) { cx.setLineDash([6, 6]); cx.strokeStyle = '#fff'; cx.strokeRect(drag.x, drag.y, drag.w, drag.h); }
  cx.restore();
}
const at = e => { const r = cv.getBoundingClientRect(); return {x: (e.clientX - r.left) * cv.width / r.width, y: (e.clientY - r.top) * cv.height / r.height}; };
cv.onpointerdown = e => { if (kind !== 'image' || !img) return; start = at(e); cv.setPointerCapture(e.pointerId); };
cv.onpointermove = e => { if (!start) return; const p = at(e); drag = {x: Math.min(start.x, p.x), y: Math.min(start.y, p.y), w: Math.abs(p.x - start.x), h: Math.abs(p.y - start.y)}; drawImage(true); };
cv.onpointerup = e => {
  if (!start) return; const p = at(e), W = cv.width, H = cv.height;
  if (drag && drag.w > 12 && drag.h > 12) boxes.push({...drag, on: true, hand: true});
  else {
    const hit = boxes.slice().reverse().find(b => { const g = grow(b, W, H); return p.x >= g.x && p.x <= g.x + g.w && p.y >= g.y && p.y <= g.y + g.h; });
    if (hit) hit.on = !hit.on;
  }
  start = null; drag = null; drawImage(true);
  say(`가릴 곳 ${boxes.filter(b => b.on).length}군데. 칸을 누르면 빼고, 끌면 더해요.`);
};
function saveImage() {
  drawImage(false);
  const type = file.type === 'image/png' ? 'image/png' : 'image/jpeg';
  cv.toBlob(b => {
    const name = (file.name.replace(/\.[^.]+$/, '') || 'photo') + (type === 'image/png' ? '.png' : '.jpg');
    close({file: new File([b], name, {type}), masked: true});
  }, type, 0.95);
}

// ---- 영상 ---------------------------------------------------------------------
function drawPoster() {
  const r = detImg ? detImg.detect(video).detections.map(toBox) : [];
  cx.drawImage(video, 0, 0); r.forEach(b => pixelate(cx, grow(b, cv.width, cv.height))); stamp(cx, cv.width, cv.height);
  return r.length;
}
function openVideo() {
  say('영상을 여는 중이에요');
  video = document.createElement('video'); video.playsInline = true; video.preload = 'auto'; video.muted = true; video.src = URL.createObjectURL(file);
  const v = video;
  v.onloadeddata = () => {
    if (v !== video) return;
    if (!v.videoWidth) { convert(); return; }  // 소리만 열리고 화면은 못 읽음 (HEVC)
    cv.width = v.videoWidth; cv.height = v.videoHeight;
    v.currentTime = Math.min(0.5, v.duration / 2);
  };
  v.onseeked = () => {
    if (v !== video || v.dataset.ready) return; v.dataset.ready = '1';
    const n = drawPoster(); runB.disabled = false;
    say(`영상 ${Math.round(v.duration)}초. ${n ? '첫 장면에서 얼굴 ' + n + '개를 찾았어요. ' : ''}'얼굴 가린 영상 만들어 넣기'를 누르면 처음부터 끝까지 얼굴을 가려요. 영상 길이만큼 걸리고, 그동안 이 화면을 켜 두세요.`);
  };
  v.onerror = () => { if (v === video) convert(); };
}
// 아이폰·카톡 영상(HEVC)처럼 브라우저가 못 여는 영상은 서버에서 MP4(H.264)로 바꿔서 다시 엶. 바꾼 파일은 1시간 안에 서버에서 지워짐
let converting = false;
async function convert() {
  if (converting || file.name === 'soboru-converted.mp4') { say('이 영상은 열 수 없어요. 다른 영상으로 해 주세요.'); skipB.disabled = true; return; }
  if (!CFG.canConvert) { say('이 영상은 브라우저가 못 읽는 형식(아이폰 고효율 HEVC)이에요. 서버 업데이트 후 다시 해 주세요.'); skipB.disabled = true; return; }
  converting = true; skipB.disabled = true;
  const CH = 8 * 1024 * 1024; let job = '';
  try {
    for (let i = 0, k = 0; i < file.size; i += CH, k++) {
      say(`이 영상은 브라우저가 바로 못 읽는 형식(아이폰 고효율 HEVC)이라 읽을 수 있게 바꾸고 있어요 · 올리는 중 ${Math.min(100, Math.round((i + CH) / file.size * 100))}%`);
      const r = await fetch(`${CFG.convUpload}?i=${k}${job ? '&job=' + job : ''}`, {method: 'POST', body: file.slice(i, i + CH), headers: {'X-CSRFToken': CSRF}, credentials: 'same-origin'});
      const j = await r.json(); if (!j.ok) throw new Error(j.error); job = j.job;
    }
    await fetch(`${CFG.convStart}?job=${job}`, {method: 'POST', headers: {'X-CSRFToken': CSRF}, credentials: 'same-origin'});
    for (let t = 0; ; t++) {
      say(`읽을 수 있는 영상으로 바꾸는 중이에요${'.'.repeat(t % 4)} 영상 길이에 따라 몇십 초 걸려요`);
      await new Promise(r => setTimeout(r, 1500));
      const s = (await (await fetch(`${CFG.convDone}?check=1&job=${job}`, {credentials: 'same-origin'})).json()).state;
      if (s === 'done') break; if (s === 'error') throw new Error('영상을 바꾸지 못했어요.');
    }
    const blob = await (await fetch(`${CFG.convDone}?job=${job}`, {credentials: 'same-origin'})).blob();
    converting = false; skipB.disabled = false;
    file = new File([blob], 'soboru-converted.mp4', {type: 'video/mp4'}); openVideo();
  } catch (e) { converting = false; say((e && e.message) || '영상을 바꾸지 못했어요. 잠시 뒤 다시 해 주세요.'); }
}
const PITCH = `class P extends AudioWorkletProcessor{constructor(o){super();this.r=o.processorOptions.ratio;this.n=Math.floor(sampleRate*0.05);this.L=this.n*2+4;this.b=[new Float32Array(this.L),new Float32Array(this.L)];this.w=0;this.p=0}
process(i,o){const x=i[0],y=o[0];if(!x||!x.length)return true;const n=this.n,L=this.L,step=(1-this.r)/n;for(let k=0;k<x[0].length;k++){let ph=this.p;for(let c=0;c<y.length;c++){const s=(x[c]||x[0])[k],b=this.b[c];b[this.w]=s;let v=0;for(let t=0;t<2;t++){const q=(ph+t*0.5)%1,d=q*n+1,r=(this.w-d+L)%L,f=Math.floor(r),a=r-f,s0=b[f],s1=b[(f+1)%L];v+=(s0+(s1-s0)*a)*Math.sin(Math.PI*q)}y[c][k]=v*0.9}
this.p=(this.p+step+1)%1;this.w=(this.w+1)%L}return true}}registerProcessor('soboru-pitch',P)`;
async function runVideo() {
  busy = true; runB.disabled = true; skipB.disabled = true; q('.mo-bar').hidden = false;
  try {
    // 같은 영상 요소에는 소리 연결을 한 번만 할 수 있어서 새로 만듦
    const v = document.createElement('video'); v.playsInline = true; v.src = video.src; await new Promise(r => { v.onloadeddata = r; v.load(); });
    const W = v.videoWidth, H = v.videoHeight; cv.width = W; cv.height = H;
    const mode = au.value, tracks = [];
    const vs = cv.captureStream(0), vt = vs.getVideoTracks()[0]; tracks.push(vt);
    let ac = null;
    if (mode !== 'mute') {
      ac = new AudioContext(); const src = ac.createMediaElementSource(v), dest = ac.createMediaStreamDestination();
      if (mode === 'keep') src.connect(dest);
      else {
        await ac.audioWorklet.addModule(URL.createObjectURL(new Blob([PITCH], {type: 'text/javascript'})));
        const node = new AudioWorkletNode(ac, 'soboru-pitch', {processorOptions: {ratio: mode === 'low' ? 0.78 : 1.32}, outputChannelCount: [2]});
        src.connect(node).connect(dest);
      }
      dest.stream.getAudioTracks().forEach(t => tracks.push(t));
    } else v.muted = true;
    const types = ['video/mp4;codecs=avc1.640028,mp4a.40.2', 'video/mp4', 'video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm'];
    const mime = types.find(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t));
    if (!mime) throw new Error('이 브라우저는 영상 만들기를 지원하지 않아요. 크롬이나 엣지 최신판에서 해 주세요.');
    const bps = Math.max(6e6, Math.min(16e6, file.size * 8 / Math.max(1, v.duration) * 1.2));
    const rec = new MediaRecorder(new MediaStream(tracks), {mimeType: mime, videoBitsPerSecond: Math.round(bps), audioBitsPerSecond: 160000});
    const chunks = []; rec.ondataavailable = e => e.data.size && chunks.push(e.data);
    const done = new Promise(r => rec.onstop = r);
    let tracked = [], last = -1;
    const frame = (now, meta) => {
      let ts = Math.round(((meta && meta.mediaTime) || v.currentTime) * 1000); if (ts <= last) ts = last + 1; last = ts;
      const found = detVid ? detVid.detectForVideo(v, ts).detections.map(toBox) : [];
      tracked.forEach(t => t.age++);  // 잠깐 놓친 얼굴도 몇 장 동안 계속 가림 (깜빡임 방지)
      found.forEach(b => { const m = tracked.find(t => iou(t, b) > 0.2); if (m) Object.assign(m, b, {age: 0}); else tracked.push({...b, age: 0}); });
      tracked = tracked.filter(t => t.age < 12);
      cx.drawImage(v, 0, 0, W, H); tracked.forEach(b => pixelate(cx, grow(b, W, H))); stamp(cx, W, H);
      vt.requestFrame && vt.requestFrame();
      q('.mo-bar i').style.width = (v.currentTime / v.duration * 100).toFixed(1) + '%';
      if (!v.ended) next();
    };
    const next = () => v.requestVideoFrameCallback ? v.requestVideoFrameCallback(frame) : requestAnimationFrame(() => frame());
    v.onended = () => setTimeout(() => rec.state !== 'inactive' && rec.stop(), 300);
    say('얼굴을 가린 영상을 만드는 중이에요. 영상 길이만큼 걸려요. 이 화면을 켜 둔 채로 기다려 주세요.');
    rec.start(1000); next(); if (ac) await ac.resume(); await v.play();
    await done; if (ac) ac.close();
    const ext = mime.startsWith('video/mp4') ? 'mp4' : 'webm';
    busy = false;
    close({file: new File(chunks, (file.name.replace(/\.[^.]+$/, '') || 'video') + '.' + ext, {type: 'video/' + ext}), masked: true});
  } catch (e) {
    busy = false; runB.disabled = false; skipB.disabled = false; say((e && e.message) || '영상을 만들지 못했어요.');
  }
}
