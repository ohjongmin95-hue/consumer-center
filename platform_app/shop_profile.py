"""가게 프로필: 고객이 상담창에서 보는 로고·이름·안내사항·첫인사 (채널톡 '채널 프로필'처럼).

로고는 정사각형 256px webp로 줄여 UPLOAD/logos/<회사 id>.webp에 둔다. 누구나 볼 수 있는 그림이라
상담창(consumer 앱)과 사장님 화면(business 앱) 둘 다 /logo/<id>.webp 로 보여 준다.
"""
import io, time
from flask import send_file, abort
import core
from core import conn, clean

DIR=core.UPLOAD/'logos'
DIR.mkdir(parents=True,exist_ok=True)
MAX_BYTES=5*1024*1024
SIZE=256
NAME_MAX=30
NOTICE_MAX=200
GREET_MAX=120

def init():
    with conn() as db:
        cols={r[1] for r in db.execute('PRAGMA table_info(companies)')}
        for col in ('shop_logo','shop_title','shop_notice','shop_greet'):
            if col not in cols:db.execute(f"ALTER TABLE companies ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
init()

def _get(co,k):
    try:return co[k] or ''
    except (KeyError,IndexError):return ''
def title(co):return _get(co,'shop_title') or co['name']
def notice(co):return _get(co,'shop_notice')
def greet(co):return _get(co,'shop_greet') or f'안녕하세요, {title(co)} 고객센터예요.\n어떤 일인지 편하게 적어 주시거나 아래에서 골라 주세요.'
def logo_ver(co):return _get(co,'shop_logo')
def path(co_id):return DIR/f'{int(co_id)}.webp'

def save_logo(raw):
    """올린 그림을 가운데 정사각형으로 잘라 256px webp 바이트로. 그림이 아니면 ValueError."""
    if not raw:raise ValueError('그림 파일을 골라 주세요')
    if len(raw)>MAX_BYTES:raise ValueError('그림은 5MB까지 올릴 수 있어요')
    from PIL import Image, ImageOps
    try:
        im=Image.open(io.BytesIO(raw));im.load()
    except Exception:raise ValueError('PNG·JPG 같은 그림 파일만 올릴 수 있어요')
    im=ImageOps.exif_transpose(im).convert('RGBA')
    w,h=im.size;s=min(w,h);im=im.crop(((w-s)//2,(h-s)//2,(w-s)//2+s,(h-s)//2+s)).resize((SIZE,SIZE),Image.LANCZOS)
    bg=Image.new('RGBA',im.size,(255,255,255,255));bg.alpha_composite(im)  # 투명 로고는 흰 바탕 위에
    out=io.BytesIO();bg.convert('RGB').save(out,'WEBP',quality=90);return out.getvalue()

def save(db,co,f,files):
    """설정 저장. -> (문구, 'ok'|'error')"""
    up=files.get('logo') if files else None
    ver=logo_ver(co)
    if str(f.get('logo_del'))=='1':
        try:path(co['id']).unlink()
        except FileNotFoundError:pass
        ver=''
    elif up and up.filename:
        try:data=save_logo(up.read(MAX_BYTES+1))
        except ValueError as e:return str(e),'error'
        path(co['id']).write_bytes(data);ver=str(int(time.time()))
    name=clean(f.get('shop_title'),NAME_MAX)
    if name==co['name']:name=''
    db.execute('UPDATE companies SET shop_logo=?,shop_title=?,shop_notice=?,shop_greet=? WHERE id=?',
        (ver,name,clean(f.get('shop_notice'),NOTICE_MAX),clean(f.get('shop_greet'),GREET_MAX),co['id']))
    return '가게 프로필을 저장했어요. 상담창에 바로 보여요','ok'

def serve(company_id):
    p=path(company_id)
    if not p.exists():abort(404)
    r=send_file(p,mimetype='image/webp',max_age=86400);return r

def register(app):
    """두 앱 모두에 /logo/<id>.webp 와 템플릿 함수를 단다."""
    app.add_url_rule('/logo/<int:company_id>.webp','shop_logo',serve)
    if 'favicon' not in app.view_functions:app.add_url_rule('/favicon.ico','favicon',lambda:app.send_static_file('favicon.ico'))  # 브라우저가 따로 찾는 탭 아이콘 (소보루CX 심벌)
    app.jinja_env.globals.update(shop_title=title,shop_notice=notice,shop_greet=greet,shop_logo_ver=logo_ver,css_ver=lambda name='hanq.css':css_ver(app,name))

def css_ver(app,name):
    """정적 파일 캐시 번호 = 파일 바뀐 시각. 서버에 새 파일이 올라가면 브라우저가 알아서 새로 받는다."""
    import os
    try:return int(os.path.getmtime(os.path.join(app.static_folder,name)))
    except OSError:return 0
