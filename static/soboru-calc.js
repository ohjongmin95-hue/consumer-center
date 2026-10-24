/* 소보루 상담소 계산기 (soboru_tools.py CALCS). 계산은 브라우저에서만 해요. */
(function () {
  var form = document.querySelector('[data-calc]'); if (!form) return;
  var out = document.querySelector('[data-calc-out]'), slug = form.getAttribute('data-calc');
  function num(n) { var el = form.elements[n]; if (!el) return NaN; var v = String(el.value).replace(/[^0-9.\-]/g, ''); return v === '' ? NaN : Number(v); }
  function val(n) { var el = form.elements[n]; return el ? el.value : ''; }
  function won(x) { return Math.round(x).toLocaleString('ko-KR') + '원'; }
  function pct(x) { return (Math.round(x * 10) / 10).toLocaleString('ko-KR') + '%'; }
  function ok(x) { return isFinite(x) && x >= 0; }
  function ymd(d) { return d.getFullYear() + '년 ' + (d.getMonth() + 1) + '월 ' + d.getDate() + '일'; }
  // 결과: big = 맨 위 큰 숫자, rows = [이름, 값, 강조]
  function show(r) {
    if (!r) { out.innerHTML = '<p class="tc-wait">칸을 채우면 바로 계산해요.</p>'; return; }
    var h = '<p class="tc-big-k">' + r.k + '</p><p class="tc-big">' + r.big + '</p>';
    if (r.sub) h += '<p class="tc-sub">' + r.sub + '</p>';
    if (r.rows && r.rows.length) { h += '<dl class="tc-rows">'; r.rows.forEach(function (x) { h += '<div' + (x[2] ? ' class="on"' : '') + '><dt>' + x[0] + '</dt><dd>' + x[1] + '</dd></div>'; }); h += '</dl>'; }
    out.innerHTML = h;
  }
  var TAX = { normal: 0.154, pref: 0.095, free: 0 };
  var C = {
    fitness: function () {
      var p = num('price'), d = num('days'), u = num('used'); if (!ok(p) || !(d > 0) || !ok(u)) return;
      u = Math.min(u, d); var fee = p * 0.1, use = u > 0 ? p * u / d : 0, back = Math.max(0, p - fee - use);
      return { k: '돌려받을 수 있는 돈', big: won(back), sub: u > 0 ? '이용을 시작한 뒤 해지' : '이용을 시작하기 전 해지',
        rows: [['결제한 금액', won(p)], ['위약금 (10%)', '− ' + won(fee)], ['이용한 ' + u + '일 몫', '− ' + won(use)], ['돌려받을 돈', won(back), 1]] };
    },
    academy: function () {
      var f = num('fee'), m = num('months'), done = num('done'), t = num('total'), a = num('attended'); if (!ok(f) || !(m > 0) || !ok(done) || !(t > 0) || !ok(a)) return;
      done = Math.min(done, m); var left = m - done; if (left <= 0) return { k: '돌려받을 수 있는 돈', big: won(0), sub: '결제한 달이 모두 끝났어요.' };
      var r = a / t, part = a <= 0 ? f : r < 1 / 3 ? f * 2 / 3 : r < 1 / 2 ? f / 2 : 0, rest = f * (left - 1);
      var why = a <= 0 ? '이번 달 수업 전이라 전액' : r < 1 / 3 ? '1/3이 지나기 전이라 2/3' : r < 1 / 2 ? '1/2이 지나기 전이라 1/2' : '1/2이 지나 그달 몫은 없음';
      return { k: '돌려받을 수 있는 돈', big: won(part + rest), sub: '이번 달 ' + pct(r * 100) + ' 지남',
        rows: [['이번 달 (' + why + ')', won(part)], ['남은 ' + (left - 1) + '개월 (전액)', won(rest)], ['합계', won(part + rest), 1]] };
    },
    cooling: function () {
      var s = val('day'); if (!s) return; var d = new Date(s + 'T00:00:00'); if (isNaN(d)) return;
      var n = val('kind') === 'visit' ? 14 : 7, end = new Date(d); end.setDate(end.getDate() + n);
      var today = new Date(); today.setHours(0, 0, 0, 0); var left = Math.round((end - today) / 864e5);
      return { k: '청약철회 마지막 날', big: ymd(end), sub: left > 0 ? left + '일 남았어요' : left === 0 ? '오늘까지예요' : '기간이 지났어요 (' + (-left) + '일 지남)',
        rows: [['받은 날', ymd(d)], ['기간', '받은 다음 날부터 ' + n + '일']] };
    },
    unit: function () {
      var xs = []; ['a', 'b', 'c'].forEach(function (k) {
        var p = num(k + '_price'), s = num(k + '_size'), n = num(k + '_n'); if (!(p > 0) || !(s > 0)) return; n = n > 0 ? n : 1;
        xs.push({ k: k.toUpperCase(), per: p / (s * n) * 100, one: p / n });
      });
      if (xs.length < 2) return; var best = xs.reduce(function (a, b) { return b.per < a.per ? b : a; }), worst = xs.reduce(function (a, b) { return b.per > a.per ? b : a; });
      return { k: '가장 싼 상품', big: best.k + ' · 100당 ' + won(best.per), sub: worst.per > best.per ? '가장 비싼 ' + worst.k + '보다 ' + pct((1 - best.per / worst.per) * 100) + ' 싸요' : '값이 같아요',
        rows: xs.map(function (x) { return [x.k + ' (100g·ml당)', won(x.per) + ' · 1개 ' + won(x.one), x === best]; }) };
    },
    discount: function () {
      var p = num('price'), q = num('qty'), fr = num('free'), d1 = num('d1'), d2 = num('d2'), cp = num('coupon'); if (!(p > 0)) return;
      q = q > 0 ? q : 1; fr = fr > 0 ? fr : 0; d1 = ok(d1) ? d1 : 0; d2 = ok(d2) ? d2 : 0; cp = ok(cp) ? cp : 0;
      var list = p * q, after = list * (1 - d1 / 100) * (1 - d2 / 100), pay = Math.max(0, after - cp), got = q + fr, base = p * got;
      return { k: '내는 돈', big: won(pay), sub: '정가 대비 실제 ' + pct((1 - pay / base) * 100) + ' 할인 · 1개당 ' + won(pay / got),
        rows: [['정가 × ' + q + '개', won(list)], ['할인 ' + d1 + '% 뒤 ' + d2 + '% 더', won(after)], ['쿠폰', '− ' + won(Math.min(cp, after))], ['받는 개수', got + '개'], ['내는 돈', won(pay), 1]] };
    },
    card: function () {
      var a = num('amount'), m = Math.round(num('months')), r = num('rate'); if (!(a > 0) || !(m > 0) || !ok(r)) return;
      var left = a, fee = 0, first = 0, each = a / m;
      for (var i = 0; i < m; i++) { var f = left * r / 100 / 12; fee += f; if (i === 0) first = each + f; left -= each; }
      return { k: '할부 수수료 합계', big: won(fee), sub: '총 ' + won(a + fee) + ' 내요',
        rows: [['첫 달 내는 돈', won(first)], ['마지막 달 내는 돈', won(each + each * r / 100 / 12)], ['원금', won(a)], ['수수료', won(fee), 1]] };
    },
    subscription: function () {
      var s = 0, n = 0; for (var i = 1; i <= 6; i++) { var x = num('s' + i); if (x > 0) { s += x; n++; } } if (!n) return;
      return { k: '1년이면', big: won(s * 12), sub: n + '개 구독 · 한 달 ' + won(s), rows: [['한 달', won(s)], ['1년', won(s * 12), 1], ['5년', won(s * 60)]] };
    },
    loan: function () {
      var a = num('amount'), r = num('rate') / 100 / 12, m = Math.round(num('months')), way = val('way'); if (!(a > 0) || !(m > 0) || !(r >= 0)) return;
      var interest = 0, first = 0, last = 0;
      if (way === 'equal') { var pay = r ? a * r * Math.pow(1 + r, m) / (Math.pow(1 + r, m) - 1) : a / m; interest = pay * m - a; first = last = pay; }
      else if (way === 'principal') { var p = a / m; for (var i = 0; i < m; i++) { var it = (a - p * i) * r; interest += it; if (!i) first = p + it; last = p + it; } }
      else { interest = a * r * m; first = a * r; last = a + a * r; }
      return { k: '이자 합계', big: won(interest), sub: '총 ' + won(a + interest) + ' 갚아요',
        rows: [['첫 달 내는 돈', won(first)], ['마지막 달 내는 돈', won(last)], ['원금', won(a)], ['이자', won(interest), 1]] };
    },
    deposit: function () {
      var a = num('amount'), r = num('rate'), m = num('months'), t = TAX[val('tax')] || 0; if (!(a > 0) || !ok(r) || !(m > 0)) return;
      var it = a * r / 100 * m / 12, tax = Math.floor(it * t / 10) * 10;
      return { k: '만기에 받는 돈', big: won(a + it - tax), sub: '세금 떼고 이자 ' + won(it - tax), rows: [['원금', won(a)], ['세전 이자', won(it)], ['세금', '− ' + won(tax)], ['받는 돈', won(a + it - tax), 1]] };
    },
    saving: function () {
      var a = num('monthly'), r = num('rate'), m = Math.round(num('months')), t = TAX[val('tax')] || 0; if (!(a > 0) || !ok(r) || !(m > 0)) return;
      var it = a * r / 100 / 12 * m * (m + 1) / 2, tax = Math.floor(it * t / 10) * 10, put = a * m;
      return { k: '만기에 받는 돈', big: won(put + it - tax), sub: '넣은 돈 ' + won(put) + ' · 세금 떼고 이자 ' + won(it - tax),
        rows: [['넣은 돈', won(put)], ['세전 이자', won(it)], ['세금', '− ' + won(tax)], ['받는 돈', won(put + it - tax), 1]] };
    },
    vat: function () {
      var a = num('amount'); if (!(a > 0)) return; var sup = val('way') === 'total' ? Math.round(a / 1.1) : a, tax = val('way') === 'total' ? a - sup : Math.round(a * 0.1);
      return { k: '부가세', big: won(tax), rows: [['공급가액', won(sup)], ['부가세 (10%)', won(tax)], ['합계', won(sup + tax), 1]] };
    },
    jeonse: function () {
      var d = num('diff'), r = num('rate'); if (!(d > 0) || !ok(r)) return;
      return { k: '늘어나는 월세', big: won(d * r / 100 / 12), sub: '1년이면 ' + won(d * r / 100), rows: [['월세로 바꿀 보증금', won(d)], ['전환율', pct(r)], ['한 달 월세', won(d * r / 100 / 12), 1]] };
    },
    inflation: function () {
      var a = num('amount'), r = num('rate'), y = num('years'); if (!(a > 0) || !ok(r) || !(y > 0)) return;
      var f = Math.pow(1 + r / 100, y);
      return { k: y + '년 뒤 지금 ' + won(a) + '의 값어치', big: won(a / f), sub: '같은 걸 사려면 ' + won(a * f) + ' 필요해요',
        rows: [['지금 돈', won(a)], [y + '년 뒤 같은 물건 값', won(a * f)], ['돈의 값어치', won(a / f), 1]] };
    }
  };
  function run() { var f = C[slug]; var r; try { r = f && f(); } catch (e) { r = null; } show(r); }
  form.addEventListener('input', run); form.addEventListener('change', run);
  form.addEventListener('submit', function (e) { e.preventDefault(); run(); });
  // 원 칸은 쉼표 넣어 보이기
  Array.prototype.forEach.call(form.querySelectorAll('[data-won]'), function (el) {
    el.addEventListener('input', function () { var v = el.value.replace(/[^0-9]/g, ''); el.value = v ? Number(v).toLocaleString('ko-KR') : ''; });
  });
  var d = form.querySelector('input[type=date]'); if (d && !d.value) { var t = new Date(); d.value = t.getFullYear() + '-' + ('0' + (t.getMonth() + 1)).slice(-2) + '-' + ('0' + t.getDate()).slice(-2); }
  run();
})();
