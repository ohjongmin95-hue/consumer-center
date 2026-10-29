"""소비자 법률 질문창(/ask)과 관리자 > 법령 학습(/admin/laws).

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다.
- 질문창: 소비자가 질문을 적으면 법령 원문 모음(platform_app/law_corpus.py, triage와 같은 모듈)에서 맞는 조문을 찾고,
  AI는 그 조문만 근거로 해요체로 답한다(인터넷 검색·일반 지식 없이). AI가 적은 근거 조문은 넘겨준 후보 안의 것만 남긴다.
  AI 키가 없거나 AI가 실패하면 찾은 조문 카드만 보여 준다. AI에는 전화번호·이메일 등을 지운 질문만 보낸다(companydesk.scrub).
- 도배 막기: 접속 IP 해시와 시각만 남겨 1시간에 PER_HOUR번까지 (질문 글은 저장하지 않음, 하루 지난 기록은 지움). 숨은 칸(website)도 둔다.
- 관리자 > 문구 고치기 '법률 질문창 끄기'에 '끔'이라고 적으면 질문창과 메뉴가 닫힌다.
- 법령 학습: 관리자가 국가법령정보센터(law.go.kr) 법령 PDF를 올리면 pdftotext(없으면 pypdf)로 글자를 뽑아 law_corpus_build와 같은 방식으로
  조문을 나누고, 미리 보기로 확인한 뒤 저장한다. 저장은 저장소 파일이 아니라 UPLOAD/laws/extra_laws.json (서버 데이터 폴더).
  저장하면 질문창과 AI 제보 분류(triage)의 법령 찾기에 바로 들어간다. 올린 법령은 지울 수 있고, 기본 모음(law_corpus.json)은 지울 수 없다.
"""
import datetime, importlib.util, json, logging, os, re, secrets, subprocess, tempfile
from pathlib import Path
from flask import abort, flash, g, redirect, render_template, request, url_for

LOG = logging.getLogger(__name__)
_spec = importlib.util.spec_from_file_location('jebo_law_corpus_build', Path(__file__).parent / 'platform_app' / 'law_corpus_build.py')
build = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(build)

MIN_Q, MAX_Q = 5, 500      # 질문 글자 수
PER_HOUR = 10              # IP마다 1시간에 질문 수
MAX_PDF = 20 * 1024 * 1024
MAX_FILES = 5
PENDING_HOURS = 24         # 미리 보기만 하고 저장하지 않은 파일은 이만큼 지나면 지움
EXAMPLES = ['온라인에서 산 옷, 7일 지나서도 환불되나요?', '받은 옷이 광고 사진이랑 너무 달라요. 반품할 수 있나요?', '약관에 환불 불가라고 적혀 있으면 정말 안 되나요?',
            '화장품에 사용기한이 안 적혀 있어요', '택배가 분실됐어요. 보상받을 수 있나요?', '배달 음식에서 이물질이 나왔어요']
SYSTEM = ('너는 소보루의 소비자 법률 안내 도우미다. 소비자의 질문에 아래 [조문 후보]의 법령 원문만 근거로 답한다.\n'
          '- 인터넷 검색이나 네가 알고 있는 일반 지식으로 법 내용을 채우지 않는다. 후보 원문에 없는 기간·금액·예외는 말하지 않는다.\n'
          '- 후보 조문이 질문을 다루지 않으면 covered를 false로 하고, 그렇다고 분명히 말한 뒤 1372 소비자상담센터 상담을 권한다.\n'
          '- 쉬운 해요체로, 법률 용어는 풀어서 쓴다(예: 청약철회 = 주문 취소·반품). 단정하지 말고 "~할 수 있어요", "~인 경우가 많아요"처럼 쓴다.\n'
          '- 어느 법 몇 조에 따른 것인지 문장 안에 밝힌다(예: 전자상거래법 제17조에 따르면).\n'
          '- 업체가 응하지 않거나 피해가 크면 1372 소비자상담센터나 소보루 제보를 권한다. 법률 자문이 아니라 일반 안내임을 잊지 않는다.\n'
          'JSON 객체 하나로만 답한다: {"headline": 한 줄 답(40자 안팎), "paragraphs": [설명 문단 2~4개, 문자열 배열], '
          '"refs": [근거로 쓴 후보 id 0~4개, 후보 목록의 id 그대로], "covered": true 또는 false, "suggest_report": 업체와 다툼이 있어 제보가 도움이 되면 true}')
