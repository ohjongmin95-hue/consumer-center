"""콘텐츠 관리: 자료실(블로그)·도움말·고객 사례 (Gorgias의 Blog·Help Center·Customer stories에 해당).

  · 운영 화면 /ops/content 에서 쓰고 고치고 지우고 공개/비공개를 바꾼다. 비공개 글은 운영 로그인으로만 미리 본다.
  · 글은 간단한 마크다운(제목 ##, 목록 -, 1., 굵게 **, 링크 [글](주소), 그림 ![설명](주소), 인용 >)으로 쓴다. HTML은 모두 글자로 바뀐다.
  · 고객 사례는 그 회사의 공개 동의(누가·언제·어떻게)를 적어야만 공개할 수 있다. 가상의 사례·성과를 올리지 않는다.
  · 글마다 검색 제목·설명·대표 그림(OG)을 따로 정할 수 있고, 사이트맵·구조화 데이터(Article·FAQPage·BreadcrumbList)에 자동으로 들어간다.
"""
import datetime, html, json, re, secrets
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session, send_file
from markupsafe import Markup
import core
from core import conn, clean

bp=Blueprint('cms',__name__)
KINDS={'blog':'자료실','help':'도움말','story':'고객 사례'}
CATS={'blog':['CS 운영','판매처 문의 관리','교환·반품 응대','AI 상담','CS 자동화','응대 템플릿','소식'],
      'help':['시작하기','처음 설정','AI 상담','판매처 연동','자동 처리','직원·권한','자주 묻는 질문','영상 안내'],
      'story':['패션·잡화','뷰티','식품','생활·주방','가전·디지털','가구·인테리어','기타']}
MEDIA=core.UPLOAD/'cms';MEDIA.mkdir(parents=True,exist_ok=True)
IMG_EXT={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}
MAX_IMG=3*1024*1024
SLUG_RE=re.compile(r'^[0-9a-z가-힣]+(?:-[0-9a-z가-힣]+)*$')

