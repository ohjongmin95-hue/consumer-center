/* 카드뉴스·릴스 만들기 (운영자 2026-11-05) — mag_maker.py, templates/mag_admin_maker.html
   글씨·디자인은 이 파일이 canvas로 그림. 카드뉴스는 PNG로 바로 받고, 릴스는 장면별 글씨 판(투명 PNG)을 서버로 보내 ffmpeg가 영상과 겹침.
   디자인: 릴스 wide(이슈 와이드)·full(풀스크린 뉴스)·chat(채팅 스레드)·quote(인용 클로즈업)·clean(클린 포토)
           카드: 디자인(모든 장) soboru·ref·newneek·magazine·poster·clean·dark × 장 역할 cover·body·quote·last (소보루 카드뉴스 원칙, 운영자 2026-11-05)
   줄 쓰는 법: '#글' 흰 상자, '!글' 귤색 상자, '이름 : 말' 이름 굵게 말풍선, 나머지는 말풍선. **굵게** */
(function () {
  'use strict';
  var C = window.MAKER_CFG || {};
  var OR = '#EF920E', ORD = '#CE6719', BR = '#652D1C', FONT = '"Pretendard Variable", Pretendard, -apple-system, sans-serif';
  var CAT = {'쇼핑': 'SHOPPING', '뷰티': 'BEAUTY', '음식': 'FOOD', '생활': 'LIFE', '금융': 'MONEY', '통신': 'TELECOM', '여행': 'TRAVEL', '자동차': 'CAR', '리콜': 'RECALL'};
  var LAY = {wide: ['blur', [0, 620, 1080, 608]], full: ['cover', null], chat: ['#15120f', [60, 460, 960, 540]], quote: ['blur', null], clean: ['cover', null]};
  var REEL_D = [['wide', '이슈 와이드'], ['full', '풀스크린 뉴스'], ['chat', '채팅 스레드'], ['quote', '인용 클로즈업'], ['clean', '클린 포토']];
  var CARD_D = [['cover', '표지'], ['body', '본문'], ['quote', '인용'], ['last', '마무리 (저장)']];
  var OLD_ROLE = {clean: 'cover', text: 'body'};
  var $ = function (s, r) { return (r || document).querySelector(s); };

  // ---- 글꼴·로고 ----------------------------------------------------------------------------
  var logo = new Image(); logo.src = C.logo;
  var logoW = null, logoK = null;
  function tint(color) {
    var c = document.createElement('canvas'); c.width = logo.naturalWidth; c.height = logo.naturalHeight;
    var x = c.getContext('2d'); x.drawImage(logo, 0, 0); x.globalCompositeOperation = 'source-in'; x.fillStyle = color; x.fillRect(0, 0, c.width, c.height); return c;
  }
  // 로고는 늘 진짜 SOBORU 로고체 그림(static/img/soboru-wordmark.png)만 씀 — 글꼴로 SOBORU를 치지 않음 (운영자 2026-11-05 '로고 똑바로')
  // 큰 그림을 한 번에 작게 줄이면 획이 가늘고 거칠어져서, 반씩 여러 번 줄여 둔 판을 씀
  var logoCache = {};
  function logoAt(color, h) {
    var key = color + h; if (logoCache[key]) return logoCache[key];
    var src = color === 'brown' ? logo : (color === 'white' ? (logoW = logoW || tint('#fff')) : (logoK = logoK || tint('#111')));
    var w = src.naturalWidth || src.width, ht = src.naturalHeight || src.height, cur = src;
    while (ht / 2 >= h * 2) {
      var c = document.createElement('canvas'); c.width = Math.round(w / 2); c.height = Math.round(ht / 2);
      var x = c.getContext('2d'); x.imageSmoothingQuality = 'high'; x.drawImage(cur, 0, 0, c.width, c.height); cur = c; w = c.width; ht = c.height;
    }
    return (logoCache[key] = cur);
  }
  function drawLogo(ctx, color, x, y, h, align) {
    if (!logo.complete || !logo.naturalWidth) return;
    var src = logoAt(color, h), w = h * logo.naturalWidth / logo.naturalHeight;
    ctx.save(); ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(src, align === 'right' ? x - w : align === 'center' ? x - w / 2 : x, y, w, h);
    ctx.restore();
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
  // 운영자 2026-11-05: 소보루 카드뉴스 원칙(캐러셀 레퍼런스북) + 디자인 여러 개 — 예전 '민주의 카드뉴스' 프로그램의 디자인(레퍼런스북식·뉴닉식·매거진·포스터·깔끔·다크)도 고름.
  // 장 역할: cover 표지(고른 문구 + 큰 숫자) / body 본문(꼬리표·제목·글·큰 숫자) / quote 인용 / last 마무리(챙길 것 3개 + 저장 유도 + 출처)
  // 글자는 가운데 70% 안(x 90~990, y 110~1240). 로고·쪽 번호만 그 밖.
  var X = 90, TW = 900, Y1 = 1240;
  var THEME_D = [['soboru', '소보루 매거진', '꽉 찬 사진 · 흰 속 장'], ['ref', '레퍼런스북식', '큰 숫자 · 형광펜 제목'], ['newneek', '뉴닉식', '사진 위 제목 상자'],
                 ['magazine', '매거진', '위 사진 · 아래 흰 판'], ['poster', '포스터', '꽉 찬 귤색 · 큰 글씨'], ['clean', '깔끔', '흰 바탕 · 둥근 사진'], ['dark', '다크', '어두운 사진 · 흰 글씨'], ['center', '센터 포토', '사진 꽉 · 가운데 큰 제목']];
  function bg(ctx, c) { ctx.fillStyle = c; ctx.fillRect(0, 0, 1080, 1350); }
  function full(ctx, img, empty) { bg(ctx, empty); if (img) cover(ctx, img, 0, 0, 1080, 1350); }
  function photo(ctx, img, x, y, w, h, r, empty) {
    if (h < 160 || (!img && !empty)) return;
    ctx.save(); rrect(ctx, x, y, w, h, r || 0); ctx.clip();
    if (img) cover(ctx, img, x, y, w, h); else { ctx.fillStyle = empty; ctx.fillRect(x, y, w, h); }
    ctx.restore();
  }
  function paras(t) { return String(t || '').split('\n').map(function (x) { return x.trim(); }).filter(Boolean); }
  function TT(ctx, t, size, w) { return layout(ctx, t, size, 800, 800, w || TW, {lh: 1.24, ls: -3}); }
  function BT(ctx, t, size, w) { return layout(ctx, paras(t).join('\n\n'), size || 38, 500, 800, w || TW, {lh: 1.6, ls: -1}); }
  function lineOf(T, i) { return {lines: [T.lines[i]], width: [T.width[i]], lh: T.lh, size: T.size, w0: T.w0, w1: T.w1, ls: T.ls}; }
  // 제목: 마지막 줄만 다른 색 또는 형광펜
  function title2(ctx, T, x, y, c1, c2, mark) {
    T.lines.forEach(function (ln, i) {
      var last = i === T.lines.length - 1 && T.lines.length > 1;
      if (last && mark) { ctx.fillStyle = mark; ctx.fillRect(x - 6, y + i * T.lh + T.size * 0.55, T.width[i] + 12, T.size * 0.45); }
      drawText(ctx, lineOf(T, i), x, y + i * T.lh, last && c2 ? c2 : c1);
    });
    return textH(T);
  }
  function fitSize(ctx, text, max, w) { ctx.font = F(900, 100); var k = ctx.measureText(text).width / 100; return Math.max(40, Math.min(max, Math.floor(w / Math.max(k, 0.1)))); }
  function bigNum(ctx, text, x, y, max, color, boxBg) {  // 크게 박은 숫자 하나. 높이를 돌려줌
    if (!text) return 0;
    var sz = fitSize(ctx, text, max, TW - (boxBg ? 60 : 0));
    ctx.font = F(900, sz); ctx.letterSpacing = '-3px'; var w = ctx.measureText(text).width;
    if (boxBg) { ctx.fillStyle = boxBg; rrect(ctx, x, y, w + 60, sz + 44, 22); ctx.fill(); ctx.fillStyle = color; ctx.fillText(text, x + 30, y + sz * 0.92 + 22); ctx.letterSpacing = '0px'; return sz + 44; }
    ctx.fillStyle = color; ctx.fillText(text, x, y + sz * 0.92); ctx.letterSpacing = '0px'; return sz;
  }
  function pill(ctx, text, x, y, fg, bgc, size) {
    if (!text) return 0;
    size = size || 28; ctx.font = F(800, size); var w = ctx.measureText(text).width;
    ctx.fillStyle = bgc; rrect(ctx, x, y, w + 36, size + 24, 14); ctx.fill();
    ctx.fillStyle = fg; ctx.fillText(text, x + 18, y + size + 6); return size + 24;
  }
  function pageNo(ctx, n, N, color) { if (N < 2) return; ctx.font = F(700, 26); ctx.fillStyle = color; ctx.textAlign = 'right'; ctx.fillText(n + ' / ' + N, 990, 76); ctx.textAlign = 'left'; }
  function brandFoot(ctx, color, n, N, ink) { drawLogo(ctx, color, X, 1272, 34); if (N > 1) { ctx.font = F(700, 26); ctx.fillStyle = ink; ctx.textAlign = 'right'; ctx.fillText(n + ' / ' + N, 990, 1300); ctx.textAlign = 'left'; } }
  // 본문 글이 아래 선을 넘으면 글씨를 줄임
  function fitBody(ctx, t, size, w, maxH) { var B; for (var z = size; z >= 28; z -= 2) { B = BT(ctx, t, z, w); if (textH(B) <= maxH) return B; } return B; }
  // 마무리 장: 챙길 것 3개 + 저장 유도(형광펜) + 출처 — 색만 디자인마다
  function lastPage(ctx, s, n, N, P) {
    bg(ctx, P.bg); if (P.deco) P.deco(ctx);
    if (P.top) { drawLogo(ctx, P.logo, 540, 46, 38, 'center'); pageNo(ctx, n, N, P.sub); } else brandFoot(ctx, P.logo, n, N, P.sub);
    // 맺음말(형광펜)을 위에 크게, 그 아래 챙길 것 카드 — 묶음 전체를 세로 가운데에 (빈자리 없게)
    var E = TT(ctx, s.title || '헷갈리면 저장해 두세요', 88);
    var tips = paras(s.items).slice(0, 4).map(function (tip) { var T = layout(ctx, tip, 46, 700, 900, TW - 150, {lh: 1.4, ls: -1}); return {T: T, h: Math.max(150, textH(T) + 70)}; });
    var total = 56 + 40 + textH(E) + 64 + tips.reduce(function (a, t) { return a + t.h + 26; }, 0) - 26;
    var y = Math.max(150, (Y1 - 50 - total) / 2 + 40);
    y += pill(ctx, s.tag || '이것만 챙겨요', X, y, P.kickInk, P.kick, 32) + 40;
    E.lines.forEach(function (ln, i) { ctx.fillStyle = P.mark; ctx.fillRect(X - 8, y + i * E.lh + E.size * 0.55, E.width[i] + 16, E.size * 0.48); });
    y += title2(ctx, E, X, y, P.end, P.end, null) + 64;
    tips.forEach(function (t, k) {
      var h = t.h;
      ctx.fillStyle = P.card; rrect(ctx, X, y, TW, h, 28); ctx.fill();
      if (P.cardLine) { ctx.lineWidth = 3; ctx.strokeStyle = P.cardLine; ctx.stroke(); }
      ctx.fillStyle = P.num; ctx.beginPath(); ctx.arc(X + 62, y + h / 2, 34, 0, 7); ctx.fill();
      ctx.font = F(900, 36); ctx.fillStyle = P.numInk; ctx.textAlign = 'center'; ctx.fillText(String(k + 1), X + 62, y + h / 2 + 13); ctx.textAlign = 'left';
      drawText(ctx, t.T, X + 120, y + h / 2 - textH(t.T) / 2, P.tip); y += h + 26;
    });
    if (s.sub) { ctx.font = F(700, 26); ctx.fillStyle = P.sub; ctx.fillText(s.sub, X, Y1); }
  }
  // 인용 장 (밝은 바탕·어두운 바탕)
  function quotePage(ctx, s, img, n, N, P) {
    bg(ctx, P.bg);
    if (img && P.blur) { ctx.save(); ctx.filter = 'blur(12px) brightness(.35)'; cover(ctx, img, -40, -40, 1160, 1430); ctx.restore(); }
    drawLogo(ctx, P.logo, 540, 46, 38, 'center'); pageNo(ctx, n, N, P.sub);
    var T = layout(ctx, s.title, 88, 900, 900, TW, {lh: 1.28, ls: -4}), y = Math.max(420, (1350 - textH(T) - 100) / 2 + 40);
    ctx.font = F(900, 240); ctx.fillStyle = OR; ctx.fillText('“', X - 10, y - 50);
    y += drawText(ctx, T, X, y, P.ink, {mark: OR, markInk: '#111'});
    if (s.sub) { ctx.font = F(700, 42); ctx.fillStyle = P.sub; ctx.fillText('— ' + s.sub, X, Math.min(y + 80, Y1)); }
  }
  // 아래에서부터 쌓는 글 묶음(꼬리표 → 큰 숫자 → 제목 → 본문)의 높이와 그리기
  function stackUp(ctx, s, o) {
    var T = TT(ctx, s.title, o.tsize, TW);
    var nh = s.sub && o.num ? fitSize(ctx, s.sub, o.nmax || 120, TW) + 24 : 0;
    var head = (s.tag ? 76 : 0) + nh + textH(T), B = null;
    if (paras(s.items).length) {
      // 글만 있는 본문(사진 없음)은 빈자리가 남지 않게 글씨를 남은 높이에 맞춰 키움 (운영자 2026-11-05: 본문이 휑하면 안 됨)
      if (o.avail) { for (var z = 52; z >= 34; z -= 2) { B = BT(ctx, s.items, z, TW); if (head + 44 + textH(B) <= o.avail) break; } }
      else B = fitBody(ctx, s.items, o.bsize || 38, TW, o.bmax || 330);
    }
    var gap = o.avail ? 44 : 28, h = head + (B ? gap + textH(B) : 0);
    return {h: h, at: function (top) { return top + Math.max(0, (o.avail - h) * 0.3); }, draw: function (y) {
      if (s.tag) { if (o.kickPill) pill(ctx, s.tag, X, y, o.kickInk, o.kickPill); else { ctx.font = F(800, 30); ctx.letterSpacing = '3px'; ctx.fillStyle = o.kick; ctx.fillText(s.tag, X, y + 30); ctx.letterSpacing = '0px'; } y += 76; }
      if (nh) { bigNum(ctx, s.sub, X, y, o.nmax || 120, o.num); y += nh; }
      y += title2(ctx, T, X, y, o.ink, o.ink2, o.mark);
      if (B) { y += gap; drawText(ctx, B, X, y, o.body, {boldColor: o.bold || ORD}); }
    }};
  }

  var CARD = {};
  // 0) 소보루 매거진 (기본): 표지 = 꽉 찬 사진 + 아래 흰 큰 제목 / 본문 = 따뜻한 흰 바탕 / 인용 = 검은 바탕
  CARD.soboru = {
    cover: function (ctx, s, img, n, N) {
      full(ctx, img, '#3a2a20'); grad(ctx, 0, 260, .3, 0); grad(ctx, 480, 1350, 0, .82);
      drawLogo(ctx, 'white', 540, 46, 38, 'center'); pageNo(ctx, n, N, 'rgba(255,255,255,.85)');
      var T = TT(ctx, s.title, 84), y = Y1 - textH(T);
      shadowed(ctx, function () { drawText(ctx, T, X, y, '#fff'); });
      if (s.sub) { var sz = fitSize(ctx, s.sub, 64, TW - 60) + 44; bigNum(ctx, s.sub, X, y - sz - 28, 64, '#fff', OR); y -= sz + 28; }
      if (s.tag) { ctx.font = F(800, 26); ctx.letterSpacing = '4px'; ctx.fillStyle = 'rgba(255,255,255,.92)'; ctx.fillText(s.tag, X + 4, y - 24); ctx.letterSpacing = '0px'; }
    },
    body: function (ctx, s, img, n, N) {
      bg(ctx, '#FAFAF7'); drawLogo(ctx, 'brown', 540, 46, 38, 'center'); pageNo(ctx, n, N, ORD);
      var st = stackUp(ctx, s, {tsize: img ? 60 : 72, kick: ORD, num: OR, ink: '#111', body: '#2a2a2a', avail: img ? 0 : Y1 - 160}), y = img ? 160 : st.at(160);
      if (img && Y1 - 60 - st.h - y >= 300) { photo(ctx, img, X, y, TW, Math.min(500, Y1 - 60 - st.h - y), 0); y += Math.min(500, Y1 - 60 - st.h - y) + 50; }
      st.draw(y);
      ctx.fillStyle = '#111'; ctx.fillRect(X, 1264, TW, 2);
      ctx.font = F(700, 26); ctx.fillStyle = ORD; ctx.fillText('소보루 매거진', X, 1306); ctx.textAlign = 'right'; ctx.fillText('soboru.co.kr', 990, 1306); ctx.textAlign = 'left';
    },
    quote: function (ctx, s, img, n, N) { quotePage(ctx, s, img, n, N, {bg: '#000', blur: true, logo: 'white', ink: '#fff', sub: '#eee'}); },
    last: function (ctx, s, img, n, N) { lastPage(ctx, s, n, N, {bg: '#FAFAF7', top: true, logo: 'brown', sub: ORD, kick: OR, kickInk: '#fff', card: '#fff', cardLine: '#EADFCF', num: OR, numInk: '#fff', tip: '#111', end: '#111', mark: '#FFD99E'}); }
  };
  // 1) 레퍼런스북식: 표지 = 사진 + 흰 상자 속 큰 숫자 + 형광펜 제목 / 본문 = 꼬리표 '02 · 언제부터' · 큰 숫자 · 둥근 사진 · 제목 / 마무리 = 노란 바탕
  CARD.ref = {
    cover: function (ctx, s, img, n, N) {
      full(ctx, img, OR); grad(ctx, 400, 1350, 0, .82);
      shadowed(ctx, function () { drawLogo(ctx, 'white', X, 96, 40); }); if (s.tag) pill(ctx, s.tag, X + 40 * logo.naturalWidth / Math.max(1, logo.naturalHeight) + 20, 92, '#fff', 'rgba(0,0,0,.32)'); pageNo(ctx, n, N, '#fff');
      var T = TT(ctx, s.title, 90), y = Y1 - textH(T);
      title2(ctx, T, X, y, '#fff', '#fff', OR);
      if (s.sub) { var h = fitSize(ctx, s.sub, 72, TW - 60) + 44; bigNum(ctx, s.sub, X, y - h - 30, 72, OR, '#fff'); }
    },
    body: function (ctx, s, img, n, N) {
      bg(ctx, '#F6F1EA'); var lab = String(n).padStart(2, '0') + (s.tag ? ' · ' + s.tag : '');
      pill(ctx, lab, X, 96, '#fff', '#3A2E25'); pageNo(ctx, n, N, '#8A6F5A');
      var st = stackUp(ctx, Object.assign({}, s, {tag: ''}), {tsize: img ? 70 : 78, num: OR, nmax: 150, ink: '#191512', mark: '#FFD99E', body: '#4E4237', avail: img ? 0 : Y1 - 200}), top = 200, ph = Y1 - st.h - 50 - top;
      if (img && ph >= 220) photo(ctx, img, X, top, TW, ph, 36);
      st.draw(img ? Y1 - st.h : st.at(200)); drawLogo(ctx, 'brown', X, 1272, 34);
    },
    quote: function (ctx, s, img, n, N) { quotePage(ctx, s, img, n, N, {bg: '#F6F1EA', logo: 'brown', ink: '#191512', sub: '#8A6F5A'}); },
    last: function (ctx, s, img, n, N) { lastPage(ctx, s, n, N, {bg: '#FFDF6B', logo: 'black', sub: '#5C4A00', kick: '#191512', kickInk: '#fff', card: '#fff', num: OR, numInk: '#fff', tip: '#191512', end: '#191512', mark: '#fff'}); }
  };
  // 2) 뉴닉식: 사진을 꽉 채우고 위쪽을 크림으로 흐리게, 제목은 줄마다 귤색 상자(갈색 테두리)
  function boxes(ctx, t, size, y) {
    var T = TT(ctx, t, size, TW - 40), h = Math.round(size * 1.42);
    T.lines.forEach(function (ln, i) {
      var w = T.width[i] + size * 0.72; ctx.fillStyle = OR; rrect(ctx, X, y, w, h, 10); ctx.fill(); ctx.lineWidth = 3; ctx.strokeStyle = BR; ctx.stroke();
      drawText(ctx, lineOf(T, i), X + size * 0.36, y + (h - size * 1.24) / 2, BR); y += h + 12;
    });
    return y - 12;
  }
  function boxesH(ctx, t, size) { var n = TT(ctx, t, size, TW - 40).lines.length; return n * (Math.round(size * 1.42) + 12) - 12; }
  function creamFade(ctx, to, c) { var g = ctx.createLinearGradient(0, 0, 0, Math.min(to + 260, 1350)); g.addColorStop(0, c); g.addColorStop(Math.min(.95, to / (to + 260)), c); g.addColorStop(1, 'rgba(255,246,230,0)'); ctx.fillStyle = g; ctx.fillRect(0, 0, 1080, Math.min(to + 260, 1350)); }
  CARD.newneek = {
    head: function (ctx, t) { ctx.fillStyle = OR; ctx.beginPath(); ctx.arc(X + 10, 112, 10, 0, 7); ctx.fill(); ctx.font = F(800, 30); ctx.fillStyle = '#4A3A30'; ctx.fillText(t || '', X + 34, 123); },
    cover: function (ctx, s, img, n, N) {
      full(ctx, img, '#F6EBDA');
      var y0 = 170, y = y0 + boxesH(ctx, s.title, 70), nh = s.sub ? fitSize(ctx, s.sub, 56, TW - 60) + 44 : 0;
      creamFade(ctx, y + 40 + nh, '#FFF6E6'); this.head(ctx, s.tag); pageNo(ctx, n, N, '#8A6F5A');
      y = boxes(ctx, s.title, 70, y0); if (s.sub) bigNum(ctx, s.sub, X, y + 30, 56, BR, '#fff');
      shadowed(ctx, function () { brandFoot(ctx, img ? 'white' : 'brown', n, 0, BR); });
    },
    body: function (ctx, s, img, n, N) {
      full(ctx, img, '#F6EBDA');
      var th = boxesH(ctx, s.title, img ? 58 : 66), room = Y1 - 210 - th - (s.sub ? 140 : 0), B = null;
      if (paras(s.items).length) { if (img) B = fitBody(ctx, s.items, 38, TW, 420); else for (var z = 52; z >= 34; z -= 2) { B = BT(ctx, s.items, z, TW); if (textH(B) <= room) break; } }
      var est = 170 + th + (B ? 40 + textH(B) : 0) + (s.sub ? 140 : 0);
      creamFade(ctx, est, '#FFF6E6'); this.head(ctx, s.tag); pageNo(ctx, n, N, '#8A6F5A');
      var y = boxes(ctx, s.title, img ? 58 : 66, 170) + 44;
      if (B) y += drawText(ctx, B, X, y, '#4A3A30', {boldColor: ORD}) + 24;
      if (s.sub) bigNum(ctx, s.sub, X, y, 80, OR);
      shadowed(ctx, function () { brandFoot(ctx, img ? 'white' : 'brown', n, 0, BR); });
    },
    quote: function (ctx, s, img, n, N) { quotePage(ctx, s, img, n, N, {bg: '#FFF6E6', logo: 'brown', ink: BR, sub: '#8A6F5A'}); },
    last: function (ctx, s, img, n, N) { lastPage(ctx, s, n, N, {bg: '#FFF6E6', logo: 'brown', sub: '#8A6F5A', kick: OR, kickInk: '#fff', card: '#fff', cardLine: '#F1D3A6', num: OR, numInk: '#fff', tip: '#4A3A30', end: BR, mark: '#F8D59F'}); }
  };
  // 3) 매거진: 위쪽 큰 사진, 아래 흰 판(둥근 위 모서리)에 큰 제목 — 마지막 줄 귤색
  CARD.magazine = {
    panel: function (ctx, img, top, c) { photo(ctx, img, 0, 0, 1080, top + 60, 0, '#EFE4D4'); ctx.fillStyle = c || '#fff'; rrect(ctx, 0, top, 1080, 1350 - top, [48, 48, 0, 0]); ctx.fill(); },
    cover: function (ctx, s, img, n, N) {
      var st = stackUp(ctx, s, {tsize: 84, kick: OR, num: OR, nmax: 90, ink: '#191512', ink2: OR, body: '#4E4237'}), top = Math.min(Y1 - st.h - 70, 760);
      this.panel(ctx, img, top); st.draw(top + 70); pageNo(ctx, n, N, '#fff'); brandFoot(ctx, 'brown', n, 0, BR);
    },
    body: function (ctx, s, img, n, N) {
      var st = stackUp(ctx, s, {tsize: img ? 64 : 76, kick: OR, num: OR, nmax: 110, ink: '#191512', body: '#4E4237', avail: img ? 0 : Y1 - 150}), top = img ? Math.max(Math.min(Y1 - st.h - 70, 640), 260) : st.at(150) - 70;
      if (img) this.panel(ctx, img, top); else bg(ctx, '#fff');
      ctx.font = F(900, 130); ctx.fillStyle = 'rgba(239,146,14,.16)'; ctx.textAlign = 'right'; ctx.fillText(String(n).padStart(2, '0'), 990, top + 140); ctx.textAlign = 'left';
      st.draw(top + 70); pageNo(ctx, n, N, '#fff'); brandFoot(ctx, 'brown', n, 0, BR);
    },
    quote: function (ctx, s, img, n, N) { quotePage(ctx, s, img, n, N, {bg: '#fff', logo: 'brown', ink: '#191512', sub: '#8A6F5A'}); },
    last: function (ctx, s, img, n, N) { lastPage(ctx, s, n, N, {bg: '#fff', logo: 'brown', sub: '#8A6F5A', kick: '#191512', kickInk: '#fff', card: '#F7F3EC', num: OR, numInk: '#fff', tip: '#333', end: '#191512', mark: '#FFD99E'}); }
  };
  // 4) 포스터: 표지는 귤색으로 꽉, 아주 큰 흰 글씨 + 동그란 사진 / 본문은 크림 바탕에 큰 번호
  CARD.poster = {
    cover: function (ctx, s, img, n, N) {
      bg(ctx, OR); pageNo(ctx, n, N, '#fff');
      ctx.font = F(800, 32); ctx.fillStyle = '#fff'; ctx.fillText(s.tag || '', X, 150);
      var T = TT(ctx, s.title, 104), y = 220; y += title2(ctx, T, X, y, '#fff', BR);
      if (s.sub) y += bigNum(ctx, s.sub, X, y + 30, 64, BR, '#fff') + 30;
      var r = Math.max(150, Math.min(300, (Y1 - y - 40) / 2)), cx = 990 - r, cy = Math.max(y + 40 + r, Y1 - r);
      ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.clip(); if (img) cover(ctx, img, cx - r, cy - r, 2 * r, 2 * r); else { ctx.fillStyle = 'rgba(255,255,255,.22)'; ctx.fill(); } ctx.restore();
      ctx.lineWidth = 12; ctx.strokeStyle = '#fff'; ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.stroke();
      drawLogo(ctx, 'white', X, 1272, 34);
    },
    body: function (ctx, s, img, n, N) {
      bg(ctx, '#FFF1DE'); pageNo(ctx, n, N, BR);
      ctx.font = F(900, 260); ctx.fillStyle = 'rgba(239,146,14,.18)'; ctx.textAlign = 'right'; ctx.fillText(String(n).padStart(2, '0'), 1010, 300); ctx.textAlign = 'left';
      var st = stackUp(ctx, s, {tsize: img ? 76 : 84, kick: OR, num: OR, nmax: 130, ink: BR, body: '#4A3A30', avail: img ? 0 : Y1 - 170}); st.draw(img ? 170 : st.at(170));
      var top = 170 + st.h + 50; if (img && Y1 - top >= 240) photo(ctx, img, X, top, TW, Y1 - top, 40);
      drawLogo(ctx, 'brown', X, 1272, 34);
    },
    quote: function (ctx, s, img, n, N) { quotePage(ctx, s, img, n, N, {bg: '#FFF1DE', logo: 'brown', ink: BR, sub: '#8A6F5A'}); },
    last: function (ctx, s, img, n, N) { lastPage(ctx, s, n, N, {bg: OR, logo: 'white', sub: '#fff', kick: BR, kickInk: '#fff', card: '#fff', num: BR, numInk: '#fff', tip: '#333', end: '#fff', mark: BR}); }
  };
  // 5) 깔끔: 흰 바탕, 작은 꼬리표, 큰 검은 제목(마지막 줄 귤색), 아래 둥근 사진 카드
  CARD.clean = {
    cover: function (ctx, s, img, n, N) {
      bg(ctx, '#fff'); pageNo(ctx, n, N, ORD);
      var st = stackUp(ctx, s, {tsize: 88, kickPill: '#FFF1DE', kickInk: ORD, num: OR, nmax: 90, ink: '#191512', ink2: OR, body: '#4E4237'}); st.draw(140);
      var top = Math.max(140 + st.h + 56, 560); photo(ctx, img, X, top, TW, Y1 - top, 44, '#FFF1DE'); brandFoot(ctx, 'brown', n, 0, BR);
    },
    body: function (ctx, s, img, n, N) {
      bg(ctx, '#fff'); pageNo(ctx, n, N, ORD);
      var st = stackUp(ctx, s, {tsize: img ? 70 : 80, kickPill: '#FFF1DE', kickInk: ORD, num: OR, nmax: 120, ink: '#191512', body: '#4E4237', avail: img ? 0 : Y1 - 140}); st.draw(img ? 140 : st.at(140));
      var top = 140 + st.h + 50; if (img && Y1 - top >= 240) photo(ctx, img, X, top, TW, Y1 - top, 44); brandFoot(ctx, 'brown', n, 0, BR);
    },
    quote: function (ctx, s, img, n, N) { quotePage(ctx, s, img, n, N, {bg: '#fff', logo: 'brown', ink: '#191512', sub: ORD}); },
    last: function (ctx, s, img, n, N) { lastPage(ctx, s, n, N, {bg: '#fff', logo: 'brown', sub: ORD, kick: '#FFF1DE', kickInk: ORD, card: '#FFF6EA', num: OR, numInk: '#fff', tip: '#333', end: '#191512', mark: '#FFD99E'}); }
  };
  // 7) 센터 포토 (운영자 2026-11-05, 영상 매거진 표지처럼): 사진 꽉 + 위 가운데 SOBORU 로고·쪽 점 + 가운데 작은 꼬리표·큰 흰 제목·부제
  function dots(ctx, n, N, on, off) {
    if (N < 2) return; var w = 10, gap = 10, cur = 34, tw = (N - 1) * (w + gap) + cur, x = 540 - tw / 2;
    for (var i = 1; i <= N; i++) { var ww = i === n ? cur : w; ctx.fillStyle = i === n ? on : off; rrect(ctx, x, 104, ww, 10, 5); ctx.fill(); x += ww + gap; }
  }
  function centerStack(ctx, s, o) {
    var T = TT(ctx, s.title, o.tsize, TW), S = s.sub ? layout(ctx, s.sub, o.ssize || 40, 600, 800, TW, {lh: 1.4, ls: -1}) : null;
    var B = o.avail && paras(s.items).length ? (function () { var b; for (var z = 50; z >= 34; z -= 2) { b = layout(ctx, paras(s.items).join('\n\n'), z, 500, 800, TW, {lh: 1.6, ls: -1}); if (90 + textH(T) + (S ? 30 + textH(S) : 0) + 50 + textH(b) <= o.avail) break; } return b; })() : null;
    var h = (s.tag ? 90 : 0) + textH(T) + (S ? 30 + textH(S) : 0) + (B ? 50 + textH(B) : 0);
    return {h: h, draw: function (y) {
      if (s.tag) { ctx.font = F(800, 28); var w = ctx.measureText(s.tag).width + 40; ctx.fillStyle = o.pill; rrect(ctx, 540 - w / 2, y, w, 52, 26); ctx.fill(); ctx.fillStyle = o.pillInk; ctx.textAlign = 'center'; ctx.fillText(s.tag, 540, y + 36); ctx.textAlign = 'left'; y += 90; }
      var draw1 = function () { y += drawText(ctx, T, 540, y, o.ink, {align: 'center', boldColor: OR}); };
      if (o.shadow) shadowed(ctx, draw1); else draw1();
      if (S) { y += 30; var Sy = y; var d2 = function () { drawText(ctx, S, 540, Sy, o.sub, {align: 'center'}); }; if (o.shadow) shadowed(ctx, d2); else d2(); y += textH(S); }
      if (B) { y += 50; drawText(ctx, B, 540, y, o.body, {align: 'center', boldColor: o.bold || ORD}); }
    }};
  }
  CARD.center = {
    cover: function (ctx, s, img, n, N) {
      full(ctx, img, '#3a2a20'); grad(ctx, 0, 300, .35, 0); grad(ctx, 380, 1350, .05, .55);
      shadowed(ctx, function () { drawLogo(ctx, 'white', 540, 44, 40, 'center'); }); dots(ctx, n, N, OR, 'rgba(255,255,255,.55)');
      var st = centerStack(ctx, s, {tsize: 92, ssize: 42, ink: '#fff', sub: 'rgba(255,255,255,.92)', pill: 'rgba(255,255,255,.22)', pillInk: '#fff', shadow: true});
      st.draw(Math.min(Y1 - st.h, Math.max(560, 760 - st.h / 2)));
    },
    // 속 장 (운영자 2026-11-05 '앞이 깔끔하니까 여기도 깔끔하게'): 모든 장이 같은 머리(로고·점), 흰 바탕, 왼쪽 정렬 한 줄기 — 꼬리표 → 제목 → 짧은 귤색 선 → 글
    head: function (ctx, n, N) { bg(ctx, '#fff'); drawLogo(ctx, 'brown', 540, 44, 40, 'center'); dots(ctx, n, N, OR, '#EDE6DC'); },
    body: function (ctx, s, img, n, N) {
      this.head(ctx, n, N);
      var T = TT(ctx, s.title, 76, TW), top = 220, room = Y1 - top, B = null;
      var nh = s.sub ? fitSize(ctx, s.sub, 110, TW) + 30 : 0, head = (s.tag ? 70 : 0) + nh + textH(T) + 70;
      if (paras(s.items).length) for (var z = 46; z >= 34; z -= 2) { B = layout(ctx, paras(s.items).join('\n\n'), z, 500, 800, TW, {lh: 1.62, ls: -1}); if (head + textH(B) <= room) break; }
      var h = head + (B ? textH(B) : 0), y = top + Math.max(0, (room - h) * 0.42);
      if (s.tag) { ctx.font = F(800, 30); ctx.fillStyle = OR; ctx.fillText((n < 10 ? '0' : '') + n + '  ' + s.tag, X, y + 30); y += 70; }
      if (nh) { bigNum(ctx, s.sub, X, y, 110, OR); y += nh; }
      y += drawText(ctx, T, X, y, '#191512');
      ctx.fillStyle = OR; ctx.fillRect(X, y + 26, 56, 5); y += 70;
      if (B) drawText(ctx, B, X, y, '#3A2E25', {boldColor: ORD});
    },
    quote: function (ctx, s, img, n, N) {
      this.head(ctx, n, N);
      var T = layout(ctx, s.title, 80, 900, 900, TW, {lh: 1.32, ls: -4}), h = 150 + textH(T) + (s.sub ? 90 : 0), y = 220 + Math.max(0, (Y1 - 220 - h) / 2);
      ctx.font = F(900, 200); ctx.fillStyle = OR; ctx.fillText('“', X - 8, y + 150); y += 170;
      y += drawText(ctx, T, X, y, '#191512');
      if (s.sub) { ctx.font = F(700, 38); ctx.fillStyle = '#8A6F5A'; ctx.fillText('— ' + s.sub, X, y + 70); }
    },
    last: function (ctx, s, img, n, N) {
      this.head(ctx, n, N);
      var E = TT(ctx, s.title || '헷갈리면 저장해 두세요', 80), tips = paras(s.items).slice(0, 4).map(function (t) { return layout(ctx, t, 42, 600, 800, TW - 90, {lh: 1.42, ls: -1}); });
      var rows = tips.reduce(function (a, T) { return a + textH(T) + 64; }, 0), h = 70 + textH(E) + 60 + rows, y = 220 + Math.max(0, (Y1 - 60 - 220 - h) * 0.42);
      ctx.font = F(800, 30); ctx.fillStyle = OR; ctx.fillText(s.tag || '이것만 챙겨요', X, y + 30); y += 70;
      y += drawText(ctx, E, X, y, '#191512') + 60;
      tips.forEach(function (T, k) {
        ctx.fillStyle = '#EDE6DC'; ctx.fillRect(X, y, TW, 2);
        ctx.font = F(800, 40); ctx.fillStyle = OR; ctx.fillText(String(k + 1), X, y + 32 + 40);
        drawText(ctx, T, X + 70, y + 32, '#191512'); y += textH(T) + 64;
      });
      if (tips.length) { ctx.fillStyle = '#EDE6DC'; ctx.fillRect(X, y, TW, 2); }
      if (s.sub) { ctx.font = F(700, 26); ctx.fillStyle = '#8A6F5A'; ctx.fillText(s.sub, X, Y1); }
    }
  };
  // 6) 다크: 사진을 꽉 채우고 아래를 어둡게, 흰 글씨를 아래에
  CARD.dark = {
    shade: function (ctx, img) { full(ctx, img, '#201a16'); grad(ctx, 0, 600, .25, .35); grad(ctx, 600, 1350, .35, .92); },
    cover: function (ctx, s, img, n, N) {
      this.shade(ctx, img); pageNo(ctx, n, N, '#fff');
      var st = stackUp(ctx, s, {tsize: 88, kick: OR, num: OR, nmax: 100, ink: '#fff', ink2: OR, body: '#EDE6DD'}); st.draw(Y1 - st.h); drawLogo(ctx, 'white', 990, 1272, 34, 'right');
    },
    body: function (ctx, s, img, n, N) {
      this.shade(ctx, img); pageNo(ctx, n, N, '#fff');
      var st = stackUp(ctx, s, {tsize: img ? 66 : 78, kick: OR, num: OR, nmax: 120, ink: '#fff', body: '#EDE6DD', bold: '#FFB347', avail: img ? 0 : Y1 - 170}); st.draw(img ? Y1 - st.h : st.at(170)); drawLogo(ctx, 'white', 990, 1272, 34, 'right');
    },
    quote: function (ctx, s, img, n, N) { quotePage(ctx, s, img, n, N, {bg: '#000', blur: true, logo: 'white', ink: '#fff', sub: '#eee'}); },
    last: function (ctx, s, img, n, N) { lastPage(ctx, s, n, N, {bg: '#191512', logo: 'white', sub: '#CDBFB0', kick: OR, kickInk: '#fff', card: '#2A2420', num: OR, numInk: '#fff', tip: '#F2ECE4', end: '#fff', mark: ORD}); }
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
      : {design: slides.length ? 'body' : 'cover', tag: '', title: '', sub: '', items: '', media: null, scene: ''};
  }
  function size() { return mode === 'reel' ? [1080, 1920] : [1080, 1350]; }
  var deck = {theme: 'soboru', covers: []};
  try { var th0 = localStorage.getItem('mk-theme'); if (th0 && CARD[th0]) deck.theme = th0; } catch (e) {}
  function texts() { var a = []; slides.forEach(function (s) { a.push(s.tag, s.title, s.sub, s.items); }); deck.covers.forEach(function (c) { a.push(c.text); }); a.push('헷갈리면 저장해 두세요 이것만 챙겨요 소비자 뉴스 출처: 소보루 매거진 억울한 소비자 피해, 제보해 주세요 consumerjebo.co.kr — “ 0123456789/'); return a; }

  function paint(ctx, s, i, overlayOnly) {
    var wh = size(); ctx.clearRect(0, 0, wh[0], wh[1]);
    var el = s.media && s.media.el;
    if (mode === 'reel') {
      if (!overlayOnly) reelBase(ctx, s.design, el);
      REEL[s.design](ctx, s);
    } else {
      var role = OLD_ROLE[s.design] || s.design, th = CARD[deck.theme] || CARD.soboru;
      // 운영자 2026-11-05: 뉴닉처럼 이미지는 표지에만, 본문 장은 글만
      (th[role] || th.body).call(th, ctx, s, role === 'cover' ? el : null, i + 1, slides.length);
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
    var thBox = $('#mk-theme');
    if (thBox) thBox.innerHTML = THEME_D.map(function (d) { return '<label class="mk-chip mk-th-chip"><input type="radio" name="mk-t" value="' + d[0] + '"' + (deck.theme === d[0] ? ' checked' : '') + '><span><b>' + d[1] + '</b><small>' + d[2] + '</small></span></label>'; }).join('');
    var role = OLD_ROLE[s.design] || s.design, cv = $('#mk-covers');
    if (cv) {
      cv.hidden = !(mode === 'card' && role === 'cover' && deck.covers.length);
      $('#mk-cv').innerHTML = deck.covers.map(function (c, k) { return '<label class="mk-cv"><input type="radio" name="mk-cv" value="' + k + '"' + (c.text === s.title ? ' checked' : '') + '><span><small>' + esc(c.type || ('문구 ' + (k + 1))) + '</small>' + esc(c.text).replace(/\n/g, '<br>') + '</span></label>'; }).join('');
    }
    var sr = $('#mk-scene-row'); if (sr) sr.hidden = mode !== 'card' || role !== 'cover';
    var mf = $('#mk-file') && $('#mk-file').closest('label'); if (mf) mf.hidden = mode === 'card' && role !== 'cover';
    $('#mk-design').innerHTML = ds.map(function (d) { return '<label class="mk-chip"><input type="radio" name="mk-d" value="' + d[0] + '"' + (s.design === d[0] ? ' checked' : '') + '><span>' + d[1] + '</span></label>'; }).join('');
    form.querySelectorAll('[data-f]').forEach(function (el) { var k = el.dataset.f; if (el.type === 'checkbox') el.checked = !!s[k]; else el.value = s[k] == null ? '' : s[k]; });
    $('#mk-media-st').textContent = s.media ? (s.media.kind === 'video' ? '영상' : '사진') + ' 넣었어요' + (s.media.len ? ' (' + s.media.len.toFixed(1) + '초)' : '') : (mode === 'reel' ? '사진이나 영상을 골라 주세요' : '사진 고르기 (속 장은 비워도 돼요)');
    $('#mk-timing').hidden = mode !== 'reel';
    $('#mk-start-row').hidden = !(s.media && s.media.kind === 'video');
    $('#mk-n').textContent = (cur + 1) + ' / ' + slides.length;
    var lab = mode === 'reel' ? {tag: '태그', title: s.design === 'quote' ? '인용할 말' : '제목', sub: s.design === 'quote' ? '말한 사람' : '부제', items: '줄 (#흰 상자, !귤색 상자, 이름 : 말)'}
      : {cover: {tag: '분야', title: '표지 문구 (두 줄)', sub: '크게 박을 숫자 (예: 배달비 3,000원)', items: '(표지는 비워 두세요)'},
         body: {tag: '꼬리표 (예: 언제부터 · 누가 해당 · 내가 챙길 것)', title: '제목 (한 장에 메시지 하나)', sub: '크게 보여 줄 숫자 (비워도 돼요)', items: '글 2~3문장 (**굵게**는 귤색)'},
         quote: {tag: '꼬리표', title: '인용할 말', sub: '말한 사람', items: '(비워 두세요)'},
         last: {tag: '꼬리표 (예: 이것만 챙겨요)', title: '맺음말 (기본: 헷갈리면 저장해 두세요)', sub: '출처 (예: 출처: 연합뉴스 2026.11.05)', items: '챙길 것 3개 (한 줄에 하나)'}}[role] || {};
    var ip = $('#mk-items-row'); if (ip) ip.hidden = mode === 'card' && (role === 'cover' || role === 'quote');
    Object.keys(lab).forEach(function (k) { var l = $('#mk-l-' + k); if (l) l.textContent = lab[k]; });
    var db = $('#mk-draw'); if (db) db.disabled = drawing;
  }
  $('#mk-design').addEventListener('change', function (e) {
    if (e.target.name !== 'mk-d') return;
    var s = slides[cur], v = e.target.value; s.design = v;
    if (v === 'last' && !s.title) { s.title = '헷갈리면 저장해 두세요'; s.tag = s.tag || '이것만 챙겨요'; }
    fill(); draw();
  });
  var thBox0 = $('#mk-theme');
  if (thBox0) thBox0.addEventListener('change', function (e) { if (e.target.name === 'mk-t') { deck.theme = e.target.value; try { localStorage.setItem('mk-theme', deck.theme); } catch (x) {} draw(); } });
  var cvBox = $('#mk-cv');
  if (cvBox) cvBox.addEventListener('change', function (e) { if (e.target.name === 'mk-cv') { var c = deck.covers[+e.target.value]; if (c) { slides[cur].title = c.text; fill(); draw(); } } });
  function esc(t) { return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  // AI 그림 (카드뉴스 원칙: 기사 사진·캡처 대신 장면 설명으로 새로 그림)
  var drawing = false;
  function aiDraw(list) {
    list = list.filter(function (s) { return (s.scene || '').trim(); });
    if (!list.length || drawing) return Promise.resolve();
    drawing = true; var done = 0; fill();
    say('AI가 표지 그림을 새로 그리고 있어요. 30초~1분쯤 걸려요.');
    return Promise.all(list.map(function (s) {
      return post(C.draw, JSON.stringify({scene: s.scene}), 'application/json').then(function (j) {
        if (!j.ok) throw new Error(j.error || '그림을 그리지 못했어요.');
        return loadImg(j.url).then(function (el) { s.media = {kind: 'image', url: j.url, el: el}; done++; say('AI 그림 ' + done + ' / ' + list.length + '장 그렸어요.'); draw(); });
      });
    })).then(function () { say('그림을 다 그렸어요. AI 그림이라 인스타에 올릴 때 \'AI 정보\' 표시를 켜 주세요.'); }, function (e) { say(e.message); })
      .then(function () { drawing = false; fill(); });
  }
  var drawBtn = $('#mk-draw');
  if (drawBtn) drawBtn.onclick = function () { var s = slides[cur]; if (!(s.scene || '').trim()) { s.scene = (s.title || '').replace(/\n/g, ' '); } aiDraw([s]); };
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
      slides = [{design: 'cover', tag: tg, title: a.title, sub: '', items: '', media: img, scene: ''}];
      secs.filter(function (x) { return x.paras.length; }).slice(0, 4).forEach(function (x) { slides.push({design: 'body', tag: '', title: x.title || a.title, sub: '', items: x.paras.join('\n\n'), media: null, scene: ''}); });
      slides.push({design: 'last', tag: '이것만 챙겨요', title: '헷갈리면 저장해 두세요', sub: '출처: 소보루 매거진', items: '', media: null, scene: ''}); deck.covers = [];
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
      var o = blank(); o.design = p.design; o.tag = mode === 'card' ? (p.tag || '') : (j.tag || o.tag); o.title = p.title || ''; o.sub = p.sub || ''; o.items = p.items || ''; o.media = null; o.scene = p.scene || '';
      if (mode === 'reel') { o.start = 0; o.dur = p.dur || 4; o.end = o.dur; }
      return o;
    });
    if (mode === 'card') deck.covers = j.covers || [];
    return loadMedia(j).then(function (ms) {
      if (keep) ms.unshift(keep);
      slides.forEach(function (s, i) {
        if (!ms.length || (mode === 'card' && s.design !== 'cover')) return;
        var m = ms[i % ms.length]; s.media = m;
        if (m.kind === 'video') { s.start = Math.min(i * 3, Math.max(0, m.len - s.dur)); s.dur = Math.min(s.dur, Math.floor(m.len * 10) / 10); s.end = s.start + s.dur; seek(s); }
      });
      cur = 0; fill(); draw();
      var n = slides.length, miss = slides.filter(function (s) { return !s.media; }).length;
      say((mode === 'card' ? '카드 ' + n + '장을' : '장면 ' + n + '개를') + ' 짰어요. ' + (mode === 'card' && deck.covers.length ? '표지 문구 ' + deck.covers.length + '개 중 하나를 골라 주세요. ' : '') + (miss && mode === 'reel' ? '사진·영상 없는 장면에 넣어 주세요. ' : '') + '글과 디자인은 자유롭게 고쳐도 돼요.' + (j.warn ? ' ' + j.warn : ''));
      if (mode === 'card' && j.draw) return aiDraw(slides.filter(function (s) { return !s.media && s.design === 'cover'; }));
    });
  }
  var lastSrc = '';
  function aiBuild(payload, fallback) {
    say('AI가 기사를 읽고 ' + (mode === 'card' ? '카드' : '장면') + '을 짜고 있어요. 10~20초쯤 걸려요.');
    lastSrc = payload.note ? (/^https?:\/\//.test(payload.note) ? payload.note.slice(0, 300) : '붙여 넣은 기사 글') : payload.art ? '소보루 매거진 기사 #' + payload.art : payload.letter ? '소보루 레터 ' + payload.letter : '';
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
  // 네이버 경제 뉴스 댓글 많은 순 (운영자 2026-11-05) — 고르면 그 기사 링크로 AI가 짬
  var nvSel = $('#mk-naver');
  if (nvSel) {
    fetch(C.naver, {credentials: 'same-origin'}).then(function (r) { return r.json(); }).then(function (j) {
      if (!j.ok || !(j.items || []).length) throw new Error(j.error || '');
      nvSel.innerHTML = '<option value="">뉴스 고르기</option>' + j.items.map(function (x) { return '<option value="' + esc(x.url) + '">' + esc(x.title.slice(0, 44)) + (x.comments >= 0 ? ' · 댓글 ' + x.comments.toLocaleString('ko-KR') : '') + '</option>'; }).join('');
    }).catch(function () { nvSel.innerHTML = '<option value="">불러오지 못했어요. 링크를 아래에 붙여 넣어 주세요</option>'; });
    nvSel.addEventListener('change', function () {
      if (!nvSel.value) return;
      if (artSel) artSel.value = ''; if (letSel) letSel.value = '';
      nvSel.disabled = true; aiBuild({note: nvSel.value}).then(function () { nvSel.disabled = false; });
    });
    [artSel, letSel].forEach(function (el) { if (el) el.addEventListener('change', function () { if (el.value) nvSel.value = ''; }); });
  }
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
  function oneTitle() { return ((slides[0] && slides[0].title) || '').replace(/\s+/g, ' ').trim().slice(0, 120); }
  function saveCards(blobs) {
    return post(C.made_new, JSON.stringify({kind: 'card', title: oneTitle(), caption: capT ? capT.value : '', source: lastSrc}), 'application/json').then(function (j) {
      if (!j.ok) throw new Error('');
      var base = C.made_base.replace('/0/', '/' + j.id + '/');
      return blobs.reduce(function (p, b, i) {
        return p.then(function () { return post(base + 'file?name=' + ('0' + (i + 1)).slice(-2) + '.png', b, 'application/octet-stream').then(function (r) { if (!r.ok) throw new Error(''); }); });
      }, Promise.resolve()).then(function () { return post(base + 'done'); }).then(function (r) { if (!r.ok) throw new Error(''); return r.url; });
    });
  }
  function blobOf(c) { return new Promise(function (ok) { c.toBlob(ok, 'image/png'); }); }
  $('#mk-go').onclick = function () {
    var btn = this;
    fontsFor(texts()).then(function () {
      if (mode === 'card') {
        var stamp = new Date().toISOString().slice(0, 10).replace(/-/g, ''), blobs = [];
        btn.disabled = true;
        return slides.reduce(function (p, s, i) {
          return p.then(function () {
            var c = document.createElement('canvas'); c.width = 1080; c.height = 1350; paint(c.getContext('2d'), s, i);
            return blobOf(c).then(function (b) { blobs.push(b); var a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = 'soboru-card-' + stamp + '-' + (i + 1) + '.png'; document.body.appendChild(a); a.click(); a.remove(); return new Promise(function (r) { setTimeout(r, 350); }); });
          });
        }, Promise.resolve()).then(function () {
          // 운영자 2026-11-05: 내려받은 카드는 만든 것 보관함(서버)에도 저장
          say('카드 ' + slides.length + '장을 내려받았어요. 보관함에 저장하는 중이에요.');
          return saveCards(blobs).then(function (url) { say('카드 ' + slides.length + '장을 내려받고 만든 것 보관함에 저장했어요.'); },
                                       function () { say('카드 ' + slides.length + '장을 내려받았어요. 보관함 저장은 못 했어요.'); });
        });
      }
      var miss = slides.findIndex(function (s) { return !s.media || !s.media.url; });
      if (miss >= 0) { say((miss + 1) + '번 장면에 사진이나 영상을 넣어 주세요.'); return; }
      var c = document.createElement('canvas'); c.width = 1080; c.height = 1920; var x = c.getContext('2d');
      var scenes = slides.map(function (s, i) { x.clearRect(0, 0, 1080, 1920); REEL[s.design](x, s); return {media: s.media.url, layout: s.design, start: s.start || 0, dur: s.dur || 4, slow: !!s.slow, narration: s.narration || '', png: c.toDataURL('image/png')}; });
      x.clearRect(0, 0, 1080, 1920); REEL.outro(x, fromLetter);
      btn.disabled = true; say('릴스를 만들고 있어요. 1~3분쯤 걸려요. 이 화면을 닫지 말아 주세요.');
      return post(C.render, JSON.stringify({scenes: scenes, outro: c.toDataURL('image/png'), title: oneTitle(), caption: capT ? capT.value : '', source: lastSrc}), 'application/json').then(function (j) {
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
        say('릴스를 만들었어요. 만든 것 보관함에도 저장했어요. 내려받아 인스타그램에 올리거나 매거진 릴스 칸에 올려 보세요.');
      });
    }).catch(function (e) { say(e.message); }).then(function () { btn.disabled = false; });
  };

  slides = [blank()];
  if (mode === 'reel') { slides[0].tag = '블랙박스 이슈'; slides[0].title = '제목을\n두 줄로'; slides[0].sub = ': 한 줄 부제'; slides[0].items = '#11월 3일 오후 2시께\n운전자 A씨 : “피할 수 없었다”'; }
  else { slides[0].tag = 'FOOD'; slides[0].title = '표지 문구는 짧게,\n두 줄이 좋아요'; slides[0].sub = '숫자 하나'; }
  logo.onload = function () { logoW = logoK = null; logoCache = {}; draw(); };
  fill(); draw();
})();
