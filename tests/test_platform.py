"""SOBORU 플랫폼(platform_app): 한큐 접수 → 기업 승인·자동 처리 → 소비자 확인, 비입점 처리, 권한."""
import json, os, re, sys, secrets, tempfile, unittest, importlib
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from werkzeug.test import Client

ROOT=Path(__file__).resolve().parents[1]


class PlatformTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.ops_pw=secrets.token_urlsafe(16)
        cls.env=patch.dict(os.environ,{'PLATFORM_DATABASE_PATH':str(Path(cls.temp.name)/'p.sqlite3'),'PLATFORM_UPLOAD_DIR':str(Path(cls.temp.name)/'up'),
            'SECRET_KEY':secrets.token_hex(16),'OPS_PASSWORD_HASH':generate_password_hash(cls.ops_pw),'CONSUMER_HOST':'','BUSINESS_HOST':'','PLATFORM_MODE':'pilot'})
        cls.env.start()
        sys.path.insert(0,str(ROOT/'platform_app'))
        for m in ('core','consumer','business','hanq','law','insights','drafting'):sys.modules.pop(m,None)
        cls.hanq=importlib.import_module('hanq');cls.core=sys.modules['core']
        cls.core.MAIL_ASYNC=False
        cls.real_throttled=staticmethod(cls.core.throttled);cls.core.throttled=lambda *a,**k:False  # 횟수 제한은 아래 테스트에서 따로 확인
        for a in (sys.modules['consumer'].app,sys.modules['business'].app):a.config['TESTING']=True

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(ROOT/'platform_app'))
        for m in ('core','consumer','business','hanq','law','insights','drafting'):sys.modules.pop(m,None)
        cls.env.stop();cls.temp.cleanup()

    def client(self):return Client(self.hanq.app)
    def csrf(self,c,path):
        r=c.get(path);m=re.search(r'name="csrf" value="([^"]+)"',r.get_data(as_text=True));self.assertTrue(m,path);return m.group(1)
    def post(self,c,path,data,form_path=None,**kw):
        data=dict(data,csrf=self.csrf(c,form_path or path));return c.post(path,data=data,**kw)

    def signup_and_approve(self,name,email):
        b=self.client()
        r=self.post(b,'/biz/signup',{'name':name,'biz_no':'123-45-67890','owner_name':'대표','phone':'010-1111-2222','contact':'1588-0000','login_id':email,'password':'longpassword1','terms':'1'})
        self.assertIn('가입 신청했습니다',r.get_data(as_text=True))
        r=self.post(b,'/biz/login',{'login_id':email,'password':'longpassword1'})
        self.assertIn('승인을 기다리고',r.get_data(as_text=True))
        o=self.client();self.post(o,'/biz/ops/login',{'password':self.ops_pw})
        with self.core.conn() as db:cid=db.execute('SELECT id FROM companies WHERE login_id=?',(email,)).fetchone()[0]
        self.post(o,'/biz/ops/companies',{'act':'approve','id':cid})
        r=self.post(b,'/biz/login',{'login_id':email,'password':'longpassword1'})
        self.assertEqual(r.status_code,302)
        # 같은 브라우저에서 운영 화면에 로그인해도 기업 로그인이 풀리지 않는다
        self.post(b,'/biz/ops/login',{'password':self.ops_pw})
        self.assertEqual(b.get('/biz/').status_code,200);self.assertEqual(b.get('/biz/ops').status_code,200)
        return b,o,cid

    def file_case(self,c,company,cat,company_id='',consent='1',**extra):
        data={'company':company,'company_id':company_id,'category':cat,'title':extra.get('title','크림 용기가 깨져서 왔어요'),'body':'10월 7일 주문한 크림 용기가 깨져서 도착했어요.',
              'want':'교환','name':'김소비','phone':'010-1234-5678','password':'1234','privacy':'1'}
        if consent:data['consent']='1'
        if extra.get('received_on'):data['received_on']=extra['received_on']
        elif cat in ('교환','반품·환불'):data['received_on']=__import__('datetime').date.today().isoformat()
        r=self.post(c,'/submit',data,'/new')
        self.assertEqual(r.status_code,302,r.get_data(as_text=True)[:300])
        return int(r.headers['Location'].rstrip('/').split('/')[-1])

    def test_app_api(self):
        """소보루 CS 앱 API: 쿠키 없이 요청별 토큰으로 접수·조회·답변 확인·알림 등록."""
        b,o,cid=self.signup_and_approve('앱테스트상점','apptest@example.com')
        a=self.client()
        meta=a.get('/api/v1/meta').get_json();self.assertEqual(meta['cats'][0],{'name':'배송 조회','hint':'배송이 안 오거나 늦어요'})
        self.assertEqual(a.get('/api/v1/companies?q=앱테스트').get_json()[0]['id'],cid)
        self.assertTrue(a.get(f'/api/v1/companies/{cid}').get_json()['member'])
        self.assertEqual(a.post(f'/api/v1/chat/{cid}',json={'text':'택배가 아직 안 왔어요'}).get_json()['category'],'배송 조회')
        bad=a.post('/api/v1/cases',json={'company':'앱테스트상점','category':'제품 불량','title':'x','body':'짧음'})
        self.assertEqual(bad.status_code,400);self.assertIn('10자',bad.get_json()['error'])
        r=a.post('/api/v1/cases',json={'company':'앱테스트상점','company_id':cid,'category':'제품 불량','title':'앱에서 접수','body':'앱으로 접수한 불량 요청 내용이에요.',
            'want':'교환','phone':'010-5555-6666','password':'abcd','privacy':True,'consent':True})
        self.assertEqual(r.status_code,201,r.get_data(as_text=True));j=r.get_json();case_id,tok=j['id'],j['token']
        auth={'Authorization':'Bearer '+tok}
        d=a.get(f'/api/v1/cases/{case_id}',headers=auth).get_json()
        self.assertEqual(d['status'],'forwarded');self.assertTrue(d['can']['cancel']);self.assertNotIn('phone',d)
        self.assertEqual(a.get(f'/api/v1/cases/{case_id}').status_code,404)  # 토큰 없이는 못 연다
        other=self.file_case(self.client(),'앱테스트상점','기타',str(cid))
        self.assertEqual(a.get(f'/api/v1/cases/{other}',headers=auth).status_code,404)  # 다른 요청은 못 연다
        self.assertEqual([c['id'] for c in a.post('/api/v1/mine',json={'tokens':[tok,'garbage']}).get_json()['cases']],[case_id])
        self.assertEqual(a.post('/api/v1/lookup',json={'phone':'01055556666','password':'nope'}).status_code,404)
        found=a.post('/api/v1/lookup',json={'phone':'01055556666','password':'abcd'}).get_json()['cases']
        self.assertEqual(found[0]['id'],case_id);self.assertEqual(a.get(f"/api/v1/cases/{case_id}?t={found[0]['token']}").status_code,200)
        self.assertEqual(a.post('/api/v1/push',json={'push_token':'nope','tokens':[tok]}).status_code,400)
        self.assertEqual(a.post('/api/v1/push',json={'push_token':'ExponentPushToken[abc123]','tokens':[tok]}).get_json()['cases'],1)
        sent=[]
        class R:
            def __init__(s,req):sent.append(req)
            def read(s):return b'{"data":[{"status":"ok"}]}'
            def __enter__(s):return s
            def __exit__(s,*x):pass
        with patch.object(self.core.urllib.request,'urlopen',lambda req,timeout=0:R(req)):
            self.post(b,f'/biz/case/{case_id}',{'act':'reply','msg':'새 상품으로 보내 드릴게요.'})
        self.assertTrue(any('exp.host' in q.full_url for q in sent))
        d=a.get(f'/api/v1/cases/{case_id}',headers=auth).get_json()
        self.assertEqual(d['status'],'answered');self.assertIn('새 상품으로 보내 드릴게요.',[e['reply'] for e in d['events']])
        r=a.post(f'/api/v1/cases/{case_id}',headers=auth,json={'act':'rate','v':'resolved'})
        self.assertEqual(r.get_json()['status'],'resolved')
        self.assertEqual(a.post(f'/api/v1/cases/{case_id}',headers=auth,json={'act':'ship','courier':'x','tracking':'1'}).status_code,200)  # 반품 안내가 없으면 그냥 무시

    def test_biz_app_api(self):
        """사장님 앱 API: 로그인 토큰으로 승인 대기 확인·승인·답변·알림 등록, 비밀번호를 바꾸면 토큰이 끊긴다."""
        b,o,cid=self.signup_and_approve('사장앱상점','bizapp@example.com')
        a=self.client()
        self.assertEqual(a.post('/biz/api/v1/login',json={'login_id':'bizapp@example.com','password':'wrong-password'}).status_code,400)
        j=a.post('/biz/api/v1/login',json={'login_id':'bizapp@example.com','password':'longpassword1'}).get_json()
        tok=j['token'];auth={'Authorization':'Bearer '+tok};self.assertEqual(j['company']['id'],cid)
        self.assertEqual(a.get('/biz/api/v1/home').status_code,401)
        case_id=self.file_case(self.client(),'사장앱상점','교환',str(cid))
        h=a.get('/biz/api/v1/home',headers=auth).get_json()
        self.assertEqual([c['id'] for c in h['pending']],[case_id]);self.assertEqual(h['counts']['pending'],1)
        d=a.get(f'/biz/api/v1/cases/{case_id}',headers=auth).get_json()
        self.assertEqual(d['status'],'seen');self.assertTrue(d['can']['approve']);self.assertTrue(d['plan']['reply'])
        other_b,_,other_cid=self.signup_and_approve('남의상점','other@example.com')
        other=self.file_case(self.client(),'남의상점','기타',str(other_cid))
        self.assertEqual(a.get(f'/biz/api/v1/cases/{other}',headers=auth).status_code,404)  # 다른 회사 요청은 못 연다
        self.assertEqual(a.post(f'/biz/api/v1/cases/{case_id}',headers=auth,json={'act':'reply','msg':''}).status_code,400)
        d=a.post(f'/biz/api/v1/cases/{case_id}',headers=auth,json={'act':'approve'}).get_json()
        self.assertEqual(d['decision'],'approved');self.assertEqual(d['message'],'승인했습니다');self.assertFalse(d['can']['approve'])
        self.assertEqual(a.post('/biz/api/v1/push',headers=auth,json={'push_token':'ExponentPushToken[biz1]'}).get_json(),{'ok':True})
        sent=[]
        class R:
            def __init__(s,req):sent.append(req)
            def read(s):return b'{"data":[{"status":"ok"}]}'
            def __enter__(s):return s
            def __exit__(s,*x):pass
        with patch.object(self.core.urllib.request,'urlopen',lambda req,timeout=0:R(req)):
            self.file_case(self.client(),'사장앱상점','기타',str(cid))
        self.assertTrue(any(b'ExponentPushToken[biz1]' in q.data for q in sent if 'exp.host' in q.full_url))
        a.post('/biz/api/v1/logout',headers=auth,json={'push_token':'ExponentPushToken[biz1]'})
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM biz_push').fetchone()[0],0)
        with self.core.conn() as db:db.execute('UPDATE companies SET pw_hash=? WHERE id=?',(generate_password_hash('newpassword99'),cid))
        self.assertEqual(a.get('/biz/api/v1/home',headers=auth).status_code,401)  # 비밀번호를 바꾸면 예전 토큰은 끊긴다

    def test_biz_search_registration(self):
        c=self.client()
        robots=c.get('/biz/robots.txt').get_data(as_text=True)
        self.assertIn('Sitemap: ',robots);self.assertIn('/sitemap.xml',robots)
        sm=c.get('/biz/sitemap.xml');self.assertEqual(sm.status_code,200);self.assertIn('/signup</loc>',sm.get_data(as_text=True))
        with patch.dict(self.core.GOOGLE_VERIFY,{'biz':'g-code'}),patch.dict(self.core.VERIFY,{'biz':'n-code'}),patch.dict(self.core.DAUM_ROBOTS,{'biz':'DaumWebMasterTool:abc'}):
            home=c.get('/biz/').get_data(as_text=True)
            self.assertIn('content="g-code"',home);self.assertIn('og-biz.png',home);self.assertIn('content="n-code"',home);self.assertIn('SoftwareApplication',home)
            self.assertTrue(c.get('/biz/robots.txt').get_data(as_text=True).startswith('#DaumWebMasterTool:abc'))

    def test_biz_terms_page(self):
        c=self.client()
        t=c.get('/biz/terms');self.assertEqual(t.status_code,200);page=t.get_data(as_text=True)
        self.assertIn('이용약관',page);self.assertIn('제1조',page);self.assertNotIn('noindex',page)
        self.assertIn('/biz/terms',c.get('/biz/signup').get_data(as_text=True))
        self.assertIn('/terms</loc>',c.get('/biz/sitemap.xml').get_data(as_text=True))

    def test_biz_app_inapp_pages(self):
        """앱 안 가입 신청·규칙·통계·설정·가이드: 웹과 같은 검사, 비밀번호를 바꾸면 새 토큰을 준다."""
        a=self.client()
        self.assertEqual(a.post('/biz/api/v1/signup',json={'name':'앱가입','biz_no':'123','owner_name':'김','login_id':'x@example.com','password':'longpassword1','terms':'1'}).status_code,400)
        j=a.post('/biz/api/v1/signup',json={'name':'앱가입','biz_no':'1234567890','owner_name':'김사장','login_id':'appjoin@example.com','password':'longpassword1','terms':True}).get_json()
        self.assertTrue(j['ok'])
        with self.core.conn() as db:self.assertEqual(db.execute("SELECT status FROM companies WHERE login_id='appjoin@example.com'").fetchone()[0],'pending')
        self.assertIn('승인을 기다리고',a.post('/biz/api/v1/login',json={'login_id':'appjoin@example.com','password':'longpassword1'}).get_json()['error'])
        b,o,cid=self.signup_and_approve('설정상점','appset@example.com')
        tok=a.post('/biz/api/v1/login',json={'login_id':'appset@example.com','password':'longpassword1'}).get_json()['token'];auth={'Authorization':'Bearer '+tok}
        r=a.get('/biz/api/v1/rules',headers=auth).get_json()
        self.assertEqual([x['category'] for x in r['rules']],self.core.CATS)
        r=a.post('/biz/api/v1/rules',headers=auth,json={'category':'배송 조회','auto':True}).get_json()
        self.assertTrue(next(x for x in r['rules'] if x['category']=='배송 조회')['auto'])
        self.assertEqual(a.post('/biz/api/v1/rules',headers=auth,json={'category':'없는유형'}).status_code,400)
        st=a.get('/biz/api/v1/stats',headers=auth).get_json();self.assertEqual(len(st['weeks']),8)
        s=a.post('/biz/api/v1/settings',headers=auth,json={'act':'return','return_address':'서울시 반품로 1','return_courier':'CJ대한통운'}).get_json()
        self.assertIn('서울시 반품로 1',s['return_guide'])
        self.assertEqual(a.post('/biz/api/v1/settings',headers=auth,json={'act':'password','old':'wrong','new':'newpassword99'}).status_code,400)
        s=a.post('/biz/api/v1/settings',headers=auth,json={'act':'password','old':'longpassword1','new':'newpassword99'}).get_json()
        self.assertEqual(a.get('/biz/api/v1/settings',headers=auth).status_code,401)
        self.assertEqual(a.get('/biz/api/v1/settings',headers={'Authorization':'Bearer '+s['token']}).status_code,200)  # 새 토큰으로 계속 쓴다
        g=a.get('/biz/api/v1/guide',headers={'Authorization':'Bearer '+s['token']}).get_json()
        self.assertTrue(g['guide'][0]['points'] and g['guide'][0]['laws'][0]['text'])
        A={'Authorization':'Bearer '+s['token']}
        self.assertEqual(a.post('/biz/api/v1/new',headers=A,json={'channel':'전화','category':'교환','title':'','body':'x','want':'교환'}).status_code,400)
        n=a.post('/biz/api/v1/new',headers=A,json={'channel':'전화','category':'교환','title':'사이즈 교환','body':'M을 L로','want':'교환'}).get_json()
        self.assertEqual(a.get(f"/biz/api/v1/cases/{n['id']}",headers=A).get_json()['title'],'사이즈 교환')
        rec=a.get(f"/biz/api/v1/cases/{n['id']}/record",headers=A).get_json();self.assertIn('사이즈 교환',rec['html']);self.assertNotIn('window.print',rec['html'])
        rp=a.get('/biz/api/v1/report',headers=A).get_json();self.assertEqual(len(rp['months']),12);self.assertIn('CS 리포트',rp['text'])
        self.assertIn('news',a.get('/biz/api/v1/news',headers=A).get_json())
        self.assertEqual(a.post('/biz/api/v1/leave',headers={'Authorization':'Bearer '+s['token']},json={'password':'newpassword99'}).status_code,200)

    def test_member_flow_pending_approve_and_rate(self):
        b,o,cid=self.signup_and_approve('달빛화장품','dalbit@example.com')
        me=self.client()
        self.assertIn('한 번에</em> 해결해요',me.get('/').get_data(as_text=True))
        self.assertEqual(me.get('/companies?q=달빛').get_json()[0]['name'],'달빛화장품')
        case_id=self.file_case(me,'달빛화장품','제품 불량',str(cid))
        self.assertIn('담당자에게 바로 전달됐어요',me.get(f'/done/{case_id}').get_data(as_text=True))
        # 기업: 승인 카드에 보이고, 승인하면 추천 조치 실행 + 답변
        page=b.get('/biz/').get_data(as_text=True)
        self.assertIn('승인할 요청이',page);self.assertIn('무상 교환',page);self.assertIn('달빛화장품',page)
        self.assertEqual(b.get('/biz/pending').status_code,302)
        self.assertIn('크림 용기',b.get('/biz/all?q=크림').get_data(as_text=True))
        self.assertNotIn('크림 용기',b.get('/biz/all?q=없는말').get_data(as_text=True))
        self.assertIn('주별 요청',b.get('/biz/stats').get_data(as_text=True))
        self.assertIn('value="제품 불량" checked',me.get('/new?category=제품 불량').get_data(as_text=True))
        self.assertEqual(me.get('/guide').status_code,200)
        r=self.post(b,f'/biz/case/{case_id}',{'act':'approve'})
        self.assertEqual(r.status_code,302)
        with self.core.conn() as db:c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        self.assertEqual((c['status'],c['decision']),('answered','approved'))
        page=me.get(f'/case/{case_id}').get_data(as_text=True)
        self.assertIn('답변이 도착했어요',page);self.assertIn('배송비 없이',page)
        self.post(me,f'/case/{case_id}',{'act':'rate','v':'unresolved'})
        page=me.get(f'/case/{case_id}').get_data(as_text=True)
        self.assertIn('1372 소비자상담센터',page)

    def test_auto_rule_and_info_request(self):
        b,o,cid=self.signup_and_approve('오늘배송마켓','today@example.com')
        self.post(b,'/biz/rules',{'category':'배송 조회','auto':'1'})
        me=self.client()
        case_id=self.file_case(me,'오늘배송마켓','배송 조회',title='배송이 안 와요')
        with self.core.conn() as db:c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        self.assertEqual((c['status'],c['decision']),('answered','auto'))
        self.assertIn('자동으로 바로 처리됐어요',me.get(f'/done/{case_id}').get_data(as_text=True))
        # 자동 처리 안 된 유형은 자료 요청 → 소비자 답장 → 다시 승인 대기
        case2=self.file_case(me,'오늘배송마켓','교환',title='교환 요청')
        self.post(b,f'/biz/case/{case2}',{'act':'ask'})
        self.assertIn('자료를 보내 주세요',me.get(f'/case/{case2}').get_data(as_text=True))
        self.post(me,f'/case/{case2}',{'act':'info','msg':'주문번호 A-1'})
        with self.core.conn() as db:c=db.execute('SELECT * FROM cases WHERE id=?',(case2,)).fetchone()
        self.assertEqual((c['status'],c['decision']),('seen','pending'))

    def test_products_and_ai_chat(self):
        """상품정보 등록(웹·CSV·앱)과, 키가 있으면 상담창이 회사 정보로 AI 답변을 하는지."""
        b,o,cid=self.signup_and_approve('상품마켓','products@example.com')
        r=self.post(b,'/biz/products',{'name':'보습 크림','price':'29,000원','stock':'있음','info':'하루 두 번 바르세요'},'/biz/rules',follow_redirects=True)
        self.assertIn('보습 크림',r.get_data(as_text=True))
        self.assertIn('이름을 적어',self.post(b,'/biz/products',{'name':''},'/biz/rules',follow_redirects=True).get_data(as_text=True))
        csv_=('상품명,가격,재고,안내\n보습 크림,31000원,품절,\n선크림,18000원,있음,SPF50\n').encode('cp949')
        from io import BytesIO
        r=self.post(b,'/biz/products',{'act':'csv','file':(BytesIO(csv_),'p.csv')},'/biz/rules',follow_redirects=True)
        self.assertIn('2개 상품을 저장',r.get_data(as_text=True))
        with self.core.conn() as db:ps={p['name']:p for p in self.core.products(db,cid)}
        self.assertEqual((ps['보습 크림']['price'],ps['보습 크림']['stock'],ps['선크림']['info']),('31000원','품절','SPF50'))
        # 앱: 목록·수정·삭제, 다른 회사 상품은 못 고친다
        tok=self.client().post('/biz/api/v1/login',json={'login_id':'products@example.com','password':'longpassword1'}).get_json()['token'];auth={'Authorization':'Bearer '+tok}
        a=self.client();j=a.get('/biz/api/v1/products',headers=auth).get_json();self.assertEqual(len(j['products']),2)
        pid=ps['선크림']['id']
        j=a.post('/biz/api/v1/products',json={'id':pid,'price':'19000원'},headers=auth).get_json();p=[x for x in j['products'] if x['id']==pid][0]
        self.assertEqual((p['name'],p['price'],p['stock']),('선크림','19000원','있음'))
        b2,_,_=self.signup_and_approve('남의마켓','other-products@example.com')
        self.assertIn('찾을 수 없',self.post(b2,'/biz/products',{'id':pid,'act':'delete'},'/biz/rules',follow_redirects=True).get_data(as_text=True))
        # 키가 없으면 예전처럼 유형 안내
        me=self.client();page=me.get(f'/to/{cid}').get_data(as_text=True);ctok=re.search(r'data-csrf="([^"]+)"',page).group(1)
        j=me.post(f'/chat/{cid}',data={'csrf':ctok,'text':'택배가 아직 안 왔어요'}).get_json()
        self.assertNotIn('answer',j);self.assertEqual(j['category'],'배송 조회')
        # 키가 있으면 AI가 회사 정보(상품 포함)를 보고 답한다
        seen={}
        def fake(system,messages,**k):seen.update(system=system,messages=messages);return '{"category": null, "answer": "선크림은 19000원이에요."}'
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'test'}),patch.object(sys.modules['drafting'],'call',fake):
            hist=json.dumps([{'who':'bot','text':'안녕하세요'},{'who':'me','text':'선크림 있어요?'},{'who':'bot','text':'네, 있어요.'}])
            j=me.post(f'/chat/{cid}',data={'csrf':ctok,'text':'얼마예요?','history':hist}).get_json()
        self.assertEqual((j['answer'],j['category']),('선크림은 19000원이에요.',None))
        self.assertIn('선크림 / 가격 19000원',seen['system']);self.assertIn('보습 크림 / 가격 31000원 / 품절',seen['system'])
        self.assertEqual([m['role'] for m in seen['messages']],['user','assistant','user']);self.assertEqual(seen['messages'][-1]['content'],'얼마예요?')
        # AI가 실패하면 기본 안내로 돌아간다
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'test'}),patch.object(sys.modules['drafting'],'call',lambda *a,**k:None):
            j=me.post(f'/chat/{cid}',data={'csrf':ctok,'text':'환불하고 싶어요'}).get_json()
        self.assertNotIn('answer',j);self.assertEqual(j['category'],'반품·환불')

    def test_chat_and_conditional_auto(self):
        import datetime
        b,o,cid=self.signup_and_approve('상담창마켓','chat@example.com')
        self.assertEqual(self.core.classify('주문한 게 아직 안 왔어요'),'배송 조회')
        self.assertEqual(self.core.classify('깨져서 왔어요 환불해 주세요'),'제품 불량')
        self.assertIsNone(self.core.classify('안녕하세요'))
        self.post(b,'/biz/rules',{'category':'반품·환불','faq':'우리 회사 반품 안내예요.'})
        self.post(b,'/biz/rules',{'category':'반품·환불','auto':'1'})
        self.post(b,'/biz/rules',{'category':'반품·환불','cond':'within7'})
        me=self.client()
        page=me.get(f'/to/{cid}').get_data(as_text=True);self.assertIn('id="cb"',page)
        self.assertIn(f'/to/{cid}',b.get('/biz/').get_data(as_text=True))  # 기업 홈에서 바로 복사하는 고객센터 링크
        tok=re.search(r'data-csrf="([^"]+)"',page).group(1)
        j=me.post(f'/chat/{cid}',data={'csrf':tok,'text':'마음에 안 들어서 환불하고 싶어요'}).get_json()
        self.assertEqual((j['category'],j['faq'],j['auto'],j['cond'],j['ask_days']),('반품·환불','우리 회사 반품 안내예요.',True,'within7',True))
        self.assertIsNone(me.post(f'/chat/{cid}',data={'csrf':tok,'text':'안녕'}).get_json()['category'])
        me.post(f'/chat/{cid}',data={'csrf':tok,'outcome':'solved','category':'반품·환불'})
        self.assertIn('<dd>1</dd>',b.get('/biz/rules').get_data(as_text=True))
        # 상담창에서 쓴 문장이 접수 화면에 이어진다
        self.assertIn('환불하고 싶어요',me.get(f'/new?company_id={cid}&category=반품·환불&body=환불하고 싶어요').get_data(as_text=True))
        # 조건: 받은 지 7일 이내만 자동 처리, 지났거나 모르면 승인 대기
        today=datetime.date.today()
        ok=self.file_case(me,'상담창마켓','반품·환불',company_id=str(cid),received_on=(today-datetime.timedelta(days=2)).isoformat())
        late=self.file_case(me,'상담창마켓','반품·환불',company_id=str(cid),received_on=(today-datetime.timedelta(days=10)).isoformat())
        with self.core.conn() as db:d={r['id']:r['decision'] for r in db.execute('SELECT id,decision FROM cases WHERE id IN (?,?)',(ok,late))}
        self.assertEqual((d[ok],d[late]),('auto','pending'))
        # 환불 계좌: 고객이 등록 -> 기업이 보고 환불 완료 -> 계좌 정보는 지워진다
        self.assertIn('환불 받을 계좌',me.get(f'/case/{ok}').get_data(as_text=True))
        self.post(me,f'/case/{ok}',{'act':'refund','bank':'카카오뱅크','account':'3333-01-2345678','holder':'김소비'})
        self.assertIn('*******5678',me.get(f'/case/{ok}').get_data(as_text=True))
        self.assertIn('3333012345678',b.get(f'/biz/case/{ok}').get_data(as_text=True))
        self.post(b,f'/biz/case/{ok}',{'act':'refund_done'})
        with self.core.conn() as db:r=db.execute('SELECT refund_status,refund_account,refund_holder FROM cases WHERE id=?',(ok,)).fetchone()
        self.assertEqual(tuple(r),('done','',''))
        self.assertNotIn('3333012345678',b.get(f'/biz/case/{ok}').get_data(as_text=True))

    def test_review_fixes(self):
        import datetime
        b,o,cid=self.signup_and_approve('검토마켓','review@example.com')
        me=self.client()
        # 자동 답변이 하지 않는 일(기사 방문, 도착 예정일)을 약속하지 않는다
        for cat,pb in self.core.PLAYBOOK.items():self.assertNotIn('기사님',pb['reply']);self.assertNotIn('도착 예정',pb['reply'])
        # 교환·반품은 받은 날이 꼭 필요
        r=self.post(me,'/submit',{'company':'검토마켓','category':'교환','title':'교환','body':'사이즈가 작아서 교환하고 싶어요','want':'교환','phone':'010-1234-5678','password':'1234','privacy':'1','consent':'1'},'/new')
        self.assertIn('/new',r.headers['Location'])
        # 고객에게 보이는 기록에 답변 목표일이 없다
        c1=self.file_case(me,'검토마켓','배송 조회',company_id=str(cid),title='배송이 안 와요')
        self.assertNotIn('목표일',me.get(f'/case/{c1}').get_data(as_text=True))
        # 접수 취소
        self.post(me,f'/case/{c1}',{'act':'cancel'})
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT status FROM cases WHERE id=?',(c1,)).fetchone()[0],'withdrawn')
        # 같은 유형 한 번에 승인 -> 답변 후 7일 응답 없으면 자동 종료
        a=self.file_case(me,'검토마켓','배송 조회',company_id=str(cid));bb=self.file_case(me,'검토마켓','배송 조회',company_id=str(cid))
        self.assertIn('배송 조회 2건 모두 승인',b.get('/biz/').get_data(as_text=True))
        self.post(b,'/biz/approve_many',{'category':'배송 조회'},'/biz/')
        with self.core.conn() as db:self.assertEqual({r[0] for r in db.execute('SELECT status FROM cases WHERE id IN (?,?)',(a,bb))},{'answered'})
        self.assertGreaterEqual(self.core.close_idle(self.core.now()+datetime.timedelta(days=8)),2)
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT status FROM cases WHERE id=?',(a,)).fetchone()[0],'closed')
        # 교환품 발송 송장
        ex=self.file_case(me,'검토마켓','교환',company_id=str(cid))
        self.post(b,f'/biz/case/{ex}',{'act':'approve'});self.post(b,f'/biz/case/{ex}',{'act':'ret_received'})
        self.post(b,f'/biz/case/{ex}',{'act':'out_ship','courier':'CJ대한통운','tracking':'1234-5678-9012'})
        self.assertIn('새 상품을 보냈어요',me.get(f'/case/{ex}').get_data(as_text=True))
        # 첫 화면은 회사 찾기만 두고 상담창은 기업 페이지에서 (기업 없이 물으면 기본 문구)
        page=me.get('/').get_data(as_text=True);self.assertIn('id="hq"',page);self.assertNotIn('id="cb"',page)
        page=me.get(f'/to/{cid}').get_data(as_text=True);self.assertIn('id="cb"',page)
        self.assertIn(f'/to/{cid}',b.get('/biz/').get_data(as_text=True))  # 기업 홈에서 바로 복사하는 고객센터 링크
        tok=re.search(r'data-csrf="([^"]+)"',page).group(1)
        j=me.post('/chat',data={'csrf':tok,'text':'택배가 아직 안 와요'}).get_json()
        self.assertEqual((j['category'],j['faq']),('배송 조회',self.core.CHAT_FAQ['배송 조회']))

    def test_copy_edits_from_ops(self):
        o=self.client();self.post(o,'/biz/ops/login',{'password':self.ops_pw})
        page=o.get('/biz/ops/copy?q=접수하기').get_data(as_text=True);self.assertIn('접수하기',page)
        me=self.client();self.assertIn('>접수하기<',me.get('/').get_data(as_text=True))
        self.post(o,'/biz/ops/copy',{'site':'me','src':'접수하기','dst':'문의 남기기'})
        home=me.get('/').get_data(as_text=True);self.assertIn('>문의 남기기<',home);self.assertNotIn('>접수하기<',home)
        self.assertNotIn('문의 남기기',self.client().get('/biz/login').get_data(as_text=True))  # 기업용에는 적용 안 됨
        self.post(o,'/biz/ops/copy',{'site':'all','src':'이용 안내','act':'hide'})
        self.assertNotIn('이용 안내',me.get('/').get_data(as_text=True))
        self.assertIn('이용 안내',o.get('/biz/ops/copy').get_data(as_text=True))  # 운영 화면은 그대로
        # 되돌리기 버튼 없이, 같은 자리에서 다시 고친다 (원래 문구로 저장하면 처음처럼)
        self.post(o,'/biz/ops/copy',{'site':'me','src':'접수하기','dst':'문의하기'})
        self.assertIn('>문의하기<',me.get('/').get_data(as_text=True))
        self.post(o,'/biz/ops/copy',{'site':'me','src':'접수하기','dst':'접수하기'});self.post(o,'/biz/ops/copy',{'site':'all','src':'이용 안내','dst':'이용 안내'})
        self.assertIn('>접수하기<',me.get('/').get_data(as_text=True))
        j=self.post(o,'/biz/ops/copy',{'site':'me','src':'모든 서비스는 무료로 이용할 수 있어요.','dst':'모두 무료예요.'},headers={'X-Requested-With':'fetch'}).get_json()
        self.assertTrue(j['ok'] and j['edited']);self.assertIn('모두 무료예요.',me.get('/guide').get_data(as_text=True))
        # 템플릿 코드 안 문구(자주 묻는 질문)와 응대 가이드 문구도 목록에 나온다
        self.assertIn('모든 서비스는 무료로',o.get('/biz/ops/copy?q=무료로 이용').get_data(as_text=True))
        self.assertIn('마음이 바뀌어',o.get('/biz/ops/copy?q=마음이').get_data(as_text=True))
        self.post(o,'/biz/ops/copy',{'site':'me','src':'접수하기','dst':'<b>x</b>'})
        self.assertIn('&lt;b&gt;x&lt;/b&gt;',me.get('/').get_data(as_text=True))  # 고친 문구는 글자로만 들어감
        with self.core.conn() as db:db.execute('DELETE FROM copy_edits')

    def test_visual_move_from_ops(self):
        o=self.client();self.post(o,'/biz/ops/login',{'password':self.ops_pw})
        fr=o.get('/biz/ops/visual/frame?p=2');page=fr.get_data(as_text=True)
        self.assertEqual(fr.headers['X-Frame-Options'],'SAMEORIGIN');self.assertIn('cp-tool-css',page);self.assertIn('"tpl": "c_guide.html"',page)
        tok=re.search(r'"csrf": "([^"]+)"',page).group(1)
        sel='body>main:nth-of-type(1)>div:nth-of-type(1)>h1:nth-of-type(1)'
        j=o.post('/biz/ops/visual/move',data={'csrf':tok,'tpl':'c_guide.html','sel':sel,'dev':'pc','dx':'30','dy':'-8'}).get_json();self.assertTrue(j['ok'])
        self.assertFalse(o.post('/biz/ops/visual/move',data={'csrf':tok,'tpl':'c_guide.html','sel':'h1{}body','dev':'pc','dx':'1','dy':'1'}).get_json()['ok'])
        me=self.client();g=me.get('/guide').get_data(as_text=True)
        self.assertIn(sel+'{position:relative;left:30px;top:-8px}',g)
        self.assertIn('@media (max-width:767.98px){'+sel+'{left:calc(30 * 100vw / 1280)}}',g)  # PC에서 옮기면 모바일도 따라감
        o.post('/biz/ops/visual/move',data={'csrf':tok,'tpl':'c_guide.html','sel':sel,'dev':'m','dx':'4','dy':'2'})
        g=me.get('/guide').get_data(as_text=True)
        self.assertIn('@media (max-width:767.98px){'+sel+'{position:relative;left:4px;top:2px}}',g);self.assertNotIn('calc(30',g)  # 모바일에서 따로 옮기면 그 위치
        o.post('/biz/ops/visual/move',data={'csrf':tok,'tpl':'c_guide.html','sel':sel,'dev':'m','dx':'0','dy':'0','reset':'1'})
        self.assertNotIn('cp-moves',me.get('/').get_data(as_text=True))  # 다른 화면에는 없음
        o.post('/biz/ops/visual/move',data={'csrf':tok,'tpl':'c_guide.html','sel':sel,'dev':'pc','dx':'0','dy':'0'})
        self.assertNotIn('cp-moves',me.get('/guide').get_data(as_text=True))
        self.assertEqual(self.client().get('/biz/ops/visual').status_code,302)  # 운영자만
        # 색이 섞인 제목도 조각마다 고친다 (화면에서 고친 경우 shown=1)
        self.post(o,'/biz/ops/copy',{'site':'biz','src':'승인 한 번으로','dst':'한 곳에서','shown':'1'})
        self.post(o,'/biz/ops/copy',{'site':'biz','src':'한 곳에서','dst':'바로','shown':'1'})  # 이미 바꾼 글자를 다시 고치면 같은 기록을 고친다
        self.assertIn('고객 요청,<br>바로<br>끝냅니다',self.client().get('/biz/').get_data(as_text=True))
        # 줄을 비우면 그 줄바꿈도 같이 사라져 아래 글이 당겨진다, 칸 안의 줄바꿈은 그대로 줄바꿈
        self.post(o,'/biz/ops/copy',{'site':'biz','src':'끝냅니다','dst':'','shown':'1'})
        biz=self.client().get('/biz/').get_data(as_text=True);self.assertIn('고객 요청,<br>바로</',biz);self.assertNotIn('바로<br></',biz)
        self.post(o,'/biz/ops/copy',{'site':'biz','src':'바로','dst':'바로\n끝','shown':'1'})
        self.assertIn('고객 요청,<br>바로<br>끝</',self.client().get('/biz/').get_data(as_text=True))
        with self.core.conn() as db:db.execute('DELETE FROM copy_edits')

    def test_visual_edit_stays_on_its_page(self):
        o=self.client();self.post(o,'/biz/ops/login',{'password':self.ops_pw})
        # 화면 보며 고친 글자는 그 화면에서만 (같은 글자가 있는 로그인 화면은 그대로)
        self.post(o,'/biz/ops/copy',{'site':'biz','tpl':'b_intro.html','src':'승인 한 번으로','dst':'클릭 한 번으로'})
        self.assertIn('클릭 한 번으로',self.client().get('/biz/').get_data(as_text=True))
        self.assertIn('<br>승인 한 번으로<br>',self.client().get('/biz/login').get_data(as_text=True))
        self.assertIn('클릭 한 번으로',o.get('/biz/ops/copy?pg=edited').get_data(as_text=True))
        # 목록에서 일부 글자를 바꾼 뒤 화면에서 그 줄을 다시 고쳐도 반영된다 (원래 글자로 저장)
        self.post(o,'/biz/ops/copy',{'site':'biz','src':'고객 요청','dst':'우리 요청'})
        fr=o.get('/biz/ops/visual/frame?p=6').get_data(as_text=True)
        m=json.loads(re.search(r'<script type="application/json" id="cp-map">(.*?)</script>',fr).group(1))
        self.assertEqual(m['우리 요청,']['o'],'고객 요청,');self.assertEqual(m['클릭 한 번으로']['o'],'승인 한 번으로')
        self.post(o,'/biz/ops/copy',{'site':'biz','tpl':'b_intro.html','src':'고객 요청,','dst':'우리 회사 요청,'})
        h=self.client().get('/biz/').get_data(as_text=True);self.assertIn('<h1>우리 회사 요청,<br>클릭 한 번으로<br>끝냅니다</h1>',h)
        self.assertNotIn('우리 회사 우리',h)  # 바꾼 글자를 다시 바꾸지 않는다
        with self.core.conn() as db:db.execute('DELETE FROM copy_edits');db.execute('DELETE FROM copy_page_edits')

    def test_password_links_and_consumer_kakao(self):
        sent=[];kakao=[]
        b,o,cid=self.signup_and_approve('비번마켓','pw@example.com')
        with patch.object(self.core,'mail_ready',lambda:True),patch.object(self.core,'send_mail',lambda to,sub,body:sent.append((to,body))),\
             patch.object(self.core,'send_kakao',lambda phone,v,tpl='',label='':kakao.append((phone,tpl,v))):
            # 기업 비밀번호 재설정
            x=self.client();self.post(x,'/biz/forgot',{'login_id':'pw@example.com'})
            link=re.search(r'/reset/(\S+)',sent[-1][1]).group(1)
            self.post(x,f'/biz/reset/{link}',{'password':'newpassword99'})
            self.assertEqual(self.post(x,'/biz/login',{'login_id':'pw@example.com','password':'newpassword99'},'/biz/login').status_code,302)
            self.assertIn('만료',x.get(f'/biz/reset/{link}',follow_redirects=True).get_data(as_text=True))  # 한 번 쓰면 끝
        # 메일이 꺼져 있으면 비밀번호 찾기는 운영팀 문의 안내 화면
        g=self.client().get('/biz/forgot').get_data(as_text=True);self.assertIn('운영팀에 문의',g);self.assertNotIn('name="login_id"',g)
        # 메일이 꺼져 있어도 운영 화면에서 재설정 링크를 만들어 보낼 수 있다
        self.assertIn('운영팀에 연락',self.post(self.client(),'/biz/forgot',{'login_id':'pw@example.com'},'/biz/login',follow_redirects=True).get_data(as_text=True))
        page=self.post(o,'/biz/ops/companies',{'act':'pwlink','id':str(cid)},follow_redirects=True).get_data(as_text=True)
        y=self.client();self.post(y,'/biz/reset/'+re.search(r'/reset/([^\s<]+)',page).group(1),{'password':'another1234x'})
        self.assertEqual(self.post(y,'/biz/login',{'login_id':'pw@example.com','password':'another1234x'},'/biz/login').status_code,302)
        with patch.object(self.core,'mail_ready',lambda:True),patch.object(self.core,'send_mail',lambda to,sub,body:sent.append((to,body))),\
             patch.object(self.core,'send_kakao',lambda phone,v,tpl='',label='':kakao.append((phone,tpl,v))):
            # 소비자: 이메일로 내 접수 다시 열기
            me=self.client();cs=self.file_case(me,'비번마켓','배송 조회',company_id=str(cid))
            with self.core.conn() as db:db.execute("UPDATE cases SET email='me@example.com' WHERE id=?",(cs,))
            other=self.client();self.post(other,'/lookup/mail',{'phone':'010-1234-5678','email':'ME@example.com'},'/mine')
            tok=re.search(r'/lookup/t/(\S+)',sent[-1][1]).group(1)
            other.get(f'/lookup/t/{tok}');self.assertEqual(other.get(f'/case/{cs}').status_code,200)
            # 기업 답변이 나가면 소비자에게 알림톡
            self.post(b,f'/biz/case/{cs}',{'act':'approve'})
            self.assertTrue(any(t=='CS_KAKAO_TPL_REPLY' and p=='01012345678' for p,t,v in kakao))

    def test_non_member_ops_flow_and_lookup(self):
        me=self.client()
        case_id=self.file_case(me,'하루가구','반품·환불',title='의자 회수가 안 돼요')
        with self.core.conn() as db:c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        self.assertEqual((c['member'],c['status']),(0,'received'))
        o=self.client();self.post(o,'/biz/ops/login',{'password':self.ops_pw})
        self.assertIn('의자 회수가 안 돼요',o.get('/biz/ops').get_data(as_text=True))
        self.post(o,f'/biz/ops/case/{case_id}',{'act':'attempt','channel':'이메일'})
        self.post(o,f'/biz/ops/case/{case_id}',{'act':'reply','msg':'다음 주 회수 예정입니다.'})
        # 다른 기기: 휴대폰 번호 + 조회 비밀번호로 찾기
        other=self.client()
        self.assertEqual(other.get(f'/case/{case_id}').status_code,404)
        self.post(other,'/lookup',{'phone':'01012345678','password':'1234'},'/mine')
        page=other.get(f'/case/{case_id}').get_data(as_text=True)
        self.assertIn('다음 주 회수 예정입니다.',page)
        bad=self.client();self.post(bad,'/lookup',{'phone':'01012345678','password':'0000'},'/mine')
        self.assertEqual(bad.get(f'/case/{case_id}').status_code,404)

    def test_audit_fixes(self):
        b,o,cid=self.signup_and_approve('점검상회','check@example.com')
        # 미리 정한 답변이 없는 유형(기타)은 승인만으로 처리되지 않는다
        me=self.client();cs=self.file_case(me,'점검상회','기타',str(cid))
        r=self.post(b,f'/biz/case/{cs}',{'act':'approve'});print(r.status_code,r.headers.get('Location'));page=b.get(r.headers.get('Location') or f'/biz/case/{cs}').get_data(as_text=True)
        self.assertIn('답변을 직접 적어',page)
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT decision FROM cases WHERE id=?',(cs,)).fetchone()[0],'pending')
        # 정보 제공에 동의하지 않은 요청에는 환불 계좌 칸이 없다
        me2=self.client();cs2=self.file_case(me2,'점검상회','반품·환불',str(cid),consent='')
        with self.core.conn() as db:self.assertFalse(self.core.refund_case(db.execute('SELECT * FROM cases WHERE id=?',(cs2,)).fetchone()))
        # 앱 API에 배열을 보내도 서버 오류가 나지 않는다
        self.assertNotEqual(self.client().post('/api/v1/mine',json=[1]).status_code,500)
        self.assertNotEqual(self.client().post('/biz/api/v1/login',json=[1]).status_code,500)
        # 오래 열어 둔 화면에서 보내면 우리말 안내
        r=self.client().post('/biz/login',data={'login_id':'x'});self.assertEqual(r.status_code,400);self.assertIn('새로고침',r.get_data(as_text=True))

    def test_access_control(self):
        b1,o,cid1=self.signup_and_approve('갑회사','a@example.com')
        b2,_,cid2=self.signup_and_approve('을회사','b@example.com')
        me=self.client();case_id=self.file_case(me,'갑회사','교환',str(cid1))
        self.assertEqual(b2.get(f'/biz/case/{case_id}').status_code,404)
        home=self.client().get('/biz/');self.assertEqual(home.status_code,200);page=home.get_data(as_text=True)
        self.assertIn('승인 한 번으로',page);self.assertIn('곧 출시',page);self.assertIn('/biz/signup',page);self.assertNotIn('noindex',page)
        login=self.client().get('/biz/login').get_data(as_text=True);self.assertIn('소보루 CS 로그인',login)
        self.assertEqual(self.client().get('/biz/all').status_code,302)
        self.assertEqual(self.client().get('/biz/ops').status_code,302)
        # CSRF 없는 요청은 거절
        self.assertEqual(b1.post(f'/biz/case/{case_id}',data={'act':'approve'}).status_code,400)
        # 동의 없으면 입점 기업에도 전달 안 됨
        c2=self.file_case(me,'갑회사','교환',str(cid1),consent='',title='동의 없음')
        with self.core.conn() as db:c=db.execute('SELECT * FROM cases WHERE id=?',(c2,)).fetchone()
        self.assertEqual(c['status'],'received')
        self.assertNotIn('동의 없음',b1.get('/biz/').get_data(as_text=True))

    def test_follow_up_relief_company_page_and_late_notice(self):
        b,o,cid=self.signup_and_approve('바른가전','barun@example.com')
        me=self.client()
        home=me.get('/').get_data(as_text=True)
        self.assertNotIn('/new?category=',home);self.assertEqual(home.count('>접수하기<'),1)
        # 기업별 접수 링크: 회사가 미리 채워진 접수 화면
        self.assertIn('바른가전에 접수하기',me.get(f'/to/{cid}').get_data(as_text=True))
        self.assertEqual(me.get('/to/99999').status_code,404)
        self.assertIn('value="바른가전"',me.get(f'/new?company_id={cid}').get_data(as_text=True))
        page=b.get('/biz/settings').get_data(as_text=True)
        self.assertIn(f'/to/{cid}',page);self.assertIn('설정 · 소보루 CS',page);self.assertIn('soboru-char.png',page);self.assertIn('soboru-favicon.png',page);self.assertNotIn('SOBORU Business',page)
        case_id=self.file_case(me,'바른가전','교환',str(cid),title='세탁기 소음')
        self.assertNotIn('기업에 다시 요청할까요',me.get(f'/case/{case_id}').get_data(as_text=True))
        # 답변 목표일이 지나면 한 번만 지연 알림
        with self.core.conn() as db:db.execute("UPDATE cases SET due='2020-01-01 00:00:00' WHERE id=?",(case_id,))
        self.assertEqual(self.core.notify_late(),1);self.assertEqual(self.core.notify_late(),0)
        with self.core.conn() as db:
            self.assertEqual(db.execute('SELECT late_sent FROM cases WHERE id=?',(case_id,)).fetchone()[0],'2020-01-01 00:00:00')
        self.assertIn('답변 목표일이 지나',me.get(f'/case/{case_id}').get_data(as_text=True))
        # 늦어진 요청은 다시 요청 → 승인 대기로 돌아가고 목표일이 새로 잡힘, 24시간 안에는 또 못 함
        self.assertIn('기업에 다시 요청할까요',me.get(f'/case/{case_id}').get_data(as_text=True))
        self.post(me,f'/case/{case_id}',{'act':'again','msg':'아직 연락이 없어요'})
        with self.core.conn() as db:c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        self.assertEqual((c['status'],c['decision']),('seen','pending'));self.assertGreater(c['due'],'2020-01-01')
        self.assertNotIn('기업에 다시 요청할까요',me.get(f'/case/{case_id}').get_data(as_text=True))
        self.assertIn('세탁기 소음',b.get('/biz/').get_data(as_text=True))
        # 피해구제 자료 정리, 내 증빙 자료
        page=me.get(f'/case/{case_id}/relief').get_data(as_text=True)
        self.assertIn('사건 개요',page);self.assertIn('다시 요청: 아직 연락이 없어요',page)
        self.assertEqual(self.client().get(f'/case/{case_id}/relief').status_code,404)
        self.assertEqual(me.get('/mine').status_code,200)
        # 검색 노출: 공개 화면만 색인, 사이트맵에 기업 접수 페이지
        self.assertNotIn('noindex',home);self.assertIn('<meta name="description"',home)
        self.assertIn('noindex',me.get(f'/case/{case_id}').get_data(as_text=True))
        robots=me.get('/robots.txt').get_data(as_text=True)
        self.assertIn('Disallow: /case',robots);self.assertIn('Sitemap: http://localhost/sitemap.xml',robots)
        sm=me.get('/sitemap.xml').get_data(as_text=True)
        self.assertIn(f'<loc>http://localhost/to/{cid}</loc>',sm);self.assertIn('<loc>http://localhost/guide</loc>',sm)
        self.assertIn('Disallow: /ops',me.get('/biz/robots.txt').get_data(as_text=True))
        self.assertNotIn('noindex',self.client().get('/biz/login').get_data(as_text=True))

    def test_privacy_policy_and_purge(self):
        """처리방침에 법정 항목(운영 주체·보호책임자·위탁·보유 기간)이 있고, 보유 기간이 지난 요청은 첨부 파일까지 파기된다"""
        import datetime
        page=self.client().get('/privacy').get_data(as_text=True)
        for t in ('소보루','오규섭','129-14-81596','논현로 310-1','개인정보 보호책임자','네이버클라우드 주식회사','3년','파기','118'):self.assertIn(t,page)
        self.assertNotIn('초안',page)
        me=self.client();old=self.file_case(me,'파기상점','기타',title='오래된 요청');new=self.file_case(me,'파기상점','기타',title='최근 요청')
        stored='purge-test.txt';(self.core.UPLOAD/stored).write_text('x')
        long_ago=self.core.iso(self.core.now()-datetime.timedelta(days=365*3+1))
        with self.core.conn() as db:
            db.execute('UPDATE cases SET updated=? WHERE id=?',(long_ago,old))
            db.execute("INSERT INTO files(case_id,stored,original) VALUES(?,?,'a.txt')",(old,stored))
        self.assertEqual(self.core.purge_old(),1)
        with self.core.conn() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM cases WHERE id=?',(old,)).fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM events WHERE case_id=?',(old,)).fetchone())
            self.assertIsNotNone(db.execute('SELECT 1 FROM cases WHERE id=?',(new,)).fetchone())
        self.assertFalse((self.core.UPLOAD/stored).exists())

    def test_cs_tools(self):
        """법 기준·응대 가이드·답변 초안·직접 등록·반품 안내/송장·기록·리포트·업종 비교·경보·법 소식"""
        import datetime, json, law, insights
        b,o,cid=self.signup_and_approve('보리상점','bori@example.com')
        # 조문은 law_texts.json 원문 그대로
        texts=json.loads((ROOT/'platform_app'/'law_texts.json').read_text(encoding='utf-8'))
        self.assertIn('7일',texts['ecom']['articles']['제17조']['paras'][0]['items'][0]['text'])
        self.assertEqual(law.cite('ecom:제21조:①:3')['label'],'전자상거래법 제21조 제1항 제3호')
        page=b.get('/biz/guide').get_data(as_text=True)
        self.assertIn('응대 가이드',page);self.assertIn(texts['ecom']['articles']['제18조']['paras'][8]['text'],page);self.assertIn('law.go.kr',page)
        # 설정: 반품 안내, 업종, 알림
        r=self.post(b,'/biz/settings',{'act':'return','return_address':'서울시 보리로 1, 보리상점 반품담당','return_courier':'CJ대한통운','return_memo':'단순 변심은 배송비 동봉'},'/biz/settings')
        self.post(b,'/biz/settings',{'contact':'1588-0000','notify_email':'bori@example.com','industry':'식품','tone':'friendly'},'/biz/settings')
        self.post(b,'/biz/settings',{'act':'notify','phone':'010-2222-3333','kakao':'1','report_mail':'1'},'/biz/settings')
        with self.core.conn() as db:co=self.core.company(db,cid)
        self.assertEqual((co['return_courier'],co['industry'],co['tone'],co['kakao']),('CJ대한통운','식품','friendly',1))
        self.assertIn('이용 택배사: CJ대한통운',b.get('/biz/settings').get_data(as_text=True))
        # 소비자 접수: 받은 날 → 7일 계산, 상품명
        me=self.client();recv=(datetime.date.today()-datetime.timedelta(days=3)).isoformat()
        data={'company':'보리상점','company_id':str(cid),'category':'반품·환불','title':'단순 변심 반품','body':'사이즈가 안 맞아 반품하고 싶어요.','want':'환불',
              'name':'이소비','phone':'010-5555-6666','password':'1234','privacy':'1','consent':'1','product':'보리차 티백','received_on':recv}
        r=self.post(me,'/submit',data,'/new');case_id=int(r.headers['Location'].rstrip('/').split('/')[-1])
        page=b.get(f'/biz/case/{case_id}').get_data(as_text=True)
        self.assertIn('받은 지 3일째',page);self.assertIn('청약철회 기간 7일 안',page);self.assertIn('전자상거래법 제18조 제9항',page)
        self.assertIn('받은 지 3일 · 7일 이내',b.get('/biz/').get_data(as_text=True))
        # 답변 초안: API 키가 없으면 기본 문구
        os.environ.pop('ANTHROPIC_API_KEY',None)
        d=self.post(b,f'/biz/case/{case_id}/draft',{},f'/biz/case/{case_id}').get_json()
        self.assertEqual(d['by'],'template');self.assertIn('7일 이내라 반품',d['text']);self.assertIn('보리상점',d['text'])
        # 승인하면 반품 안내가 붙고, 소비자가 송장 입력 → 기업이 회수 확인
        self.post(b,f'/biz/case/{case_id}',{'act':'approve'},f'/biz/case/{case_id}')
        with self.core.conn() as db:
            c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone();rep=db.execute("SELECT reply FROM events WHERE case_id=? AND kind='co'",(case_id,)).fetchone()[0]
        self.assertEqual(c['ret_status'],'guided');self.assertIn('서울시 보리로 1',rep)
        self.assertIn('송장번호 알리기',me.get(f'/case/{case_id}').get_data(as_text=True))
        self.post(me,f'/case/{case_id}',{'act':'ship','courier':'CJ대한통운','tracking':'1234-5678-9012'},f'/case/{case_id}')
        self.assertIn('123456789012',b.get(f'/biz/case/{case_id}').get_data(as_text=True))
        self.assertIn('단순 변심 반품',b.get('/biz/all?f=ret').get_data(as_text=True))
        self.post(b,f'/biz/case/{case_id}',{'act':'ret_received'},f'/biz/case/{case_id}')
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT ret_status FROM cases WHERE id=?',(case_id,)).fetchone()[0],'received')
        # 기록 PDF(인쇄용)
        page=b.get(f'/biz/case/{case_id}/record').get_data(as_text=True)
        self.assertIn('요청 처리 기록',page);self.assertIn('window.print()',page);self.assertIn('회수 확인',page)
        # 직접 등록: 소비자에게 메일 없음, 같은 상품 3건이면 경보
        for n in range(3):
            r=self.post(b,'/biz/new',{'channel':'전화','category':'제품 불량','title':f'티백 찢어짐 {n}','body':'티백이 찢어져 왔어요','want':'교환','product':'보리차 티백 ','email':'x@example.com'},'/biz/new')
            self.assertEqual(r.status_code,302)
        page=b.get(r.headers['Location']).get_data(as_text=True)
        self.assertIn('전화 · 직접 등록',page)
        with self.core.conn() as db:
            self.assertEqual(len(insights.alerts(db,co)),1)
        self.assertIn("'보리차 티백' 관련 요청이 최근 7일 4건",b.get('/biz/').get_data(as_text=True))
        sent=insights.send_alerts();self.assertEqual(insights.send_alerts(),0)  # 하루 한 번
        self.assertEqual(sent,1)
        # 월간 리포트·업종 비교
        today=datetime.date.today()
        self.assertIn('CS 리포트',b.get(f'/biz/report?ym={today.year}-{today.month:02d}').get_data(as_text=True))
        self.assertEqual(insights.send_monthly_reports(datetime.date(today.year,today.month,2)),0)
        self.assertIn('3곳 이상 모이면',b.get('/biz/stats').get_data(as_text=True))
        # 법 소식: 운영자가 출처와 함께 올림
        r=self.post(o,'/biz/ops/news',{'title':'전자상거래법 개정 시행','body':'개정 법률이 시행됐어요.','source_url':'https://www.law.go.kr/법령/전자상거래등에서의소비자보호에관한법률'},'/biz/ops/news')
        self.assertIn('전자상거래법 개정 시행',b.get('/biz/').get_data(as_text=True))
        self.assertIn('출처 보기',b.get('/biz/news').get_data(as_text=True))
        r=self.post(o,'/biz/ops/news',{'title':'출처 없음','body':'내용','source_url':''},'/biz/ops/news')
        self.assertNotIn('출처 없음',b.get('/biz/news').get_data(as_text=True))
        self.assertIn('soboru-favicon.png',self.client().get(f'/to/{cid}').get_data(as_text=True))  # 고객센터 탭 아이콘은 캐릭터
        # 화면 점검: 제목 칸에 화면 내용이 섞이거나 템플릿 문법이 그대로 보이면 안 된다
        for path in ['/biz/','/biz/all','/biz/stats','/biz/report','/biz/guide','/biz/new','/biz/news','/biz/settings','/biz/rules',f'/biz/case/{case_id}',f'/biz/case/{case_id}/record']:
            page=b.get(path).get_data(as_text=True)
            title=re.search(r'<title>(.*?)</title>',page,re.S).group(1)
            self.assertNotIn('<',title,path);self.assertEqual(page.count('<title>'),1,path)
            self.assertNotIn('{%',page,path);self.assertNotIn('{{',page,path)
        self.assertEqual(b.get('/biz/stats').get_data(as_text=True).count('같은 업종과 비교'),1)

    def test_submit_validation_keeps_draft(self):
        me=self.client()
        r=self.post(me,'/submit',{'company':'아무회사','category':'교환','title':'제목','body':'짧음','want':'교환','phone':'010-1234-5678','password':'1234','privacy':'1'},'/new')
        self.assertEqual(r.status_code,302)
        page=me.get('/new').get_data(as_text=True)
        self.assertIn('10자 이상',page);self.assertIn('value="아무회사"',page)

    def test_throttle(self):
        app=sys.modules['consumer'].app
        with app.test_request_context('/',environ_base={'REMOTE_ADDR':'10.9.9.9'}):
            self.assertEqual([self.real_throttled('t',limit=3,minutes=10) for _ in range(4)],[False,False,False,True])


if __name__=='__main__':unittest.main()
