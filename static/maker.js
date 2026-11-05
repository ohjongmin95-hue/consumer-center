/* 카드뉴스·릴스 만들기 (운영자 2026-11-05) — mag_maker.py, templates/mag_admin_maker.html
   글씨·디자인은 이 파일이 canvas로 그림. 카드뉴스는 PNG로 바로 받고, 릴스는 장면별 글씨 판(투명 PNG)을 서버로 보내 ffmpeg가 영상과 겹침.
   디자인: 릴스 wide(이슈 와이드)·full(풀스크린 뉴스)·chat(채팅 스레드)·quote(인용 클로즈업)·clean(클린 포토)
           카드 clean(클린 포토 표지)·text(속 장)·quote(인용)
   줄 쓰는 법: '#글' 흰 상자, '!글' 귤색 상자, '이름 : 말' 이름 굵게 말풍선, 나머지는 말풍선. **굵게** */
(function () {
  'use strict';
  var C = window.MAKER_CFG || {};
  var OR = '#EF920E', ORD = '#CE6719', BR = '#652D1C', FONT = '"Pretendard Variable", Pretendard, -apple-system, sans-serif';
  var CAT = {'쇼핑': 'SHOPPING', '뷰티': 'BEAUTY', '음식': 'FOOD', '생활': 'LIFE', '금융': 'MONEY', '통신': 'TELECOM', '여행': 'TRAVEL', '자동차': 'CAR', '리콜': 'RECALL'};
  var LAY = {wide: ['blur', [0, 620, 1080, 608]], full: ['cover', null], chat: ['#15120f', [60, 460, 960, 540]], quote: ['blur', null], clean: ['cover', null]};
  var REEL_D = [['wide', '이슈 와이드'], ['full', '풀스크린 뉴스'], ['chat', '채팅 스레드'], ['quote', '인용 클로즈업'], ['clean', '클린 포토']];
  var CARD_D = [['clean', '클린 포토 표지'], ['text', '속 장 (글)'], ['quote', '인용']];
  var $ = function (s, r) { return (r || document).querySelector(s); };

  // ---- 글꼴·로고 ----------------------------------------------------------------------------
  var logo = new Image(); logo.src = C.logo;
  var logoW = null, logoK = null;
  function tint(color) {
    var c = document.createElement('canvas'); c.width = logo.naturalWidth; c.height = logo.naturalHeight;
    var x = c.getContext('2d'); x.drawImage(logo, 0, 0); x.globalCompositeOperation = 'source-in'; x.fillStyle = color; x.fillRect(0, 0, c.width, c.height); return c;
  }
  function drawLogo(ctx, color, x, y, h, align) {
    if (!logo.complete || !logo.naturalWidth) return;
    var src = color === 'white' ? (logoW = logoW || tint('#fff')) : color === 'brown' ? logo : (logoK = logoK || tint('#111'));
    var w = h * logo.naturalWidth / logo.naturalHeight;
    ctx.drawImage(src, align === 'right' ? x - w : align === 'center' ? x - w / 2 : x, y, w, h);
  }
  function fontsFor(texts) {
    var s = texts.join(' ');
    if (!document.fonts || !s.trim()) return Promise.resolve();
    return Promise.all(['500', '600', '700', '800', '900'].map(function (w) { return document.fonts.load(w + ' 40px "Pretendard Variable"', s).catch(function () {}); }));
  }
  function F(w, size) { return w + ' ' + size + 'px ' + FONT; }

  // ---- 글씨 (굵게 **…** 섞어 줄 바꿈) ------------------------------------------------------------
  function words(text, bold0) {
    var out = [], b = !!bold0;
    String(text || '').split(/(\*\*)/).forEach(function (part) {
      if (part === '**') { b = !b; return; }
      part.split(/(\n)/).forEach(function (p) {
        if (p === '\n') { out.push({br: true}); return; }
        p.split(/(\s+)/).forEach(function (w) { if (w) out.push({t: w, b: b}); });
      });
    });
    return out;
  }
  function layout(ctx, text, size, w0, w1, maxW, opt) {
    opt = opt || {};
    var lines = [[]], width = [0];
    function wid(tok) { ctx.font = F(tok.b ? w1 : w0, size); ctx.letterSpacing = (opt.ls || 0) + 'px'; return ctx.measureText(tok.t).width; }
    words(text, opt.bold).forEach(function (tok) {
      var L = lines.length - 1;
      if (tok.br) { lines.push([]); width.push(0); return; }
      var sp = /^\s+$/.test(tok.t);
      if (sp) { if (lines[L].length) { lines[L].push(tok); width[L] += wid(tok); } return; }
      var w = wid(tok);
      if (width[L] + w > maxW && lines[L].length) {
        while (lines[L].length && /^\s+$/.test(lines[L][lines[L].length - 1].t)) { width[L] -= wid(lines[L].pop()); }
        lines.push([]); width.push(0); L++;
      }
      if (w > maxW) {  // 띄어쓰기 없는 긴 낱말은 글자로 자름
        Array.from(tok.t).forEach(function (ch) {
          var c = {t: ch, b: tok.b}, cw = wid(c);
          if (width[L] + cw > maxW && lines[L].length) { lines.push([]); width.push(0); L++; }
          lines[L].push(c); width[L] += cw;
        });
        return;
      }
      lines[L].push(tok); width[L] += w;
    });
    return {lines: lines, width: width, lh: size * (opt.lh || 1.35), size: size, w0: w0, w1: w1, ls: opt.ls || 0};
  }
  function drawText(ctx, T, x, y, color, opt) {
    opt = opt || {};
    ctx.textBaseline = 'alphabetic'; ctx.fillStyle = color;
    T.lines.forEach(function (line, i) {
      var cx = opt.align === 'center' ? x - T.width[i] / 2 : x, base = y + i * T.lh + T.size * 0.95;
      line.forEach(function (tok) {
        ctx.font = F(tok.b ? T.w1 : T.w0, T.size); ctx.letterSpacing = T.ls + 'px';
        var w = ctx.measureText(tok.t).width;
        if (tok.b && opt.mark) { ctx.fillStyle = opt.mark; ctx.fillRect(cx - 2, base - T.size * 0.92, w + 8, T.size * 1.12); ctx.fillStyle = opt.markInk || color; ctx.fillText(tok.t, cx, base); ctx.fillStyle = color; }
        else { ctx.fillStyle = tok.b && opt.boldColor ? opt.boldColor : color; ctx.fillText(tok.t, cx, base); ctx.fillStyle = color; }
        cx += w;
      });
    });
    ctx.letterSpacing = '0px';
    return T.lines.length * T.lh;
  }
  function textH(T) { return T.lines.length * T.lh; }
  function rrect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.roundRect ? ctx.roundRect(x, y, w, h, r) : ctx.rect(x, y, w, h); }

  // ---- 줄(상자·말풍선) ---------------------------------------------------------------------------
  function parseItems(text) {
    return String(text || '').split('\n').map(function (s) { return s.trim(); }).filter(Boolean).map(function (s) {
      if (s[0] === '#') return {k: 'box', t: s.slice(1).trim()};
      if (s[0] === '!') return {k: 'obox', t: s.slice(1).trim()};
      var m = s.match(/^([^:：“"]{1,16}?)\s*[:：]\s*(.+)$/);
      if (m) return {k: 'bubble', who: m[1].trim(), t: m[2]};
      return {k: 'bubble', t: s};
    });
  }
  function itemBox(ctx, it, maxW, size) {
    var pad = it.k === 'bubble' ? [30, 18] : [28, 22];
    var txt = it.who ? '**' + it.who + ' :** ' + it.t : it.t;
    var T = layout(ctx, txt, size, 600, 800, maxW - pad[0] * 2, {lh: 1.36});
    return {T: T, w: Math.max.apply(null, T.width) + pad[0] * 2, h: textH(T) + pad[1] * 2, pad: pad};
  }
  function drawItem(ctx, it, b, x, y, opt) {
    opt = opt || {};
    ctx.save();
    if (it.k === 'bubble') {
      ctx.shadowColor = 'rgba(0,0,0,.18)'; ctx.shadowBlur = opt.flat ? 0 : 20; ctx.shadowOffsetY = opt.flat ? 0 : 6;
      ctx.fillStyle = opt.fill || '#fff'; rrect(ctx, x, y, b.w, b.h, Math.min(40, b.h / 2)); ctx.fill();
      ctx.shadowColor = 'transparent';
      if (opt.border) { ctx.lineWidth = 4; ctx.strokeStyle = '#111'; ctx.stroke(); }
    } else {
      ctx.fillStyle = it.k === 'obox' ? OR : '#fff'; ctx.fillRect(x, y, b.w, b.h);
      ctx.lineWidth = 4; ctx.strokeStyle = '#111'; ctx.strokeRect(x + 2, y + 2, b.w - 4, b.h - 4);
    }
    ctx.restore();
    drawText(ctx, b.T, x + b.pad[0], y + b.pad[1], '#111');
  }
  function stack(ctx, items, x, y, maxW, size, opt) {
    items.forEach(function (it) { var b = itemBox(ctx, it, maxW, size); drawItem(ctx, it, b, x, y, opt); y += b.h + 18; });
    return y;
  }
  function stackH(ctx, items, maxW, size) { var h = 0; items.forEach(function (it, i) { h += itemBox(ctx, it, maxW, size).h + (i ? 18 : 0); }); return h; }
  function tag(ctx, text, x, y, opt) {
    if (!text) return;
    opt = opt || {};
    ctx.font = F(800, 32); var w = ctx.measureText(text).width;
    ctx.fillStyle = opt.bg || OR; ctx.fillRect(x, y, w + 36, 54);
    if (!opt.noBorder) { ctx.lineWidth = 3; ctx.strokeStyle = '#111'; ctx.strokeRect(x + 1.5, y + 1.5, w + 33, 51); }
    ctx.fillStyle = opt.ink || '#111'; ctx.textBaseline = 'middle'; ctx.fillText(text, x + 18, y + 28); ctx.textBaseline = 'alphabetic';
  }
  function grad(ctx, y0, y1, a0, a1, w) {
    var g = ctx.createLinearGradient(0, y0, 0, y1); g.addColorStop(0, 'rgba(0,0,0,' + a0 + ')'); g.addColorStop(1, 'rgba(0,0,0,' + a1 + ')');
    ctx.fillStyle = g; ctx.fillRect(0, y0, w || 1080, y1 - y0);
  }
  function shadowed(ctx, fn) { ctx.save(); ctx.shadowColor = 'rgba(0,0,0,.45)'; ctx.shadowBlur = 18; ctx.shadowOffsetY = 4; fn(); ctx.restore(); }

  // ---- 릴스 글씨 판 (1080x1920, 투명) -------------------------------------------------------------
  var REEL = {
    wide: function (ctx, s) {
      tag(ctx, s.tag, 60, 170); drawLogo(ctx, 'white', 1020, 180, 34, 'right');
      var T = layout(ctx, s.title, 112, 900, 900, 960, {lh: 1.08, ls: -6});
      shadowed(ctx, function () { drawText(ctx, T, 56, 250, '#fff'); });
      if (s.sub) { var S2 = layout(ctx, s.sub, 52, 900, 900, 960, {ls: -2}); shadowed(ctx, function () { drawText(ctx, S2, 58, 262 + textH(T), '#FFA733'); }); }
      stack(ctx, parseItems(s.items), 60, 1290, 900, 42);
    },
    full: function (ctx, s) {
      grad(ctx, 0, 760, .8, 0); grad(ctx, 1040, 1920, 0, .88);
      tag(ctx, s.tag, 60, 150); drawLogo(ctx, 'white', 1020, 160, 34, 'right');
      var T = layout(ctx, s.title, 120, 900, 900, 960, {lh: 1.06, ls: -7});
      shadowed(ctx, function () { drawText(ctx, T, 56, 236, '#fff'); });
      if (s.sub) { var S2 = layout(ctx, s.sub, 50, 800, 800, 960); shadowed(ctx, function () { drawText(ctx, S2, 58, 252 + textH(T), '#FFA733'); }); }
      var items = parseItems(s.items), h = stackH(ctx, items, 900, 42);
      stack(ctx, items, 60, 1720 - h, 900, 42);
    },
    chat: function (ctx, s) {
      ctx.font = F(800, 30); ctx.fillStyle = OR; ctx.fillText('● ' + (s.tag || ''), 60, 182); drawLogo(ctx, 'white', 1020, 156, 34, 'right');
      var T = layout(ctx, s.title, 84, 900, 900, 960, {lh: 1.1, ls: -4}); drawText(ctx, T, 56, 222, '#fff');
      var y = 1040, first = null;
      parseItems(s.items).forEach(function (it) {
        if (!it.who) { var N = layout(ctx, it.t, 30, 600, 800, 900); drawText(ctx, N, 540, y + 6, '#9a948c', {align: 'center'}); y += textH(N) + 30; return; }
        first = first || it.who; var right = it.who !== first;
        var b = itemBox(ctx, {k: 'bubble', t: it.t}, 820, 40);
        ctx.font = F(700, 28); ctx.fillStyle = '#aaa'; ctx.textAlign = right ? 'right' : 'left'; ctx.fillText(it.who, right ? 1012 : 68, y + 26); ctx.textAlign = 'left';
        drawItem(ctx, {k: 'bubble'}, b, right ? 1020 - b.w : 60, y + 40, {fill: right ? OR : '#fff'});
        y += b.h + 40 + 26;
      });
    },
    quote: function (ctx, s) {
      tag(ctx, s.tag, 64, 150); drawLogo(ctx, 'white', 1016, 160, 34, 'right');
      ctx.font = F(900, 260); ctx.fillStyle = OR; ctx.fillText('“', 56, 700);
      var T = layout(ctx, s.title, 84, 900, 900, 952, {lh: 1.25, ls: -4});
      var y = 760; y += drawText(ctx, T, 64, y, '#fff', {mark: OR, markInk: '#111'});
      if (s.sub) { ctx.font = F(700, 40); ctx.fillStyle = '#ddd'; ctx.fillText('— ' + s.sub, 64, y + 80); }
      var it = parseItems(s.items)[0];
      if (it) { var N = layout(ctx, it.who ? it.who + ' : ' + it.t : it.t, 34, 600, 800, 952); drawText(ctx, N, 64, 1680 - textH(N), '#bbb'); }
    },
    clean: function (ctx, s) {
      grad(ctx, 0, 340, .35, 0); grad(ctx, 760, 1920, 0, .82);
      drawLogo(ctx, 'white', 540, 70, 40, 'center');
      var T = layout(ctx, s.title, 84, 800, 800, 960, {lh: 1.24, ls: -3}), y = 1700 - textH(T);
      shadowed(ctx, function () { drawText(ctx, T, 60, y, '#fff'); });
      if (s.tag) { ctx.font = F(800, 28); ctx.letterSpacing = '4px'; ctx.fillStyle = 'rgba(255,255,255,.92)'; ctx.fillText(s.tag, 64, y - 30); ctx.letterSpacing = '0px'; }
    },
    outro: function (ctx, letter) {  // 레터 꼭지로 만든 릴스는 끝 화면도 레터 구독 안내 (운영자 2026-11-05)
      drawLogo(ctx, 'white', 540, 620, 108, 'center');
      ctx.font = F(800, 46); ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.fillText(letter ? '소보루 레터' : '소보루 매거진', 540, 830); ctx.textAlign = 'left';
      var a = {k: 'bubble', t: letter ? '매일 아침 소비·경제 뉴스를 메일로' : '억울한 소비자 피해, 제보해 주세요'}, b1 = itemBox(ctx, a, 900, 44); drawItem(ctx, a, b1, 540 - b1.w / 2, 1150);
      var c = {k: 'box', t: letter ? '**프로필 링크에서 무료 구독**' : '**consumerjebo.co.kr**'}, b2 = itemBox(ctx, c, 900, 44); drawItem(ctx, c, b2, 540 - b2.w / 2, 1150 + b1.h + 22);
    }
  };

  // ---- 카드 (1080x1350) -------------------------------------------------------------------------
  var CARD = {
    clean: function (ctx, s, img, n, N) {
      cover(ctx, img, 0, 0, 1080, 1350); grad(ctx, 0, 260, .3, 0); grad(ctx, 520, 1350, 0, .8);
      drawLogo(ctx, 'white', 540, 46, 38, 'center');
      if (N > 1) { ctx.font = F(700, 26); ctx.fillStyle = 'rgba(255,255,255,.85)'; ctx.textAlign = 'right'; ctx.fillText(n + '/' + N, 1024, 74); ctx.textAlign = 'left'; }
      var T = layout(ctx, s.title, 72, 800, 800, 960, {lh: 1.24, ls: -3}), y = 1254 - textH(T);
      shadowed(ctx, function () { drawText(ctx, T, 60, y, '#fff'); });
      if (s.tag) { ctx.font = F(800, 26); ctx.letterSpacing = '4px'; ctx.fillStyle = 'rgba(255,255,255,.92)'; ctx.fillText(s.tag, 64, y - 26); ctx.letterSpacing = '0px'; }
    },
    text: function (ctx, s, img, n, N) {
      ctx.fillStyle = '#FAFAF7'; ctx.fillRect(0, 0, 1080, 1350);
      drawLogo(ctx, 'brown', 540, 46, 38, 'center');
      if (N > 1) { ctx.font = F(700, 26); ctx.fillStyle = '#999'; ctx.textAlign = 'right'; ctx.fillText(n + '/' + N, 1024, 74); ctx.textAlign = 'left'; }
      var y = 170;
      if (img) { cover(ctx, img, 80, y, 920, 440); y += 480; }
      var T = layout(ctx, s.title, 60, 900, 900, 920, {lh: 1.25, ls: -3}); y += drawText(ctx, T, 80, y, '#111') + 34;
      var body = String(s.items || '').split(/\n\s*\n|\n/).filter(function (x) { return x.trim(); });
      body.forEach(function (p) { if (y > 1180) return; var P = layout(ctx, p, 40, 500, 800, 920, {lh: 1.62, ls: -1}); y += drawText(ctx, P, 80, y, '#2a2a2a', {boldColor: ORD}) + 28; });
      ctx.fillStyle = '#111'; ctx.fillRect(80, 1264, 920, 2);
      ctx.font = F(700, 26); ctx.fillStyle = '#999'; ctx.fillText('소보루 매거진', 80, 1306); ctx.textAlign = 'right'; ctx.fillText('soboru.co.kr', 1000, 1306); ctx.textAlign = 'left';
    },
    quote: function (ctx, s, img) {
      ctx.fillStyle = '#000'; ctx.fillRect(0, 0, 1080, 1350);
      if (img) { ctx.save(); ctx.filter = 'blur(12px) brightness(.35)'; cover(ctx, img, -40, -40, 1160, 1430); ctx.restore(); }
      drawLogo(ctx, 'white', 540, 46, 38, 'center');
      ctx.font = F(900, 220); ctx.fillStyle = OR; ctx.fillText('“', 56, 470);
      var T = layout(ctx, s.title, 76, 900, 900, 952, {lh: 1.26, ls: -4}), y = 520; y += drawText(ctx, T, 64, y, '#fff', {mark: OR, markInk: '#111'});
      if (s.sub) { ctx.font = F(700, 38); ctx.fillStyle = '#ddd'; ctx.fillText('— ' + s.sub, 64, y + 70); }
    }
  };

  // ---- 사진·영상 그리기 ---------------------------------------------------------------------------
  function cover(ctx, img, x, y, w, h) {
    if (!img) return;
    var iw = img.videoWidth || img.naturalWidth || img.width, ih = img.videoHeight || img.naturalHeight || img.height;
    if (!iw || !ih) return;
    var r = Math.max(w / iw, h / ih), sw = w / r, sh = h / r;
    ctx.drawImage(img, (iw - sw) / 2, (ih - sh) / 2, sw, sh, x, y, w, h);
  }
  function reelBase(ctx, lay, media) {
    var L = LAY[lay], bg = L[0], fg = L[1];
    ctx.fillStyle = bg[0] === '#' ? bg : '#000'; ctx.fillRect(0, 0, 1080, 1920);
    if (media && bg === 'blur') { ctx.save(); ctx.filter = 'blur(36px) brightness(.55) saturate(.6)'; cover(ctx, media, -60, -60, 1200, 2040); ctx.restore(); }
    if (media && bg === 'cover') cover(ctx, media, 0, 0, 1080, 1920);
    if (media && fg) cover(ctx, media, fg[0], fg[1], fg[2], fg[3]);
  }

  // ---- 화면 -------------------------------------------------------------------------------------
  var root = $('#mk'); if (!root) return;
  var mode = root.dataset.mode || 'card';
  var slides = [], cur = 0;
  var stage = $('#mk-stage'), sctx = stage.getContext('2d');
  var list = $('#mk-list'), form = $('#mk-form');
  function blank(prev) {
    prev = prev || {};
    return mode === 'reel'
      ? {design: prev.design || 'wide', tag: prev.tag || '', title: prev.title || '', sub: prev.sub || '', items: '', media: prev.media || null, start: prev.end || 0, dur: 4, slow: false}
      : {design: slides.length ? 'text' : 'clean', tag: prev.tag || '', title: '', sub: '', items: '', media: null};
  }
  function size() { return mode === 'reel' ? [1080, 1920] : [1080, 1350]; }
  function texts() { var a = []; slides.forEach(function (s) { a.push(s.tag, s.title, s.sub, s.items); }); a.push('소보루 매거진 억울한 소비자 피해, 제보해 주세요 consumerjebo.co.kr — “ 0123456789/'); return a; }

  function paint(ctx, s, i, overlayOnly) {
    var wh = size(); ctx.clearRect(0, 0, wh[0], wh[1]);
    var el = s.media && s.media.el;
    if (mode === 'reel') {
      if (!overlayOnly) reelBase(ctx, s.design, el);
      REEL[s.design](ctx, s);
    } else {
      CARD[s.design](ctx, s, el, i + 1, slides.length);
    }
  }
  function draw() {
    var wh = size(); stage.width = wh[0]; stage.height = wh[1];
    var s = slides[cur]; if (!s) return;
    fontsFor(texts()).then(function () { paint(sctx, s, cur); thumbs(); });
  }
  function thumbs() {
    list.innerHTML = '';
    slides.forEach(function (s, i) {
      var li = document.createElement('li'); li.className = 'mk-th' + (i === cur ? ' on' : '');
      var c = document.createElement('canvas'), wh = size(); c.width = wh[0]; c.height = wh[1];
      paint(c.getContext('2d'), s, i);
      var b = document.createElement('button'); b.type = 'button'; b.setAttribute('aria-label', (i + 1) + '번 ' + (mode === 'reel' ? '장면' : '장'));
      b.appendChild(c); var n = document.createElement('span'); n.textContent = (i + 1) + (mode === 'reel' && s.media ? ' · ' + s.dur + '초' : ''); b.appendChild(n);
      b.onclick = function () { cur = i; fill(); draw(); };
      li.appendChild(b); list.appendChild(li);
    });
  }
  function fill() {
    var s = slides[cur]; if (!s) return;
    var ds = mode === 'reel' ? REEL_D : CARD_D;
    $('#mk-design').innerHTML = ds.map(function (d) { return '<label class="mk-chip"><input type="radio" name="mk-d" value="' + d[0] + '"' + (s.design === d[0] ? ' checked' : '') + '><span>' + d[1] + '</span></label>'; }).join('');
    form.querySelectorAll('[data-f]').forEach(function (el) { var k = el.dataset.f; if (el.type === 'checkbox') el.checked = !!s[k]; else el.value = s[k] == null ? '' : s[k]; });
    $('#mk-media-st').textContent = s.media ? (s.media.kind === 'video' ? '영상' : '사진') + ' 넣었어요' + (s.media.len ? ' (' + s.media.len.toFixed(1) + '초)' : '') : (mode === 'reel' ? '사진이나 영상을 골라 주세요' : '사진 고르기 (속 장은 비워도 돼요)');
    $('#mk-timing').hidden = mode !== 'reel';
    $('#mk-start-row').hidden = !(s.media && s.media.kind === 'video');
    $('#mk-n').textContent = (cur + 1) + ' / ' + slides.length;
    var lab = {title: s.design === 'quote' ? '인용할 말' : '제목', sub: s.design === 'quote' ? '말한 사람' : '부제', items: mode === 'card' && s.design === 'text' ? '본문 (빈 줄로 문단, **굵게**는 귤색)' : '줄 (#흰 상자, !귤색 상자, 이름 : 말)'};
    Object.keys(lab).forEach(function (k) { var l = $('#mk-l-' + k); if (l) l.textContent = lab[k]; });
  }
  $('#mk-design').addEventListener('change', function (e) { if (e.target.name === 'mk-d') { slides[cur].design = e.target.value; fill(); draw(); } });
  form.addEventListener('input', function (e) {
    var k = e.target.dataset.f; if (!k) return;
    var s = slides[cur]; s[k] = e.target.type === 'checkbox' ? e.target.checked : (e.target.type === 'number' ? parseFloat(e.target.value) || 0 : e.target.value);
    if (k === 'start' || k === 'dur') { s.end = (s.start || 0) + (s.dur || 0) / (s.slow ? 2 : 1); seek(s); }
    draw();
  });
  $('#mk-add').onclick = function () { slides.splice(cur + 1, 0, blank(slides[cur])); cur++; fill(); draw(); };
  $('#mk-del').onclick = function () { if (slides.length < 2) return; slides.splice(cur, 1); cur = Math.max(0, cur - 1); fill(); draw(); };
  $('#mk-up').onclick = function () { if (!cur) return; var s = slides.splice(cur, 1)[0]; slides.splice(--cur, 0, s); fill(); draw(); };

  // 사진·영상 넣기
  function say(t) { var st = $('#mk-st'); st.hidden = !t; st.textContent = t || ''; }
  function seek(s) { if (s.media && s.media.kind === 'video') { s.media.el.currentTime = Math.min((s.start || 0) + .1, (s.media.len || 1) - .05); } }
  function loadVideo(url) {
    return new Promise(function (ok, no) {
      var v = document.createElement('video'); v.muted = true; v.playsInline = true; v.preload = 'auto'; v.crossOrigin = 'anonymous';
      v.onloadeddata = function () { ok(v); }; v.onerror = function () { no(new Error('이 영상은 미리 볼 수 없어요. MP4(H.264)로 바꿔 올려 주세요.')); };
      v.onseeked = function () { draw(); };
      v.src = url;
    });
  }
  function loadImg(url) { return new Promise(function (ok, no) { var i = new Image(); if (/^https?:/.test(url) && url.indexOf(location.origin) !== 0) i.crossOrigin = 'anonymous'; i.onload = function () { ok(i); }; i.onerror = function () { no(new Error('사진을 읽지 못했어요.')); }; i.src = url; }); }
  function post(url, body, type) {
    return fetch(url, {method: 'POST', body: body, headers: Object.assign({'X-CSRFToken': C.csrf}, type ? {'Content-Type': type} : {}), credentials: 'same-origin'}).then(function (r) { return r.json(); });
  }
  function uploadVideo(file) {
    var CH = 8 * 1024 * 1024, n = Math.ceil(file.size / CH), job = '', i = 0;
    function next() {
      if (i >= n) return post(C.vsave + '?job=' + encodeURIComponent(job));
      say('영상을 올리고 있어요 ' + Math.round(i / n * 100) + '%');
      return post(C.vup + '?i=' + i + (job ? '&job=' + encodeURIComponent(job) : ''), file.slice(i * CH, (i + 1) * CH), 'application/octet-stream').then(function (j) { if (!j.ok) throw new Error(j.error || '올리지 못했어요.'); job = j.job; i++; return next(); });
    }
    return next();
  }
  $('#mk-file').addEventListener('change', function () {
    var f = this.files[0], s = slides[cur]; this.value = ''; if (!f) return;
    var isV = /^video\//.test(f.type);
    if (mode === 'card') {
      if (isV) { say('카드뉴스에는 사진만 넣을 수 있어요.'); return; }
      loadImg(URL.createObjectURL(f)).then(function (img) { s.media = {kind: 'image', el: img}; say(''); fill(); draw(); }, function (e) { say(e.message); });
      return;
    }
    var up = isV ? uploadVideo(f) : (function () { var fd = new FormData(); fd.append('photo', f); say('사진을 올리고 있어요'); return post(C.pup, fd); })();
    up.then(function (j) {
      if (!j || !j.ok) throw new Error((j && j.error) || '올리지 못했어요.');
      return (isV ? loadVideo(j.url) : loadImg(j.url)).then(function (el) {
        s.media = {kind: isV ? 'video' : 'image', url: j.url, el: el, len: isV ? el.duration : 0};
        if (isV) { s.start = 0; s.dur = Math.min(4, Math.floor(el.duration * 10) / 10); s.end = s.dur; seek(s); }
        // 같은 영상을 이어 쓰는 장면에도 넣어 둠 (비어 있는 장면만)
        slides.forEach(function (o) { if (!o.media) { o.media = s.media; } });
        say(''); fill(); draw();
      });
    }).catch(function (e) { say(e.message); });
  });

  // 기사로 만들기 (운영자 2026-11-05: '기사 넣으면 만들어지게') — AI(mag_assist cards·reel)가 장·장면을 짜고, 기사 사진·영상을 자동으로 넣음
  var artSel = $('#mk-art');
  function artOf(id) { return (C.arts || []).filter(function (x) { return String(x.id) === String(id); })[0]; }
  function localFill(a) {  // AI를 못 쓸 때: 기사 소제목·문단을 그대로 잘라 넣음
    var secs = [], curS = null;
    String(a.body || '').split('\n').forEach(function (line) {
      var t = line.trim(); if (!t || /^\[(사진|영상)/.test(t)) return;
      if (/^##\s/.test(t)) { curS = {title: t.replace(/^##\s*/, ''), paras: []}; secs.push(curS); return; }
      if (!curS) { curS = {title: '', paras: []}; secs.push(curS); }
      if (curS.paras.length < 2) curS.paras.push(t.replace(/^[-*]\s*/, '').slice(0, 170));
    });
    var tg = CAT[a.category] || (a.category || '').toUpperCase();
    if (mode === 'card') {
      var img = slides[0] && slides[0].media;
      slides = [{design: 'clean', tag: tg, title: a.title, sub: '', items: '', media: img}];
      secs.filter(function (x) { return x.paras.length; }).slice(0, 6).forEach(function (x) { slides.push({design: 'text', tag: tg, title: x.title || a.title, sub: '', items: x.paras.join('\n\n'), media: null}); });
    } else {
      slides[0].title = a.title; slides[0].tag = a.category ? a.category + ' 이슈' : slides[0].tag;
    }
    cur = 0; fill(); draw();
  }
  function loadMedia(j) {  // 기사 사진·영상을 미리 읽어 둠. 릴스는 서버가 겹칠 수 있는 우리 서버 파일만
    var ph = (j.photos || []), vd = mode === 'reel' ? (j.videos || []) : [];
    if (mode === 'reel') ph = ph.filter(function (u) { return /^\/art\//.test(u); });
    return Promise.all(vd.slice(0, 3).map(function (u) { return loadVideo(u).then(function (el) { return {kind: 'video', url: u, el: el, len: el.duration}; }, function () { return null; }); })
      .concat(ph.slice(0, 8).map(function (u) { return loadImg(u).then(function (el) { return {kind: 'image', url: u, el: el}; }, function () { return null; }); })))
      .then(function (ms) { return ms.filter(Boolean); });
  }
  var fromLetter = false, capBox = $('#mk-cap'), capT = $('#mk-cap-t');
  function applyPlan(j) {
    fromLetter = !!j.letter;
    if (capBox) { capBox.hidden = !j.caption; capT.value = j.caption || ''; }
    var list = (mode === 'card' ? j.slides : j.scenes) || [], keep = slides[0] && slides[0].media;
    slides = list.map(function (p) {
      var o = blank(); o.design = p.design; o.tag = j.tag || o.tag; o.title = p.title || ''; o.sub = p.sub || ''; o.items = p.items || ''; o.media = null;
      if (mode === 'reel') { o.start = 0; o.dur = p.dur || 4; o.end = o.dur; }
      return o;
    });
    return loadMedia(j).then(function (ms) {
      if (keep) ms.unshift(keep);
      slides.forEach(function (s, i) {
        if (!ms.length) return;
        var m = ms[i % ms.length]; s.media = m;
        if (m.kind === 'video') { s.start = Math.min(i * 3, Math.max(0, m.len - s.dur)); s.dur = Math.min(s.dur, Math.floor(m.len * 10) / 10); s.end = s.start + s.dur; seek(s); }
      });
      cur = 0; fill(); draw();
      var n = slides.length, miss = slides.filter(function (s) { return !s.media; }).length;
      say((mode === 'card' ? '카드 ' + n + '장을' : '장면 ' + n + '개를') + ' 짰어요. ' + (miss ? (mode === 'card' ? '사진 없는 장은 사진을 골라 넣어 주세요. ' : '사진·영상 없는 장면에 넣어 주세요. ') : '') + '글과 디자인은 자유롭게 고쳐도 돼요.' + (j.warn ? ' ' + j.warn : ''));
    });
  }
  function aiBuild(payload, fallback) {
    say('AI가 기사를 읽고 ' + (mode === 'card' ? '카드' : '장면') + '을 짜고 있어요. 10~20초쯤 걸려요.');
    return post(C.assist, JSON.stringify(Object.assign({act: mode === 'card' ? 'cards' : 'reel'}, payload)), 'application/json')
      .then(function (j) { if (!j.ok) throw new Error(j.error || '짜지 못했어요.'); return applyPlan(j); })
      .catch(function (e) { if (fallback) { fallback(); say(e.message + ' 기사 글을 그대로 넣었으니 다듬어 주세요.'); } else say(e.message); });
  }
  if (artSel) artSel.addEventListener('change', function () { var a = artOf(artSel.value); if (a) aiBuild({art: a.id}, function () { localFill(a); }); });
  var letSel = $('#mk-letter');
  if (letSel) letSel.addEventListener('change', function () {
    if (!letSel.value) return;
    if (artSel) artSel.value = '';
    letSel.disabled = true; aiBuild({letter: letSel.value}).then(function () { letSel.disabled = false; });
  });
  if (artSel && letSel) artSel.addEventListener('change', function () { if (artSel.value) letSel.value = ''; });
  var copyBtn = $('#mk-cap-copy');
  if (copyBtn) copyBtn.onclick = function () {
    var done = function () { copyBtn.textContent = '복사했어요'; setTimeout(function () { copyBtn.textContent = '캡션 복사'; }, 1600); };
    try { navigator.clipboard.writeText(capT.value).then(done, function () { capT.select(); document.execCommand('copy'); done(); }); }
    catch (e) { capT.select(); document.execCommand('copy'); done(); }
  };
  var srcBox = $('#mk-src'), aiBtn = $('#mk-ai');
  if (aiBtn) aiBtn.onclick = function () {
    var v = (srcBox.value || '').trim();
    if (v.replace(/\s/g, '').length < 100 && !/^https?:\/\//.test(v)) { say('기사 주소나 기사 글 전체를 붙여 넣어 주세요.'); return; }
    aiBtn.disabled = true; aiBuild({note: v}).then(function () { aiBtn.disabled = false; });
  };

  // 받기·만들기
  function blobOf(c) { return new Promise(function (ok) { c.toBlob(ok, 'image/png'); }); }
  $('#mk-go').onclick = function () {
    var btn = this;
    fontsFor(texts()).then(function () {
      if (mode === 'card') {
        var stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
        return slides.reduce(function (p, s, i) {
          return p.then(function () {
            var c = document.createElement('canvas'); c.width = 1080; c.height = 1350; paint(c.getContext('2d'), s, i);
            return blobOf(c).then(function (b) { var a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = 'soboru-card-' + stamp + '-' + (i + 1) + '.png'; document.body.appendChild(a); a.click(); a.remove(); return new Promise(function (r) { setTimeout(r, 350); }); });
          });
        }, Promise.resolve()).then(function () { say('카드 ' + slides.length + '장을 내려받았어요.'); });
      }
      var miss = slides.findIndex(function (s) { return !s.media || !s.media.url; });
      if (miss >= 0) { say((miss + 1) + '번 장면에 사진이나 영상을 넣어 주세요.'); return; }
      var c = document.createElement('canvas'); c.width = 1080; c.height = 1920; var x = c.getContext('2d');
      var scenes = slides.map(function (s, i) { x.clearRect(0, 0, 1080, 1920); REEL[s.design](x, s); return {media: s.media.url, layout: s.design, start: s.start || 0, dur: s.dur || 4, slow: !!s.slow, png: c.toDataURL('image/png')}; });
      x.clearRect(0, 0, 1080, 1920); REEL.outro(x, fromLetter);
      btn.disabled = true; say('릴스를 만들고 있어요. 1~3분쯤 걸려요. 이 화면을 닫지 말아 주세요.');
      return post(C.render, JSON.stringify({scenes: scenes, outro: c.toDataURL('image/png')}), 'application/json').then(function (j) {
        if (!j.ok) throw new Error(j.error || '만들지 못했어요.');
        return new Promise(function (ok, no) {
          (function poll() {
            fetch(C.status + '?job=' + encodeURIComponent(j.job), {credentials: 'same-origin'}).then(function (r) { return r.json(); }).then(function (st) {
              if (st.state === 'done') ok(st.url); else if (st.state === 'error') no(new Error('영상을 만들지 못했어요. 영상 길이와 시작 시간을 확인해 주세요.')); else setTimeout(poll, 2500);
            }, function () { setTimeout(poll, 4000); });
          })();
        });
      }).then(function (url) {
        var out = $('#mk-out'); out.hidden = false;
        $('#mk-out-v').src = url; $('#mk-out-dl').href = url; $('#mk-out-url').value = url;
        say('릴스를 만들었어요. 내려받아 인스타그램에 올리거나 매거진 릴스 칸에 올려 보세요.');
      });
    }).catch(function (e) { say(e.message); }).then(function () { btn.disabled = false; });
  };

  slides = [blank()];
  if (mode === 'reel') { slides[0].tag = '블랙박스 이슈'; slides[0].title = '제목을\n두 줄로'; slides[0].sub = ': 한 줄 부제'; slides[0].items = '#11월 3일 오후 2시께\n운전자 A씨 : “피할 수 없었다”'; }
  else { slides[0].tag = 'FOOD'; slides[0].title = '제목은 짧게,\n두 줄이 좋아요'; }
  logo.onload = function () { logoW = logoK = null; draw(); };
  fill(); draw();
})();