CORPUS = 'corpus:'


def migrate(db):
    # 질문 글은 저장하지 않고 IP 해시·시각만 (1시간 도배 막기용)
    db.execute('CREATE TABLE IF NOT EXISTS law_questions(id INTEGER PRIMARY KEY,ip_hash TEXT NOT NULL,created TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS law_questions_ip ON law_questions(ip_hash,created)')


def pdf_text(raw):
    """PDF 글자. pdftotext(쪽 순서대로 읽기)가 없으면 pypdf. 못 읽으면 ValueError."""
    with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
        f.write(raw); f.flush()
        try:
            r = subprocess.run(['pdftotext', '-enc', 'UTF-8', f.name, '-'], capture_output=True, timeout=90)
            if r.returncode != 0: raise ValueError('PDF를 열지 못했어요. 암호가 걸려 있거나 손상된 파일인지 확인해 주세요.')
            return r.stdout.decode('utf-8', 'replace')
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            raise ValueError('PDF가 너무 커서 읽지 못했어요.')
    try:
        import io, pypdf
        return '\n'.join(p.extract_text() or '' for p in pypdf.PdfReader(io.BytesIO(raw)).pages)
    except ImportError:
        raise ValueError('서버에 PDF 읽기 프로그램(pdftotext)이 없어요. deploy/update.sh를 다시 돌려 주세요.')
    except Exception:
        raise ValueError('PDF를 열지 못했어요. 암호가 걸려 있거나 손상된 파일인지 확인해 주세요.')


def parse_pdf(raw):
    """PDF -> [법령]. 국가법령정보센터 법령 PDF가 아니면 ValueError."""
    text = pdf_text(raw)
    if len(re.sub(r'\s', '', text)) < 100: raise ValueError('글자를 거의 읽지 못했어요. 스캔한 그림 PDF가 아니라 국가법령정보센터에서 받은 PDF인지 확인해 주세요.')
    return parse_text(text)


def parse_text(text):
    try: laws = build.parse_text(text)
    except ValueError: raise ValueError("'[시행 …] [법률 제…호 …]' 줄을 찾지 못했어요. 국가법령정보센터(law.go.kr)에서 받은 법령 PDF인지 확인해 주세요.")
    laws = [l for l in laws if l['articles']]
    if not laws: raise ValueError('조문(제1조, 제2조 …)을 찾지 못했어요. 국가법령정보센터(law.go.kr)에서 받은 법령 PDF인지 확인해 주세요.')
    return laws


