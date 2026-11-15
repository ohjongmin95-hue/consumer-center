"""기사 초안함 (운영자 2026-11-15: "앞으로 관리자 페이지에 만들도록 해").
기사 스레드에서 쓴 기사 초안(기획기사 컷, 받아쓰기 등)을 관리자 > 콘텐츠 > 기사 초안에서 보고 고친 뒤
신문 사이트(consumertimes.kr, ND소프트 관리자)에 붙여 넣는다.
- 초안 파일: content/drafts/*.json ([{key, section, cut, title, body, source, note, origin}]) — 배포할 때 새 key만 들어옴
  (이미 들어온 초안은 관리자가 고친 내용을 덮어쓰지 않음)
- [가상] 표시는 화면에서 노란색으로 보여 실제 취재로 채울 곳을 찾기 쉽게 함
"""
import json
from pathlib import Path

from flask import abort, flash, redirect, render_template, request, url_for

DRAFT_DIR = Path(__file__).resolve().parent / 'content' / 'drafts'
STATUS = {'draft': '초안', 'ready': '고침 끝', 'posted': '신문에 올림'}


def install(S):
    app = S.app
    with S.conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS article_drafts(id INTEGER PRIMARY KEY, key TEXT UNIQUE, section TEXT NOT NULL DEFAULT '',
            cut TEXT NOT NULL DEFAULT '', title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
            origin TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft', created TEXT NOT NULL, updated TEXT NOT NULL)''')
    load_files(S)

    @app.route('/admin/drafts')
    @S.admin_only
    def admin_drafts():
        with S.conn() as db:
            rows = db.execute('SELECT id,section,cut,title,status,origin,updated,length(body) n FROM article_drafts ORDER BY id DESC').fetchall()
        return render_template('admin_drafts.html', rows=rows, status=STATUS, d=None)

    @app.route('/admin/drafts/<int:did>', methods=['GET', 'POST'])
    @S.admin_only
    def admin_draft(did):
        with S.conn() as db:
            d = db.execute('SELECT * FROM article_drafts WHERE id=?', (did,)).fetchone()
            if not d: abort(404)
            if request.method == 'POST':
                f = request.form
                title = (f.get('title') or '').strip()[:300] or d['title']
                st = f.get('status') if f.get('status') in STATUS else d['status']
                db.execute('UPDATE article_drafts SET title=?,body=?,source=?,status=?,updated=? WHERE id=?',
                           (title, (f.get('body') or '')[:50000], (f.get('source') or '')[:2000], st, S.now(), did))
                flash('저장했어요.')
                return redirect(url_for('admin_draft', did=did))
        return render_template('admin_drafts.html', d=d, status=STATUS, rows=None)


def load_files(S):
    """content/drafts/*.json 에서 아직 없는 초안만 넣는다"""
    if not DRAFT_DIR.is_dir(): return 0
    n = 0
    with S.conn() as db:
        for p in sorted(DRAFT_DIR.glob('*.json')):
            try:
                items = json.loads(p.read_text(encoding='utf-8'))
            except Exception as e:
                print('기사 초안 파일을 못 읽었어요:', p.name, e); continue
            for it in items:
                if not it.get('key') or not it.get('title'): continue
                if db.execute('SELECT 1 FROM article_drafts WHERE key=?', (it['key'],)).fetchone(): continue
                db.execute('INSERT INTO article_drafts(key,section,cut,title,body,source,note,origin,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (it['key'], it.get('section', ''), it.get('cut', ''), it['title'], it.get('body', ''), it.get('source', ''),
                            it.get('note', ''), it.get('origin', ''), S.now(), S.now()))
                n += 1
    return n