def init():
    with conn() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,slug TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL DEFAULT '',
          body TEXT NOT NULL DEFAULT '',category TEXT NOT NULL DEFAULT '',video_url TEXT NOT NULL DEFAULT '',cover TEXT NOT NULL DEFAULT '',
          seo_title TEXT NOT NULL DEFAULT '',seo_desc TEXT NOT NULL DEFAULT '',published INTEGER NOT NULL DEFAULT 0,published_at TEXT NOT NULL DEFAULT '',
          sort INTEGER NOT NULL DEFAULT 100,story_company TEXT NOT NULL DEFAULT '',consent INTEGER NOT NULL DEFAULT 0,consent_by TEXT NOT NULL DEFAULT '',
          consent_on TEXT NOT NULL DEFAULT '',consent_note TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,updated TEXT NOT NULL,UNIQUE(kind,slug));''')
        if not db.execute('SELECT 1 FROM posts LIMIT 1').fetchone():seed(db)

# ---------- 글 모양 (마크다운 일부) ----------
def _inline(t):
    t=html.escape(t,quote=True)
    t=re.sub(r'`([^`]+)`',r'<code>\1</code>',t)
    t=re.sub(r'\*\*([^*]+)\*\*',r'<b>\1</b>',t)
    def img(m):
        u=m.group(2)
        return f'<img src="{u}" alt="{m.group(1)}" loading="lazy">' if safe_url(u) else m.group(0)
    t=re.sub(r'!\[([^\]]*)\]\(([^)\s]+)\)',img,t)
    def link(m):
        u=m.group(2)
        if not safe_url(u):return m.group(1)
        ext=u.startswith('http')
        return f'<a class="link" href="{u}"'+(' target="_blank" rel="noopener nofollow"' if ext else '')+f'>{m.group(1)}</a>'
    return re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)',link,t)
def safe_url(u):return bool(re.match(r'^(https?://|/)[^\s"<>]*$',html.unescape(u)))
def render(text):
    out=[];lst=None;para=[]
    def flush():
        nonlocal lst
        if para:out.append('<p>'+'<br>'.join(_inline(x) for x in para)+'</p>');para.clear()
        if lst:out.append(f'<{lst[0]}>'+''.join(f'<li>{_inline(x)}</li>' for x in lst[1])+f'</{lst[0]}>');lst=None
    for raw in (text or '').replace('\r','').split('\n'):
        line=raw.rstrip()
        m=re.match(r'^(#{2,4})\s+(.*)$',line)
        if m:flush();n=len(m.group(1));out.append(f'<h{n} id="{anchor(m.group(2))}">{_inline(m.group(2))}</h{n}>');continue
        m=re.match(r'^\s*[-*]\s+(.*)$',line) or None;o=re.match(r'^\s*\d+[.)]\s+(.*)$',line)
        if m or o:
            if para:out.append('<p>'+'<br>'.join(_inline(x) for x in para)+'</p>');para.clear()
            k='ul' if m else 'ol'
            if not lst or lst[0]!=k:
                if lst:out.append(f'<{lst[0]}>'+''.join(f'<li>{_inline(x)}</li>' for x in lst[1])+f'</{lst[0]}>')
                lst=(k,[])
            lst[1].append((m or o).group(1));continue
        if line.startswith('>'):flush();out.append('<blockquote>'+_inline(line.lstrip('> '))+'</blockquote>');continue
        if line.strip() in ('---','***'):flush();out.append('<hr>');continue
        if not line.strip():flush();continue
        if lst:flush()
        para.append(line)
    flush()
    return Markup('\n'.join(out))
def anchor(t):return re.sub(r'[^0-9a-z가-힣]+','-',t.lower()).strip('-')[:60]
def faq_pairs(text):
    """### 질문 다음 줄들 = 답. FAQPage 구조화 데이터에 쓴다."""
    pairs=[];q=None;a=[]
    for line in (text or '').split('\n'):
        m=re.match(r'^###\s+(.*)$',line.strip())
        if m:
            if q and a:pairs.append((q,' '.join(a)))
            q=m.group(1);a=[]
        elif q and line.strip() and not line.startswith('#'):a.append(re.sub(r'[*`>\[\]]','',line.strip()))
    if q and a:pairs.append((q,' '.join(a)))
    return pairs
def youtube_id(u):
    m=re.match(r'^https?://(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})',u or '')
    return m.group(1) if m else ''
def reading_min(text):return max(1,round(len(text or '')/600))

# ---------- 저장 ----------
def slugify(t):
    s=re.sub(r'[^0-9a-z가-힣]+','-',(t or '').lower()).strip('-')
    return s[:60].strip('-') or secrets.token_hex(3)
def save(db,f,files,post=None):
    """글 저장. (글 id, 오류 문구)"""
    kind=post['kind'] if post else f.get('kind')
    if kind not in KINDS:return None,'종류를 골라 주세요'
    d={k:clean(f.get(k),n) for k,n in (('title',120),('summary',300),('category',30),('video_url',300),('seo_title',70),('seo_desc',160),('story_company',60),('consent_by',60),('consent_on',10),('consent_note',300))}
    d['body']=(f.get('body') or '').replace('\r','')[:60000]
    d['slug']=clean(f.get('slug'),60).lower() or slugify(d['title'])
    d['sort']=int(f.get('sort')) if str(f.get('sort','')).isdigit() else 100
    d['consent']=1 if str(f.get('consent')) in ('1','True','true') else 0
    if not d['title']:return None,'제목을 적어 주세요'
    if not SLUG_RE.match(d['slug']):return None,'주소는 영문 소문자·숫자·한글과 -만 쓸 수 있어요'
    if d['category'] not in CATS[kind]:d['category']=CATS[kind][0]
    if d['video_url'] and not youtube_id(d['video_url']) and not re.match(r'^https://',d['video_url']):return None,'영상 주소는 https로 시작해야 해요'
    if d['consent_on'] and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',d['consent_on']):return None,'동의 받은 날을 확인해 주세요'
    dup=db.execute('SELECT id FROM posts WHERE kind=? AND slug=?',(kind,d['slug'])).fetchone()
    if dup and (not post or dup['id']!=post['id']):return None,'같은 주소의 글이 있어요. 주소를 바꿔 주세요'
    up=files.get('cover') if files else None
    if up and up.filename:
        ext=Path(up.filename).suffix.lower()
        if ext not in IMG_EXT:return None,'대표 그림은 png·jpg·webp만 올릴 수 있어요'
        data=up.read()
        if len(data)>MAX_IMG:return None,'대표 그림은 3MB까지예요'
        name=secrets.token_hex(12)+ext;(MEDIA/name).write_bytes(data);d['cover']='/media/'+name
    elif post:d['cover']=post['cover']
    else:d['cover']=''
    if str(f.get('cover_clear'))=='1':d['cover']=''
    t=core.iso();keys=list(d)
    if post:
        db.execute('UPDATE posts SET '+','.join(f'{k}=?' for k in keys)+',updated=? WHERE id=?',[d[k] for k in keys]+[t,post['id']]);pid=post['id']
    else:
        pid=db.execute('INSERT INTO posts(kind,'+','.join(keys)+',created,updated) VALUES(?,'+','.join('?'*len(keys))+',?,?)',[kind]+[d[k] for k in keys]+[t,t]).lastrowid
    return pid,''
def can_publish(p):
    """고객 사례는 공개 동의 기록이 있어야 공개할 수 있다."""
    if p['kind']=='story' and not (p['consent'] and p['consent_by'] and p['consent_on'] and p['story_company']):
        return '고객 사례는 회사 이름, 동의한 분, 동의 받은 날을 적고 공개 동의를 체크해야 공개할 수 있어요'
    if not p['body'].strip():return '본문이 비어 있어요'
    return ''

def published(db,kind,category=None):
    sql='SELECT * FROM posts WHERE kind=? AND published=1';a=[kind]
    if category:sql+=' AND category=?';a.append(category)
    return db.execute(sql+' ORDER BY sort,published_at DESC,id DESC',a).fetchall()
def get(db,kind,slug):
    p=db.execute('SELECT * FROM posts WHERE kind=? AND slug=?',(kind,slug)).fetchone()
    if not p or (not p['published'] and not session.get('ops')):abort(404)
    return p

# ---------- 공개 화면 ----------
def page_ld(p,url,crumbs):
    """구조화 데이터: Article(+FAQPage) + BreadcrumbList."""
    org={'@type':'Organization','name':core.OPERATOR['name']}
    art={'@context':'https://schema.org','@type':'Article','headline':p['seo_title'] or p['title'],'description':p['seo_desc'] or p['summary'],'inLanguage':'ko',
         'datePublished':(p['published_at'] or p['created'])[:10],'dateModified':p['updated'][:10],'mainEntityOfPage':url,'publisher':org,'author':org}
    if p['cover']:art['image']=core.site_url('biz',p['cover'])
    out=[art,{'@context':'https://schema.org','@type':'BreadcrumbList','itemListElement':[{'@type':'ListItem','position':i+1,'name':n,'item':u} for i,(n,u) in enumerate(crumbs)]}]
    if p['kind']=='help' and p['category']=='자주 묻는 질문':
        qa=faq_pairs(p['body'])
        if qa:out.append({'@context':'https://schema.org','@type':'FAQPage','mainEntity':[{'@type':'Question','name':q,'acceptedAnswer':{'@type':'Answer','text':a}} for q,a in qa]})
    return Markup(json.dumps(out,ensure_ascii=False).replace('</','<\\/'))

def show(kind,slug,tpl):
    with conn() as db:
        p=get(db,kind,slug)
        more=[x for x in published(db,kind,p['category']) if x['id']!=p['id']][:4]
    home={'blog':'cms.blog','help':'cms.help_home','story':'cms.stories'}[kind]
    url=core.site_url('biz',request.path)
    crumbs=[(core.BNAME,core.site_url('biz','/')),(KINDS[kind],core.site_url('biz',url_for(home))),(p['title'],url)]
    return render_template(tpl,p=p,body=render(p['body']),more=more,ld=page_ld(p,url,crumbs),yt=youtube_id(p['video_url']),mins=reading_min(p['body']),
                           KINDS=KINDS,home=home,tab=home)

@bp.route('/blog')
def blog():
    cat=request.args.get('c') if request.args.get('c') in CATS['blog'] else None
    with conn() as db:rows=published(db,'blog',cat)
    return render_template('p_list.html',kind='blog',rows=rows,cat=cat,cats=CATS['blog'],title='자료실',lead='쇼핑몰 CS를 더 잘하는 방법을 정리해요.',tab='cms.blog')
@bp.route('/blog/<slug>')
def blog_post(slug):return show('blog',slug,'p_post.html')

@bp.route('/help')
def help_home():
    q=clean(request.args.get('q'),40)
    with conn() as db:rows=published(db,'help')
    if q:rows=[r for r in rows if q.lower() in (r['title']+' '+r['summary']+' '+r['body']).lower()]
    groups=[(c,[r for r in rows if r['category']==c]) for c in CATS['help']]
    return render_template('p_help.html',groups=[g for g in groups if g[1]],q=q,n=len(rows),tab='cms.help_home')
@bp.route('/help/<slug>')
def help_post(slug):return show('help',slug,'p_post.html')

@bp.route('/customers')
def stories():
    with conn() as db:rows=published(db,'story')
    return render_template('p_list.html',kind='story',rows=rows,cat=None,cats=[],title='고객 사례',lead='소보루 CS를 쓰는 회사의 실제 이야기예요. 회사가 공개에 동의한 사례만 올려요.',tab='cms.stories')
@bp.route('/customers/<slug>')
def story(slug):return show('story',slug,'p_post.html')

@bp.route('/media/<name>')
def media(name):
    if not re.fullmatch(r'[0-9a-f]{24}\.(png|jpe?g|webp)',name):abort(404)
    p=MEDIA/name
    if not p.exists():abort(404)
    r=send_file(p,mimetype=IMG_EXT[p.suffix],max_age=86400*30);return r

def nav():return [('cms.help_home','도움말')]  # 자료실·고객 사례는 아래쪽 링크에 (위 메뉴가 넘치지 않게)
def sitemap_entries():
    """(경로, 마지막 수정일)"""
    out=[('/blog',''),('/help',''),('/customers','')]
    with conn() as db:
        for p in db.execute('SELECT kind,slug,updated FROM posts WHERE published=1').fetchall():
            out.append(({'blog':'/blog/','help':'/help/','story':'/customers/'}[p['kind']]+p['slug'],p['updated'][:10]))
    return out

# ---------- 운영 화면 ----------
def ops_only():
    if not session.get('ops'):return redirect(url_for('ops_login'))
@bp.route('/ops/content')
def ops_list():
    g=ops_only()
    if g:return g
    kind=request.args.get('k','blog')
    if kind not in KINDS:kind='blog'
    with conn() as db:
        rows=db.execute('SELECT * FROM posts WHERE kind=? ORDER BY published,sort,id DESC',(kind,)).fetchall()
        n={k:db.execute('SELECT COUNT(*) FROM posts WHERE kind=?',(k,)).fetchone()[0] for k in KINDS}
    return render_template('o_content.html',rows=rows,kind=kind,n=n,KINDS=KINDS,n_signup=n_waiting(),otab='content')
@bp.route('/ops/content/new',methods=['GET','POST'])
@bp.route('/ops/content/<int:pid>',methods=['GET','POST'])
def ops_edit(pid=None):
    g=ops_only()
    if g:return g
    with conn() as db:
        post=db.execute('SELECT * FROM posts WHERE id=?',(pid,)).fetchone() if pid else None
        if pid and not post:abort(404)
        kind=post['kind'] if post else (request.values.get('kind') if request.values.get('kind') in KINDS else 'blog')
        if request.method=='POST':
            act=request.form.get('act','save')
            if act=='delete' and post:
                db.execute('DELETE FROM posts WHERE id=?',(post['id'],));flash('글을 지웠어요','ok');return redirect(url_for('cms.ops_list',k=post['kind']))
            if act in ('publish','unpublish') and post:
                if act=='publish':
                    err=can_publish(post)
                    if err:flash(err,'error');return redirect(url_for('cms.ops_edit',pid=post['id']))
                    db.execute("UPDATE posts SET published=1,published_at=CASE published_at WHEN '' THEN ? ELSE published_at END WHERE id=?",(core.iso(),post['id']));flash('공개했어요','ok')
                else:db.execute('UPDATE posts SET published=0 WHERE id=?',(post['id'],));flash('비공개로 바꿨어요','ok')
                return redirect(url_for('cms.ops_edit',pid=post['id']))
            pid2,err=save(db,request.form,request.files,post)
            if err:flash(err,'error');return render_template('o_content_edit.html',p=dict(request.form,kind=kind,id=pid,cover=post['cover'] if post else '',published=post['published'] if post else 0),kind=kind,CATS=CATS,KINDS=KINDS,n_signup=n_waiting(),otab='content'),400
            p2=db.execute('SELECT * FROM posts WHERE id=?',(pid2,)).fetchone()
            if p2['published'] and can_publish(p2):db.execute('UPDATE posts SET published=0 WHERE id=?',(pid2,));flash(can_publish(p2)+' 그래서 비공개로 바꿨어요','error')
            else:flash('저장했어요','ok')
            return redirect(url_for('cms.ops_edit',pid=pid2))
    return render_template('o_content_edit.html',p=post or {'kind':kind},kind=kind,CATS=CATS,KINDS=KINDS,n_signup=n_waiting(),otab='content')
def n_waiting():
    import onboard
    with conn() as db:return db.execute('SELECT COUNT(*) FROM companies WHERE '+onboard.WAITING_SQL).fetchone()[0]
@bp.route('/ops/content/preview',methods=['POST'])
def ops_preview():
    if not session.get('ops'):abort(403)
    return {'html':str(render(request.form.get('body','')))}

# ---------- 처음 도움말 (실제 기능 그대로) ----------
SEED_HELP=[
 ('start','시작하기','가입하고 바로 쓰기','가입하면 운영자 승인 없이 바로 작업 공간이 생겨요. 무엇이 바로 되고, 무엇이 회사 인증 뒤에 열리는지 정리했어요.',
  """## 가입하면 바로 되는 것
- 처음 설정 도우미(8단계), 데모, 자동 처리 규칙, AI 상담 설정, 직원 초대, 직접 등록한 문의 처리

## 회사 인증 뒤에 열리는 것
- 소비자가 우리 회사로 접수한 요청 받기
- 카페24·판매처 연결 (실제 고객 정보를 가져오는 일이라서요)

## 회사 인증은 어떻게 되나요
1. 가입할 때 적은 로그인 이메일로 온 확인 메일의 링크를 눌러요.
2. 사업자번호가 국세청에 '계속사업자'로 확인되면 자동으로 인증이 끝나요.
3. 자동 확인이 안 되면 운영팀이 사업자 정보를 확인해 인증해 드려요.

> 사업자번호가 맞는지와, 가입한 분이 그 회사 사람인지는 따로 확인해요. 같은 사업자번호로는 한 번만 가입할 수 있고, 직원은 대표가 팀 화면에서 초대해요."""),
 ('setup','처음 설정','처음 설정 8단계','기업 정보부터 시험 문의 처리까지, 처음 설정 도우미의 8단계를 설명해요.',
  """처음 설정은 단계마다 저장돼요. 중간에 나가도 다음에 이어서 할 수 있어요.

1. **기업 정보**: 업종, 대표 연락처
2. **쇼핑몰 종류**: 카페24, 자사몰 등
3. **고객센터 정보**: 고객에게 보일 연락처, 상담 시간, 알림 받을 이메일
4. **교환·반품·환불 정책**: 배송 정책, 반품 규정, 반품 주소, 택배사
5. **판매처 연결**: 회사 인증 뒤에 할 수 있어요. 나중에 하기를 눌러도 돼요
6. **AI 상담 설정**: 회사 소개, AI가 답할 범위, 담당자에게 넘길 때
7. **위젯 설치**: 쇼핑몰에 문의하기 버튼 붙이기
8. **시험 문의 처리**: 시험 문의를 만들고 직접 답해 보기 (고객에게는 아무것도 나가지 않아요)"""),
 ('ai','AI 상담','AI 상담 설정하기','AI가 우리 회사 정보로 고객에게 먼저 답하도록 설정하는 방법이에요.',
  """## 어디서 설정하나요
자동 처리 화면의 **AI 상담** 칸이에요.

## 무엇을 넣나요
- 회사·브랜드 소개, 상담 시간, 배송 정책, 교환·반품 규정
- AI가 상담할 범위, 자주 묻는 질문, 담당자에게 넘길 때, 응대 지침
- 상품 정보(가격, 재고, 사용법). PDF로 한꺼번에 올릴 수도 있어요

## 알아 두세요
- 가격·재고·배송·반품 정책처럼 우리 가게만의 사실은 넣어 둔 정보로만 답해요. 없으면 지어내지 않고 담당자 확인을 안내해요.
- 환불·취소·교환처럼 사람이 처리할 일, 불량·파손, 강한 불만은 담당자에게 넘기고 요약을 남겨요.
- AI는 주문 조회·환불 승인·주문 취소를 직접 하지 않아요.
- 효능을 단정하거나 법적 판단을 하지 않도록 응대 지침에 적어 두세요.
- AI 상담은 운영팀이 AI 키를 연결해야 켜져요."""),
 ('smartstore','판매처 연동','스마트스토어 연결하기','네이버 커머스API센터에서 키를 발급받아 스마트스토어 문의와 주문을 가져오는 방법이에요.',
  """1. 네이버 커머스API센터에 판매자 계정으로 로그인해요.
2. 애플리케이션을 등록해요 (판매자 직접 사용).
3. API 호출 IP에 소보루 서버 IP를 넣어요. IP는 서비스 연동 > 스마트스토어 화면에 있어요.
4. 애플리케이션 ID와 시크릿을 소보루 서비스 연동 화면에 넣어요.

연결하면 답하지 않은 고객 문의와 주문을 10분마다 가져와요. 키는 암호화해서 저장하고 화면에는 끝 4자리만 보여요.

> 회사 인증이 끝나야 연결할 수 있어요."""),
 ('coupang','판매처 연동','쿠팡 연결하기','쿠팡 Wing에서 OPEN API 키를 발급받아 쿠팡 문의와 주문을 가져오는 방법이에요.',
  """1. 쿠팡 Wing > 판매자 정보 > 추가판매정보에서 OPEN API 키를 발급해요.
2. 허용 IP에 소보루 서버 IP를 넣어요.
3. 업체코드, Access Key, Secret Key를 소보루 서비스 연동 화면에 넣어요.

쿠팡 키는 발급 후 실제로 쓸 수 있을 때까지 하루 정도 걸릴 수 있어요."""),
 ('rules','자동 처리','자동 처리 규칙 만들기','배송 조회처럼 자주 오는 요청을 들어오는 즉시 처리하는 방법이에요.',
  """## 이렇게 동작해요
유형마다 자동 처리를 켜 두면, 그 유형의 요청이 들어오는 즉시 정해 둔 조치와 답변이 나가요.

## 조건 붙이기
교환·반품처럼 상황에 따라 다른 유형은 '자동 처리 조건'을 정할 수 있어요.

## 보상
유형별로 보상(예: 적립금)을 정해 두면, 사장님이 승인할 때 고객에게 안내돼요."""),
 ('team','직원·권한','직원 초대와 역할','팀 화면에서 직원을 초대하고 역할을 정하는 방법이에요. 직원 수로 요금을 받지 않아요.',
  """## 역할
- **대표**: 가입한 계정. 모든 권한
- **관리자**: 대표와 같은 권한 (설정·자동 처리·연동·팀)
- **상담원**: 답변·자료 요청·보류·메모·담당자 배정. 승인·보상·환불 완료는 못 해요
- **보기 전용**: 화면만 봐요

## 초대
팀 화면에서 이름·이메일·역할을 적으면 초대 메일이 가요. 메일을 보낼 수 없으면 초대 링크를 직접 전해 주세요. 링크는 72시간 동안 한 번만 쓸 수 있어요.

## 담당자와 내부 메모
요청마다 담당자를 정하고, 고객에게 보이지 않는 내부 메모를 남겨요. 메모에 @이름을 쓰면 그 직원에게 알림 메일이 가요."""),
 ('faq','자주 묻는 질문','자주 묻는 질문','요금, 데이터, 판매처 연결에 대해 자주 묻는 질문이에요.',
  """### 요금은 얼마인가요?
지금은 무료 시범으로 기간·건수 제한 없이 쓸 수 있어요. 요금제가 생기면 미리 알려 드리고, 동의 없이 바뀌지 않아요.

### 직원 수에 따라 요금이 오르나요?
아니요. 직원 수로 요금을 받지 않아요.

### 데모에서 한 일이 실제 고객에게 가나요?
아니요. 데모는 회사마다 따로 만든 견본 공간이라 실제 고객·주문·환불과 완전히 나뉘어 있어요.

### 판매처 키는 안전한가요?
키는 서버 비밀키로 암호화해서 저장하고, 화면에는 끝 4자리만 보여요. 연결을 끊으면 저장한 키도 지워요.

### 카페24도 연결되나요?
네. 서비스 연동 > 카페24에서 쇼핑몰 아이디를 넣고 카페24 관리자로 로그인해 권한에 동의하면 주문·상품·게시판 문의를 자동으로 가져오고, 단순 문의엔 AI가 답글로 답해요."""),
]
def seed(db):
    t=core.iso()
    for i,(slug,cat,title,summary,body) in enumerate(SEED_HELP):
        db.execute('INSERT OR IGNORE INTO posts(kind,slug,title,summary,body,category,published,published_at,sort,created,updated) VALUES(?,?,?,?,?,?,1,?,?,?,?)',
                   ('help',slug,title,summary,body,cat,t,i,t,t))

init()