def install(S):
    app = S.app; conn = S.conn; desk = S.companydesk
    corpus = S.triage.corpus  # triage와 같은 모듈: 올린 법령이 AI 제보 분류에도 바로 들어감
    folder = S.UPLOAD / 'laws'; folder.mkdir(parents=True, exist_ok=True)
    extra_path = folder / 'extra_laws.json'
    pending = folder / 'pending'; pending.mkdir(exist_ok=True)
    corpus.add_extra(extra_path)
    with conn() as db: migrate(db)

    def stamp(): return datetime.datetime.now().isoformat(timespec='seconds')
    def ask_on(): return (g.get('content') or {}).get('ask.off', '').strip() not in ('끔', '끄기', 'off')

    # ---- 법령 목록 ----------------------------------------------------------
    def law_list():
        rows = sorted(corpus.laws(), key=lambda l: (l['key'] == 'easylaw', bool(l.get('extra')), l['short']))
        return rows

    def read_extra(): return corpus.extra_laws(extra_path)

    def write_extra(data):
        tmp = extra_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        os.replace(tmp, extra_path); corpus.reset()

    # ---- 질문 -> 조문 찾기 -> AI ------------------------------------------------
    def card(ref, via=None):
        c = corpus.cite(ref)
        return {'ref': ref, 'short': c['label'].rsplit(' ', 1)[0], 'art': ref.split(':', 1)[1], 'title': c['title'], 'text': c['text'], 'law': c['law'],
                'kind': c['kind'], 'effective': c['effective'], 'source': c['source'], 'guide': ref.startswith('easylaw:')}

    def ask_ai(question, hits):
        """{headline, paragraphs, refs, covered, suggest_report}. 실패하면 예외(메시지에 키를 넣지 않음)."""
        key = os.getenv('OPENAI_API_KEY', '').strip()
        if not key: raise RuntimeError('OpenAI API 키가 없어요')
        block = corpus.grounding_block(question, hits=hits, per=1800, total=9000, ids=True)
        pool = [r[len(CORPUS):] for r in re.findall(r'^\[(corpus:[^\]]+)\] ', block, re.M)]
        user = '[질문]\n' + desk.scrub(question) + '\n\n[조문 후보]\n' + block
        body = {'model': desk.ai_model(), 'temperature': 0.2, 'response_format': {'type': 'json_object'},
                'messages': [{'role': 'system', 'content': SYSTEM.replace('소보루', S.notify.site_name())}, {'role': 'user', 'content': user}]}
        st, res = desk.post_json('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 40)
        if st != 200: raise RuntimeError(f'AI 응답 오류 ({st}) ' + str((res.get('error') or {}).get('message', ''))[:120].replace(key, '***'))
        try: out = json.loads(res['choices'][0]['message']['content'])
        except (KeyError, IndexError, TypeError, ValueError): raise RuntimeError('AI 응답을 읽지 못했어요')
        return clean(out, pool)

    def clean(out, pool):
        if not isinstance(out, dict): raise RuntimeError('AI 응답 형식이 달라요')
        s = lambda v: desk.scrub(str(v).strip())
        paras = out.get('paragraphs')
        if isinstance(paras, str): paras = re.split(r'\n\s*\n|\n', paras)  # 배열 대신 한 덩어리 글로 줄 때
        paras = [s(p) for p in (paras if isinstance(paras, list) else []) if str(p).strip()][:4]
        if not paras: raise RuntimeError('AI가 답을 채우지 못했어요')
        refs = []
        for r in out.get('refs') or []:
            r = str(r).strip().strip('[]')
            r = r[len(CORPUS):] if r.startswith(CORPUS) else r
            if r in pool and r not in refs: refs.append(r)  # 넘겨준 후보에 없는 조문은 버림
        return {'headline': s(out.get('headline') or '')[:120], 'paragraphs': paras, 'refs': refs[:4],
                'covered': out.get('covered') is not False, 'suggest_report': bool(out.get('suggest_report'))}

    def answer(question):
        try: hits = corpus.related(question, 6)
        except Exception as e:
            LOG.warning('법령 찾기 실패: %s', type(e).__name__); hits = []
        if not hits: return {'kind': 'none', 'cards': []}
        fallback = {'kind': 'fallback', 'cards': [card(h['ref']) for h in hits[:4]]}
        if not os.getenv('OPENAI_API_KEY', '').strip(): return fallback  # 키가 없으면 찾은 조문만
        try:
            res = ask_ai(question, hits)
            return dict(res, kind='answer', cards=[card(r) for r in res['refs']])
        except Exception as e:
            LOG.warning('법률 질문 AI 실패: %s', str(e)[:160])
            return fallback

    def counts():
        rows = corpus.laws()
        return {'laws': len([l for l in rows if l['key'] != 'easylaw']), 'articles': sum(l['count'] for l in rows if l['key'] != 'easylaw')}

    @app.route('/ask', methods=['GET', 'POST'])
    def law_ask():
        if not ask_on(): abort(404)
        question, result, error = '', None, ''
        if request.method == 'POST':
            if request.form.get('website'): abort(400)  # 자동 등록 막기용 숨은 칸
            question = ' '.join((request.form.get('q') or request.form.get('example') or '').split())
            if len(question) < MIN_Q: error = S.ui_text('ask.err_short', '궁금한 상황을 조금 더 자세히 적어 주세요.')
            elif len(question) > MAX_Q: error = S.ui_text('ask.err_long', f'질문은 {MAX_Q}자 안으로 줄여 주세요.')
            else:
                with conn() as db:
                    if S.recent_count(db, 'law_questions', 60) >= PER_HOUR: error = S.ui_text('ask.err_limit', '질문이 많아 잠시 쉬어 가요. 1시간 뒤에 다시 물어봐 주세요.')
                    else:
                        db.execute('DELETE FROM law_questions WHERE created<?', ((datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(timespec='seconds'),))
                        db.execute('INSERT INTO law_questions(ip_hash,created) VALUES(?,?)', (S.ip_hash(), stamp()))
                if not error: result = answer(question)
        return render_template('soboru_ask.html', question=question, result=result, error=error, examples=EXAMPLES, max_q=MAX_Q, min_q=MIN_Q,
                               laws=[l for l in law_list() if l['key'] != 'easylaw'], counts=counts())

    # ---- 관리자: 법령 학습 --------------------------------------------------------
    def clear_pending():
        old = datetime.datetime.now().timestamp() - PENDING_HOURS * 3600
        for p in pending.glob('*.json'):
            try:
                if p.stat().st_mtime < old: p.unlink()
            except OSError: pass

    def preview_rows(laws):
        base, extra = corpus.base_keys(), read_extra()
        return [{'key': l['key'], 'name': l['name'], 'short': l['short'], 'kind': l['kind'], 'no': l['no'], 'effective': l['effective'], 'count': len(l['articles']),
                 'file': l.get('file', ''), 'first': [(k, a['title']) for k, a in list(l['articles'].items())[:5]],
                 'replaces': 'extra' if l['key'] in extra else 'base' if l['key'] in base else ''} for l in laws]

    @app.route('/admin/laws', methods=['GET', 'POST'])
    @S.admin_only
    def admin_laws():
        clear_pending()
        if request.method == 'POST':
            act = request.form.get('act')
            if act == 'delete':
                key = request.form.get('key', '')
                data = read_extra()
                if key not in data: flash('올린 법령만 지울 수 있어요.'); return redirect(url_for('admin_laws'))
                name = data.pop(key)['name']; write_extra(data)
                flash(f'{name}을(를) 지웠어요.' + (' 기본 모음의 법령으로 돌아갔어요.' if key in corpus.base_keys() else ''))
                return redirect(url_for('admin_laws'))
            if act == 'save':
                token = request.form.get('token', '')
                p = pending / (token + '.json')
                if not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', token) or not p.exists():
                    flash('미리 보기가 끝났어요. PDF를 다시 올려 주세요.'); return redirect(url_for('admin_laws'))
                laws = json.loads(p.read_text(encoding='utf-8'))
                data = read_extra()
                for l in laws:
                    short = ' '.join(request.form.get('short_' + l['key'], '').split())[:30]
                    data[l['key']] = dict(l, short=short or l['short'], added=stamp())
                write_extra(data); p.unlink()
                flash('법령을 배웠어요: ' + ', '.join(f"{l['name']} {len(l['articles'])}개 조문" for l in laws) + '. 질문창과 AI 법률 안내에서 바로 찾아 써요.')
                return redirect(url_for('admin_laws'))
            # 올리기 -> 미리 보기
            files = [f for f in request.files.getlist('pdf') if f and f.filename][:MAX_FILES]
            if not files: flash('법령 PDF 파일을 골라 주세요.'); return redirect(url_for('admin_laws'))
            laws, errors = [], []
            for f in files:
                raw = f.read(MAX_PDF + 1); name = f.filename
                if not name.lower().endswith('.pdf') or not raw.startswith(b'%PDF-'): errors.append(f'{name}: PDF 파일만 올릴 수 있어요.'); continue
                if len(raw) > MAX_PDF: errors.append(f'{name}: 20MB보다 커요.'); continue
                try:
                    for l in parse_pdf(raw): laws.append(dict(l, file=name[:120]))
                except ValueError as e: errors.append(f'{name}: {e}')
            token = ''
            if laws:
                token = secrets.token_urlsafe(18)
                (pending / (token + '.json')).write_text(json.dumps(laws, ensure_ascii=False), encoding='utf-8')
            return render_template('admin_laws.html', laws=law_list(), preview=preview_rows(laws), token=token, errors=errors, counts=counts())
        return render_template('admin_laws.html', laws=law_list(), preview=None, token='', errors=[], counts=counts())

    app.jinja_env.globals.update(ask_on=ask_on)
    S.ask_on = ask_on
    app.extensions['lawask'] = {'answer': answer, 'clean': clean, 'extra_path': extra_path}
