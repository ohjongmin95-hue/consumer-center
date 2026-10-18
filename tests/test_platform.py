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
        for m in ('core','consumer','business','hanq','law','insights','drafting','chatbot','tracking','orders','shops','ai','product_pdf','team','onboard','demo','funnel','market','sales','cms','csimport','growth','security','cafe24','openapi','aistats','inbox','workflow','automations','livechat','mailin','instagram','billing','aibench'):sys.modules.pop(m,None)
        cls.hanq=importlib.import_module('hanq');cls.core=sys.modules['core']
        cls.core.MAIL_ASYNC=False
        cls.real_throttled=staticmethod(cls.core.throttled);cls.core.throttled=lambda *a,**k:False  # 횟수 제한은 아래 테스트에서 따로 확인
        for a in (sys.modules['consumer'].app,sys.modules['business'].app):a.config['TESTING']=True

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(ROOT/'platform_app'))
        for m in ('core','consumer','business','hanq','law','insights','drafting','chatbot','tracking','orders','shops','ai','product_pdf','team','onboard','demo','funnel','market','sales','cms','csimport','growth','security','cafe24','openapi','aistats','inbox','workflow','automations','livechat','mailin','instagram','billing','aibench'):sys.modules.pop(m,None)
        cls.env.stop();cls.temp.cleanup()

    def client(self):return Client(self.hanq.app)
    def csrf(self,c,path):
        r=c.get(path);m=re.search(r'name="csrf" value="([^"]+)"',r.get_data(as_text=True));self.assertTrue(m,path);return m.group(1)
    def post(self,c,path,data,form_path=None,**kw):
        data=dict(data,csrf=self.csrf(c,form_path or path));return c.post(path,data=data,**kw)

    _biz=[100]
    def bizno(self):
        """검증번호가 맞는 사업자번호 (테스트마다 다른 번호)."""
        self._biz[0]+=1;d=[int(x) for x in f'{self._biz[0]:09d}']
        w=[1,3,7,1,3,7,1,3,5];t=sum(a*b for a,b in zip(d,w))+(d[8]*5)//10
        return ''.join(map(str,d))+str((10-t%10)%10)
    def signup_and_approve(self,name,email):
        b=self.client()
        r=self.post(b,'/biz/signup',{'name':name,'biz_no':self.bizno(),'owner_name':'대표','phone':'010-1111-2222','contact':'1588-0000','login_id':email,'password':'longpassword1','terms':'1'})
        self.assertEqual(r.status_code,302);self.assertIn('/start',r.headers['Location'])  # 가입하면 바로 로그인되고 처음 설정으로
        self.assertIn('로그인 이메일 확인',b.get('/biz/start').get_data(as_text=True))
        o=self.client();self.post(o,'/biz/ops/login',{'password':self.ops_pw})
        with self.core.conn() as db:cid=db.execute('SELECT id FROM companies WHERE login_id=?',(email,)).fetchone()[0]
        self.post(o,'/biz/ops/companies',{'act':'approve','id':cid})
        b=self.client();r=self.post(b,'/biz/login',{'login_id':email,'password':'longpassword1'})
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
        if cat in ('주문 취소','주문 변경'):data['order_no']='20261013-0001'
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
        r=c.get('/biz/refund');self.assertEqual(r.status_code,200);page=r.get_data(as_text=True)  # 결제대행사 심사에 내는 환불 정책 (로그인 없이)
        self.assertIn('환불 정책',page);self.assertIn('7일 이내',page);self.assertNotIn('noindex',page)
        pr=c.get('/biz/pricing');self.assertEqual(pr.status_code,200);ph=pr.get_data(as_text=True)  # 공개 요금 안내 (요금제를 정하면 금액이 보인다)
        self.assertIn('정기결제',ph);self.assertIn('/biz/refund',ph);self.assertIn('/biz/pricing',c.get('/biz/').get_data(as_text=True))
        with self.core.conn() as db:db.execute("INSERT OR REPLACE INTO settings(key,value,updated) VALUES('billing_plan','{\"name\":\"베이직\",\"price\":29000}','x')")
        try:self.assertIn('월 29,000원',c.get('/biz/pricing').get_data(as_text=True))
        finally:
            with self.core.conn() as db:db.execute("DELETE FROM settings WHERE key='billing_plan'")
        self.assertIn('/pricing</loc>',c.get('/biz/sitemap.xml').get_data(as_text=True));self.assertIn('요금 안내',t.get_data(as_text=True))
        self.assertIn('코리아포트원',c.get('/privacy').get_data(as_text=True))
        for pg in (page,t.get_data(as_text=True),c.get('/biz/').get_data(as_text=True)):self.assertIn('전화. 02-749-7515',pg);self.assertIn('대표자.',pg)  # 결제대행사 심사: 사업자 정보
        self.assertIn('/biz/refund',t.get_data(as_text=True));self.assertIn('/refund</loc>',c.get('/biz/sitemap.xml').get_data(as_text=True))

    def test_biz_app_inapp_pages(self):
        """앱 안 가입 신청·규칙·통계·설정·가이드: 웹과 같은 검사, 비밀번호를 바꾸면 새 토큰을 준다."""
        a=self.client()
        self.assertEqual(a.post('/biz/api/v1/signup',json={'name':'앱가입','biz_no':'123','owner_name':'김','login_id':'x@example.com','password':'longpassword1','terms':'1'}).status_code,400)
        self.assertEqual(a.post('/biz/api/v1/signup',json={'name':'앱가입','biz_no':'1234567890','owner_name':'김','login_id':'x@example.com','password':'longpassword1','terms':'1'}).status_code,400)  # 검증번호 틀림
        j=a.post('/biz/api/v1/signup',json={'name':'앱가입','biz_no':self.bizno(),'owner_name':'김사장','login_id':'appjoin@example.com','password':'longpassword1','terms':True}).get_json()
        self.assertTrue(j['ok']);self.assertTrue(j['token']);self.assertFalse(j['verified'])  # 바로 쓰지만 회사 인증 전
        with self.core.conn() as db:self.assertEqual(tuple(db.execute("SELECT status,member FROM companies WHERE login_id='appjoin@example.com'").fetchone()),('active',0))
        self.assertTrue(a.post('/biz/api/v1/login',json={'login_id':'appjoin@example.com','password':'longpassword1'}).get_json()['token'])
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
        # 키가 있으면 AI(OpenAI, 인터넷 검색 가능)가 회사 정보(상품 포함)와 앞 대화를 보고 답한다
        def oa(url,content):  # OpenAI 응답 모양 (검색: Responses API, 아니면 Chat Completions)
            if url.endswith('/responses'):return 200,{'output':[{'type':'web_search_call'},{'type':'message','content':[{'type':'output_text','text':content}]}]}
            return 200,{'choices':[{'message':{'content':content}}]}
        seen={}
        def fake(url,headers,body,timeout):
            seen.update(url=url,headers=headers,body=body)
            return oa(url,'{"category": null, "answer": "선크림은 19000원이에요.", "handoff": false, "summary": ""}')
        aim=sys.modules['ai']
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(aim,'post',fake):
            hist=json.dumps([{'who':'bot','text':'안녕하세요'},{'who':'me','text':'선크림 있어요?'},{'who':'bot','text':'네, 있어요.'}])
            j=me.post(f'/chat/{cid}',data={'csrf':ctok,'text':'얼마예요?','history':hist}).get_json()
        self.assertEqual((j['answer'],j['category'],j['handoff']),('선크림은 19000원이에요.',None,False))
        self.assertTrue(seen['url'].endswith('/chat/completions'));self.assertNotIn('tools',seen['body'])  # 먼저 검색 없이 (빠르게)
        system=seen['body']['messages'][0]['content'];msgs=seen['body']['messages'][1:]
        self.assertIn('선크림 / 가격 19000원',system);self.assertIn('보습 크림 / 가격 31000원 / 품절',system);self.assertIn('인터넷 검색',system)
        self.assertEqual([m['role'] for m in msgs],['user','assistant','user']);self.assertEqual(msgs[-1]['content'],'얼마예요?')
        # 검색 답이 JSON이 아니어도 글이면 답으로 쓰고, 출처 링크 표시는 뺀다
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(aim,'post',lambda url,h,b,t:oa(url,'자외선 차단제는 2~3시간마다 덧바르는 게 좋아요 ([example.com](https://example.com/a)).')):
            j=me.post(f'/chat/{cid}',data={'csrf':ctok,'text':'선크림 얼마나 자주 발라요?'}).get_json()
        self.assertEqual(j['answer'],'자외선 차단제는 2~3시간마다 덧바르는 게 좋아요.')
        # 검색이 안 되면(예: 모델이 검색 도구를 지원하지 않음) 검색 없이 다시 묻는다
        urls=[]
        def nosearch(url,headers,body,timeout):
            urls.append(url)
            if url.endswith('/responses'):return 400,{'error':{'message':'tool not supported'}}
            return oa(url,'{"category": null, "answer": "네, 있어요.", "handoff": false, "summary": "", "sure": false}')
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(aim,'post',nosearch):
            j=me.post(f'/chat/{cid}',data={'csrf':ctok,'text':'보습 크림 있어요?'}).get_json()
        self.assertEqual(j['answer'],'네, 있어요.');self.assertEqual([u.rsplit('/',1)[1] for u in urls],['completions','responses','completions'])  # 확신이 없을 때만 검색, 검색이 안 되면 검색 없이
        # 네이버 검색 키가 있으면 AI가 필요할 때 네이버에서 검색하고, 그 결과를 보고 답한다
        calls=[];got=[]
        def nv_post(url,headers,body,timeout):
            if 'tools' not in body and not calls:return 200,{'choices':[{'message':{'content':'{"answer": "아마 2시간쯤이에요.", "sure": false}'}}]}  # 처음엔 검색 없이: 확신이 없다고 함
            calls.append(body)
            if len(calls)==1:return 200,{'choices':[{'message':{'content':None,'tool_calls':[{'id':'c1','type':'function','function':{'name':'search','arguments':'{"query": "선크림 덧바르는 주기"}'}}]}}]}
            return 200,{'choices':[{'message':{'content':'{"category": null, "answer": "보통 2~3시간마다 덧바르는 게 좋아요.", "handoff": false, "summary": ""}'}}]}
        def nv_get(url,headers,timeout):
            got.append((url,headers));return 200,{'items':[{'title':'<b>선크림</b> 바르는 법','description':'2~3시간마다 &amp; 땀 흘린 뒤'}]}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test','NAVER_SEARCH_ID':'nid','NAVER_SEARCH_SECRET':'nsec'}),patch.object(aim,'post',nv_post),patch.object(aim,'get',nv_get):
            j=me.post(f'/chat/{cid}',data={'csrf':ctok,'text':'선크림 얼마나 자주 발라요?'}).get_json()
        self.assertEqual(j['answer'],'보통 2~3시간마다 덧바르는 게 좋아요.')
        self.assertEqual(calls[0]['tools'][0]['function']['name'],'search')
        self.assertIn('openapi.naver.com/v1/search/webkr.json',got[0][0]);self.assertIn('query=%EC%84%A0%ED%81%AC%EB%A6%BC',got[0][0])
        self.assertEqual(got[0][1]['X-Naver-Client-Id'],'nid')
        tool=calls[1]['messages'][-1];self.assertEqual((tool['role'],tool['tool_call_id']),('tool','c1'))
        self.assertIn('선크림 바르는 법',tool['content']);self.assertIn('2~3시간마다 & 땀',tool['content'])
        # 사람이 처리할 일이면 담당자 연결과 요약을 돌려준다
        def fake2(url,headers,body,timeout):
            return oa(url,'{"category": "반품·환불", "answer": "불편을 드려 죄송해요. 환불은 담당자가 확인해야 해요.", "handoff": true, "summary": "고객 요구: 환불\\n주문번호: A-1"}')
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(aim,'post',fake2):
            j=me.post(f'/chat/{cid}',data={'csrf':ctok,'text':'A-1 주문 환불해 주세요'}).get_json()
        self.assertEqual((j['category'],j['handoff']),('반품·환불',True));self.assertIn('주문번호: A-1',j['summary'])
        # AI가 실패하면 기본 안내로 돌아간다 (키는 로그에 남지 않는다)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'sk-secret-test'}),patch.object(aim,'post',lambda *a,**k:(500,{'error':{'message':'boom'}})),self.assertLogs('ai',level='WARNING') as lg:
            j=me.post(f'/chat/{cid}',data={'csrf':ctok,'text':'환불하고 싶어요'}).get_json()
        self.assertNotIn('answer',j);self.assertEqual(j['category'],'반품·환불');self.assertNotIn('sk-secret-test',''.join(lg.output))
        # 다른 회사 상담창에는 이 회사 상품이 들어가지 않는다
        b3,_,cid3=self.signup_and_approve('다른가게','other-shop@example.com')
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(aim,'post',fake):
            me.post(f'/chat/{cid3}',data={'csrf':ctok,'text':'선크림 있어요?'})
        self.assertNotIn('선크림',seen['body']['messages'][0]['content'])

    def test_ai_model_luna_tiers_and_log(self):
        """AI 상담: Luna 낮은 추론 기본, 어려운 문의는 높은 추론. 예전 4.1-mini는 쓰지 않는다. Sol은 운영에서 켠 경우만. 호출은 모델·추론·토큰·비용·결과로 남는다."""
        aim=sys.modules['ai'];cb=sys.modules['chatbot'];sent=[]
        def reply(d):return 200,{'choices':[{'message':{'content':json.dumps(d,ensure_ascii=False)}}],'usage':{'prompt_tokens':1000,'completion_tokens':300,'prompt_tokens_details':{'cached_tokens':200},'completion_tokens_details':{'reasoning_tokens':100}}}
        script={}
        def fake(url,headers,body,timeout):
            sent.append(body);k=(body['model'],body.get('reasoning_effort',''))
            r=script.get(k,{'answer':'네, 있어요.','handoff':False})
            return r if isinstance(r,tuple) else reply(r)
        def ask(text,meta=None):
            with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(aim,'post',fake),patch.object(aim,'naver_ready',lambda:False),patch.object(aim,'web_answer',lambda *a,**k:None),\
                 patch.object(cb,'system_prompt',lambda *a:'sys'),patch.object(cb,'law_context',lambda t:('',False)):
                return cb.answer(None,'',text,meta=meta)
        # 평소 문의·환불 절차는 낮은 추론 (temperature 없이, 생각할 자리를 더 둔다)
        for q in ('이 크림 몇 ml예요?','환불은 어떻게 신청해요?','교환 방법 알려 주세요'):
            sent.clear();a=ask(q);self.assertEqual((a['tier'],[(b['model'],b['reasoning_effort']) for b in sent]),('low',[('gpt-6-luna','low')]),q)
        self.assertNotIn('temperature',sent[0]);self.assertGreater(sent[0]['max_completion_tokens'],900)
        # 분쟁·불량 책임·강한 불만·반복 문의는 높은 추론
        for q in ('환불 거부하시는 거예요? 소비자원에 신고할게요','쓰다가 깨졌는데 불량 아닌가요? 누구 책임이에요?','몇 번째 문의인데 아직도 답이 없네요'):
            sent.clear();self.assertEqual(ask(q)['tier'],'high',q);self.assertEqual(sent[0]['reasoning_effort'],'high')
        # 낱말로 못 잡아도 낮은 추론의 AI가 deep이라고 하면 높은 추론으로 다시 묻는다
        script[('gpt-6-luna','low')]={'answer':'확인할게요.','deep':True}
        sent.clear();self.assertEqual(ask('세탁기 돌렸더니 이렇게 됐어요')['tier'],'high');self.assertEqual([b['reasoning_effort'] for b in sent],['low','high'])
        script.clear()
        # Sol: 꺼져 있으면 안 부르고, 켜면 높은 추론이 확신 없을 때만
        script[('gpt-6-luna','high')]={'answer':'아마도요.','sure':False}
        sent.clear();ask('보상해 주세요');self.assertNotIn('gpt-6.1-sol',[b['model'] for b in sent])
        aim.save_setting('ai_sol','1')
        script[('gpt-6.1-sol','high')]={'answer':'규정상 이렇게 돼요.','sure':True}
        sent.clear();a=ask('보상해 주세요');self.assertEqual((a['answer'],a['tier']),('규정상 이렇게 돼요.','sol'))
        # 높은 추론이 실패하면 (켠 경우) Sol. 그것도 실패하면 답 없음 (기본 안내·승인으로). 4.1-mini는 부르지 않는다
        script[('gpt-6-luna','high')]=(500,{'error':{'message':'x'}});script[('gpt-6.1-sol','high')]=(400,{'error':{'message':'y'}})
        sent.clear();self.assertIsNone(ask('배상하세요'));self.assertEqual([b['model'] for b in sent],['gpt-6-luna','gpt-6.1-sol'])
        aim.save_setting('ai_sol','');script.clear()
        self.assertEqual(aim.ladder(7,'low'),[('gpt-6-luna','low')]);self.assertEqual(aim.ladder(7,'high'),[('gpt-6-luna','high')])
        # 기록: 모델·추론·토큰·비용·결과
        meta={'company_id':None,'purpose':'chat'};ask('이거 얼마예요?',meta);aim.outcome(meta,'answered')
        with self.core.conn() as db:r=db.execute('SELECT * FROM ai_calls WHERE req=?',(meta['req'],)).fetchone()
        self.assertEqual((r['model'],r['effort'],r['in_tok'],r['cached_tok'],r['out_tok'],r['reason_tok'],r['outcome']),('gpt-6-luna','low',1000,200,300,100,'answered'))
        self.assertAlmostEqual(r['cost'],(800*0.10+200*0.01+300*0.50)/1e6)
        rep={g['key']:g for g in aim.report()};self.assertGreaterEqual(rep['low']['n'],1);self.assertGreaterEqual(rep['high']['n'],1)
        # 환불·보상을 약속하는 답은 약속으로 보고(사장님 승인), 절차 안내는 아니다
        self.assertTrue(cb.promises('바로 환불해 드릴게요.'));self.assertTrue(cb.promises('보상으로 적립금 지급 처리했어요'))
        self.assertFalse(cb.promises('환불 방법을 안내해 드릴게요.'));self.assertFalse(cb.promises('교환은 마이페이지에서 신청하실 수 있어요.'))
        # 운영 화면: 설정·비교가 보인다
        o=self.client();self.post(o,'/biz/ops/login',{'password':self.ops_pw})
        page=o.get('/biz/ops/ai').get_data(as_text=True);self.assertIn('최근 30일 비교',page);self.assertIn('고추론 Luna',page)
        self.post(o,'/biz/ops/ai',{'sol':'1'});self.assertEqual(aim.plan(),{'model':'gpt-6-luna','sol':True})
        self.post(o,'/biz/ops/ai',{});self.assertFalse(aim.plan()['sol'])
        # 같은 질문으로 비교: 예전 모델·Luna 낮은·높은 추론에 샘플 질문을 보내고 채점해 나란히 남긴다
        bench=sys.modules['aibench']
        def bfake(url,headers,body,timeout):
            if '채점자' in body['messages'][0]['content']:return 200,{'choices':[{'message':{'content':'{"score": 4, "note": "정확해요"}'}}]}
            return reply({'answer':'바로 환불해 드릴게요.' if body.get('reasoning_effort')=='low' and '환불' in body['messages'][1]['content'] else '안내해 드릴게요.'})
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(aim,'post',bfake):bench.run()
        res=bench.last();self.assertTrue(res['done']);self.assertEqual(res['models'],['일반 Luna','고추론 Luna'])
        self.assertEqual(len(res['rows']),6);self.assertEqual(res['sum']['일반 Luna']['score'],4.0);self.assertGreaterEqual(res['sum']['일반 Luna']['promise'],1);self.assertEqual(res['sum']['고추론 Luna']['promise'],0)
        self.assertEqual({r['kind']:r['level'] for r in res['rows']}['강한 불만'],'high');self.assertEqual({r['kind']:r['level'] for r in res['rows']}['환불 절차'],'low')
        self.assertIn('같은 질문으로 비교',o.get('/biz/ops/ai').get_data(as_text=True))

    def test_pdf_product_import(self):
        """상품소개서 PDF(2쪽, 11개 상품) -> AI 추출 -> 검토·수정 -> 등록. 공급가는 따로 저장되고 상담 AI에 들어가지 않는다."""
        import shutil
        if not shutil.which('pdftotext'):self.skipTest('pdftotext 없음')
        b,o,cid=self.signup_and_approve('헬스마켓','health@example.com')
        self.post(b,'/biz/products',{'name':'비타민C 1000','price':'18,000원','stock':'있음','info':'예전 안내'},'/biz/rules')
        pp=sys.modules['product_pdf'];aim=sys.modules['ai'];pp.BACKGROUND=False
        from pathlib import Path;pdf=(Path(__file__).parent/'fixtures'/'catalog-11.pdf').read_bytes()
        names=['6년근 홍삼정 스틱','프로바이오틱스 19','루테인 지아잔틴','비타민C 1000','오메가3 알티지','밀크씨슬 간케어','마그네슘 플러스','콜라겐 펩타이드','흑마늘 진액','여성 멀티비타민','아르기닌 6000']
        sent=[]
        def fake(url,headers,body,timeout):
            sent.append(body);items=[]
            for n in names:
                it={'name':n,'brand':'소보루헬스','kind':'건강기능식품','spec':'','price':'','desc':'','features':'','ingredients':'','usage':'','shelf':'','caution':'','internal':{'supply':''}}
                items.append(it)
            items[0].update(price='39,000원',spec='10g x 30포',ingredients='홍삼농축액(6년근, 국산) 100%',internal={'supply':'21,000원 (VAT 별도)','terms':'월말 정산, 최소 주문 20개'})
            items[1].update(price='32,000원',desc='공급가 17,500원으로 판매처에 제공\n유산균 19종',internal={'supply':'17,500원'})  # AI가 실수로 공급가를 고객용 칸에 넣음
            items[2].update(price='14,000원',internal={'supply':'14,000원'})  # 소비자가 칸에 공급가 숫자
            items[3].update(price='19,000원',internal={'supply':'9,800원'})
            items[4].update(features='관절 건강에 도움 99,999개 판매')  # PDF에 없는 숫자
            items.append(dict(items[5],name='PDF에 없는 상품'))
            return 200,{'choices':[{'message':{'content':json.dumps({'products':items},ensure_ascii=False)}}]}
        from io import BytesIO
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(aim,'post',fake):
            self.assertIn('PDF 파일만',self.post(b,'/biz/products/pdf',{'file':(BytesIO(b'not a pdf'),'x.pdf')},'/biz/rules',follow_redirects=True).get_data(as_text=True))
            r=self.post(b,'/biz/products/pdf',{'file':(BytesIO(pdf),'catalog-11.pdf')},'/biz/rules')
        loc=r.headers['Location'];self.assertIn('/biz/products/import/',loc);token=loc.rsplit('/',1)[1]
        user=sent[0]['messages'][-1]['content'];self.assertIn('6년근 홍삼정 스틱',user);self.assertIn('아르기닌 6000',user)  # 두 쪽 글자가 모두 갔다
        page=b.get(loc).get_data(as_text=True)
        self.assertIn('상품 12개를 찾았어요',page);self.assertIn('이미 있는 상품',page)
        self.assertIn('PDF에서 못 찾은 내용: 제품명',page);self.assertIn('PDF에서 못 찾은 내용: 특징',page)
        with self.core.conn() as db:items=pp.job(db,cid,token)['items']
        it={x['name']:x for x in items}
        self.assertNotIn('공급가',it['프로바이오틱스 19']['desc']);self.assertIn('유산균 19종',it['프로바이오틱스 19']['desc'])
        self.assertIn('공급가 17,500원',it['프로바이오틱스 19']['internal']['other'])
        self.assertEqual(it['루테인 지아잔틴']['price'],'')  # 공급가와 같은 숫자는 소비자가에서 뺀다
        # 다른 회사는 이 추출 결과를 못 본다
        b2,_,_=self.signup_and_approve('남의헬스','other-health@example.com')
        self.assertEqual(b2.get(loc).status_code,404)
        self.assertIn('찾을 수 없',self.post(b2,loc,{'pick0':'1'},'/biz/rules',follow_redirects=True).get_data(as_text=True))
        # 사장님이 고르고 고친 뒤 등록 (가짜 상품은 고르지 않음, 이미 있는 비타민C는 골라서 덮어씀)
        form={f'pick{i}':'1' for i in range(11)};form['name0']='6년근 홍삼정 스틱 30포';form['price1']='31,000원'
        r=self.post(b,loc,form,'/biz/rules',follow_redirects=True);self.assertIn('11개 상품을 등록',r.get_data(as_text=True))
        with self.core.conn() as db:
            ps={p['name']:p for p in self.core.products(db,cid)};priv=pp.private_for(db,cid)
            left=db.execute('SELECT items FROM product_imports WHERE token=?',(token,)).fetchone()[0]
        self.assertEqual(len(ps),11);self.assertNotIn('PDF에 없는 상품',ps);self.assertEqual(ps['비타민C 1000']['price'],'19,000원')
        self.assertEqual(ps['프로바이오틱스 19']['price'],'31,000원');self.assertIn('원재료·성분: 홍삼농축액',ps['6년근 홍삼정 스틱 30포']['info'])
        self.assertIn('공급가: 21,000원',priv[ps['6년근 홍삼정 스틱 30포']['id']]);self.assertEqual(left,'[]')  # 다 쓴 추출 결과는 지운다
        # 사장님 화면에는 내부 정보가 보이고, 상담 AI·앱 API에는 안 간다
        self.assertIn('공급가: 21,000원',b.get('/biz/products').get_data(as_text=True));self.assertIn('AI 상담 설정',b.get('/biz/rules').get_data(as_text=True))
        with self.core.conn() as db:facts=sys.modules['chatbot'].company_facts(db,self.core.company(db,cid))
        self.assertIn('6년근 홍삼정 스틱 30포',facts);self.assertIn('39,000원',facts)
        for secret in ('21,000','17,500','9,800','공급가','정산','최소 주문'):self.assertNotIn(secret,facts)
        tok=self.client().post('/biz/api/v1/login',json={'login_id':'health@example.com','password':'longpassword1'}).get_json()['token']
        api=json.dumps(self.client().get('/biz/api/v1/products',headers={'Authorization':'Bearer '+tok}).get_json(),ensure_ascii=False)
        self.assertNotIn('21,000',api);self.assertNotIn('공급가',api)
        # 상품을 지우면 내부 정보도 같이 지운다
        pid=ps['6년근 홍삼정 스틱 30포']['id'];self.post(b,'/biz/products',{'id':pid,'act':'delete'},'/biz/rules')
        with self.core.conn() as db:self.assertNotIn(pid,pp.private_for(db,cid))
        pp.BACKGROUND=True

    def test_ai_profile(self):
        """사업자별 AI 상담 설정이 저장되고, 그 회사 상담에만 들어간다."""
        b,o,cid=self.signup_and_approve('설정마켓','aiset@example.com')
        self.post(b,'/biz/ai-profile',{'shipping':'오후 2시 전 주문은 당일 출고'},'/biz/rules')
        self.post(b,'/biz/ai-profile',{'handoff':'불량은 담당자에게'},'/biz/rules')
        with self.core.conn() as db:
            cb=sys.modules['chatbot'];prof=cb.profile(db,cid);facts=cb.company_facts(db,self.core.company(db,cid))
        self.assertEqual((prof['shipping'],prof['handoff']),('오후 2시 전 주문은 당일 출고','불량은 담당자에게'))
        self.assertIn('[배송 정책]\n오후 2시 전 주문은 당일 출고',facts)
        b2,_,cid2=self.signup_and_approve('옆가게','aiset2@example.com')
        with self.core.conn() as db:self.assertNotIn('당일 출고',cb.company_facts(db,self.core.company(db,cid2)))

    def test_courier_tracking(self):
        """배송 조회 요청에 송장으로 답하고, 스마트택배 알림(콜백)으로 배송 상태가 바뀌면 기록·알림한다."""
        b,o,cid=self.signup_and_approve('택배마켓','courier@example.com')
        me=self.client();case_id=self.file_case(me,'택배마켓','배송 조회',str(cid),title='주문한 게 안 와요')
        trk=sys.modules['tracking']
        # 키가 없으면 송장번호와 택배사 조회 링크로 답한다
        page=b.get(f'/biz/case/{case_id}').get_data(as_text=True);self.assertIn('송장번호로 답하기',page)
        self.assertIn('확인해 주세요',self.post(b,f'/biz/case/{case_id}',{'act':'ship_track','courier':'CJ대한통운','tracking':'12'},follow_redirects=True).get_data(as_text=True))
        self.post(b,f'/biz/case/{case_id}',{'act':'ship_track','courier':'CJ대한통운','tracking':'1234-5678-9012'})
        with self.core.conn() as db:
            c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone();ev=self.core.events(db,case_id)
        self.assertEqual(c['status'],'answered');self.assertIn('cjlogistics.com',ev[-1]['reply'])
        self.assertNotIn('송장번호로 답하기',b.get(f'/biz/case/{case_id}').get_data(as_text=True))  # 한 번만
        self.assertIn('123456789012',me.get(f'/case/{case_id}').get_data(as_text=True))
        # 키가 있으면 스마트택배에 등록하고, 콜백으로 상태를 받는다
        case2=self.file_case(me,'택배마켓','배송 조회',str(cid),title='배송이 늦어요')
        sent={}
        def fake_post(path,body):sent.update(path=path,body=body);return {'success':True,'num':body['num'],'fid':body['fid']}
        with patch.dict(os.environ,{'SWEETTRACKER_TIER':'t','SWEETTRACKER_KEY':'k'}),patch.object(trk,'post',fake_post):
            self.post(b,f'/biz/case/{case2}',{'act':'ship_track','courier':'롯데택배','tracking':'987654321098'})
            self.assertIn('확인 중',me.get(f'/case/{case2}').get_data(as_text=True))
        body=sent['body'];self.assertEqual((sent['path'],body['code'],body['num'],body['fid']),('/add_invoice','08','987654321098',f'{case2}-ship'))
        hook=body['callback_url'][body['callback_url'].index('/biz/hook/'):]
        a=self.client()
        self.assertFalse(a.post(hook.replace('/trace/','/trace/x'),json={'fid':f'{case2}-ship','level':'5'}).get_json()['code'])  # 토큰이 틀리면 거절
        self.assertFalse(a.post(hook,json={'fid':f'{case_id}-ship','level':'5'}).get_json()['code'])  # 다른 송장 fid도 거절
        self.assertTrue(a.post(hook,json={'fid':f'{case2}-ship','level':'5','where':'서울 강남','time_trans':'2026-10-13 09:10:00'}).get_json()['code'])
        self.assertTrue(a.post(hook,data={'fid':f'{case2}-ship','level':'3'}).get_json()['code'])  # 늦게 온 예전 단계는 무시
        page=me.get(f'/case/{case2}').get_data(as_text=True);self.assertIn('배송 출발',page);self.assertIn('서울 강남',page)
        with self.core.conn() as db:texts=[e['text'] for e in self.core.events(db,case2)]
        self.assertEqual(sum('배송 출발' in t for t in texts),1);self.assertFalse(any('배송 중' in t for t in texts))
        tok=self.client().post('/biz/api/v1/login',json={'login_id':'courier@example.com','password':'longpassword1'}).get_json()['token']
        d=a.get(f'/biz/api/v1/cases/{case2}',headers={'Authorization':'Bearer '+tok}).get_json()
        self.assertEqual((d['tracks'][0]['status'],d['can']['ship_track']),('배송 출발',False))
        # 교환 새 상품 발송도 같은 방식으로 등록된다
        self.assertEqual(trk.CODES['CJ대한통운'],'04')

    def test_order_cancel_and_change(self):
        b,o,cid=self.signup_and_approve('주문변경상회','order@example.com')
        cl=self.core.classify
        self.assertEqual(cl('어제 산 거 주문 취소하고 싶어요'),'주문 취소')
        self.assertEqual(cl('배송지 주소 변경 가능한가요'),'주문 변경')
        self.assertEqual(cl('마음에 안 들어서 반품할게요'),'반품·환불')
        # 주문 취소: 승인하면 정한 답이 가고, 환불 계좌를 받을 수 있다
        me=self.client();cs=self.file_case(me,'주문변경상회','주문 취소',str(cid))
        with self.core.conn() as db:self.assertTrue(self.core.refund_case(db.execute('SELECT * FROM cases WHERE id=?',(cs,)).fetchone()))
        self.post(b,f'/biz/case/{cs}',{'act':'approve'})
        self.assertIn('주문 취소 요청 확인했습니다',me.get(f'/case/{cs}').get_data(as_text=True))
        # 주문 변경: 자동 처리 대상이 아니라 사장님이 확인한다
        cs2=self.file_case(self.client(),'주문변경상회','주문 변경',str(cid))
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT decision FROM cases WHERE id=?',(cs2,)).fetchone()[0],'pending')
        self.assertIn('주문 변경',b.get('/biz/rules').get_data(as_text=True))

    def test_customer_track_lookup(self):
        """고객이 송장번호로 직접 배송 조회: 요청을 만들지 않고 바로 상태를 본다."""
        b,o,cid=self.signup_and_approve('조회마켓','track@example.com')
        trk=sys.modules['tracking'];me=self.client()
        page=me.get(f'/to/{cid}').get_data(as_text=True)
        self.assertIn(f'/track?company_id={cid}',page)  # 배송 조회 버튼은 조회 화면으로
        ans={'level':5,'complete':False,'receiverName':'홍길동','receiverAddr':'서울 어딘가',
             'trackingDetails':[{'timeString':'2026-10-12 21:00:00','where':'대전 HUB','kind':'간선상차'},{'timeString':'2026-10-13 07:30:00','where':'강남 대리점','kind':'배송출발'}]}
        with self.core.conn() as db:n0=db.execute('SELECT COUNT(*) FROM cases').fetchone()[0]
        with patch.dict(os.environ,{'SWEETTRACKER_T_KEY':'k'}),patch.object(trk,'get_info',lambda code,inv:ans if (code,inv)==('04','123456789012') else {'status':False,'msg':'운송장 미등록'}):
            page=me.get(f'/track?company_id={cid}&courier=CJ대한통운&invoice=1234-5678-9012').get_data(as_text=True)
            self.assertIn('배송 출발',page);self.assertIn('강남 대리점',page);self.assertIn('간선상차',page)
            self.assertNotIn('홍길동',page);self.assertNotIn('서울 어딘가',page)  # 받는 사람 정보는 보이지 않는다
            self.assertIn('운송장 미등록',me.get('/track?courier=CJ대한통운&invoice=111111111111').get_data(as_text=True))
            self.assertIn('송장번호를 확인해',me.get('/track?courier=CJ대한통운&invoice=12').get_data(as_text=True))
            self.assertIn('홈페이지에서',me.get('/track?courier=CU 편의점택배&invoice=123456789012').get_data(as_text=True))
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM cases').fetchone()[0],n0)
        # 키가 없으면 택배사 홈페이지로 안내
        self.assertIn('CJ대한통운 홈페이지에서 조회하기',me.get('/track?courier=CJ대한통운&invoice=123456789012').get_data(as_text=True))

    def test_simple_request_form(self):
        """요청은 버튼으로 사유만 골라도 접수된다 (긴 글·원하는 해결 질문 없이)."""
        b,o,cid=self.signup_and_approve('간편상회','simple@example.com')
        me=self.client();base={'company':'간편상회','company_id':str(cid),'phone':'010-2222-3333','password':'1234','privacy':'1','consent':'1'}
        r=self.post(me,'/submit',dict(base,category='주문 취소',reason='잘못 주문했어요',order_no='A-1'),'/new')
        self.assertEqual(r.status_code,302)
        with self.core.conn() as db:c=db.execute('SELECT * FROM cases ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual((c['title'],c['body'],c['want'],c['order_no']),('주문 취소 · 잘못 주문했어요','잘못 주문했어요','환불','A-1'))
        # 주문번호가 없으면, 주문 변경은 바꿀 내용이 없으면 다시 묻는다
        r=self.post(me,'/submit',dict(base,category='주문 취소',reason='단순 변심'),'/new');self.assertIn('/new',r.headers['Location'])
        self.assertIn('주문번호를 적어',me.get('/new').get_data(as_text=True))
        r=self.post(me,'/submit',dict(base,category='주문 변경',reason='배송지',order_no='A-2'),'/new');self.assertIn('/new',r.headers['Location'])
        self.assertIn('바꿀 내용을 적어',me.get('/new').get_data(as_text=True))
        self.post(me,'/submit',dict(base,category='주문 변경',reason='배송지',order_no='A-2',body='서울 강남구 테헤란로 1로 바꿔 주세요'),'/new')
        with self.core.conn() as db:c=db.execute('SELECT * FROM cases ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual((c['title'],c['want']),('주문 변경 · 배송지','기타'));self.assertIn('테헤란로',c['body'])
        # 유형마다 묻는 말이 다르다
        self.assertIn('어떤 주문을<br>취소할까요?',me.get(f'/new?company_id={cid}&category=주문 취소').get_data(as_text=True))

    def test_ops_service_keys(self):
        """운영 화면에서 택배 조회 키를 넣으면 서버 설정 없이 바로 쓰인다. 화면에는 끝 4자리만."""
        o=self.client();self.post(o,'/biz/ops/login',{'password':self.ops_pw})
        trk=sys.modules['tracking']
        with patch.dict(os.environ,{'SWEETTRACKER_T_KEY':''}):
            self.assertEqual(trk.t_key(),'')
            self.post(o,'/biz/ops/keys',{'name':'SWEETTRACKER_T_KEY','value':' abcd1234WXYZ '})
            self.assertEqual(trk.t_key(),'abcd1234WXYZ')
            page=o.get('/biz/ops/keys').get_data(as_text=True);self.assertIn('WXYZ',page);self.assertNotIn('abcd1234',page)
            self.post(o,'/biz/ops/keys',{'name':'SWEETTRACKER_T_KEY','act':'delete'})
            self.assertEqual(trk.t_key(),'')
        self.assertNotEqual(self.client().get('/biz/ops/keys').status_code,200)  # 운영자만

    def test_ops_overview_filters_and_company(self):
        """운영 화면: 전체 현황 요약, 비입점 요청 검색·필터, 기업 상세(읽기 전용)."""
        b,o,cid=self.signup_and_approve('운영상세상점','opsdetail@example.com')
        self.file_case(self.client(),'운영상세상점','기타',str(cid),title='입점 기업 요청이에요')
        self.file_case(self.client(),'아무도모르는가게','기타',title='비입점 가게 요청이에요')
        page=o.get('/biz/ops/all').get_data(as_text=True)
        for t in ('입점 기업','비입점 요청','처리 대기','처리할 비입점 요청','비입점 가게 요청이에요'):self.assertIn(t,page)
        self.assertIn('비입점 가게 요청이에요',o.get('/biz/ops?q=아무도모르는').get_data(as_text=True))
        self.assertNotIn('비입점 가게 요청이에요',o.get('/biz/ops?q=없는가게이름').get_data(as_text=True))
        self.assertNotIn('비입점 가게 요청이에요',o.get('/biz/ops?f=done').get_data(as_text=True))
        page=o.get(f'/biz/ops/company/{cid}').get_data(as_text=True)
        self.assertIn('운영상세상점',page);self.assertIn('입점 기업 요청이에요',page);self.assertNotIn('비입점 가게 요청이에요',page)
        self.assertEqual(o.get('/biz/ops/company/99999').status_code,404)
        self.assertNotEqual(self.client().get(f'/biz/ops/company/{cid}').status_code,200)  # 운영자만

    def test_order_ledger(self):
        """주문 장부: 판매처 CSV를 올리고, 요청과 주문번호·휴대폰으로 이어지고, 송장을 넣으면 배송 중."""
        b,o,cid=self.signup_and_approve('주문장부상회','ledger@example.com')
        csv_text=('스마트스토어 주문 내역\n상품주문번호,주문일시,수취인명,수취인연락처1,배송지,상품명,옵션정보,수량,최종 상품별 총 주문금액,주문상태,택배사,송장번호\n'
                  '2026101300001,2026.10.13 09:00,김구매,010-5555-6666,서울 강남구,수분 크림,50ml,2,"39,800",결제완료,,\n'
                  '2026101300002,2026.10.12 11:00,이구매,010-7777-8888,부산,토너,,1,15000,배송중,CJ대한통운,123412341234\n').encode('cp949')
        import io as _io
        r=self.post(b,'/biz/orders',{'act':'csv','channel':'스마트스토어','file':(_io.BytesIO(csv_text),'orders.csv')},'/biz/orders',content_type='multipart/form-data',follow_redirects=True)
        self.assertIn('새 주문 2건',r.get_data(as_text=True))
        with self.core.conn() as db:rows={x['order_no']:x for x in db.execute('SELECT * FROM orders WHERE company_id=?',(cid,)).fetchall()}
        a=rows['2026101300001'];self.assertEqual((a['product'],a['qty'],a['amount'],a['status'],a['phone'],a['ordered_on'],a['channel']),('수분 크림 / 50ml',2,39800,'paid','01055556666','2026-10-13','스마트스토어'))
        self.assertEqual((rows['2026101300002']['status'],rows['2026101300002']['courier']),('shipped','CJ대한통운'))
        page=b.get('/biz/orders').get_data(as_text=True);self.assertIn('수분 크림',page);self.assertIn('김구매',page)
        self.assertIn('토너',b.get('/biz/orders?g=moving').get_data(as_text=True));self.assertNotIn('수분 크림',b.get('/biz/orders?g=moving').get_data(as_text=True))
        # 같은 파일을 다시 올리면 새로 만들지 않고 고친다
        r=self.post(b,'/biz/orders',{'act':'csv','file':(_io.BytesIO(csv_text),'orders.csv')},'/biz/orders',content_type='multipart/form-data',follow_redirects=True)
        self.assertIn('고친 주문 2건',r.get_data(as_text=True))
        # 고객 요청이 주문번호로 이어진다
        me=self.client();cs=self.file_case(me,'주문장부상회','주문 취소',str(cid))
        with self.core.conn() as db:db.execute("UPDATE cases SET order_no='2026101300001' WHERE id=?",(cs,))
        page=b.get(f'/biz/case/{cs}').get_data(as_text=True);self.assertIn('수분 크림 / 50ml',page);self.assertIn('결제 완료',page)
        self.assertIn(f'/biz/case/{cs}',b.get(f'/biz/order/{a["id"]}').get_data(as_text=True))
        # 송장을 넣으면 배송 중, 상태 버튼으로 바꾸기
        self.post(b,f'/biz/order/{a["id"]}',{'courier':'한진택배','invoice':'5555-6666-7777'})
        with self.core.conn() as db:x=db.execute('SELECT status,invoice FROM orders WHERE id=?',(a['id'],)).fetchone()
        self.assertEqual((x['status'],x['invoice']),('shipped','555566667777'))
        self.post(b,f'/biz/order/{a["id"]}',{'status':'delivered'})
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT status,product FROM orders WHERE id=?',(a['id'],)).fetchone()[:],('delivered','수분 크림 / 50ml'))
        # 직접 넣기, 같은 번호는 막는다
        self.post(b,'/biz/orders',{'order_no':'M-1','product':'선물 세트','amount':'30,000','phone':'010-1212-3434'})
        r=self.post(b,'/biz/orders',{'order_no':'M-1'},'/biz/orders',follow_redirects=True);self.assertIn('같은 주문번호가 이미',r.get_data(as_text=True))
        # 앱 API
        tok=self.client().post('/biz/api/v1/login',json={'login_id':'ledger@example.com','password':'longpassword1'}).get_json()['token'];h={'Authorization':'Bearer '+tok}
        d=self.client().get('/biz/api/v1/orders?g=done',headers=h).get_json();self.assertEqual([x['order_no'] for x in d['orders']],['2026101300001'])
        d=self.client().post(f'/biz/api/v1/orders/{a["id"]}',json={'status':'refunded','memo':'환불 완료'},headers=h).get_json()
        self.assertEqual((d['status_label'],d['memo'],d['cases'][0]['id']),('환불','환불 완료',cs))
        self.assertEqual(self.client().post('/biz/api/v1/orders',json={'order_no':'M-1'},headers=h).status_code,400)
        # 다른 기업은 볼 수 없다
        b2,_,_=self.signup_and_approve('남의주문상회','other-orders@example.com')
        self.assertEqual(b2.get(f'/biz/order/{a["id"]}').status_code,404);self.assertNotIn('김구매',b2.get('/biz/orders').get_data(as_text=True))

    def test_order_sync_with_requests(self):
        """요청을 처리하면 이어진 주문 상태도 같이 바뀐다. 이미 보낸 주문은 취소하지 않고 알려 준다."""
        b,o,cid=self.signup_and_approve('주문맞춤상회','ordersync@example.com')
        for no in ('20261013-0001','S-2','S-3','S-4'):self.post(b,'/biz/orders',{'order_no':no,'product':'크림','phone':'010-1111-2222'})
        self.post(b,'/biz/orders',{'order_no':'S-9','product':'짐작','phone':'010-1111-2222'})
        def st(no):
            with self.core.conn() as db:return db.execute('SELECT status,invoice FROM orders WHERE company_id=? AND order_no=?',(cid,no)).fetchone()[:]
        me=self.client()
        def case(cat,no):
            cs=self.file_case(me,'주문맞춤상회',cat,str(cid))
            with self.core.conn() as db:db.execute('UPDATE cases SET order_no=? WHERE id=?',(no,cs))
            return cs
        # 취소 승인 → 주문도 취소
        c1=case('주문 취소','20261013-0001');self.post(b,f'/biz/case/{c1}',{'act':'approve'})
        self.assertEqual(st('20261013-0001')[0],'canceled')
        self.assertIn('취소',b.get(f'/biz/case/{c1}').get_data(as_text=True))
        # 이미 보낸 주문: 경고가 보이고 취소되지 않는다
        with self.core.conn() as db:db.execute("UPDATE orders SET status='shipped' WHERE company_id=? AND order_no='S-2'",(cid,))
        c2=case('주문 취소','S-2');self.assertIn('이미 발송된 주문이에요',b.get(f'/biz/case/{c2}').get_data(as_text=True))
        self.post(b,f'/biz/case/{c2}',{'act':'approve'});self.assertEqual(st('S-2')[0],'shipped')
        # 송장 알리기 → 배송 중 + 송장
        c3=case('배송 조회','S-3');self.post(b,f'/biz/case/{c3}',{'act':'ship_track','courier':'한진택배','tracking':'123456789012'})
        self.assertEqual(st('S-3'),('shipped','123456789012'))
        # 환불 완료 → 환불
        c4=case('반품·환불','S-4');self.post(b,f'/biz/case/{c4}',{'act':'refund_done'});self.assertEqual(st('S-4')[0],'refunded')
        # 주문번호 없이 휴대폰으로만 짐작한 주문은 바꾸지 않는다
        c5=case('반품·환불','');self.post(b,f'/biz/case/{c5}',{'act':'refund_done'});self.assertEqual(st('S-9')[0],'paid')
        # 앱 API도 같은 정보
        tok=self.client().post('/biz/api/v1/login',json={'login_id':'ordersync@example.com','password':'longpassword1'}).get_json()['token']
        d=self.client().get(f'/biz/api/v1/cases/{c2}',headers={'Authorization':'Bearer '+tok}).get_json()
        self.assertEqual((d['order']['order_no'],d['cancel_blocked']),('S-2',True))

    def test_owner_workspace_pages(self):
        """사장님 화면: 홈 한 화면 요약·브리핑, 승인할 일, 교환·반품 단계, 서비스 연동."""
        b,o,cid=self.signup_and_approve('한화면상회','oneview@example.com')
        me=self.client();c1=self.file_case(me,'한화면상회','교환',str(cid),title='사이즈가 안 맞아요');c2=self.file_case(me,'한화면상회','배송 조회',str(cid),title='언제 와요')
        home=b.get('/biz/').get_data(as_text=True)
        for t in ('사장님','오늘 들어온 요청','승인할 요청이','소보루 브리핑','사장님 승인이 필요한 요청이 2건','사이즈가 안 맞아요','class="bside"','서비스 연동'):self.assertIn(t,home)
        ap=b.get('/biz/approvals').get_data(as_text=True);self.assertIn('사이즈가 안 맞아요',ap);self.assertIn('언제 와요',ap)
        r=b.get('/biz/returns').get_data(as_text=True);self.assertIn('사이즈가 안 맞아요',r);self.assertNotIn('언제 와요',r);self.assertIn('새로 접수',r)
        self.post(b,f'/biz/case/{c1}',{'act':'approve'})
        r=b.get('/biz/returns?s=back').get_data(as_text=True);self.assertIn('사이즈가 안 맞아요',r)
        self.post(b,f'/biz/case/{c1}',{'act':'ret_received'})
        self.assertIn('사이즈가 안 맞아요',b.get('/biz/returns?s=next').get_data(as_text=True))
        cn=b.get('/biz/connect').get_data(as_text=True)
        for t in ('네이버 스마트스토어','쿠팡','택배 배송 조회','카카오 알림톡','엑셀 올리기','준비 중'):self.assertIn(t,cn)
        self.post(b,'/biz/orders',{'order_no':'X-1','channel':'쿠팡','product':'크림'})
        self.assertIn('주문 1건',b.get('/biz/connect').get_data(as_text=True))

    def test_courier_tracking_free_key(self):
        """무료 조회 키(t_key): 송장을 넣으면 바로 한 번 묻고, cron(poll)이 다시 물어 단계가 바뀌면 기록한다."""
        b,o,cid=self.signup_and_approve('무료택배마켓','freekey@example.com')
        me=self.client();trk=sys.modules['tracking']
        answers={'111122223333':{'level':3,'lastDetail':{'where':'대전 HUB','timeString':'2026-10-13 08:00:00'}},'999988887777':{'status':False,'code':'104','msg':'운송장 미등록'}}
        asked=[]
        def fake(code,invoice):asked.append((code,invoice));return answers.get(invoice,{})  # 다른 테스트의 송장은 빈 답
        with patch.dict(os.environ,{'SWEETTRACKER_T_KEY':'k'}),patch.object(trk,'get_info',fake):
            c1=self.file_case(me,'무료택배마켓','배송 조회',str(cid),title='언제 와요')
            self.post(b,f'/biz/case/{c1}',{'act':'ship_track','courier':'한진택배','tracking':'111122223333'})
            self.assertEqual(asked,[('05','111122223333')])
            page=me.get(f'/case/{c1}').get_data(as_text=True);self.assertIn('배송 중',page);self.assertIn('대전 HUB',page)
            c2=self.file_case(me,'무료택배마켓','배송 조회',str(cid),title='송장이 이상해요')
            self.post(b,f'/biz/case/{c2}',{'act':'ship_track','courier':'CJ대한통운','tracking':'999988887777'})
            with self.core.conn() as db:self.assertIn('운송장 미등록',db.execute("SELECT note FROM tracks WHERE fid=?",(f'{c2}-ship',)).fetchone()[0])
            answers['111122223333']={'level':6,'trackingDetails':[{'where':'서울 강남','timeString':'2026-10-13 15:00:00'}]}
            asked.clear();self.assertEqual(trk.poll(),1)
            self.assertIn(('05','111122223333'),asked);self.assertNotIn(('04','999988887777'),asked)  # 조회가 안 되는 송장은 다시 묻지 않는다
            asked.clear();trk.poll();self.assertNotIn(('05','111122223333'),asked)  # 배송 완료된 송장도 더 묻지 않는다
        with self.core.conn() as db:texts=[e['text'] for e in self.core.events(db,c1)]
        self.assertTrue(any('배송 완료' in t and '서울 강남' in t for t in texts))

    def test_compensation_approval(self):
        b,o,cid=self.signup_and_approve('보상상회','comp@example.com')
        self.post(b,'/biz/rules',{'category':'제품 불량','comp':'적립금 3,000원'})
        self.assertIn('적립금 3,000원',b.get('/biz/rules').get_data(as_text=True))
        me=self.client();cs=self.file_case(me,'보상상회','제품 불량',str(cid))
        # 홈과 목록에 보상 승인 대기로 보이고, 요청 화면에 추천 보상이 채워져 있다
        self.assertIn('보상 승인을 기다리는 요청 1건',b.get('/biz/').get_data(as_text=True))
        self.assertIn('보상 승인',b.get('/biz/all?f=comp').get_data(as_text=True))
        self.assertIn('value="적립금 3,000원"',b.get(f'/biz/case/{cs}').get_data(as_text=True))
        # 승인 전에는 고객에게 보상 안내가 가지 않는다
        self.assertNotIn('적립금',me.get(f'/case/{cs}').get_data(as_text=True))
        self.post(b,f'/biz/case/{cs}',{'act':'comp','comp':'적립금 5,000원'})  # 사장님이 고쳐서 승인
        self.assertIn('적립금 5,000원',me.get(f'/case/{cs}').get_data(as_text=True))
        with self.core.conn() as db:c=db.execute('SELECT comp,comp_status FROM cases WHERE id=?',(cs,)).fetchone()
        self.assertEqual((c['comp'],c['comp_status']),('적립금 5,000원','given'))
        self.assertNotIn('보상 승인을 기다리는',b.get('/biz/').get_data(as_text=True))
        # 두 번 주지 않는다
        self.post(b,f'/biz/case/{cs}',{'act':'comp','comp':'적립금 9,000원'})
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT comp FROM cases WHERE id=?',(cs,)).fetchone()[0],'적립금 5,000원')
        # 보상 안 함
        cs2=self.file_case(self.client(),'보상상회','제품 불량',str(cid))
        self.post(b,f'/biz/case/{cs2}',{'act':'comp_skip'})
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT comp_status FROM cases WHERE id=?',(cs2,)).fetchone()[0],'skipped')
        # 앱 API
        tok=self.client().post('/biz/api/v1/login',json={'login_id':'comp@example.com','password':'longpassword1'}).get_json()['token']
        h={'Authorization':'Bearer '+tok}
        cs3=self.file_case(self.client(),'보상상회','제품 불량',str(cid))
        self.assertEqual(self.client().get('/biz/api/v1/home',headers=h).get_json()['counts']['comp'],1)
        d=self.client().get(f'/biz/api/v1/cases/{cs3}',headers=h).get_json()
        self.assertEqual((d['comp']['reco'],d['can']['comp']),('적립금 3,000원',True))
        r=self.client().get('/biz/api/v1/rules',headers=h).get_json()
        self.assertEqual(next(x for x in r['rules'] if x['category']=='제품 불량')['comp'],'적립금 3,000원')

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
        self.assertIn('배송 조회 2건 모두 승인',b.get('/biz/approvals').get_data(as_text=True))
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

    def test_shop_naver_connect_and_sync(self):
        """스마트스토어: 사장님 키로 연결 확인 -> 암호화 저장 -> 문의는 요청으로, 주문은 장부로. 같은 문의는 한 번만."""
        import bcrypt,urllib.parse
        shops=sys.modules['shops'];b,o,cid=self.signup_and_approve('네이버연결상점','naverlink@example.com')
        secret=bcrypt.gensalt().decode();calls=[]
        def fake(method,url,headers=None,body=None):
            calls.append((method,url))
            if url.endswith('/oauth2/token'):
                f=dict(urllib.parse.parse_qsl(body.decode()))
                self.assertEqual((f['type'],f['grant_type'],f['client_id']),('SELF','client_credentials','app-id-1234'))
                ok=bcrypt.checkpw(f"app-id-1234_{f['timestamp']}".encode(),__import__('base64').b64decode(f['client_secret_sign']))
                return (200,{'access_token':'tok','expires_in':10800}) if ok else (401,{})
            self.assertEqual(headers['Authorization'],'Bearer tok')
            if '/last-changed-statuses' in url:return 200,{'data':{'lastChangeStatuses':[{'productOrderId':'2026101400001'}]}}
            if url.endswith('/product-orders/query'):
                self.assertEqual(json.loads(body)['productOrderIds'],['2026101400001'])
                return 200,{'data':[{'order':{'orderId':'O1','ordererName':'김네이','orderDate':'2026-10-13T10:00:00.0+09:00'},
                    'productOrder':{'productOrderId':'2026101400001','productOrderStatus':'DELIVERING','productName':'수분 크림','quantity':2,'totalPaymentAmount':39800,
                                    'shippingAddress':{'name':'김네이','tel1':'010-2222-3333','baseAddress':'서울','detailedAddress':'1층'}},
                    'delivery':{'deliveryCompany':'CJGLS','trackingNumber':'612300001111'}}]}
            if '/pay-user/inquiries' in url:return 200,{'content':[{'inquiryNo':77,'title':'배송이 언제 되나요?','inquiryContent':'주문한 크림 언제 와요','customerName':'김*이',
                                                                  'productOrderIdList':['2026101400001'],'answered':False,'inquiryRegistrationDateTime':'2026-10-14T09:00:00'}],'totalPages':1}
            return 404,{}
        with patch.object(shops,'http',fake):
            shops._tokens.clear()
            r=self.post(b,'/biz/connect/naver',{'client_id':'app-id-1234','client_secret':'wrong'})
            self.assertIn('시크릿이 맞지 않아요',b.get(r.headers['Location']).get_data(as_text=True))
            with self.core.conn() as db:self.assertIsNone(shops.link(db,cid,'naver'))
            self.post(b,'/biz/connect/naver',{'client_id':'app-id-1234','client_secret':secret})
            with self.core.conn() as db:
                lk=shops.link(db,cid,'naver');self.assertNotIn(secret,lk['creds']);self.assertEqual(shops.unseal(lk['creds'])['client_secret'],secret)
                c=db.execute("SELECT * FROM cases WHERE company_id=? AND channel='스마트스토어'",(cid,)).fetchone()
                od=db.execute("SELECT * FROM orders WHERE company_id=? AND order_no='2026101400001'",(cid,)).fetchone()
            self.assertEqual((c['title'],c['category'],c['status'],c['order_no']),('배송이 언제 되나요?','배송 조회','forwarded','2026101400001'))
            self.assertEqual((od['channel'],od['status'],od['courier'],od['invoice'],od['qty'],od['phone']),('스마트스토어','shipped','CJ대한통운','612300001111',2,'01022223333'))
            page=b.get('/biz/connect/naver').get_data(as_text=True);self.assertIn('••••1234',page);self.assertNotIn(secret,page)
            self.assertIn('연결됨',b.get('/biz/connect').get_data(as_text=True))
            self.post(b,'/biz/connect/naver',{'act':'sync'})  # 같은 문의는 다시 만들지 않는다
            with self.core.conn() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM cases WHERE company_id=? AND channel='스마트스토어'",(cid,)).fetchone()[0],1)
            self.assertIn('스마트스토어',b.get(f"/biz/case/{c['id']}").get_data(as_text=True))
        self.assertFalse(any('coupang' in u for _,u in calls))
        self.assertEqual(self.client().get('/biz/connect/naver').status_code,302)  # 로그인해야
        self.post(b,'/biz/connect/naver',{'act':'delete'})
        with self.core.conn() as db:self.assertIsNone(shops.link(db,cid,'naver'))

    def test_shop_coupang_signature_and_errors(self):
        """쿠팡: HMAC 서명 머리글, 주문서·문의 가져오기, 키가 틀리면 저장하지 않고 이유를 보여 준다."""
        import hmac,hashlib,urllib.parse
        shops=sys.modules['shops'];b,o,cid=self.signup_and_approve('쿠팡연결상점','coupanglink@example.com')
        state={'deny':True}
        def fake(method,url,headers=None,body=None):
            m=re.match(r'CEA algorithm=HmacSHA256, access-key=AK1, signed-date=(\d{6}T\d{6}Z), signature=([0-9a-f]{64})$',headers['Authorization'])
            self.assertTrue(m,headers['Authorization'])
            u=urllib.parse.urlsplit(url)
            self.assertEqual(m.group(2),hmac.new(b'SK1',(m.group(1)+'GET'+u.path+u.query).encode(),hashlib.sha256).hexdigest())
            if state['deny']:return 401,{}
            q=dict(urllib.parse.parse_qsl(u.query))
            if u.path.endswith('/onlineInquiries'):
                self.assertEqual(q['answeredType'],'NOANSWER')
                return 200,{'data':{'content':[{'inquiryId':5,'content':'반품하고 환불받고 싶어요','inquiryAt':'2026-10-14T08:00:00','orderIds':[9001]}],'pagination':{'totalPages':1}}}
            if u.path.endswith('/callCenterInquiries'):return 200,{'data':{'content':[],'pagination':{'totalPages':1}}}
            if u.path.endswith('/ordersheets'):
                self.assertTrue(q['createdAtFrom'].endswith('+09:00'))
                rows=[{'orderId':9001,'orderedAt':'2026-10-12T10:00:00','status':'INSTRUCT','orderer':{'name':'이쿠팡'},'receiver':{'name':'이쿠팡','safeNumber':'0502-1234-5678','addr1':'부산','addr2':'2층'},
                       'orderItems':[{'vendorItemName':'니트','shippingCount':1,'orderPrice':20000},{'vendorItemName':'양말','shippingCount':2,'orderPrice':6000}],'deliveryCompanyName':'','invoiceNumber':''}]
                return 200,{'data':rows if q['status']=='INSTRUCT' else [],'nextToken':''}
            return 404,{}
        with patch.object(shops,'http',fake):
            r=self.post(b,'/biz/connect/coupang',{'vendor_id':'A00012345','access_key':'AK1','secret_key':'SK1'})
            self.assertIn('서버 IP가 등록되지 않았어요',b.get(r.headers['Location']).get_data(as_text=True))
            with self.core.conn() as db:self.assertIsNone(shops.link(db,cid,'coupang'))
            state['deny']=False
            self.post(b,'/biz/connect/coupang',{'vendor_id':'A00012345','access_key':'AK1','secret_key':'SK1'})
            with self.core.conn() as db:
                c=db.execute("SELECT * FROM cases WHERE company_id=? AND channel='쿠팡'",(cid,)).fetchone()
                od=db.execute("SELECT * FROM orders WHERE company_id=? AND order_no='9001'",(cid,)).fetchone()
            self.assertEqual((c['category'],c['order_no']),('반품·환불','9001'))
            self.assertEqual((od['status'],od['product'],od['qty'],od['amount']),('ready','니트 외 1건',3,26000))
            state['deny']=True  # 나중에 키가 만료되면 연결 화면에 이유가 남는다
            self.post(b,'/biz/connect/coupang',{'act':'sync'})
            with self.core.conn() as db:self.assertEqual(shops.link(db,cid,'coupang')['status'],'error')
            self.assertIn('확인 필요',b.get('/biz/connect').get_data(as_text=True))

    def test_team_roles_notes_assign(self):
        """직원 초대 → 비밀번호 정하고 로그인 → 상담원은 승인·설정 못 함, 메모는 고객에게 안 보임, 담당자 배정."""
        b,o,cid=self.signup_and_approve('팀테스트상점','teamowner@example.com')
        r=self.post(b,'/biz/team',{'act':'invite','name':'김상담','email':'agent1@example.com','role':'agent'})
        html=r.get_data(as_text=True);m=re.search(r'value="(http[^"]*/join/[^"]+)"',html);self.assertTrue(m,html[:500])
        path='/biz/join/'+m.group(1).split('/join/')[1]
        # 같은 이메일로 다시 초대하거나 대표로 가입할 수 없다
        self.assertIn('이미 쓰고 있는',self.post(b,'/biz/team',{'act':'invite','name':'x','email':'agent1@example.com','role':'agent'},follow_redirects=True).get_data(as_text=True))
        a=self.client();r=self.post(a,path,{'password':'agentpassword1'})
        self.assertEqual(r.status_code,302)
        self.assertEqual(self.client().get(path).status_code,302)  # 한 번 쓰면 끝
        # 다시 로그인도 된다
        a2=self.client();self.assertEqual(self.post(a2,'/biz/login',{'login_id':'agent1@example.com','password':'agentpassword1'}).status_code,302)
        # 상담원은 설정·자동 처리·팀에 못 들어간다
        for p in ('/biz/settings','/biz/rules','/biz/team','/biz/connect'):self.assertEqual(a.get(p).status_code,302,p)
        self.assertNotIn('href="/biz/rules"',a.get('/biz/all').get_data(as_text=True))
        c=self.client();case_id=self.file_case(c,'팀테스트상점','제품 불량',company_id=cid)
        # 승인은 못 하고, 메모·배정은 된다
        self.post(a,f'/biz/case/{case_id}',{'act':'approve'})
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT decision FROM cases WHERE id=?',(case_id,)).fetchone()[0],'pending')
        with self.core.conn() as db:sid=db.execute("SELECT id FROM staff WHERE email='agent1@example.com'").fetchone()[0]
        self.post(a,f'/biz/case/{case_id}',{'act':'note','note':'비밀 메모: 사진 다시 확인'})
        self.post(a,f'/biz/case/{case_id}',{'act':'assign','assignee':str(sid)})
        page=a.get(f'/biz/case/{case_id}').get_data(as_text=True)
        self.assertIn('비밀 메모',page);self.assertIn('담당자를 김상담',page)
        self.assertIn(f'/biz/case/{case_id}',a.get('/biz/all?f=mine').get_data(as_text=True))
        # 답변에는 누가 보냈는지 기업 화면에만 남는다
        self.post(a,f'/biz/case/{case_id}',{'act':'reply','msg':'확인 후 교환해 드릴게요.'})
        self.assertIn('· 김상담',a.get(f'/biz/case/{case_id}').get_data(as_text=True))
        # 고객 화면·앱 API에는 메모와 직원 이름이 없다
        r=self.post(c,'/lookup',{'phone':'010-1234-5678','password':'1234'},'/mine')
        cpage=c.get(f'/case/{case_id}').get_data(as_text=True)
        self.assertNotIn('비밀 메모',cpage);self.assertNotIn('김상담',cpage)
        tok=self.client().post('/biz/api/v1/login',json={'login_id':'teamowner@example.com','password':'longpassword1'}).get_json()['token']
        d=self.client().get(f'/biz/api/v1/cases/{case_id}',headers={'Authorization':'Bearer '+tok}).get_data(as_text=True)
        self.assertNotIn('비밀 메모',d)
        # 대표는 승인할 수 있다
        self.post(b,f'/biz/case/{case_id}',{'act':'approve'})
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT decision FROM cases WHERE id=?',(case_id,)).fetchone()[0],'approved')
        # 보기 전용으로 바꾸면 아무것도 못 바꾸고, 맡던 요청은 비워진다
        self.post(b,'/biz/team',{'act':'role','id':sid,'role':'viewer'})
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT assignee FROM cases WHERE id=?',(case_id,)).fetchone()[0],'')
        self.post(a,f'/biz/case/{case_id}',{'act':'note','note':'보기 전용 메모'})
        self.assertNotIn('보기 전용 메모',b.get(f'/biz/case/{case_id}').get_data(as_text=True))
        # 내보내면 로그인이 풀린다
        self.post(b,'/biz/team',{'act':'remove','id':sid})
        self.assertEqual(a.get('/biz/all').status_code,302)
        self.assertEqual(self.post(self.client(),'/biz/login',{'login_id':'agent1@example.com','password':'agentpassword1'}).status_code,400)
        # 다른 회사 직원은 이 회사 요청을 못 본다
        b2,_,cid2=self.signup_and_approve('다른팀상점','teamother@example.com')
        self.assertEqual(b2.get(f'/biz/case/{case_id}').status_code,404)

    def test_instant_signup_verify_wizard(self):
        """바로 가입: 검증번호·중복 막기, 국세청 상태(모의), 이메일 확인 링크, 인증 전 판매처 연결 막기, 8단계 설정 저장·이어 하기, 시험 문의."""
        ob=sys.modules['onboard']
        c=self.client()
        bad=self.bizno();bad=bad[:9]+str((int(bad[9])+1)%10)
        r=self.post(c,'/biz/signup',{'name':'가짜번호','biz_no':bad,'owner_name':'김','login_id':'fakeno@example.com','password':'longpassword1','terms':'1'})
        self.assertEqual(r.status_code,400);self.assertIn('사업자등록번호가 맞지 않아요',r.get_data(as_text=True))
        no=self.bizno()
        # 국세청 키가 있으면 폐업 번호는 가입 못 하고, 계속사업자는 이메일 확인만 끝나면 자동 인증
        with patch.dict(os.environ,{'NTS_API_KEY':'k'}),patch.object(ob,'nts_post',return_value=(200,{'data':[{'b_stt_cd':'03'}]})):
            r=self.post(self.client(),'/biz/signup',{'name':'폐업상점','biz_no':no,'owner_name':'김','login_id':'closed@example.com','password':'longpassword1','terms':'1'})
            self.assertIn('폐업',r.get_data(as_text=True))
        with patch.dict(os.environ,{'NTS_API_KEY':'k'}),patch.object(ob,'nts_post',return_value=(200,{'data':[{'b_stt_cd':'01'}]})):
            r=self.post(c,'/biz/signup',{'name':'바로상점','biz_no':no,'owner_name':'김바로','login_id':'instant@example.com','password':'longpassword1','terms':'1','industry':'식품'})
        self.assertEqual(r.status_code,302)
        with self.core.conn() as db:co=db.execute("SELECT * FROM companies WHERE login_id='instant@example.com'").fetchone()
        self.assertEqual((co['status'],co['member'],co['biz_status'],co['plan']),('active',0,'01','pilot'))
        # 같은 사업자번호·같은 이메일은 다시 가입할 수 없다 (직원 초대로 안내)
        r=self.post(self.client(),'/biz/signup',{'name':'바로상점2','biz_no':no,'owner_name':'김','login_id':'instant2@example.com','password':'longpassword1','terms':'1'})
        self.assertIn('직원으로 초대',r.get_data(as_text=True))
        r=self.post(self.client(),'/biz/signup',{'name':'바로상점3','biz_no':self.bizno(),'owner_name':'김','login_id':'instant@example.com','password':'longpassword1','terms':'1'})
        self.assertIn('이미 가입된 이메일',r.get_data(as_text=True))
        # 인증 전: 화면은 쓰지만 판매처 연결은 막히고, 소비자 접수 화면에서도 입점사로 보이지 않는다
        self.assertIn('회사 인증 전',c.get('/biz/connect').get_data(as_text=True))
        r=self.post(c,'/biz/connect/naver',{'client_id':'a','client_secret':'b'},follow_redirects=True)
        self.assertIn('회사 인증이 끝난 뒤',r.get_data(as_text=True))
        with self.core.conn() as db:self.assertIsNone(db.execute('SELECT 1 FROM shop_links WHERE company_id=?',(co['id'],)).fetchone())
        self.assertFalse(self.core.active_member(co))
        # 이메일 확인 링크 -> 국세청 계속사업자라 자동 인증
        self.assertEqual(self.client().get('/biz/verify/'+ob.verify_link(co).split('/verify/')[1]).status_code,302)
        with self.core.conn() as db:co=self.core.company(db,co['id'])
        self.assertEqual((co['email_verified'],co['member']),(1,1))
        self.assertEqual(self.client().get('/biz/verify/bad-token').status_code,302)
        # 처음 설정: 단계마다 저장되고 나중에 이어서
        self.assertIn('1. 기업 정보',c.get('/biz/start').get_data(as_text=True))
        self.post(c,'/biz/start',{'step':'company','industry':'식품','owner_name':'김바로','phone':'010-2222-3333'},'/biz/start?step=company')
        self.post(c,'/biz/start',{'step':'shop','shop_types':['네이버 스마트스토어','쿠팡']},'/biz/start?step=shop')
        r=self.post(c,'/biz/start',{'step':'center','contact':'02-111-2222','hours':'평일 10시~17시','notify_email':'cs@example.com'},'/biz/start?step=center')
        self.assertIn('step=policy',r.headers['Location'])
        self.post(c,'/biz/start',{'step':'policy','returns':'7일 안에 반품 가능','shipping':'당일 출고','return_address':'서울시 반품로 9','return_courier':'CJ대한통운'},'/biz/start?step=policy')
        self.post(c,'/biz/start',{'step':'connect','act':'skip'},'/biz/start?step=connect')
        self.post(c,'/biz/start',{'step':'ai','brand':'건강한 간식','scope':'상품 문의','handoff':'불량은 담당자'},'/biz/start?step=ai')
        self.post(c,'/biz/start',{'step':'widget'},'/biz/start?step=widget')
        with self.core.conn() as db:
            co=self.core.company(db,co['id']);prof=sys.modules['chatbot'].profile(db,co['id'])
        p=ob.progress(co);self.assertEqual((p['n'],p['next']),(7,'test'))
        self.assertEqual((co['contact'],co['notify_email'],co['shop_types'],co['return_address']),('02-111-2222','cs@example.com','네이버 스마트스토어,쿠팡','서울시 반품로 9'))
        self.assertEqual((prof['hours'],prof['returns'],prof['brand']),('평일 10시~17시','7일 안에 반품 가능','건강한 간식'))
        self.assertIn('처음 설정 7/8',c.get('/biz/all').get_data(as_text=True))
        # 시험 문의를 만들고 답하면 마지막 단계가 끝난다. 고객 알림은 나가지 않는다.
        r=self.post(c,'/biz/start',{'step':'test','act':'test_new'},'/biz/start?step=test')
        tid=int(r.headers['Location'].rsplit('/',1)[1])
        sent=[]
        with patch.object(self.core,'send_mail',lambda to,sub,body:sent.append(to)):self.post(c,f'/biz/case/{tid}',{'act':'reply','msg':'시험 답변이에요'})
        self.assertEqual(sent,[])
        with self.core.conn() as db:co=self.core.company(db,co['id'])
        self.assertTrue(ob.progress(co)['finished'])
        self.assertNotIn('처음 설정 ',c.get('/biz/all').get_data(as_text=True).replace('처음 설정 이어서',''))
        # 설정: 무료 시범·이용 현황 (답장한 요청 1건)
        page=c.get('/biz/settings').get_data(as_text=True)
        self.assertIn('무료 시범 이용 중',page);self.assertIn('답장한 요청',page)
        with self.core.conn() as db:self.assertEqual(ob.usage(db,co['id'])['replied'],1)
        # 쇼핑몰 위젯
        js=self.client().get(f'/widget.js?c={co["id"]}').get_data(as_text=True)
        self.assertIn(f'/to/{co["id"]}',js);self.assertIn('문의하기',js)

    def test_demo_workspace_isolated(self):
        """데모: 견본 요청으로 승인·답변·배정을 해 보되 실제 회사·소비자·알림과 완전히 나뉜다."""
        b,o,cid=self.signup_and_approve('데모주인상점','demoowner@example.com')
        self.assertIn('데모 열기',b.get('/biz/').get_data(as_text=True))
        self.post(b,'/biz/demo',{'act':'on'},'/biz/')
        home=b.get('/biz/').get_data(as_text=True)
        self.assertIn('데모 화면',home);self.assertIn('주문한 지 5일째',home)
        with self.core.conn() as db:
            d=db.execute('SELECT * FROM companies WHERE demo_of=?',(cid,)).fetchone()
            self.assertEqual(d['status'],'demo')
            ids=[r['id'] for r in db.execute('SELECT id FROM cases WHERE company_id=? ORDER BY id',(d['id'],))]
        self.assertGreaterEqual(len(ids),8)
        # 승인·답변·배정이 실제처럼 되지만 메일·알림은 나가지 않는다
        sent=[]
        with patch.object(self.core,'send_mail',lambda to,sub,body:sent.append(to)):
            self.post(b,f'/biz/case/{ids[1]}',{'act':'approve'},f'/biz/case/{ids[1]}')
            self.post(b,f'/biz/case/{ids[0]}',{'act':'reply','msg':'오늘 출고해요'},f'/biz/case/{ids[0]}')
            self.post(b,f'/biz/case/{ids[0]}',{'act':'assign','assignee':'owner'},f'/biz/case/{ids[0]}')
        self.assertEqual([x for x in sent if x],[])
        with self.core.conn() as db:
            self.assertEqual(db.execute('SELECT decision FROM cases WHERE id=?',(ids[1],)).fetchone()[0],'approved')
            self.assertEqual(db.execute('SELECT status FROM cases WHERE id=?',(ids[0],)).fetchone()[0],'answered')
        # 판매처 연결·팀·설정은 데모에서 막힌다
        self.assertEqual(b.get('/biz/connect').status_code,302);self.assertEqual(b.get('/biz/team').status_code,302)
        # 소비자 쪽: 데모 회사는 검색·접수 화면에 없다
        self.assertNotIn('(데모)',json.dumps(self.core.search_companies('데모주인')))
        self.assertEqual(self.client().get(f'/to/{d["id"]}').status_code,404)
        # 운영 화면 전체 현황에도 데모 요청이 없다
        self.assertNotIn('주문한 지 5일째',o.get('/biz/ops/all').get_data(as_text=True))
        # 처음부터 다시: 견본만 새로 만든다
        self.post(b,'/biz/demo',{'act':'reset'},'/biz/')
        with self.core.conn() as db:self.assertEqual(db.execute("SELECT decision FROM cases WHERE company_id=(SELECT id FROM companies WHERE demo_of=?) AND title LIKE '사이즈가 커서%'",(cid,)).fetchone()[0],'pending')
        # 데모 끝내기: 실제 화면에는 데모 요청이 없다
        self.post(b,'/biz/demo',{'act':'off'},'/biz/')
        home=b.get('/biz/').get_data(as_text=True)
        self.assertNotIn('데모 화면',home);self.assertNotIn('주문한 지 5일째',home)
        self.assertEqual(b.get(f'/biz/case/{ids[0]}').status_code,404)

    def test_google_signup_login(self):
        """구글로 가입·로그인 (모의 응답). 키가 없으면 버튼이 없고 이메일 가입으로 안내."""
        ob=sys.modules['onboard']
        self.assertNotIn('구글 계정으로 시작하기',self.client().get('/biz/signup').get_data(as_text=True))
        self.assertEqual(self.client().get('/biz/auth/google').status_code,302)
        def fake(method,url,data=None,headers=None):
            if 'token' in url:return 200,{'access_token':'at'}
            return 200,{'sub':'g-123','email':'GUser@example.com','email_verified':True,'name':'구글대표'}
        with patch.dict(os.environ,{'GOOGLE_CLIENT_ID':'cid','GOOGLE_CLIENT_SECRET':'sec'}),patch.object(ob,'http_json',side_effect=fake):
            c=self.client()
            self.assertIn('구글 계정으로 시작하기',c.get('/biz/signup').get_data(as_text=True))
            r=c.get('/biz/auth/google');self.assertIn('accounts.google.com',r.headers['Location'])
            state=re.search(r'state=([^&]+)',r.headers['Location']).group(1)
            self.assertEqual(c.get('/biz/auth/google/callback?state=wrong&code=x').headers['Location'].endswith('/login'),True)
            r=c.get('/biz/auth/google');state=re.search(r'state=([^&]+)',r.headers['Location']).group(1)
            r=c.get(f'/biz/auth/google/callback?state={state}&code=abc');self.assertTrue(r.headers['Location'].endswith('/signup'))
            page=c.get('/biz/signup').get_data(as_text=True);self.assertIn('guser@example.com',page);self.assertNotIn('name="password"',page)
            r=self.post(c,'/biz/signup',{'name':'구글상점','biz_no':self.bizno(),'owner_name':'구글대표','login_id':'guser@example.com','terms':'1'})
            self.assertEqual(r.status_code,302)
            with self.core.conn() as db:co=db.execute("SELECT * FROM companies WHERE login_id='guser@example.com'").fetchone()
            self.assertEqual((co['signup_via'],co['google_sub'],co['email_verified']),('google','g-123',1))
            # 다음부터는 구글로 바로 로그인
            c2=self.client();r=c2.get('/biz/auth/google');state=re.search(r'state=([^&]+)',r.headers['Location']).group(1)
            r=c2.get(f'/biz/auth/google/callback?state={state}&code=abc');self.assertEqual(r.headers['Location'].rstrip('/').endswith('/biz'),True)
            self.assertIn('구글상점',c2.get('/biz/').get_data(as_text=True))


    def test_marketing_pages(self):
        """공개 화면: 둘러보기(실제 화면 8단계), 판매처·업종 페이지, 계산기(넣은 값으로만 계산), 검색 노출, 방문 기록."""
        c=self.client()
        page=c.get('/biz/tour').get_data(as_text=True)
        self.assertEqual(page.count('class="tour-step'),8);self.assertIn('/static/tour/home-d.jpg',page);self.assertNotIn('noindex',page)
        for slug in ('smartstore','coupang','cafe24'):
            r=c.get('/biz/for/'+slug);self.assertEqual(r.status_code,200)
        page=c.get('/biz/for/cafe24').get_data(as_text=True);self.assertIn('지금 됨',page);self.assertNotIn('>연동 대기<',page)
        self.assertEqual(c.get('/biz/for/nope').status_code,404)
        page=c.get('/biz/industries').get_data(as_text=True)
        for slug in ('fashion','beauty','food','living','digital','furniture'):
            self.assertIn(f'/industries/{slug}',page);self.assertEqual(c.get('/biz/industries/'+slug).status_code,200)
        self.assertEqual(c.get('/biz/industries/nope').status_code,404)
        # 계산기: 1000건 × 6분 = 100시간, 40% 자동 = 40시간 × 12,000원 = 480,000원/월
        page=c.get('/biz/calculator?inquiries=1000&minutes=6&wage=12000&auto=40').get_data(as_text=True)
        self.assertIn('480,000',page);self.assertIn('5,760,000',page);self.assertIn('보장하지 않아요',page)
        page=c.get('/biz/calculator?inquiries=abc&minutes=-5&wage=1&auto=500').get_data(as_text=True)  # 이상한 값은 범위 안으로
        self.assertEqual(c.get('/biz/calculator?inquiries=abc').status_code,200)
        m=sys.modules['market'].calc({'inquiries':'abc','minutes':'-5','wage':'1','auto':'500'})
        self.assertEqual((m['v']['inquiries'],m['v']['minutes'],m['v']['wage'],m['v']['auto']),(300,1,1000,100))
        sm=c.get('/biz/sitemap.xml').get_data(as_text=True)
        self.assertIn('/for/coupang</loc>',sm);self.assertIn('/industries/food</loc>',sm);self.assertIn('/calculator</loc>',sm)
        self.assertIn('제품 둘러보기',c.get('/biz/').get_data(as_text=True))
        # 방문 기록: UTM 첫 유입을 기억해 가입에 붙인다 (IP는 저장하지 않음)
        v=self.client();v.get('/biz/for/smartstore?utm_source=naver&utm_medium=cpc&utm_campaign=fall')
        r=self.post(v,'/biz/signup',{'name':'유입상점','biz_no':self.bizno(),'owner_name':'김','login_id':'utm@example.com','password':'longpassword1','terms':'1'})
        with self.core.conn() as db:
            row=db.execute("SELECT source,medium,campaign FROM funnel WHERE kind='signup' AND company_id=(SELECT id FROM companies WHERE login_id='utm@example.com')").fetchone()
            self.assertEqual(tuple(row),('naver','cpc','fall'))
            self.assertTrue(db.execute("SELECT 1 FROM funnel WHERE kind='visit' AND path='/for/smartstore' AND campaign='fall'").fetchone())
            cols={r[1] for r in db.execute('PRAGMA table_info(funnel)')};self.assertNotIn('ip',cols)


    def test_consult_request_and_sales_pipeline(self):
        """상담 신청: 검사·저장·운영 알림·UTM, 봇 칸, 운영 영업 관리(단계·담당자·일정·메모·연락 기록), 운영 로그인 없이는 못 봄."""
        c=self.client();c.get('/biz/calculator?utm_source=blog&utm_campaign=guide1')
        r=self.post(c,'/biz/contact',{'company':'상담상점','name':'박담당','email':'bad'})
        self.assertEqual(r.status_code,400);self.assertIn('이메일',r.get_data(as_text=True))
        r=self.post(c,'/biz/contact',{'company':'상담상점','name':'박담당','email':'lead@example.com','phone':'010-3333-4444','shop_url':'https://shop.example.com',
            'channels':['쿠팡','카페24'],'volume':'월 500~2,000건','interests':['AI 상담','없는기능'],'message':'반품이 많아요'})
        self.assertIn('개인정보',r.get_data(as_text=True))  # 동의 안 함
        sent=[]
        with patch.object(self.core,'send_mail',lambda to,sub,body:sent.append(to)),patch.dict(os.environ,{'OPS_EMAIL':'ops@example.com'}):
            r=self.post(c,'/biz/contact',{'company':'상담상점','name':'박담당','email':'lead@example.com','phone':'010-3333-4444','shop_url':'https://shop.example.com',
                'channels':['쿠팡','카페24'],'volume':'월 500~2,000건','interests':['AI 상담','없는기능'],'message':'반품이 많아요','privacy':'1'})
        self.assertEqual(sorted(sent),['lead@example.com','ops@example.com'])
        self.assertIn('신청을 받았어요',r.get_data(as_text=True))
        with self.core.conn() as db:
            l=db.execute("SELECT * FROM leads WHERE email='lead@example.com'").fetchone()
            self.assertEqual((l['stage'],l['channels'],l['interests'],l['source'],l['campaign']),('new','쿠팡,카페24','AI 상담','blog','guide1'))
            self.assertTrue(db.execute("SELECT 1 FROM funnel WHERE kind='consult'").fetchone())
        # 봇이 숨은 칸을 채우면 저장하지 않는다
        self.post(self.client(),'/biz/contact',{'company':'봇','name':'봇','email':'bot@example.com','privacy':'1','website':'http://spam'})
        with self.core.conn() as db:self.assertIsNone(db.execute("SELECT 1 FROM leads WHERE email='bot@example.com'").fetchone())
        # 운영 로그인 없이는 못 본다
        self.assertEqual(c.get('/biz/ops/leads').status_code,302);self.assertEqual(c.get(f'/biz/ops/lead/{l["id"]}').status_code,302)
        o=self.client();self.post(o,'/biz/ops/login',{'password':self.ops_pw})
        page=o.get('/biz/ops/leads').get_data(as_text=True);self.assertIn('상담상점',page);self.assertIn('새 신청',page)
        lp=f'/biz/ops/lead/{l["id"]}'
        self.post(o,lp,{'act':'update','stage':'scheduled','owner':'김영업','demo_at':'2026-10-20T14:00','follow_up':'2026-10-01'})
        self.post(o,lp,{'act':'memo','memo':'카페24 연동을 가장 궁금해함'})
        self.post(o,lp,{'act':'contact','channel':'전화','text':'시연 일정 잡음'})
        with self.core.conn() as db:
            l=db.execute('SELECT * FROM leads WHERE id=?',(l['id'],)).fetchone()
            self.assertEqual((l['stage'],l['owner'],l['demo_at'],l['follow_up'],l['memo']),('scheduled','김영업','2026-10-20 14:00','2026-10-01','카페24 연동을 가장 궁금해함'))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lead_log WHERE lead_id=?',(l['id'],)).fetchone()[0],3)
        page=o.get(lp).get_data(as_text=True);self.assertIn('시연 일정 잡음',page);self.assertIn('단계: 새 신청 → 시연 예정',page)
        self.assertIn('오늘까지 연락할 곳',o.get('/biz/ops/leads').get_data(as_text=True))
        self.assertEqual(self.post(o,lp,{'act':'update','stage':'won','demo_at':'내일'},follow_redirects=True).status_code,200)
        # 같은 이메일로 가입하면 가입한 회사로 이어 보여 준다
        self.signup_and_approve('상담상점','lead@example.com')
        self.assertIn('가입함: 상담상점',o.get(lp).get_data(as_text=True))
        # 지우기 (개인정보 삭제 요청)
        self.post(o,lp,{'act':'delete'})
        with self.core.conn() as db:self.assertIsNone(db.execute("SELECT 1 FROM leads WHERE email='lead@example.com'").fetchone())

    def test_content_help_stories_seo_marketing(self):
        """자료실·도움말·고객 사례: 운영에서 쓰고 공개, 비공개는 숨김, HTML 막기, 동의 없는 사례 공개 막기, 사이트맵·구조화 데이터, 마케팅 분석."""
        c=self.client()
        h=c.get('/biz/help').get_data(as_text=True);self.assertIn('가입하고 바로 쓰기',h)  # 처음 도움말이 들어 있다
        self.assertIn('스마트스토어',c.get('/biz/help?q=스마트스토어').get_data(as_text=True))
        self.assertEqual(c.get('/biz/ops/content').status_code,302)
        o=self.client();self.post(o,'/biz/ops/login',{'password':self.ops_pw})
        r=self.post(o,'/biz/ops/content/new',{'kind':'blog','title':'반품 응대 잘하는 법','summary':'요약','category':'교환·반품 응대','slug':'returns-guide',
            'body':'## 첫째\n- 빨리 답하기\n<script>alert(1)</script>\n[나쁜](javascript:alert(1)) [좋은](https://example.com)','video_url':'https://youtu.be/dQw4w9WgXcQ','seo_title':'반품 응대 가이드'},form_path='/biz/ops/content/new?kind=blog')
        self.assertEqual(r.status_code,302)
        with self.core.conn() as db:p=db.execute("SELECT * FROM posts WHERE slug='returns-guide'").fetchone()
        self.assertEqual(p['published'],0)
        self.assertEqual(c.get('/biz/blog/returns-guide').status_code,404)  # 비공개는 안 보인다
        self.assertNotIn('반품 응대 잘하는 법',c.get('/biz/blog').get_data(as_text=True))
        ep=f'/biz/ops/content/{p["id"]}'
        self.post(o,ep,{'act':'publish'})
        page=c.get('/biz/blog/returns-guide').get_data(as_text=True)
        self.assertIn('<h2 id="첫째">첫째</h2>',page);self.assertIn('&lt;script&gt;',page);self.assertNotIn('<script>alert',page);self.assertNotIn('href="javascript',page)
        self.assertIn('href="https://example.com"',page);self.assertIn('youtube-nocookie.com/embed/dQw4w9WgXcQ',page);self.assertIn('"@type": "Article"',page)
        self.assertIn('<title>반품 응대 가이드',page);self.assertNotIn('noindex',page)
        self.assertIn('반품 응대 잘하는 법',c.get('/biz/blog').get_data(as_text=True))
        sm=c.get('/biz/sitemap.xml').get_data(as_text=True);self.assertIn('/blog/returns-guide</loc><lastmod>',sm);self.assertIn('/help/',sm)
        # 같은 주소는 못 쓴다
        r=self.post(o,'/biz/ops/content/new',{'kind':'blog','title':'다른 글','slug':'returns-guide','body':'x'},form_path='/biz/ops/content/new?kind=blog')
        self.assertEqual(r.status_code,400);self.assertIn('같은 주소',r.get_data(as_text=True))
        # 미리 보기
        self.assertIn('<b>굵게</b>',self.post(o,'/biz/ops/content/preview',{'body':'**굵게**'},form_path='/biz/ops/content/new').get_json()['html'])
        # 고객 사례: 동의 기록 없이는 공개 안 됨
        self.assertIn('지어낸 사례는 올리지 않아요',c.get('/biz/customers').get_data(as_text=True))
        self.post(o,'/biz/ops/content/new',{'kind':'story','title':'A사 이야기','slug':'a-story','body':'본문'},form_path='/biz/ops/content/new?kind=story')
        with self.core.conn() as db:sid=db.execute("SELECT id FROM posts WHERE slug='a-story'").fetchone()[0]
        r=self.post(o,f'/biz/ops/content/{sid}',{'act':'publish'},follow_redirects=True);self.assertIn('공개 동의',r.get_data(as_text=True))
        self.assertEqual(c.get('/biz/customers/a-story').status_code,404)
        self.post(o,f'/biz/ops/content/{sid}',{'title':'A사 이야기','slug':'a-story','body':'본문','story_company':'A사','consent_by':'김대표','consent_on':'2026-10-01','consent':'1'})
        self.post(o,f'/biz/ops/content/{sid}',{'act':'publish'})
        self.assertIn('A사의 공개 동의',c.get('/biz/customers/a-story').get_data(as_text=True))
        # 동의를 빼고 저장하면 다시 비공개
        self.post(o,f'/biz/ops/content/{sid}',{'title':'A사 이야기','slug':'a-story','body':'본문','story_company':'A사','consent_by':'김대표','consent_on':'2026-10-01'})
        self.assertEqual(c.get('/biz/customers/a-story').status_code,404)
        # 지우기
        self.post(o,ep,{'act':'delete','title':'x'})
        self.assertEqual(c.get('/biz/blog/returns-guide').status_code,404)
        # 마케팅 분석: 실제 기록만, 운영 로그인 필요
        v=self.client();v.get('/biz/help?utm_source=naver&utm_medium=cpc&utm_campaign=fall')
        self.assertEqual(v.get('/biz/ops/marketing').status_code,302)
        page=o.get('/biz/ops/marketing?d=7').get_data(as_text=True)
        self.assertIn('fall',page);self.assertIn('naver',page);self.assertIn('/help',page);self.assertIn('IP 주소',page)
        # 검색엔진 소유 확인 코드는 운영 서비스 키에서 읽는다
        with self.core.conn() as db:db.execute("INSERT OR REPLACE INTO settings(key,value,updated) VALUES('NAVER_SITE_VERIFICATION_BIZ','abc123','2026-10-14')")
        self.assertIn('naver-site-verification" content="abc123"',c.get('/biz/login').get_data(as_text=True))

    def test_cs_history_import(self):
        """지난 문의 가져오기: CSV·엑셀, 칸 짐작·고치기, 줄별 오류, 중복, 종료로 저장(알림 없음), 처리 대기 선택, 되돌리기, 권한."""
        import io, zipfile
        b,o,cid=self.signup_and_approve('가져오기상점','imp@example.com')
        csv_text='접수일시,제목,문의내용,답변,상태,판매처,주문번호,고객명,연락처\n'\
            '2026-03-02 10:15,배송 언제 와요,주문한 거 언제 와요?,내일 도착해요,답변완료,스마트스토어,A-1,김고객,010-1234-5678\n'\
            '2026.03.05 오후 3:20,,사이즈 교환 되나요,,미답변,쿠팡,B-2,이고객,\n'\
            '날짜아님,제목,내용,,,,,,\n'\
            '2026-03-07,,,,,,,,\n'\
            '2026-03-02 10:15,배송 언제 와요,주문한 거 언제 와요?,,,,A-1,,\n'
        r=b.post('/biz/import',data={'csrf':self.csrf(b,'/biz/import'),'file':(io.BytesIO(csv_text.encode('cp949')),'old.csv')},content_type='multipart/form-data')
        self.assertEqual(r.status_code,302);mp=r.headers['Location']
        page=b.get(mp).get_data(as_text=True)
        self.assertIn('접수 일시를 읽지 못했어요',page);self.assertIn('문의 내용이 비어 있어요',page);self.assertIn('파일 안에서 겹침',page)
        self.assertIn('2건 옮기기',page)
        sent=[]
        with patch.object(self.core,'send_mail',lambda to,sub,body:sent.append(to)):
            r=self.post(b,mp,{'act':'commit','f_received':'0','f_title':'1','f_body':'2','f_answer':'3','f_status':'4','f_channel':'5','f_order_no':'6','f_name':'7','f_phone':'8','open_pending':'1'})
        self.assertEqual(sent,[])  # 고객에게 아무것도 보내지 않는다
        with self.core.conn() as db:
            rows=db.execute('SELECT * FROM cases WHERE company_id=? AND import_batch>0 ORDER BY created',(cid,)).fetchall()
            self.assertEqual(len(rows),2)
            a,c=rows
            self.assertEqual((a['status'],a['channel'],a['order_no'],a['phone'],a['created'][:16],a['category']),('closed','스마트스토어','A-1','01012345678','2026-03-02 10:15','배송 조회'))
            self.assertEqual((c['status'],c['channel'],c['created'][:16],c['category']),('seen','쿠팡','2026-03-05 15:20','교환'))  # 미답변은 처리 대기로
            self.assertEqual(db.execute("SELECT reply FROM events WHERE case_id=? AND kind='co'",(a['id'],)).fetchone()[0],'내일 도착해요')
            bid=a['import_batch']
        # 같은 파일을 다시 올리면 모두 중복
        r=b.post('/biz/import',data={'csrf':self.csrf(b,'/biz/import'),'file':(io.BytesIO(csv_text.encode('utf-8')),'old.csv')},content_type='multipart/form-data')
        page=b.get(r.headers['Location']).get_data(as_text=True);self.assertIn('이미 있는 문의',page);self.assertIn('0건 옮기기',page)
        self.post(b,r.headers['Location'],{'act':'cancel'})
        # 엑셀(.xlsx)도 읽는다: 날짜가 숫자로 저장된 경우 포함
        x=io.BytesIO()
        with zipfile.ZipFile(x,'w') as z:
            z.writestr('xl/sharedStrings.xml','<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>작성일</t></si><si><t>문의</t></si><si><t>환불해 주세요</t></si></sst>')
            z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row><row r="2"><c r="A2"><v>46100.5</v></c><c r="B2" t="s"><v>2</v></c></row></sheetData></worksheet>')
        r=b.post('/biz/import',data={'csrf':self.csrf(b,'/biz/import'),'file':(io.BytesIO(x.getvalue()),'old.xlsx')},content_type='multipart/form-data')
        page=b.get(r.headers['Location']).get_data(as_text=True);self.assertIn('1건 옮기기',page);self.assertIn('2026-03-19 12:00',page)
        self.post(b,r.headers['Location'],{'act':'commit','f_received':'0','f_body':'1'})
        with self.core.conn() as db:self.assertEqual(db.execute("SELECT status FROM cases WHERE company_id=? AND body='환불해 주세요'",(cid,)).fetchone()[0],'closed')
        # 다른 회사는 남의 묶음을 되돌릴 수 없다
        b2,_,_=self.signup_and_approve('남의상점','other-imp@example.com')
        self.assertEqual(b2.post(f'/biz/import/undo/{bid}',data={'csrf':self.csrf(b2,'/biz/import')}).status_code,404)
        # 되돌리기
        self.assertIn('되돌리기',b.get('/biz/import').get_data(as_text=True))
        b.post(f'/biz/import/undo/{bid}',data={'csrf':self.csrf(b,'/biz/import')})
        with self.core.conn() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cases WHERE import_batch=?',(bid,)).fetchone()[0],0)
            self.assertEqual(db.execute("SELECT status FROM import_batches WHERE id=?",(bid,)).fetchone()[0],'undone')
        # 잘못된 파일
        r=b.post('/biz/import',data={'csrf':self.csrf(b,'/biz/import'),'file':(io.BytesIO(b'x'),'a.pdf')},content_type='multipart/form-data',follow_redirects=True)
        self.assertIn('CSV 또는 엑셀',r.get_data(as_text=True))

    def test_referral_partner_security(self):
        """추천 링크(가입 연결·통계, 보상 없음), 파트너 신청→승인→로그인→고객사 숫자만, 직원 초대, 회사가 직접 파트너 연결, 보안 안내."""
        a,o,aid=self.signup_and_approve('추천하는상점','referrer@example.com')
        page=a.get('/biz/settings').get_data(as_text=True);self.assertIn('추천 링크',page);self.assertIn('추천 보상은 아직 없어요',page)
        code=re.search(r'/r/([a-z0-9]+)',page).group(1)
        v=self.client();r=v.get('/biz/r/'+code);self.assertEqual(r.status_code,302);self.assertIn('/signup',r.headers['Location'])
        self.assertEqual(self.client().get('/biz/r/nosuchcode').status_code,302)
        self.post(v,'/biz/signup',{'name':'추천받은상점','biz_no':self.bizno(),'owner_name':'대표','phone':'010-1111-2222','contact':'1588-0000','login_id':'referred@example.com','password':'longpassword1','terms':'1'})
        with self.core.conn() as db:
            self.assertEqual(db.execute("SELECT referred_by FROM companies WHERE login_id='referred@example.com'").fetchone()[0],aid)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ref_clicks WHERE code=?',(code,)).fetchone()[0],1)
        page=a.get('/biz/settings').get_data(as_text=True);self.assertRegex(page,r'<span>가입</span><b>1</b>')
        # 파트너 신청
        p=self.client()
        r=self.post(p,'/biz/partners',{'name':'대행사','kind':'없는종류','contact':'김대행','email':'agency@example.com','privacy':'1'});self.assertEqual(r.status_code,400)
        sent=[]
        with patch.object(self.core,'send_mail',lambda to,sub,body:sent.append((to,body))),patch.dict(os.environ,{'OPS_EMAIL':'ops@example.com'}):
            r=self.post(p,'/biz/partners',{'name':'대행사','kind':'쇼핑몰 운영 대행사','contact':'김대행','email':'agency@example.com','privacy':'1'})
        self.assertIn('신청을 받았어요',r.get_data(as_text=True));self.assertEqual(sorted(x[0] for x in sent),['agency@example.com','ops@example.com'])
        with self.core.conn() as db:pid=db.execute("SELECT id FROM partners WHERE email='agency@example.com'").fetchone()[0]
        self.assertEqual(p.get(f'/biz/ops/partner/{pid}').status_code,302)  # 운영 로그인 필요
        sent=[]
        with patch.object(self.core,'send_mail',lambda to,sub,body:sent.append((to,body))):
            self.post(o,f'/biz/ops/partner/{pid}',{'act':'approve'})
        tok=re.search(r'/partner/join/(\S+)',sent[0][1]).group(1)
        with self.core.conn() as db:pc=db.execute('SELECT code FROM partners WHERE id=?',(pid,)).fetchone()[0]
        pp=self.client()
        self.assertEqual(pp.get('/biz/partner').status_code,302)
        r=self.post(pp,f'/biz/partner/join/{tok}',{'password':'partnerpass1'});self.assertEqual(r.status_code,302)
        self.assertEqual(self.client().get(f'/biz/partner/join/{tok}').status_code,400)  # 한 번 쓰면 끝
        # 파트너 링크로 가입한 회사 + 이미 가입한 회사가 직접 연결
        w=self.client();w.get('/biz/r/'+pc)
        self.post(w,'/biz/signup',{'name':'파트너고객','biz_no':self.bizno(),'owner_name':'대표','phone':'010-1111-2222','contact':'1588-0000','login_id':'pclient@example.com','password':'longpassword1','terms':'1'})
        self.post(a,'/biz/settings/partner',{'act':'link','code':pc},form_path='/biz/settings')
        with self.core.conn() as db:
            self.assertEqual(db.execute("SELECT partner_id FROM companies WHERE login_id='pclient@example.com'").fetchone()[0],pid)
            self.assertEqual(db.execute('SELECT partner_id FROM companies WHERE id=?',(aid,)).fetchone()[0],pid)
        self.file_case(self.client(),'추천하는상점','배송 조회',company_id=str(aid),title='고객비밀제목')
        page=pp.get('/biz/partner').get_data(as_text=True)
        self.assertIn('파트너고객',page);self.assertIn('추천하는상점',page);self.assertNotIn('고객비밀제목',page);self.assertNotIn('추천받은상점',page)
        # 파트너 직원 초대·내보내기
        self.post(pp,'/biz/partner',{'act':'invite','name':'이직원','email':'pstaff@example.com'})
        with self.core.conn() as db:sid=db.execute("SELECT id FROM partner_users WHERE email='pstaff@example.com'").fetchone()[0]
        self.post(pp,'/biz/partner',{'act':'remove','id':str(sid)})
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT status FROM partner_users WHERE id=?',(sid,)).fetchone()[0],'removed')
        # 회사가 연결을 끊으면 파트너 화면에서 사라진다
        self.post(a,'/biz/settings/partner',{'act':'unlink'},form_path='/biz/settings')
        self.assertNotIn('추천하는상점',pp.get('/biz/partner').get_data(as_text=True))
        # 중지하면 파트너 로그인이 막힌다
        self.post(o,f'/biz/ops/partner/{pid}',{'act':'suspend'})
        self.assertEqual(pp.get('/biz/partner').status_code,302)
        r=self.post(self.client(),'/biz/partner/login',{'email':'agency@example.com','password':'partnerpass1'});self.assertIn('맞지 않아요',r.get_data(as_text=True))
        # 보안 안내: HTTPS가 꺼진 서버에서는 HTTPS를 내세우지 않는다
        sec=self.client().get('/biz/security').get_data(as_text=True)
        self.assertIn('아직 갖추지 못한 것',sec);self.assertNotIn('접속 암호화',sec);self.assertNotIn('noindex',sec)
        with patch.dict(os.environ,{'HTTPS_ONLY':'1'}):self.assertIn('접속 암호화',self.client().get('/biz/security').get_data(as_text=True))

    def test_cafe24_oauth(self):
        """카페24: 키 없으면 연동 대기, 있으면 동의 화면으로 → 돌아오면 토큰 암호화 저장 → 만료 전 갱신 → 갱신 실패면 다시 연결 → 끊기."""
        import urllib.parse
        shops=sys.modules['shops'];c24=sys.modules['cafe24']
        b,o,cid=self.signup_and_approve('카페24상점','c24@example.com')
        self.assertIn('연동 대기',b.get('/biz/connect/cafe24').get_data(as_text=True))
        self.assertIn('연동 대기',b.get('/biz/connect').get_data(as_text=True))
        r=self.post(b,'/biz/connect/cafe24',{'act':'connect','mall_id':'myshop'},follow_redirects=True);self.assertIn('앱 등록을 마치면',r.get_data(as_text=True))
        calls=[]
        def fake(method,url,headers=None,body=None):
            calls.append((method,url,dict(urllib.parse.parse_qsl(body.decode())) if body else None))
            if url.endswith('/oauth/token'):
                self.assertTrue(headers['Authorization'].startswith('Basic '))
                f=dict(urllib.parse.parse_qsl(body.decode()))
                if f['grant_type']=='authorization_code':return 200,{'access_token':'A1','refresh_token':'R1','expires_at':'2099-01-01T00:00:00.000','refresh_token_expires_at':'2099-01-14T00:00:00.000','scopes':['mall.read_order','mall.read_store']}
                if f['refresh_token']=='R1':return 200,{'access_token':'A2','refresh_token':'R2','expires_at':'2099-01-01T02:00:00.000','refresh_token_expires_at':'2099-01-15T00:00:00.000'}
                return 400,{'error':'invalid_grant'}
            if '/admin/orders' in url:
                self.assertTrue(headers['Authorization'].startswith('Bearer A'))
                return 200,{'orders':[{'order_id':'20261014-0000011','order_date':'2026-10-14T10:00:00+09:00','billing_name':'김카페','actual_payment_amount':'25000.00',
                    'items':[{'product_name':'머그컵','quantity':1,'order_status':'N40','shipping_company_name':'CJ대한통운','tracking_no':'123412341234'}],'receivers':[{'name':'김카페','cellphone':'010-5555-6666','address1':'서울'}]}]}
            if '/admin/store' in url:return 200,{'store':{'shop_name':'내 카페24몰'}}
            return 404,{}
        with patch.dict(os.environ,{'CAFE24_CLIENT_ID':'cid','CAFE24_CLIENT_SECRET':'csec'}),patch.object(shops,'http',fake):
            r=self.post(b,'/biz/connect/cafe24',{'act':'connect','mall_id':'bad id!'},follow_redirects=True);self.assertIn('아이디를 확인',r.get_data(as_text=True))
            r=self.post(b,'/biz/connect/cafe24',{'act':'connect','mall_id':'myshop'})
            loc=r.headers['Location'];self.assertTrue(loc.startswith('https://myshop.cafe24api.com/api/v2/oauth/authorize?'))
            q=dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query));self.assertEqual((q['client_id'],q['response_type']),('cid','code'));self.assertIn('mall.read_order',q['scope'])
            # 다른 사람의 state는 안 받는다
            r=b.get('/biz/connect/cafe24/callback?code=x&state=forged',follow_redirects=True);self.assertIn('만료됐거나',r.get_data(as_text=True))
            # 카페24가 돌려준 오류 이유를 그대로 보여 줌 (동의 취소와 설정 문제를 구분)
            r=self.post(b,'/biz/connect/cafe24',{'act':'connect','mall_id':'myshop'});q=dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.headers['Location']).query))
            r=b.get('/biz/connect/cafe24/callback?error=invalid_scope&error_description=scope+not+allowed&state='+urllib.parse.quote(q['state']),follow_redirects=True)
            self.assertIn('invalid_scope: scope not allowed',r.get_data(as_text=True))
            r=self.post(b,'/biz/connect/cafe24',{'act':'connect','mall_id':'myshop'});q=dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.headers['Location']).query))
            r=b.get('/biz/connect/cafe24/callback?error=access_denied&state='+urllib.parse.quote(q['state']),follow_redirects=True)
            self.assertIn('권한 동의를 취소',r.get_data(as_text=True))
            r=self.post(b,'/biz/connect/cafe24',{'act':'connect','mall_id':'myshop'});q=dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.headers['Location']).query))
            r=b.get('/biz/connect/cafe24/callback?code=CODE1&state='+urllib.parse.quote(q['state']),follow_redirects=True)
            self.assertIn('카페24(myshop)에 연결했어요',r.get_data(as_text=True))
            self.assertEqual(calls[0][2]['code'],'CODE1')
            with self.core.conn() as db:
                lk=c24.link(db,cid);self.assertNotIn('"A1"',lk['creds']);self.assertEqual(shops.unseal(lk['creds'])['refresh_token'],'R1')
                self.assertEqual(db.execute("SELECT channel,status,invoice FROM orders WHERE company_id=? AND order_no='20261014-0000011'",(cid,)).fetchone()[:],('자사몰','delivered','123412341234'))
                # 만료가 가까우면 갱신하고 갱신 토큰도 바뀐다
                db.execute("UPDATE cafe24_links SET expires='2000-01-01 00:00:00' WHERE company_id=?",(cid,))
                self.assertEqual(c24.access_token(db,cid)[1],'A2');self.assertEqual(shops.unseal(c24.link(db,cid)['creds'])['refresh_token'],'R2')
                db.execute("UPDATE cafe24_links SET expires='2000-01-01 00:00:00' WHERE company_id=?",(cid,))
            mails=[]
            with patch.object(self.core,'send_mail',lambda to,sub,body:mails.append(sub)):
                r=self.post(b,'/biz/connect/cafe24',{'act':'sync'},follow_redirects=True);self.assertIn('만료됐어요',r.get_data(as_text=True))
                self.post(b,'/biz/connect/cafe24',{'act':'sync'})
            self.assertEqual(mails,['[소보루 CS] 카페24 연결을 확인해 주세요'])  # 처음 끊겼을 때 한 번만
            with self.core.conn() as db:self.assertEqual(c24.link(db,cid)['status'],'reconnect')
            self.assertIn('다시 연결 필요',b.get('/biz/connect/cafe24').get_data(as_text=True))
            self.post(b,'/biz/connect/cafe24',{'act':'delete'})
            with self.core.conn() as db:self.assertIsNone(c24.link(db,cid))

    def test_cafe24_boards_and_claims(self):
        """카페24: 문의 게시판 글 -> 요청 (공지·답글 제외, 한 번만) -> 답변을 답글로 올림. 취소(발송 전)·반품 접수(발송 후)는 사장님이 누를 때 한 번만."""
        shops=sys.modules['shops'];c24=sys.modules['cafe24']
        b,o,cid=self.signup_and_approve('카페24문의상점','c24b@example.com')
        sent=[];state={'N':'N10'};extra=[];comments=[]
        orders=[{'order_id':'20261015-0000001','order_date':'2026-10-15T10:00:00+09:00','billing_name':'홍길동','actual_payment_amount':'1000.00',
                 'items':[{'product_name':'시험상품','quantity':1,'order_status':'N10'}],'receivers':[{'name':'홍길동','cellphone':'010-1234-5678','address1':'서울'}]},
                {'order_id':'20261015-0000002','order_date':'2026-10-15T11:00:00+09:00','billing_name':'홍길동','actual_payment_amount':'1000.00',
                 'items':[{'product_name':'시험상품','quantity':1,'order_status':'N30','shipping_company_name':'CJ대한통운','tracking_no':'111122223333'}],'receivers':[{'name':'홍길동','cellphone':'010-1234-5678'}]}]
        def fake(method,url,headers=None,body=None):
            path=url.split('/api/v2')[1].split('?')[0]
            if method=='POST':sent.append((path,json.loads(body)))
            if path=='/admin/orders':return 200,{'orders':orders}
            if path=='/admin/boards':return 200,{'boards':[{'board_no':1,'board_name':'공지사항'},{'board_no':6,'board_name':'상품 Q&A'},{'board_no':9,'board_name':'1:1 맞춤상담'}]}
            if path=='/admin/boards/6/articles' and method=='GET':return 200,{'articles':[
                {'article_no':10,'parent_article_no':10,'reply_depth':1,'title':'배송 문의','content':'<p>언제 와요?<br>급해요</p>','writer':'홍길동','secret':'T','order_id':'20261015-0000002','created_date':'2026-10-15T12:00:00+09:00','deleted':'F','notice':'F'},
                {'article_no':11,'parent_article_no':10,'reply_depth':2,'title':'RE: 배송 문의','content':'답글','writer':'상점','notice':'F'},
                {'article_no':12,'parent_article_no':12,'title':'공지','content':'공지','notice':'T'}]+extra}
            if path=='/admin/boards/6/articles/10/comments':return 200,{'comments':comments}
            if path=='/admin/boards/9/articles':return 200,{'articles':[]}
            if path=='/admin/boards/6/articles':return 201,{'articles':[{'article_no':13}]}
            if path.startswith('/admin/orders/20261015-0000001') and method=='GET':return 200,{'order':{'items':[{'order_item_code':'A-1','quantity':1,'order_status':state['N']}]}}
            if path.startswith('/admin/orders/20261015-0000002') and method=='GET':return 200,{'order':{'items':[{'order_item_code':'B-1','quantity':1,'order_status':'N30'}]}}
            if path.endswith('/cancellation'):return 201,{'cancellation':[{'claim_code':'C1'}]}
            if path=='/admin/return':return 201,{'returns':[{'claim_code':'R1'}]}
            return 404,{}
        with patch.dict(os.environ,{'CAFE24_CLIENT_ID':'cid','CAFE24_CLIENT_SECRET':'csec'}),patch.object(shops,'http',fake):
            with self.core.conn() as db:c24.store(db,cid,'myshop',{'access_token':'A1','refresh_token':'R1','expires_at':'2099-01-01T00:00:00'})
            r=self.post(b,'/biz/connect/cafe24',{'act':'sync'},follow_redirects=True).get_data(as_text=True)
            self.assertIn('주문 2건, 새 문의 1건',r);self.assertIn('상품 Q&amp;A',r);self.assertIn('1:1 맞춤상담',r);self.assertNotIn('>공지사항<',r)
            self.post(b,'/biz/connect/cafe24',{'act':'sync'})  # 같은 글은 한 번만
            with self.core.conn() as db:
                rows=db.execute("SELECT * FROM cases WHERE company_id=? AND channel='카페24'",(cid,)).fetchall()
                self.assertEqual(len(rows),1);self.assertEqual((rows[0]['title'],rows[0]['body'],rows[0]['order_no']),('배송 문의','언제 와요?\n급해요','20261015-0000002'))
                self.assertEqual(db.execute("SELECT src FROM orders WHERE company_id=? AND order_no='20261015-0000001'",(cid,)).fetchone()[0],'cafe24')
            case_id=rows[0]['id']
            self.assertIn('누르면 카페24에 바로 올라가요',b.get(f'/biz/case/{case_id}').get_data(as_text=True))
            r=self.post(b,f'/biz/case/{case_id}',{'act':'reply','msg':'오늘 출발해요\n<내일 도착>'},follow_redirects=True)  # '답변하기' 한 번으로 올라간다
            self.assertIn('카페24에 답변을 올렸어요',r.get_data(as_text=True));self.assertEqual(len(sent),1)
            path,payload=sent[-1];rq=payload['requests'][0]
            self.assertEqual(path,'/admin/boards/6/articles');self.assertEqual((rq['reply_article_no'],rq['secret'],rq['title']),(10,'T','RE: 배송 문의'))
            self.assertEqual(rq['content'],'오늘 출발해요<br>&lt;내일 도착&gt;');self.assertTrue(rq['password'])
            # 고객이 같은 글에 단 답글·댓글은 그 요청에 이어 붙고 (가게 댓글은 빼고), 끝난 요청에 다시 쓰면 새 요청
            extra.append({'article_no':14,'parent_article_no':10,'reply_depth':2,'title':'RE: RE: 배송 문의','content':'아직 안 왔어요','writer':'홍길동','secret':'T','deleted':'F','notice':'F','created_date':'2026-10-16T09:00:00+09:00'})
            comments[:]=[{'comment_no':5,'writer':'홍길동','content':'송장번호는요?','created_date':'2026-10-16T10:00:00+09:00'},{'comment_no':6,'writer':'상점','content':'확인할게요'}]
            pushed=[];old_push=self.core.expo_push;self.core.expo_push=lambda *a:pushed.append(a)
            try:
                self.post(b,'/biz/connect/cafe24',{'act':'sync'});self.post(b,'/biz/connect/cafe24',{'act':'sync'})
                with self.core.conn() as db:
                    me=[e['text'] for e in self.core.events(db,case_id) if e['kind']=='me']
                    self.assertEqual(sorted(me),sorted(['아직 안 왔어요','송장번호는요?']));self.assertEqual(db.execute('SELECT status FROM cases WHERE id=?',(case_id,)).fetchone()[0],'seen')
                    db.execute("UPDATE cases SET status='resolved' WHERE id=?",(case_id,))
                comments.append({'comment_no':7,'writer':'홍길동','content':'또 안 와요','created_date':'2026-10-17T10:00:00+09:00'})
                self.post(b,'/biz/connect/cafe24',{'act':'sync'})  # 끝난 요청이라 댓글은 안 본다 (진행 중인 요청만)
                extra.append({'article_no':15,'parent_article_no':10,'reply_depth':2,'title':'RE: 또','content':'다시 문의해요','writer':'홍길동','secret':'T','deleted':'F','notice':'F'})
                self.post(b,'/biz/connect/cafe24',{'act':'sync'})
            finally:self.core.expo_push=old_push
            with self.core.conn() as db:
                again=db.execute("SELECT * FROM cases WHERE company_id=? AND channel='카페24' AND id!=?",(cid,case_id)).fetchall()
                self.assertEqual(len(again),1);self.assertEqual((again[0]['title'],again[0]['body']),('다시 문의: 배송 문의','다시 문의해요'))
            # 승인해도 카페24에 바로 올라간다 (처음 글에 답글로)
            n=len(sent);self.post(b,f'/biz/case/{again[0]["id"]}',{'act':'approve'})
            self.assertEqual(len(sent),n+1);self.assertEqual(sent[-1][1]['requests'][0]['reply_article_no'],10)
            with self.core.conn() as db:self.assertTrue(any(e['text']=='카페24에 답변을 올렸어요' for e in self.core.events(db,again[0]['id'])))
            # 게시판 바꾸기: 1:1만 남기면 Q&A는 더 안 본다
            self.assertIn('공지사항',self.post(b,'/biz/connect/cafe24',{'act':'boards'}).get_data(as_text=True))
            self.post(b,'/biz/connect/cafe24',{'act':'boards_save','board':'9'})
            with self.core.conn() as db:self.assertEqual(c24.boards_of(c24.link(db,cid)),[(9,'1:1 맞춤상담')])
            # 취소: 발송 전 주문
            with self.core.conn() as db:
                oa=db.execute("SELECT id FROM orders WHERE company_id=? AND order_no='20261015-0000001'",(cid,)).fetchone()[0]
                ob=db.execute("SELECT id FROM orders WHERE company_id=? AND order_no='20261015-0000002'",(cid,)).fetchone()[0]
            page=b.get(f'/biz/order/{oa}').get_data(as_text=True);self.assertIn('카페24에서 주문 취소',page);self.assertNotIn('카페24에 반품 접수',page)
            r=self.post(b,f'/biz/order/{oa}',{'act':'c24_cancel','reason_type':''},follow_redirects=True);self.assertIn('사유를 골라',r.get_data(as_text=True))
            r=self.post(b,f'/biz/order/{oa}',{'act':'c24_cancel','reason_type':'A','reason':'단순 변심'},follow_redirects=True).get_data(as_text=True)
            self.assertIn('카페24에서 주문을 취소했어요',r);self.assertIn('카페24에 취소를 보냈어요',r)
            path,payload=sent[-1];self.assertEqual(path,'/admin/orders/20261015-0000001/cancellation')
            self.assertEqual((payload['request']['status'],payload['request']['payment_gateway_cancel'],payload['request']['items']),('canceled','T',[{'order_item_code':'A-1','quantity':1}]))
            n=len(sent);r=self.post(b,f'/biz/order/{oa}',{'act':'c24_cancel','reason_type':'A'},follow_redirects=True)
            self.assertEqual(len(sent),n)  # 두 번 보내지 않는다
            with self.core.conn() as db:self.assertEqual(db.execute('SELECT status FROM orders WHERE id=?',(oa,)).fetchone()[0],'canceled')
            # 반품 접수: 발송된 주문. 발송된 걸 취소하려 하면 막는다
            self.assertIn('카페24에 반품 접수',b.get(f'/biz/order/{ob}').get_data(as_text=True))
            r=self.post(b,f'/biz/order/{ob}',{'act':'c24_cancel','reason_type':'A'},follow_redirects=True);self.assertIn('반품 접수로 처리',r.get_data(as_text=True))
            r=self.post(b,f'/biz/order/{ob}',{'act':'c24_return','reason_type':'E'},follow_redirects=True).get_data(as_text=True)
            self.assertIn('카페24에 반품을 접수했어요',r)
            path,payload=sent[-1];self.assertEqual(path,'/admin/return');self.assertEqual(payload['requests'][0]['status'],'accepted')
            with self.core.conn() as db:
                self.assertIn('카페24 반품 접수',db.execute('SELECT memo FROM orders WHERE id=?',(ob,)).fetchone()[0])
                self.assertTrue(any('반품 접수를 보냈어요' in e['text'] for e in self.core.events(db,case_id)))

    def test_biz_alerts(self):
        """알림: 모두 목록에 남고, 앱 알림·이메일은 종류별 설정대로. 목록을 열면 읽음. 웹·앱에서 설정을 바꾼다."""
        core=self.core
        b,o,cid=self.signup_and_approve('알림상점','alerts@example.com')
        pushed=[];mails=[];old_push,old_mail=core.expo_push,core.send_mail
        core.expo_push=lambda toks,title,body,data,table:pushed.append(title);core.send_mail=lambda to,subj,body,*a,**k:mails.append(subj)
        try:
            with core.conn() as db:
                co=core.company(db,cid)
                core.alert(co,'ai','AI가 답했어요: 배송','언제 와요?',mail=('ai-mail','x'),db=db)  # 기본: 목록에만
                core.alert(co,'new','승인할 문의: 반품·환불','토너 반품',mail=('new-mail','x'),db=db)  # 기본: 앱 알림 + 이메일
            self.assertEqual(pushed,['승인할 문의: 반품·환불']);self.assertEqual(mails,['new-mail'])
            self.assertIn('알림 2건 안 읽음',b.get('/biz/').get_data(as_text=True))
            page=b.get('/biz/alerts').get_data(as_text=True);self.assertIn('AI가 답했어요: 배송',page);self.assertIn('토너 반품',page)
            self.assertIn('알림 0건 안 읽음',b.get('/biz/alerts').get_data(as_text=True))
            self.post(b,'/biz/alerts',{'ai.push':'1'})
            with core.conn() as db:p=core.alert_prefs(core.company(db,cid))
            self.assertEqual(p['ai'],{'push':1,'email':0});self.assertEqual(p['new'],{'push':0,'email':0})
            pushed.clear()
            with core.conn() as db:core.alert(core.company(db,cid),'ai','AI가 답했어요: 사용법','',db=db);core.alert(core.company(db,cid),'new','승인할 문의: 교환','',db=db)
            self.assertEqual(pushed,['AI가 답했어요: 사용법'])
            tok=b.post('/biz/api/v1/login',json={'login_id':'alerts@example.com','password':'longpassword1'}).get_json()['token'];auth={'Authorization':'Bearer '+tok}
            self.assertEqual(b.get('/biz/api/v1/home',headers=auth).get_json()['counts']['alerts'],2)
            j=b.get('/biz/api/v1/alerts',headers=auth).get_json()
            self.assertEqual(len(j['items']),4);self.assertTrue(j['items'][0]['new']);self.assertEqual([k['key'] for k in j['kinds']][:3],['new','msg','ai'])
            self.assertEqual(b.get('/biz/api/v1/home',headers=auth).get_json()['counts']['alerts'],0)
            j=b.post('/biz/api/v1/alerts',headers=auth,json={'act':'prefs','new.push':True,'new.email':True}).get_json()
            self.assertEqual(j['prefs']['new'],{'push':1,'email':1});self.assertEqual(j['prefs']['ai'],{'push':0,'email':0})
        finally:core.expo_push,core.send_mail=old_push,old_mail

    def test_cafe24_product_details(self):
        """카페24 상품 안내: 요약·정가·옵션·모델명·검색어·상세 설명 글자를 담고, 사진·쇼핑몰 주소를 붙이고, 고친 안내는 되돌릴 수 있다."""
        c24=sys.modules['cafe24']
        p={'product_no':5,'price':'15000.00','retail_price':'20000.00','summary_description':'순한 클렌저','model_name':'CL-01','product_tag':['세안','클렌징'],
           'description':'<p>약산성 포뮬러로 매일 쓰기 좋아요.</p><img src="x.jpg">','list_image':'//img.cafe24.com/a.jpg',
           'options':{'has_option':'T','options':[{'option_name':'용량','option_value':[{'value_name':'150ml'},{'value_name':'300ml'}]}]}}
        info=c24.product_info(p)
        for want in ('순한 클렌저','정가 20,000원 (지금 15,000원)','옵션 용량: 150ml, 300ml','모델명 CL-01','검색어 세안, 클렌징','상세 설명: 약산성 포뮬러'):self.assertIn(want,info)
        self.assertEqual(c24.product_image(p),'https://img.cafe24.com/a.jpg');self.assertEqual(c24.product_url('myshop',5),'https://myshop.cafe24.com/product/detail.html?product_no=5')
        b,o,cid=self.signup_and_approve('상품되돌림상점','revert@example.com')
        with self.core.conn() as db:pid=db.execute("INSERT INTO products(company_id,name,price,stock,info,updated,src,ext_id,src_info) VALUES(?,?,?,?,?,?,'cafe24','5','카페24 안내')",(cid,'클렌저','','있음','고친 안내',self.core.iso())).lastrowid
        with self.core.conn() as db:db.execute("INSERT INTO products(company_id,name,price,stock,info,updated) VALUES(?,?,?,?,?,?)",(cid,'직접 넣은 수건','5,000원','품절','면 100%',self.core.iso()))
        self.assertIn('상품 2개 보기',b.get('/biz/rules').get_data(as_text=True))  # 자동 처리에는 상품 페이지로 가는 길만
        page=b.get('/biz/products').get_data(as_text=True);self.assertIn('카페24 내용으로 되돌리기',page);self.assertIn('클렌저',page);self.assertIn('직접 넣은 수건',page)
        page=b.get('/biz/products?g=cafe24').get_data(as_text=True);self.assertIn('클렌저',page);self.assertNotIn('직접 넣은 수건',page)
        page=b.get('/biz/products?g=soldout').get_data(as_text=True);self.assertNotIn('클렌저',page);self.assertIn('직접 넣은 수건',page)
        page=b.get('/biz/products?q=%EB%A9%B4').get_data(as_text=True);self.assertNotIn('>클렌저',page);self.assertIn('직접 넣은 수건',page)  # 안내 글로도 찾는다
        r=self.post(b,'/biz/products',{'id':str(pid),'act':'revert','back':'g=cafe24'},form_path='/biz/products')
        self.assertTrue(r.headers['Location'].endswith('/biz/products?g=cafe24'))
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT info FROM products WHERE id=?',(pid,)).fetchone()[0],'카페24 안내')

    def test_cafe24_app_deleted_hook(self):
        """카페24 앱 삭제 웹훅: 인증정보가 맞으면 바로, 없으면 카페24에 물어 토큰이 막혔을 때만 연결을 거둔다. 가짜 이벤트로는 살아 있는 연결이 안 끊긴다."""
        shops=sys.modules['shops'];c24=sys.modules['cafe24']
        b,o,cid=self.signup_and_approve('카페24삭제상점','c24del@example.com')
        alive=[True]
        def fake(method,url,headers=None,body=None):
            if '/oauth/token' in url:return 400,{'error':'invalid_grant'}
            return (200,{'store':{}}) if alive[0] else (401,{})
        ev={'event_no':90077,'resource':{'mall_id':'delshop','client_id':'cid','app_name':'소보루 CS'}}
        with patch.dict(os.environ,{'CAFE24_CLIENT_ID':'cid','CAFE24_CLIENT_SECRET':'csec','CAFE24_WEBHOOK_KEY':'hookkey'}),patch.object(shops,'http',fake):
            with self.core.conn() as db:c24.store(db,cid,'delshop',{'access_token':'A1','refresh_token':'R1','expires_at':'2099-01-01T00:00:00','scopes':['mall.read_order']})
            def st():
                with self.core.conn() as db:return db.execute('SELECT status FROM cafe24_links WHERE company_id=?',(cid,)).fetchone()[0]
            self.assertEqual(b.post('/biz/hook/cafe24',json=ev).status_code,200);self.assertEqual(st(),'ok')  # 인증정보 없고 토큰이 살아 있음: 그대로
            self.assertEqual(b.post('/biz/hook/cafe24',json=dict(ev,resource=dict(ev['resource'],client_id='other')),headers={'X-Api-Key':'hookkey'}).status_code,200);self.assertEqual(st(),'ok')  # 다른 앱
            alive[0]=False;b.post('/biz/hook/cafe24',json=ev);self.assertEqual(st(),'removed')  # 토큰이 막힘: 거둔다
            with self.core.conn() as db:
                self.assertEqual(db.execute('SELECT creds FROM cafe24_links WHERE company_id=?',(cid,)).fetchone()[0],'')
                self.assertTrue(db.execute("SELECT 1 FROM biz_alerts WHERE company_id=? AND kind='link'",(cid,)).fetchone())
                c24.store(db,cid,'delshop',{'access_token':'A2','refresh_token':'R2','expires_at':'2099-01-01T00:00:00','scopes':['mall.read_order']})
            alive[0]=True;b.post('/biz/hook/cafe24',json=ev,headers={'X-Api-Key':'hookkey'});self.assertEqual(st(),'removed')  # 인증정보가 맞으면 묻지 않고 거둔다

    def test_cafe24_urgent_and_deleted(self):
        """카페24 긴급문의: 답하지 않은 것만 요청이 되고, 답변은 긴급문의 답변으로 올라간다.
        고객이 글을 지웠다는 웹훅은 카페24 게시판에서 정말 없어졌을 때만 그 요청을 닫는다."""
        shops=sys.modules['shops'];c24=sys.modules['cafe24']
        b,o,cid=self.signup_and_approve('긴급문의상점','c24u@example.com')
        sent=[]
        arts=[{'article_no':30,'parent_article_no':30,'title':'배송 문의','content':'언제 와요','writer':'박손님','deleted':'F','notice':'F','created_date':'2026-10-18T10:00:00+09:00'}]
        urg=[{'article_no':5,'title':'급해요','content':'<p>주소를 바꿔 주세요</p>','writer':'최손님','member_id':'','start_date':'2026-10-18T10:00:00+09:00','reply_status':'F'},
             {'article_no':6,'title':'이미 답함','content':'고마워요','writer':'정손님','member_id':'','start_date':'2026-10-18T10:01:00+09:00','reply_status':'T'}]
        def fake(method,url,headers=None,body=None):
            path=url.split('/api/v2')[1].split('?')[0]
            if method=='POST':sent.append((path,json.loads(body)));return 201,{}
            if path=='/admin/boards':return 200,{'boards':[{'board_no':6,'board_name':'상품 Q&A'}]}
            if path=='/admin/boards/6/articles':return 200,{'articles':arts}
            if path=='/admin/urgentinquiry':return 200,{'urgentinquiry':urg}
            if '/comments' in path:return 200,{'comments':[]}
            return 404,{}
        c24.BACKGROUND=False
        try:
            with patch.dict(os.environ,{'CAFE24_CLIENT_ID':'cid','CAFE24_CLIENT_SECRET':'csec'}),patch.object(shops,'http',fake):
                with self.core.conn() as db:
                    c24.store(db,cid,'ushop',{'access_token':'A1','refresh_token':'R1','expires_at':'2099-01-01T00:00:00','scopes':['mall.read_order','mall.read_community','mall.write_community']})
                    new=c24.sync_boards(db,self.core.company(db,cid))
                titles={c['title'] for c in new}
                self.assertIn('[긴급문의] 급해요',titles);self.assertIn('배송 문의',titles);self.assertNotIn('[긴급문의] 이미 답함',titles)
                with self.core.conn() as db:
                    u=[c for c in new if c['title'].startswith('[긴급문의]')][0];self.assertEqual((u['channel'],u['body']),('카페24','주소를 바꿔 주세요'))
                    self.assertEqual(shops.post_reply(db,self.core.company(db,cid),u,'바꿔 드렸어요'),'')
                self.assertEqual(sent[-1][0],'/admin/urgentinquiry/5/reply');self.assertEqual(sent[-1][1]['request'],{'content':'바꿔 드렸어요','status':'T','user_id':'ushop'})
                q=[c for c in new if c['title']=='배송 문의'][0]
                def st():
                    with self.core.conn() as db:return db.execute('SELECT status FROM cases WHERE id=?',(q['id'],)).fetchone()[0]
                ev={'event_no':90036,'resource':{'mall_id':'ushop','board_no':6,'no':30}}
                self.assertEqual(b.post('/biz/hook/cafe24',json=ev).status_code,200);self.assertNotEqual(st(),'closed')  # 카페24엔 아직 있음: 가짜 이벤트로는 안 닫힌다
                arts[0]['deleted']='T';b.post('/biz/hook/cafe24',json=ev);self.assertEqual(st(),'closed')
                with self.core.conn() as db:self.assertTrue(any('지워서' in e['text'] for e in self.core.events(db,q['id'])))
        finally:c24.BACKGROUND=True

    def test_cafe24_ai_followup_and_handoff(self):
        """AI 자동 답변 검수 고침: 댓글로 이어 물으면 앞 대화를 보고 마지막 말에 답한다. '사이즈' 같은 낱말만으로 승인 목록에 넘기지 않는다.
        남의 주문번호면 주문 내용을 AI에 주지 않고 넘긴다. 승인하면 AI 초안을 보낸다. 카페24 관리자에서 단 답글은 '답함'으로."""
        shops=sys.modules['shops'];c24=sys.modules['cafe24'];bot=sys.modules['chatbot']
        b,o,cid=self.signup_and_approve('AI검수상점','c24fix@example.com')
        soon=lambda m:(self.core.now()+__import__('datetime').timedelta(minutes=m)).strftime('%Y-%m-%dT%H:%M:%S+09:00')
        sent=[];comments={}
        arts=[{'article_no':40,'parent_article_no':40,'title':'사이즈 문의','content':'키 165인데 M 사이즈로 바꾸면 맞을까요?','writer':'김손님','deleted':'F','notice':'F','secret':'T','created_date':soon(1)},
              {'article_no':41,'parent_article_no':41,'title':'배송','content':'20261018-0000099 언제 와요?','writer':'박손님','deleted':'F','notice':'F','created_date':soon(2)},
              {'article_no':43,'parent_article_no':43,'title':'환불','content':'환불해 주세요','writer':'최손님','deleted':'F','notice':'F','created_date':soon(3)}]
        order={'order_id':'20261018-0000099','order_date':'2026-10-18T10:00:00+09:00','billing_name':'다른사람',
               'items':[{'order_status':'N30','product_name':'티셔츠','quantity':1,'tracking_no':'123456789012','shipping_company_name':'CJ대한통운'}],'receivers':[{'name':'다른사람','cellphone':'010-9999-8888'}]}
        def fake(method,url,headers=None,body=None):
            path=url.split('/api/v2')[1].split('?')[0]
            if method=='POST':sent.append((path,json.loads(body)));return 201,{}
            if path=='/admin/boards':return 200,{'boards':[{'board_no':6,'board_name':'상품 Q&A'}]}
            if path=='/admin/boards/6/articles':return 200,{'articles':arts}
            if path=='/admin/urgentinquiry':return 200,{'urgentinquiry':[]}
            m=re.fullmatch(r'/admin/boards/6/articles/(\d+)/comments',path)
            if m:return 200,{'comments':comments.get(int(m[1]),[])}
            if path=='/admin/orders/20261018-0000099':return 200,{'order':order}
            return 404,{}
        asked=[]
        def fake_answer(co,facts,text,history=None,**k):
            asked.append((facts,text,bot.clean_history(history)))
            if 'L은요' in text:return {'answer':'L은 조금 클 거예요.','category':None,'handoff':False,'lookup':False,'summary':''}
            if '사이즈' in text:return {'answer':'165면 M이 맞아요.','category':None,'handoff':False,'lookup':False,'summary':''}
            if '언제' in text:return {'answer':'곧 도착해요.','category':'배송 조회','handoff':False,'lookup':True,'summary':''}
            return {'answer':'확인해 볼게요','category':'반품·환불','handoff':True,'lookup':False,'summary':'환불 요청'}
        bot.BACKGROUND=False
        with patch.dict(os.environ,{'CAFE24_CLIENT_ID':'cid','CAFE24_CLIENT_SECRET':'csec'}),patch.object(shops,'http',fake),patch.object(bot,'ready',lambda:True),patch.object(bot,'answer',fake_answer):
            with self.core.conn() as db:
                c24.store(db,cid,'fixshop',{'access_token':'A1','refresh_token':'R1','expires_at':'2099-01-01T00:00:00','scopes':['mall.read_order','mall.read_community','mall.write_community']})
                cs={c['title']:c for c in c24.sync_boards(db,self.core.company(db,cid))}
            bot.auto_reply_all()
            def get(t):
                with self.core.conn() as db:return db.execute('SELECT * FROM cases WHERE id=?',(cs[t]['id'],)).fetchone()
            self.assertEqual((get('사이즈 문의')['status'],get('사이즈 문의')['decision']),('answered','auto'))  # 낱말로는 '교환'이어도 AI가 상품 문의로 봤으니 답한다
            p=get('배송');self.assertEqual(p['decision'],'pending');self.assertIn('주문자',p['ai_why']);self.assertEqual(p['ai_draft'],'곧 도착해요.')
            self.assertFalse(any('티셔츠' in f for f,t,h in asked if '언제' in t))  # 남의 주문은 AI에 안 준다
            self.assertEqual(get('환불')['decision'],'pending')
            # 고객이 댓글로 이어 물으면 앞 대화를 보고 마지막 말에 답한다
            comments[40]=[{'comment_no':1,'writer':'김손님','content':'그럼 L은요?','created_date':soon(4)}]
            arts.append({'article_no':44,'parent_article_no':43,'reply_depth':1,'title':'RE: 환불','content':'환불 접수했어요','writer':'운영팀','deleted':'F','notice':'F','created_date':soon(5)})
            with self.core.conn() as db:c24.sync_boards(db,self.core.company(db,cid))
            bot.auto_reply_all()
            f,t,h=asked[-1];self.assertIn('L은요',t);self.assertNotIn('사이즈 문의',t)
            self.assertEqual([x['role'] for x in h],['user','assistant']);self.assertIn('165',h[0]['content']);self.assertIn('M이 맞아요',h[1]['content'])
            self.assertIn('L은 조금 클 거예요.',sent[-1][1]['requests'][0]['content'])
            self.assertEqual((get('환불')['status'],get('환불')['decision']),('answered','direct'))  # 카페24 관리자에서 단 답글
            # 승인하면 AI 초안을 보낸다 (기본 문구가 아니라)
            self.post(b,f"/biz/case/{cs['배송']['id']}",{'act':'approve'})
            self.assertIn('곧 도착해요.',sent[-1][1]['requests'][0]['content']);self.assertEqual(get('배송')['status'],'answered')

    def test_cafe24_launch_verifies_company(self):
        """카페24에서 연 앱으로 권한 동의까지 하면 회사 인증(국세청·이메일 확인)을 기다리지 않고 연결된다. 아이디만 넣은 연결은 인증이 있어야."""
        import base64,hashlib,hmac as _h,time,urllib.parse
        shops=sys.modules['shops']
        def q(mall):
            p=[('mall_id',mall),('shop_no','1'),('timestamp',str(int(time.time()))),('user_id','owner')];s=urllib.parse.urlencode(p)
            return s+'&hmac='+urllib.parse.quote(base64.b64encode(_h.new(b'csec',s.encode(),hashlib.sha256).digest()).decode())
        def fake(method,url,headers=None,body=None):
            if '/oauth/token' in url:return 200,{'access_token':'A1','refresh_token':'R1','expires_at':'2099-01-01T00:00:00','refresh_token_expires_at':'2099-01-01T00:00:00','scopes':['mall.read_order','mall.read_community']}
            return 200,{}
        b=self.client()
        self.post(b,'/biz/signup',{'name':'새카페24상점','biz_no':self.bizno(),'owner_name':'대표','phone':'010-1111-2222','contact':'1588-0000','login_id':'c24new@example.com','password':'longpassword1','terms':'1'})
        with self.core.conn() as db:co=db.execute("SELECT * FROM companies WHERE login_id='c24new@example.com'").fetchone()
        self.assertEqual(co['member'],0)
        with patch.dict(os.environ,{'CAFE24_CLIENT_ID':'cid','CAFE24_CLIENT_SECRET':'csec'}),patch.object(shops,'http',fake):
            self.assertIn('회사 인증이 끝난 뒤',self.post(b,'/biz/connect/cafe24',{'act':'connect','mall_id':'othershop'},follow_redirects=True).get_data(as_text=True))
            loc=b.get('/biz/cafe24/launch?'+q('newshop')).headers['Location'];self.assertIn('newshop.cafe24api.com',loc)
            state=urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)['state'][0]
            b.get('/biz/connect/cafe24/callback?'+urllib.parse.urlencode({'state':state,'code':'abc'}))
        with self.core.conn() as db:
            self.assertEqual(db.execute('SELECT member FROM companies WHERE id=?',(co['id'],)).fetchone()[0],1)
            self.assertEqual(db.execute('SELECT mall_id FROM cafe24_links WHERE company_id=?',(co['id'],)).fetchone()[0],'newshop')

    def test_cafe24_products_and_ai_reply(self):
        """카페24 상품 -> 상품정보 (사장님이 고친 안내는 그대로, 상품 권한 없는 예전 연결은 건너뜀). 상품 문의엔 상품 이름.
        AI 초안은 상품정보를 본다. AI 자동 답변: 단순 문의는 답해서 카페24에 올리고 완료, 반품 등은 안 보내고 메모. 개인정보는 가려서 보낸다."""
        shops=sys.modules['shops'];c24=sys.modules['cafe24'];bot=sys.modules['chatbot'];drafting=sys.modules['drafting'];aim=sys.modules['ai']
        b,o,cid=self.signup_and_approve('카페24상품상점','c24p@example.com')
        sent=[];prods=[{'product_no':7,'product_name':'선크림','price':'19000.00','selling':'T','sold_out':'F','summary_description':'<b>SPF50</b> 순한 선크림','simple_description':''},
                       {'product_no':8,'product_name':'토너','price':'15000.00','selling':'T','sold_out':'T','summary_description':'수분 토너'}]
        soon=lambda m:(self.core.now()+__import__('datetime').timedelta(minutes=m)).strftime('%Y-%m-%dT%H:%M:%S+09:00')  # 연결한 뒤에 올라온 글이어야 AI가 답한다
        arts=[{'article_no':20,'parent_article_no':20,'title':'선크림 문의','content':'민감성도 써도 돼요? 010-1234-5678로 연락 주세요','writer':'김손님','product_no':7,'deleted':'F','notice':'F','created_date':soon(1)},
              {'article_no':21,'parent_article_no':21,'title':'반품하고 싶어요','content':'토너 반품할게요','writer':'이손님','product_no':8,'deleted':'F','notice':'F','created_date':soon(2)}]
        def fake(method,url,headers=None,body=None):
            path=url.split('/api/v2')[1].split('?')[0]
            if method=='POST':sent.append((path,json.loads(body)));return 201,{'articles':[{'article_no':99}]}
            if path=='/admin/orders':return 200,{'orders':[]}
            if path=='/admin/products':return 200,{'products':prods}
            if path=='/admin/boards':return 200,{'boards':[{'board_no':6,'board_name':'상품 Q&A'}]}
            if path=='/admin/boards/6/articles':return 200,{'articles':arts}
            if '/comments' in path:return 200,{'comments':[]}
            return 404,{}
        with patch.dict(os.environ,{'CAFE24_CLIENT_ID':'cid','CAFE24_CLIENT_SECRET':'csec'}),patch.object(shops,'http',fake):
            with self.core.conn() as db:
                db.execute("INSERT INTO products(company_id,name,price,stock,info,updated) VALUES(?,?,?,?,?,?)",(cid,'토너','','','사장님이 쓴 안내',self.core.iso()))
                c24.store(db,cid,'myshop',{'access_token':'A1','refresh_token':'R1','expires_at':'2099-01-01T00:00:00','scopes':['mall.read_order','mall.read_community']})
            r=self.post(b,'/biz/connect/cafe24',{'act':'sync'},follow_redirects=True).get_data(as_text=True)
            self.assertNotIn('상품',r.split('를 가져왔어요')[0].split('주문')[-1])  # 상품 권한이 없는 예전 연결: 상품은 건너뛴다
            with self.core.conn() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM products WHERE company_id=?",(cid,)).fetchone()[0],1)
                db.execute("DELETE FROM cases WHERE company_id=?",(cid,));db.execute("DELETE FROM shop_seen WHERE company_id=?",(cid,));db.execute("UPDATE cafe24_links SET since_b='' WHERE company_id=?",(cid,))
                c24.store(db,cid,'myshop',{'access_token':'A1','refresh_token':'R1','expires_at':'2099-01-01T00:00:00','scopes':c24.SCOPES.split(',')})
            asked=[]
            def fake_answer(co,facts,text,history=None,**k):
                asked.append((facts,text))
                return {'answer':'민감성 피부도 쓰실 수 있어요.','category':None,'handoff':False,'lookup':False,'summary':''} if '선크림' in text else {'answer':'반품은 받은 날부터 7일 안에 신청하실 수 있어요. 주문번호를 알려 주시면 담당자가 확인한 뒤 알려 드릴게요.','category':'반품·환불','handoff':False,'action':True,'lookup':False,'summary':'토너 반품 요청'}
            bot.BACKGROUND=False
            with patch.object(bot,'ready',lambda:True),patch.object(bot,'answer',fake_answer):  # AI 자동 답변 (가입하면 켜져 있음): 가져오자마자 답한다
                r=self.post(b,'/biz/connect/cafe24',{'act':'sync'},follow_redirects=True).get_data(as_text=True)
                self.assertEqual(bot.auto_reply_all(),0)  # 한 번 본 문의는 다시 안 본다
            self.assertIn('상품 2개',r)
            with self.core.conn() as db:
                ps={p['name']:p for p in self.core.products(db,cid)}
                self.assertEqual((ps['선크림']['price'],ps['선크림']['stock'],ps['선크림']['info'],ps['선크림']['src']),('19,000원','있음','SPF50 순한 선크림','cafe24'))
                self.assertEqual((ps['토너']['stock'],ps['토너']['info'],ps['토너']['ext_id']),('품절','사장님이 쓴 안내','8'))  # 같은 이름은 이어 쓰고, 사장님 안내는 그대로
                cs={c['title']:c for c in db.execute("SELECT * FROM cases WHERE company_id=?",(cid,))}
                self.assertEqual(cs['선크림 문의']['product'],'선크림')
                prods[0]['price']='21000.00';prods[0]['summary_description']='새 설명'
                c24.sync_products(db,self.core.company(db,cid))  # 6시간 안이면 자동으로는 안 가져온다
                self.assertEqual(self.core.products(db,cid)[0]['price'] if self.core.products(db,cid)[0]['name']=='선크림' else '19,000원','19,000원')
                c24.sync_products(db,self.core.company(db,cid),force=True)
                p=db.execute("SELECT * FROM products WHERE company_id=? AND name='선크림'",(cid,)).fetchone()
                self.assertEqual((p['price'],p['info']),('21,000원','새 설명'))  # 사장님이 안 고친 안내는 카페24를 따라간다
            # AI 초안: 문의 상품의 정보를 넣는다 (내부 정보는 안 넣음)
            seen={}
            with patch.object(aim,'ready',lambda:True),patch.object(drafting,'call',lambda system,messages,**k:seen.update(u=messages[0]['content']) or '초안'):
                with self.core.conn() as db:res=drafting.draft(db,cs['선크림 문의'],self.core.company(db,cid))
            self.assertEqual(res['by'],'ai');self.assertIn('[상품정보]\n- 선크림 / 가격 21,000원',seen['u']);self.assertNotIn('토너',seen['u'].split('[상품정보]')[1].split('[관련 조문]')[0])
            # AI 자동 답변 결과
            self.assertTrue(any('(전화번호)' in t and '010-1234-5678' not in t for _,t in asked));self.assertIn('선크림 / 가격 19,000원',asked[0][0])
            self.assertEqual(len(sent),2);self.assertEqual(sent[0][1]['requests'][0]['reply_article_no'],20)  # 반품 문의에도 안내는 바로 나간다
            with self.core.conn() as db:
                a=db.execute('SELECT * FROM cases WHERE id=?',(cs['선크림 문의']['id'],)).fetchone();r2=db.execute('SELECT * FROM cases WHERE id=?',(cs['반품하고 싶어요']['id'],)).fetchone()
                self.assertEqual((a['status'],a['decision']),('answered','auto'))
                self.assertTrue(any(e['kind']=='co' and e['reply']=='민감성 피부도 쓰실 수 있어요.' for e in self.core.events(db,a['id'])))
                self.assertEqual((r2['status'],r2['decision']),('seen','pending'))  # 반품: AI가 조건·방법은 안내하고, 처리 결정만 사장님께
                self.assertTrue(any(e['kind']=='co' and e['reply'].startswith('반품은 받은 날부터') for e in self.core.events(db,r2['id'])));self.assertIn('처리할지 정해 주세요',r2['ai_why'])
                self.assertIn('토너 반품 요청',db.execute('SELECT text FROM notes WHERE case_id=?',(r2['id'],)).fetchone()[0])
            # 승인 목록엔 AI가 넘긴 것만, AI 확인 중인 건 안 보인다
            with self.core.conn() as db:db.execute("UPDATE cases SET decision='ai' WHERE id=?",(cs['선크림 문의']['id'],));db.execute("UPDATE cases SET status='forwarded' WHERE id=?",(cs['선크림 문의']['id'],))
            biz=sys.modules['business']
            with self.core.conn() as db:self.assertEqual(sum(map(biz.is_pending,db.execute('SELECT * FROM cases WHERE company_id=?',(cid,)).fetchall())),1)
            with self.core.conn() as db:db.execute("UPDATE cases SET decision='auto',status='answered' WHERE id=?",(cs['선크림 문의']['id'],))
            # 유형별로 'AI가 바로 안내 / 답도 내 승인 후'를 고른다 (기본: 모두 AI가 안내). 다른 설정을 저장해도 기본값을 굳히지 않는다
            with self.core.conn() as db:self.assertTrue(self.core.rule_for(db,cid,'반품·환불')['ai_ok']);self.assertTrue(self.core.rule_for(db,cid,'기타')['ai_ok'])
            self.assertIn('답도 내 승인 후',b.get('/biz/rules').get_data(as_text=True))
            self.post(b,'/biz/rules',{'category':'교환','faq':'교환 안내'})
            with self.core.conn() as db:self.assertEqual(db.execute("SELECT ai_ok FROM rules WHERE company_id=? AND category='교환'",(cid,)).fetchone()[0],'')
            self.post(b,'/biz/rules',{'category':'반품·환불','ai_ok':'0'});self.post(b,'/biz/rules',{'category':'기타','ai_ok':'0'})
            with self.core.conn() as db:self.assertFalse(self.core.rule_for(db,cid,'반품·환불')['ai_ok']);self.assertFalse(self.core.rule_for(db,cid,'기타')['ai_ok'])
            # 끄면 새 문의에 답하지 않는다
            self.post(b,'/biz/ai-reply',{'on':'0'},form_path='/biz/rules')
            with self.core.conn() as db:self.assertEqual(self.core.company(db,cid)['ai_reply'],'')
            self.assertIn('AI 자동 답변',b.get('/biz/rules').get_data(as_text=True))

    def test_chat_order_lookup(self):
        """상담창 주문 조회: 휴대폰 + 주문번호(또는 이름)가 둘 다 맞아야 보임. 개인정보는 고객 화면·AI 어디에도 안 나감. AI는 확인된 주문으로 답함."""
        b,o,cid=self.signup_and_approve('주문조회상점','lookup@example.com')
        with self.core.conn() as db:
            for no,st,inv,day in (('A-100','shipped','123412341234','2026-10-14'),('A-099','paid','','2026-10-10')):
                db.execute("""INSERT INTO orders(company_id,order_no,channel,ordered_on,buyer,phone,address,product,qty,amount,status,courier,invoice,created,updated)
                    VALUES(?,?,'자사몰',?,'홍길동','01012345678','서울시 비밀구 1','머그컵',1,1000,?,?,?,?,?)""",(cid,no,day,st,'CJ대한통운' if inv else '',inv,'2026-10-14','2026-10-14'))
        me=self.client();page=me.get(f'/to/{cid}').get_data(as_text=True);ctok=re.search(r'data-csrf="([^"]+)"',page).group(1)
        self.assertIn('data-orders="1"',page)
        ask=lambda **d:me.post(f'/chat/{cid}',data=dict(d,csrf=ctok,act='order')).get_json()
        self.assertIn('order_error',ask(phone='010-1234-5678',key='A-999'))   # 주문번호 틀림
        self.assertIn('order_error',ask(phone='010-9999-9999',key='A-100'))   # 휴대폰 틀림
        self.assertIn('order_error',ask(phone='010-1234-5678',key=''))
        j=ask(phone='010-1234-5678',key='a-100');self.assertEqual([x['order_no'] for x in j['orders']],['A-100'])
        x=j['orders'][0];self.assertEqual((x['status_label'],x['courier'],x['can_return'],x['can_cancel']),('배송 중','CJ대한통운',True,False))
        self.assertNotIn('01012345678',json.dumps(j,ensure_ascii=False));self.assertNotIn('비밀구',json.dumps(j,ensure_ascii=False));self.assertNotIn('홍길동',json.dumps(j,ensure_ascii=False))
        j=ask(phone='01012345678',key='홍길동');self.assertEqual([x['order_no'] for x in j['orders']],['A-100','A-099'])
        # AI는 확인된 주문만 받고, 이름·휴대폰·주소는 받지 않는다
        seen={}
        def fake(url,headers,body,timeout):
            seen.update(body=body);c='{"category": "배송 조회", "answer": "A-100은 배송 중이에요.", "handoff": false, "lookup": false, "summary": ""}'
            return (200,{'output':[{'type':'message','content':[{'type':'output_text','text':c}]}]}) if url.endswith('/responses') else (200,{'choices':[{'message':{'content':c}}]})
        aim=sys.modules['ai']
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(aim,'post',fake):
            j=me.post(f'/chat/{cid}',data={'csrf':ctok,'text':'제 택배 어디쯤이에요?'}).get_json()
        self.assertEqual((j['answer'],j['lookup']),('A-100은 배송 중이에요.',False))
        system=seen['body'].get('instructions') or seen['body']['messages'][0]['content']
        self.assertIn('[본인 확인된 주문]',system);self.assertIn('주문번호 A-100',system);self.assertIn('상태 배송 중',system)
        for pii in ('01012345678','010-1234-5678','홍길동','비밀구'):self.assertNotIn(pii,system)
        # 다른 브라우저는 확인 전이라 주문을 모르고, AI가 조회를 권하면 lookup
        other=self.client();p2=other.get(f'/to/{cid}').get_data(as_text=True);t2=re.search(r'data-csrf="([^"]+)"',p2).group(1)
        def fake2(url,headers,body,timeout):
            seen.update(body=body);c='{"category": "배송 조회", "answer": "주문 조회로 확인해 드릴게요.", "handoff": false, "lookup": true, "summary": ""}'
            return (200,{'output':[{'type':'message','content':[{'type':'output_text','text':c}]}]}) if url.endswith('/responses') else (200,{'choices':[{'message':{'content':c}}]})
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(aim,'post',fake2):
            j=other.post(f'/chat/{cid}',data={'csrf':t2,'text':'제 택배 어디쯤이에요?'}).get_json()
        self.assertTrue(j['lookup']);self.assertNotIn('A-100',seen['body'].get('instructions') or seen['body']['messages'][0]['content'])
        # 마구 넣어 보면 막는다
        with patch.object(self.core,'throttled',lambda p,**k:p=='chat_order'):
            self.assertIn('너무 많아요',ask(phone='010-1234-5678',key='A-100')['order_error'])
        # 접수 화면은 주문번호를 이어받는다
        self.assertIn('value="A-099"',me.get(f'/new?company_id={cid}&category=주문 취소&order_no=A-099').get_data(as_text=True))

    def test_cafe24_app_launch(self):
        """카페24에서 앱을 열면: hmac·시간 확인 -> 로그인 전이면 가입으로, 로그인돼 있으면 바로 권한 동의로. 위조·오래된 값은 거절."""
        import base64,hashlib,hmac as _h,time,urllib.parse
        c24=sys.modules['cafe24']
        def q(mall='myshop',ts=None,secret='csec',sort=False):
            p=[('is_multi_shop','F'),('lang','ko_KR'),('mall_id',mall),('shop_no','1'),('timestamp',str(int(ts or time.time()))),('user_id','owner'),('user_name','대표'),('user_type','P')]
            s=urllib.parse.urlencode(sorted(p) if sort else p)
            return s+'&hmac='+urllib.parse.quote(base64.b64encode(_h.new(secret.encode(),s.encode(),hashlib.sha256).digest()).decode())
        with patch.dict(os.environ,{'CAFE24_CLIENT_ID':'cid','CAFE24_CLIENT_SECRET':'csec'}):
            self.assertEqual(c24.launch_ok(q()),'myshop')
            self.assertIsNone(c24.launch_ok(q(secret='nope')))
            self.assertIsNone(c24.launch_ok(q(ts=time.time()-3*3600)))
            self.assertIsNone(c24.launch_ok(q().replace('myshop','other')))
            g=self.client()
            r=g.get('/biz/?'+q());self.assertIn('/cafe24/launch?',r.headers['Location'])  # App URL이 첫 화면이어도
            r=g.get('/biz/cafe24/launch?'+q(),follow_redirects=True);self.assertIn('myshop',r.get_data(as_text=True))  # 가입·로그인 안내
            r=g.get('/biz/cafe24/launch?'+q(secret='x'),follow_redirects=True);self.assertIn('확인하지 못했어요',r.get_data(as_text=True))
            b,o,cid=self.signup_and_approve('카페24앱상점','c24app@example.com')
            r=b.get('/biz/cafe24/launch?'+q('appshop'));self.assertTrue(r.headers['Location'].startswith('https://appshop.cafe24api.com/api/v2/oauth/authorize?'))
            # 로그인 전에 열고 나서 로그인하면 연결 화면에 아이디가 채워져 있다
            g2=self.client();g2.get('/biz/cafe24/launch?'+q('later'))
            self.post(g2,'/biz/login',{'login_id':'c24app@example.com','password':'longpassword1'})
            page=g2.get('/biz/',follow_redirects=True).get_data(as_text=True);self.assertIn('value="later"',page);self.assertIn('앱을 열었어요',page)
            self.assertNotIn('앱을 열었어요',g2.get('/biz/connect/cafe24').get_data(as_text=True))  # 한 번만 이어 준다

    def test_external_api_and_webhooks(self):
        """외부 API: 운영자가 켠 회사만, 키 해시 저장, 시험 키는 데모 데이터만, 회사 간 격리, 폐기, 웹훅 서명·기록·내부 주소 차단."""
        import hashlib,hmac as _h
        api=sys.modules['openapi'];shops=sys.modules['shops']
        b,o,cid=self.signup_and_approve('API상점','api@example.com')
        self.assertEqual(b.get('/biz/developers').status_code,404)  # 운영자가 켜기 전에는 없다
        self.post(o,f'/biz/ops/company/{cid}/api',{'on':'1'},form_path=f'/biz/ops/company/{cid}')
        page=self.post(b,'/biz/developers',{'act':'key','mode':'test','name':'시험'}).get_data(as_text=True)
        tkey=re.search(r'(sk_test_[A-Za-z0-9_-]+)',page).group(1)
        lkey=re.search(r'(sk_live_[A-Za-z0-9_-]+)',self.post(b,'/biz/developers',{'act':'key','mode':'live','name':'운영'}).get_data(as_text=True)).group(1)
        with self.core.conn() as db:self.assertFalse(db.execute('SELECT 1 FROM api_keys WHERE hash=? OR prefix=?',(tkey,tkey)).fetchone())
        c=self.client();H=lambda k:{'Authorization':'Bearer '+k}
        self.assertEqual(c.get('/biz/api/ext/v1/me').status_code,401)
        self.assertEqual(c.get('/biz/api/ext/v1/me',headers=H('sk_test_'+'x'*30)).status_code,401)
        self.assertTrue(c.get('/biz/api/ext/v1/me',headers=H(tkey)).get_json()['company']['demo'])
        demo_cases=c.get('/biz/api/ext/v1/cases',headers=H(tkey)).get_json()['data'];self.assertTrue(demo_cases)
        self.file_case(self.client(),'API상점','배송 조회',company_id=str(cid),title='실제고객문의')
        live=c.get('/biz/api/ext/v1/cases',headers=H(lkey)).get_json()['data']
        self.assertIn('실제고객문의',[x['title'] for x in live]);self.assertNotIn('실제고객문의',[x['title'] for x in demo_cases])
        r=c.post('/biz/api/ext/v1/cases',headers=H(lkey),json={'channel':'전화','category':'교환','title':'API로 등록','body':'사이즈 교환','want':'교환'});self.assertEqual(r.status_code,201)
        no=r.get_json()['data']['no']
        self.assertEqual(c.post('/biz/api/ext/v1/cases',headers=H(lkey),json={'title':'x'}).status_code,400)
        r=c.post(f'/biz/api/ext/v1/cases/{no}/replies',headers=H(lkey),json={'message':'교환 접수했어요'});self.assertEqual(r.status_code,200)
        self.assertEqual(r.get_json()['data']['status'],'answered')
        with self.core.conn() as db:self.assertTrue(db.execute("SELECT 1 FROM events e JOIN cases c ON c.id=e.case_id WHERE c.no=? AND e.actor='API (운영)'",(no,)).fetchone())
        # 다른 회사 문의는 안 보인다
        b2,_,cid2=self.signup_and_approve('남API상점','api2@example.com')
        self.post(o,f'/biz/ops/company/{cid2}/api',{'on':'1'},form_path=f'/biz/ops/company/{cid2}')
        k2=re.search(r'(sk_live_[A-Za-z0-9_-]+)',self.post(b2,'/biz/developers',{'act':'key','mode':'live'}).get_data(as_text=True)).group(1)
        self.assertEqual(c.get(f'/biz/api/ext/v1/cases/{no}',headers=H(k2)).status_code,404)
        # 폐기
        with self.core.conn() as db:kid=db.execute("SELECT id FROM api_keys WHERE company_id=? AND mode='live'",(cid2,)).fetchone()[0]
        self.post(b2,'/biz/developers',{'act':'revoke','id':str(kid)});self.assertEqual(c.get('/biz/api/ext/v1/me',headers=H(k2)).status_code,401)
        # 웹훅: http·내부 주소는 막는다
        self.assertIn('https://',self.post(b,'/biz/developers',{'act':'hook','url':'http://example.com/h','events':['case.created'],'mode':'live'},follow_redirects=True).get_data(as_text=True))
        self.assertIn('사설망',self.post(b,'/biz/developers',{'act':'hook','url':'https://127.0.0.1/h','events':['case.created'],'mode':'live'},follow_redirects=True).get_data(as_text=True))
        sent=[]
        def fake(method,url,headers=None,body=None):sent.append((url,headers,body));return 200,{}
        with patch.object(api,'safe_url',lambda u:''),patch.object(shops,'http',fake):
            page=self.post(b,'/biz/developers',{'act':'hook','url':'https://hooks.example.com/s','events':['case.created','case.replied'],'mode':'live'},follow_redirects=True).get_data(as_text=True)
            sec=re.search(r'(whsec_[A-Za-z0-9_-]+)',page).group(1)
            self.file_case(self.client(),'API상점','배송 조회',company_id=str(cid),title='웹훅문의')
            self.assertGreaterEqual(api.dispatch(),1)
            url,hd,body=sent[-1];self.assertEqual(hd['X-Soboru-Event'],'case.created');self.assertIn('웹훅문의',body.decode())
            t,v=re.match(r't=(\d+),v1=([0-9a-f]+)',hd['X-Soboru-Signature']).groups()
            self.assertEqual(v,_h.new(sec.encode(),f'{t}.'.encode()+body,hashlib.sha256).hexdigest())
            n=len(sent);api.dispatch();self.assertEqual(len(sent),n)  # 같은 것은 다시 안 보낸다
        self.assertIn('case.created',b.get('/biz/developers').get_data(as_text=True))
        # 운영자가 끄면 키도 막힌다
        self.post(o,f'/biz/ops/company/{cid}/api',{'on':'0'},form_path=f'/biz/ops/company/{cid}')
        self.assertEqual(c.get('/biz/api/ext/v1/me',headers=H(lkey)).status_code,403)

    def test_shop_reply_posting_and_ai_stats(self):
        """판매처 답변 올리기(시험 운영): 스마트스토어 문의에 답한 뒤 올리면 판매처 API로 간다. AI 성과는 실제 기록만."""
        import bcrypt
        shops=sys.modules['shops'];b,o,cid=self.signup_and_approve('답변올림상점','post@example.com')
        sent=[]
        def fake(method,url,headers=None,body=None):
            if url.endswith('/oauth2/token'):return 200,{'access_token':'tok','expires_in':10800}
            if '/pay-user/inquiries' in url:return 200,{'content':[{'inquiryNo':91,'title':'사이즈 문의','inquiryContent':'M 사이즈 있나요','answered':False}],'totalPages':1}
            if '/answer' in url:sent.append((url,json.loads(body)));return 200,{}
            return 200,{'data':{'lastChangeStatuses':[]}}
        with patch.object(shops,'http',fake):
            shops._tokens.clear();self.post(b,'/biz/connect/naver',{'client_id':'post-app','client_secret':bcrypt.gensalt().decode()})
            with self.core.conn() as db:case_id=db.execute("SELECT case_id FROM shop_seen WHERE company_id=? AND ext_id='n91'",(cid,)).fetchone()[0]
            r=self.post(b,f'/biz/case/{case_id}',{'act':'post_shop'},follow_redirects=True);self.assertIn('먼저 답변',r.get_data(as_text=True))
            r=self.post(b,f'/biz/case/{case_id}',{'act':'reply','msg':'네, M 사이즈 있어요'},follow_redirects=True)
            self.assertIn('다시 보내기',b.get(f'/biz/case/{case_id}').get_data(as_text=True))  # 다시 올리기는 그대로
        self.assertEqual(sent,[('https://api.commerce.naver.com/external/v1/pay-merchant/inquiries/91/answer',{'answerComment':'네, M 사이즈 있어요'})])
        self.assertIn('스마트스토어에 답변을 올렸어요',r.get_data(as_text=True))
        # 쿠팡은 Wing 아이디가 없으면 안내만
        with self.core.conn() as db:
            db.execute("INSERT INTO shop_links(company_id,shop,creds,created) VALUES(?,?,?,?)",(cid,'coupang',shops.seal({'vendor_id':'A1','access_key':'a','secret_key':'s'}),'2026-10-14'))
            db.execute("INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)",(cid,'coupang','q55',case_id+0))
        # AI 성과: 기록이 적으면 비율은 –
        page=b.get('/biz/stats/ai').get_data(as_text=True);self.assertIn('AI 성과',page);self.assertIn('–',page)
        with self.core.conn() as db:
            for _ in range(6):db.execute("INSERT INTO chat_log(company_id,category,outcome,created) VALUES(?,?,?,?)",(cid,'배송 조회','asked',self.core.iso()))
            for _ in range(3):db.execute("INSERT INTO chat_log(company_id,category,outcome,created) VALUES(?,?,?,?)",(cid,'배송 조회','solved',self.core.iso()))
        b.post(f'/biz/case/{case_id}/draft',data={'csrf':self.csrf(b,f'/biz/case/{case_id}')})
        page=b.get('/biz/stats/ai').get_data(as_text=True)
        self.assertRegex(page,r'상담창에서 해결</span><b>50<small>%');self.assertIn('초안을 만든 문의</dt><dd>1건',page)

    def test_suspend_resume_keeps_verification(self):
        b,o,cid=self.signup_and_approve('중지마켓','susp@example.com')
        x=self.client();self.post(x,'/biz/signup',{'name':'미인증마켓','biz_no':self.bizno(),'owner_name':'대표','phone':'010-1111-2222','contact':'1588-0000','login_id':'susp2@example.com','password':'longpassword1','terms':'1'})
        with self.core.conn() as db:uid=db.execute('SELECT id FROM companies WHERE login_id=?',('susp2@example.com',)).fetchone()[0]
        for c in (cid,uid):
            self.post(o,'/biz/ops/companies',{'act':'suspend','id':str(c)})
            self.post(o,'/biz/ops/companies',{'act':'resume','id':str(c)})
        with self.core.conn() as db:
            m=dict(db.execute('SELECT id,member FROM companies WHERE id IN (?,?)',(cid,uid)).fetchall())
            st=db.execute('SELECT status FROM companies WHERE id=?',(uid,)).fetchone()[0]
        self.assertEqual((m[cid],m[uid],st),(1,0,'active'))  # 인증한 회사는 인증 그대로, 인증 전에 중지한 회사는 다시 인증 전으로

    def test_inbox_tools(self):
        """태그·우선순위·미루기·답변 템플릿·일괄 처리·CSV·합치기·고객 프로필."""
        b,o,cid=self.signup_and_approve('받은함상점','inbox@example.com')
        c=self.client();c1=self.file_case(c,'받은함상점','제품 불량',company_id=cid,title='단추가 떨어졌어요')
        c2=self.file_case(self.client(),'받은함상점','교환',company_id=cid,title='사이즈 교환 원해요')
        # 태그는 만들면서 붙이고, 메모에 남고, 목록에서 태그로 거른다
        self.post(b,f'/biz/case/{c1}',{'act':'tag_add','tag':'불량'})
        with self.core.conn() as db:tid=db.execute("SELECT id FROM tags WHERE company_id=? AND name='불량'",(cid,)).fetchone()[0]
        page=b.get(f'/biz/case/{c1}').get_data(as_text=True);self.assertIn('태그 &#39;불량&#39;을(를) 붙였어요',page)
        lst=b.get(f'/biz/all?t={tid}').get_data(as_text=True);self.assertIn(f'/biz/case/{c1}"',lst);self.assertNotIn(f'/biz/case/{c2}"',lst)
        # 우선순위 급함은 우선순위 순 맨 위
        self.post(b,f'/biz/case/{c1}',{'act':'prio','prio':'urgent'})
        lst=b.get('/biz/all?s=prio').get_data(as_text=True);self.assertLess(lst.index(f'/biz/case/{c1}"'),lst.index(f'/biz/case/{c2}"'));self.assertIn('class="prio urgent"',lst)
        # 미루면 '답변 전'에서 빠지고 '미뤄 둠'에 나온다. 고객이 새 글을 남기면 풀린다
        self.post(b,f'/biz/case/{c2}',{'act':'snooze','when':'tomorrow'})
        self.assertNotIn(f'/biz/case/{c2}"',b.get('/biz/all?f=open').get_data(as_text=True))
        self.assertIn(f'/biz/case/{c2}"',b.get('/biz/all?f=snz').get_data(as_text=True))
        self.assertIn('미루기를 확인',self.post(b,f'/biz/case/{c2}',{'act':'snooze','when':'date','day':'2000-01-01'},follow_redirects=True).get_data(as_text=True).replace('미룰 때를 확인','미루기를 확인'))
        with self.core.conn() as db:self.core.add_event(db,c2,'me','추가로 사진 보내요');self.assertEqual(db.execute('SELECT snooze_until FROM cases WHERE id=?',(c2,)).fetchone()[0],'')
        # 답변 템플릿: 자리를 요청 내용으로 채우고, 쓰면 정한 태그가 붙는다
        self.post(b,'/biz/macros',{'act':'save','name':'교환 안내','body':'{고객명}님, 접수번호 {접수번호} 교환 도와드릴게요.','tags':'교환안내'})
        with self.core.conn() as db:mid,no2=db.execute("SELECT id FROM macros WHERE company_id=?",(cid,)).fetchone()[0],db.execute('SELECT no FROM cases WHERE id=?',(c2,)).fetchone()[0]
        page=b.get(f'/biz/case/{c2}').get_data(as_text=True);self.assertIn(f'김소비님, 접수번호 {no2} 교환 도와드릴게요.',page)
        self.post(b,f'/biz/case/{c2}',{'act':'reply','msg':'김소비님, 교환 도와드릴게요.','macro':str(mid)})
        with self.core.conn() as db:
            self.assertEqual(db.execute('SELECT used FROM macros WHERE id=?',(mid,)).fetchone()[0],1)
            self.assertTrue(db.execute("SELECT 1 FROM case_tags ct JOIN tags t ON t.id=ct.tag_id WHERE ct.case_id=? AND t.name='교환안내'",(c2,)).fetchone())
        # 일괄: 두 건에 담당자와 태그를 한 번에. 다른 회사 요청 번호는 무시
        other=self.file_case(self.client(),'없는가게','기타')
        self.post(b,'/biz/all/bulk',{'ids':[str(c1),str(c2),str(other)],'bulk':'assign','assignee':'owner'},'/biz/all')
        self.post(b,'/biz/all/bulk',{'ids':[str(c1),str(c2)],'bulk':'tag','tag':'=위험'},'/biz/all')
        with self.core.conn() as db:
            self.assertEqual([r[0] for r in db.execute('SELECT assignee FROM cases WHERE id IN (?,?) ORDER BY id',(c1,c2))],['owner','owner'])
            self.assertEqual(db.execute('SELECT assignee FROM cases WHERE id=?',(other,)).fetchone()[0],'')
        # CSV: 엑셀 수식이 되지 않게, 연락처는 넣지 않는다
        r=b.get('/biz/all.csv');self.assertEqual(r.status_code,200);txt=r.get_data().decode('utf-8-sig')
        self.assertIn('접수번호,접수일',txt);self.assertIn("'=위험",txt);self.assertNotIn('010-1234',txt);self.assertNotIn('01012345678',txt)
        # 고객 프로필: 같은 휴대폰의 다른 요청이 보인다
        self.assertIn('사이즈 교환 원해요',b.get(f'/biz/case/{c1}').get_data(as_text=True))
        # 합치기: 원래 요청은 지우지 않고 닫고, 합친 쪽에 메모·태그가 옮겨진다
        self.post(b,f'/biz/case/{c1}',{'act':'merge','target':no2})
        with self.core.conn() as db:
            r1=db.execute('SELECT status,merged_into FROM cases WHERE id=?',(c1,)).fetchone();self.assertEqual((r1[0],r1[1]),('closed',c2))
            self.assertTrue(db.execute("SELECT 1 FROM notes WHERE case_id=? AND text LIKE '합친 요청%단추가 떨어졌어요%'",(c2,)).fetchone())
            self.assertTrue(db.execute('SELECT 1 FROM case_tags WHERE case_id=? AND tag_id=?',(c2,tid)).fetchone())
        self.assertIn('에 합쳐졌어요',b.get(f'/biz/case/{c1}').get_data(as_text=True))
        self.assertIn('이미 끝난 요청',self.post(b,f'/biz/case/{c1}',{'act':'merge','target':no2},follow_redirects=True).get_data(as_text=True))

    def test_hours_sla_autoassign(self):
        """영업시간·영업시간 밖 안내·첫 답변 목표·자동 배정."""
        import datetime as dt
        b,o,cid=self.signup_and_approve('운영상점','ops-co@example.com')
        wf=sys.modules['workflow']
        for nm,em in (('가상담','ga@example.com'),('나상담','na@example.com')):
            html=self.post(b,'/biz/team',{'act':'invite','name':nm,'email':em,'role':'agent'}).get_data(as_text=True)
            path='/biz/join/'+re.search(r'value="(http[^"]*/join/[^"]+)"',html).group(1).split('/join/')[1];self.post(self.client(),path,{'password':'agentpassword1'})
        r=self.post(b,'/biz/settings',{'act':'ops','day1':'1','day2':'1','day3':'1','day4':'1','day5':'1','hours_from':'09:00','hours_to':'18:00','sla_hours':'4','away_on':'1','away_msg':'지금은 쉬는 시간이에요. {다음영업}에 답변드릴게요.','auto_assign':'1'},follow_redirects=True)
        self.assertIn('응대 운영 설정을 저장했어요',r.get_data(as_text=True))
        self.assertIn('시작 시간이 끝 시간보다',self.post(b,'/biz/settings',{'act':'ops','day1':'1','hours_from':'18:00','hours_to':'09:00'},follow_redirects=True).get_data(as_text=True))
        with self.core.conn() as db:co=self.core.company(db,cid)
        self.assertEqual(wf.hours_text(co),'평일 09:00~18:00')
        # 영업시간만 센다: 금요일 17시 + 4시간 = 월요일 12시
        self.assertEqual(wf.add_work_hours(co,dt.datetime(2026,10,16,17,0),4),dt.datetime(2026,10,19,12,0))
        self.assertFalse(wf.in_hours(co,dt.datetime(2026,10,18,10,0)))
        self.assertEqual(wf.next_open(co,dt.datetime(2026,10,17,3,0)),dt.datetime(2026,10,19,9,0))
        # 일요일 새벽에 들어온 요청: 안내가 진행 기록에 남고, 직원끼리 나눠 배정된다
        with patch.object(self.core,'now',lambda:dt.datetime(2026,10,18,3,0)):
            c1=self.file_case(self.client(),'운영상점','제품 불량',company_id=cid)
            c2=self.file_case(self.client(),'운영상점','고객 응대',company_id=cid)
        with self.core.conn() as db:
            ev=db.execute("SELECT text,reply FROM events WHERE case_id=? AND kind='co'",(c1,)).fetchall()
            self.assertEqual(ev[0][0],wf.AWAY_TEXT);self.assertIn('내일 9시에 답변드릴게요',ev[0][1])
            a1,a2=[db.execute('SELECT assignee FROM cases WHERE id=?',(x,)).fetchone()[0] for x in (c1,c2)]
            self.assertTrue(a1 and a2 and a1!=a2 and 'owner' not in (a1,a2))
            self.assertEqual(db.execute('SELECT status FROM cases WHERE id=?',(c1,)).fetchone()[0],'forwarded')  # 안내는 답변으로 치지 않는다
        with patch.object(self.core,'now',lambda:dt.datetime(2026,10,19,10,0)):
            self.assertIn('첫 답변 3시간 남음',b.get(f'/biz/case/{c1}').get_data(as_text=True))  # 일요일 접수라 월 9시부터 4시간: 13시까지
        # 목표(월 13시)가 지나면 목록에 '지남', 답하면 사라지고 달성률에 들어간다
        with patch.object(self.core,'now',lambda:dt.datetime(2026,10,19,13,30)):
            self.assertIn('첫 답변 목표 지남',b.get('/biz/all').get_data(as_text=True))
            self.post(b,f'/biz/case/{c2}',{'act':'reply','msg':'확인했어요.'})
            with self.core.conn() as db:rep=wf.report(db,self.core.company(db,cid),db.execute('SELECT * FROM cases WHERE company_id=?',(cid,)).fetchall())
            self.assertEqual((rep['n'],rep['met']),(2,0))
            self.assertIn('첫 답변 목표 달성률',b.get('/biz/stats').get_data(as_text=True))


    def test_automations(self):
        """자동화 규칙: 조건에 맞는 새 요청에 태그·우선순위·담당자·메모. 고객에게 보이는 기록은 남기지 않는다."""
        b,o,cid=self.signup_and_approve('규칙상점','rule-co@example.com')
        html=self.post(b,'/biz/team',{'act':'invite','name':'다상담','email':'da@example.com','role':'agent'}).get_data(as_text=True)
        self.post(self.client(),'/biz/join/'+re.search(r'value="(http[^"]*/join/[^"]+)"',html).group(1).split('/join/')[1],{'password':'agentpassword1'})
        with self.core.conn() as db:staff=[k for k,_ in sys.modules['team'].people(db,self.core.company(db,cid)) if k!='owner'][0]
        self.assertIn('이렇게 시작해 보세요',b.get('/biz/automations').get_data(as_text=True))
        self.assertIn('화난 고객 먼저',b.get('/biz/automations?new=1&ex=angry').get_data(as_text=True))
        # 조건·할 일이 없으면 저장하지 않는다
        self.assertIn('조건을 하나 이상',self.post(b,'/biz/automations',{'act':'save','name':'빈 규칙','af_0':'tag','av_0':'x'},follow_redirects=True).get_data(as_text=True))
        r=self.post(b,'/biz/automations',{'act':'save','name':'깨짐은 급하게','match':'all','cf_0':'text','cop_0':'has','cv_0':'깨져, 파손','cf_1':'category','cop_1':'is','cv_1':'제품 불량',
            'af_0':'tag','av_0':'파손, 사진확인','af_1':'prio','av_1':'urgent','af_2':'assign','av_2':staff,'af_3':'note','av_3':'사진 먼저 확인'},follow_redirects=True)
        self.assertIn('규칙을 저장했어요',r.get_data(as_text=True))
        self.post(b,'/biz/automations',{'act':'save','name':'꺼 둘 규칙','cf_0':'order','cop_0':'none','af_0':'tag','av_0':'주문없음'})
        with self.core.conn() as db:rid=db.execute("SELECT id FROM automations WHERE name='꺼 둘 규칙'").fetchone()[0]
        self.post(b,'/biz/automations',{'act':'toggle','id':str(rid)})
        hit=self.file_case(self.client(),'규칙상점','제품 불량',company_id=cid)
        miss=self.file_case(self.client(),'규칙상점','고객 응대',company_id=cid,title='응대가 아쉬웠어요')
        with self.core.conn() as db:
            c=db.execute('SELECT priority,assignee FROM cases WHERE id=?',(hit,)).fetchone()
            self.assertEqual((c[0],c[1]),('urgent',staff))
            tg={r[0] for r in db.execute('SELECT t.name FROM case_tags ct JOIN tags t ON t.id=ct.tag_id WHERE ct.case_id=?',(hit,))}
            self.assertEqual(tg,{'파손','사진확인'})
            notes=' '.join(r[0] for r in db.execute('SELECT text FROM notes WHERE case_id=?',(hit,)))
            self.assertIn("자동화 규칙 '깨짐은 급하게'",notes);self.assertIn('사진 먼저 확인',notes)
            self.assertFalse(db.execute("SELECT 1 FROM events WHERE case_id=? AND text LIKE '%자동화%'",(hit,)).fetchone())  # 고객이 보는 기록에는 없음
            self.assertEqual(db.execute('SELECT priority FROM cases WHERE id=?',(miss,)).fetchone()[0],'normal')
            self.assertFalse(db.execute('SELECT 1 FROM case_tags WHERE case_id=?',(miss,)).fetchone())  # 꺼 둔 규칙은 적용 안 함
            self.assertEqual(db.execute("SELECT runs FROM automations WHERE name='깨짐은 급하게'").fetchone()[0],1)
        page=b.get('/biz/automations').get_data(as_text=True)
        self.assertIn("제목·내용에 &#39;깨져, 파손&#39; 중 하나가 있음 그리고 유형이 제품 불량",page);self.assertIn('1번 적용',page);self.assertIn('꺼져 있어요',page)
        # 다른 회사 규칙은 고치거나 지울 수 없다
        b2,_,_=self.signup_and_approve('남의상점','other-co@example.com')
        self.post(b2,'/biz/automations',{'act':'delete','id':str(rid)})
        with self.core.conn() as db:self.assertTrue(db.execute('SELECT 1 FROM automations WHERE id=?',(rid,)).fetchone())
        self.post(b,'/biz/automations',{'act':'delete','id':str(rid)})
        with self.core.conn() as db:self.assertFalse(db.execute('SELECT 1 FROM automations WHERE id=?',(rid,)).fetchone())


    def test_widget_conversion_money(self):
        """문의 버튼 설치 확인, 상담 후 구매 전환, 요청 화면의 주문·환불 합계."""
        import datetime as dt
        b,o,cid=self.signup_and_approve('전환상점','conv-co@example.com')
        self.assertIn('아직 붙이지 않았어요',b.get('/biz/connect/widget').get_data(as_text=True))
        c=self.client();c.get(f'/widget.js?c={cid}',headers={'Referer':'https://myshop.example.com/product/1'})
        page=b.get('/biz/connect/widget').get_data(as_text=True)
        self.assertIn('myshop.example.com에 붙어 있어요',page)
        self.assertIn('myshop.example.com에 붙어 있어요',b.get('/biz/connect').get_data(as_text=True))
        case=self.file_case(self.client(),'전환상점','반품·환불',company_id=cid)
        today=dt.date.today()
        with self.core.conn() as db:
            ph=db.execute('SELECT phone FROM cases WHERE id=?',(case,)).fetchone()[0];t=self.core.iso()
            for no,day,amt,st in (('A-1',today-dt.timedelta(days=20),30000,'refunded'),('A-2',today+dt.timedelta(days=0),45000,'paid'),('A-3',today-dt.timedelta(days=40),10000,'delivered')):
                db.execute("INSERT INTO orders(company_id,order_no,ordered_on,phone,product,amount,status,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",(cid,no,day.isoformat(),ph,'원피스',amt,st,t,t))
            conv=sys.modules['insights'].conversion(db,self.core.company(db,cid))
        self.assertEqual((conv['n'],conv['won'],conv['pct'],conv['amount']),(1,1,100,45000))  # 요청 뒤 주문 A-2만 센다
        stats=b.get('/biz/stats').get_data(as_text=True)
        self.assertIn('상담 후 구매',stats);self.assertIn('45,000원',stats);self.assertIn('14일 안에',stats)
        pg=b.get(f'/biz/case/{case}').get_data(as_text=True)
        self.assertIn('취소·반품·환불 내역',pg);self.assertIn('85,000원',pg);self.assertIn('30,000원',pg)


    def test_live_chat(self):
        """실시간 채팅: 켜면 고객센터에 버튼, 채팅으로 접수하면 채팅방, 서로 주고받고 보고 있는지 보인다."""
        b,o,cid=self.signup_and_approve('채팅상점','chat-co@example.com')
        self.assertNotIn('상담원과 채팅',self.client().get(f'/to/{cid}').get_data(as_text=True))
        self.post(b,'/biz/settings',{'act':'ops','live_chat':'1'})
        self.assertIn('상담원과 채팅',self.client().get(f'/to/{cid}').get_data(as_text=True))
        u=self.client()
        self.assertIn('접수하면 바로 채팅방이 열려요',u.get(f'/new?company_id={cid}&live=1').get_data(as_text=True))
        data={'company':'채팅상점','company_id':cid,'category':'배송 조회','title':'배송이 언제 와요?','body':'어제 주문한 원피스 언제 받을 수 있을까요?','want':'배송 확인','name':'김채팅','phone':'010-2222-3333',
              'password':'1234','privacy':'1','consent':'1','live':'1'}
        r=self.post(u,'/submit',data,'/new')
        self.assertIn('#chat',r.headers['Location']);case=int(r.headers['Location'].split('/case/')[1].split('#')[0])
        page=u.get(f'/case/{case}').get_data(as_text=True)
        self.assertIn('id="chat"',page);self.assertIn('livechat.js',page)
        j=self.post(u,f'/case/{case}/live',{'text':'혹시 오늘 출발하나요?'},f'/case/{case}').get_json()
        self.assertEqual(j['msgs'][-1]['text'],'혹시 오늘 출발하나요?');self.assertFalse(j['co_online'])
        # 다른 사람은 채팅방을 못 본다
        self.assertEqual(self.client().get(f'/case/{case}/live').status_code,404)
        jb=b.get(f'/biz/case/{case}/live?after=0').get_json()
        self.assertIn('혹시 오늘 출발하나요?',[m['text'] for m in jb['msgs']]);self.assertTrue(jb['me_online'])
        self.assertIn('채팅 중',b.get('/biz/all').get_data(as_text=True))
        last=jb['msgs'][-1]['id']
        jb=self.post(b,f'/biz/case/{case}/live',{'text':'네, 오늘 오후에 보내요!','after':str(last)},f'/biz/case/{case}').get_json()
        self.assertEqual([m['text'] for m in jb['msgs']],['네, 오늘 오후에 보내요!'])
        j=u.get(f'/case/{case}/live?after={last}').get_json()
        self.assertEqual([(m['who'],m['text']) for m in j['msgs']],[('co','네, 오늘 오후에 보내요!')]);self.assertTrue(j['co_online'])
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT status FROM cases WHERE id=?',(case,)).fetchone()[0],'answered')
        # 답을 받은 뒤 고객이 또 말하면 다시 '확인 중'
        self.post(u,f'/case/{case}/live',{'text':'고마워요'},f'/case/{case}')
        with self.core.conn() as db:
            self.assertEqual(db.execute('SELECT status FROM cases WHERE id=?',(case,)).fetchone()[0],'seen')
            db.execute("UPDATE cases SET status='closed' WHERE id=?",(case,))
        r=self.post(u,f'/case/{case}/live',{'text':'또 있어요'},f'/case/{case}')
        self.assertEqual(r.status_code,400)
        # 끄면 버튼이 사라진다
        self.post(b,'/biz/settings',{'act':'ops'})
        self.assertNotIn('상담원과 채팅',self.client().get(f'/to/{cid}').get_data(as_text=True))

    def test_mail_inbox(self):
        """이메일 문의: 메일함을 이으면 새 메일이 요청이 되고, 답장은 이어 붙고, 답변은 눌러야 회사 메일함에서 나간다."""
        import mailin
        b,o,cid=self.signup_and_approve('메일상점','mail-co@example.com')
        logins=[];sent=[]
        class FakeImap:
            def logout(self):pass
        def imap_open(creds):
            logins.append(creds)
            if creds['password']!='app-pass-1':raise mailin.MailError('로그인하지 못했어요. 메일 주소와 앱 비밀번호, IMAP 사용 설정을 확인해 주세요.')
            return FakeImap()
        box=[]
        def fetch(creds,uv,last,since):return '7',[(u,r) for u,r in box if u>last]
        def mail(uid,frm,subj,body,mid,extra=''):
            box.append((uid,(f"From: {frm}\r\nTo: cs@mail-shop.com\r\nSubject: {subj}\r\nMessage-ID: {mid}\r\nDate: Wed, 14 Oct 2026 10:00:00 +0900\r\n{extra}"
                             f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}").encode()))
        old=(mailin.imap_open,mailin.fetch,mailin.smtp_send)
        mailin.imap_open=imap_open;mailin.fetch=fetch;mailin.smtp_send=lambda creds,msg:sent.append(msg)
        try:
            page=b.get('/biz/connect').get_data(as_text=True);self.assertIn('이메일 문의',page)
            r=self.post(b,'/biz/connect/email',{'preset':'naver','user':'cs@mail-shop.com','password':'wrong'},'/biz/connect/email')
            self.assertIn('로그인하지 못했어요',b.get('/biz/connect/email').get_data(as_text=True))
            with self.core.conn() as db:self.assertIsNone(mailin.link(db,cid))
            mail(1,'"김메일" <kim@example.com>','환불 언제 되나요?','지난주에 반품 보냈는데 환불이 아직이에요.\n\n-----Original Message-----\n지난 메일','<m1@example.com>')
            mail(2,'news@shop.example','이번 주 할인','광고','<ad@example.com>','List-Unsubscribe: <mailto:x@example.com>\r\n')
            mail(3,'no-reply@pg.example','결제 알림','자동','<pg@example.com>')
            self.post(b,'/biz/connect/email',{'preset':'naver','user':'cs@mail-shop.com','password':'app-pass-1'},'/biz/connect/email')
            self.assertEqual(logins[-1]['imap'],'imap.naver.com')
            with self.core.conn() as db:
                lk=mailin.link(db,cid);self.assertEqual(lk['status'],'ok');self.assertNotIn('app-pass-1',lk['creds'])
                rows=db.execute("SELECT * FROM cases WHERE company_id=? AND channel='이메일'",(cid,)).fetchall()
            self.assertEqual(len(rows),1);c=rows[0]
            self.assertEqual((c['title'],c['email'],c['name']),('환불 언제 되나요?','kim@example.com','김메일'))
            self.assertNotIn('지난 메일',c['body'])
            # 다시 가져와도 같은 메일은 한 번만
            self.post(b,'/biz/connect/email',{'act':'sync'},'/biz/connect/email')
            with self.core.conn() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM cases WHERE channel='이메일' AND company_id=?",(cid,)).fetchone()[0],1)
            # '답변하기'를 눌러야 나가고, 누르면 바로 간다
            self.assertIn('누르면 고객에게 메일로 바로 가요',b.get(f'/biz/case/{c["id"]}').get_data(as_text=True));self.assertEqual(sent,[])
            self.post(b,f'/biz/case/{c["id"]}',{'act':'reply','msg':'오늘 환불해 드렸어요. 2~3일 안에 들어가요.'},f'/biz/case/{c["id"]}')
            self.assertEqual(len(sent),1);m=sent[0]
            self.assertIn('다시 보내기',b.get(f'/biz/case/{c["id"]}').get_data(as_text=True))  # 다시 보내기는 그대로 있다
            self.assertEqual((m['To'],m['In-Reply-To']),('kim@example.com','<m1@example.com>'));self.assertIn('오늘 환불해 드렸어요',m.get_content())
            # 고객이 우리 답장에 다시 답하면 같은 요청에 이어 붙는다
            mail(4,'kim@example.com','Re: 환불 언제 되나요?','확인했어요 감사합니다\n\n> 오늘 환불해 드렸어요','<m4@example.com>',f"In-Reply-To: {m['Message-ID']}\r\n")
            self.post(b,'/biz/connect/email',{'act':'sync'},'/biz/connect/email')
            with self.core.conn() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM cases WHERE channel='이메일' AND company_id=?",(cid,)).fetchone()[0],1)
                ev=db.execute("SELECT text FROM events WHERE case_id=? AND kind='me' ORDER BY id DESC",(c['id'],)).fetchone()[0]
                self.assertEqual(ev,'확인했어요 감사합니다')
                self.assertEqual(db.execute('SELECT status FROM cases WHERE id=?',(c['id'],)).fetchone()[0],'seen')
            self.post(b,'/biz/connect/email',{'act':'delete'},'/biz/connect/email')
            with self.core.conn() as db:self.assertIsNone(mailin.link(db,cid))
        finally:mailin.imap_open,mailin.fetch,mailin.smtp_send=old

    def test_notify_poll(self):
        """켜 둔 화면 알림: 처음엔 위치만, 그다음엔 새 요청과 고객의 새 메시지를 요청마다 한 번씩. 다른 회사 것은 안 보인다."""
        import instagram
        b,o,cid=self.signup_and_approve('알림상점','nt-co@example.com')
        b2,o2,cid2=self.signup_and_approve('남의상점','nt-other@example.com')
        with self.core.conn() as db:
            for k,c in ((cid,'1'),(cid2,'2')):db.execute("INSERT INTO ig_links(company_id,ig_id,username,creds,created) VALUES(?,?,?,?,?)",(k,'ig'+c,'u'+c,'{}',self.core.iso()))
        old=instagram._call;instagram._call=lambda *a,**k:(200,{'username':'gogaek'})
        ev=lambda ig,mid,text:{'object':'instagram','entry':[{'id':ig,'messaging':[{'sender':{'id':'777'},'message':{'mid':mid,'text':text}}]}]}
        try:
            p0=b.get('/biz/notify/poll').get_json();self.assertEqual(p0['items'],[])
            self.assertEqual(self.client().get('/biz/notify/poll').status_code,302)  # 로그인 전
            instagram.receive(ev('ig1','m1','반품하고 싶어요'));instagram.receive(ev('ig1','m2','사진 보낼게요'));instagram.receive(ev('ig2','x1','남의 회사 문의'))
            p1=b.get(f"/biz/notify/poll?c={p0['c']}&e={p0['e']}").get_json()
            self.assertEqual([(i['kind'],i['text']) for i in p1['items']],[('new','반품하고 싶어요')])
            self.assertIn('인스타그램 DM',p1['items'][0]['title'])
            self.assertEqual(b.get(f"/biz/notify/poll?c={p1['c']}&e={p1['e']}").get_json()['items'],[])
            instagram.receive(ev('ig1','m3','언제 와요?'))
            p2=b.get(f"/biz/notify/poll?c={p1['c']}&e={p1['e']}").get_json()
            self.assertEqual([(i['kind'],i['text']) for i in p2['items']],[('msg','언제 와요?')])
            self.assertIn('notify.js',b.get('/biz/').get_data(as_text=True))
            # 인스타 요청은 '대화 끝내기'로 닫고, 그다음 DM은 새 요청이 된다
            with self.core.conn() as db:case_id=db.execute("SELECT id FROM cases WHERE company_id=? AND channel='인스타그램 DM'",(cid,)).fetchone()[0]
            self.assertIn('대화 끝내기',b.get(f'/biz/case/{case_id}').get_data(as_text=True))
            self.post(b,f'/biz/case/{case_id}',{'act':'close_chat'},f'/biz/case/{case_id}')
            self.assertNotIn('대화 끝내기',b.get(f'/biz/case/{case_id}').get_data(as_text=True))
            instagram.receive(ev('ig1','m4','또 문의할게요'))
            with self.core.conn() as db:
                rows=db.execute("SELECT status FROM cases WHERE company_id=? AND channel='인스타그램 DM' ORDER BY id",(cid,)).fetchall()
                self.assertEqual([r[0] for r in rows],['closed','forwarded'])
        finally:instagram._call=old

    def test_instagram_deauth_and_delete(self):
        """메타가 보낸 서명 맞는 승인 취소·데이터 삭제 요청만 받고, 그 계정 연결을 지운다."""
        import instagram, base64 as _b, hmac as _h, hashlib, json as _j
        b,o,cid=self.signup_and_approve('인스타삭제','ig-del@example.com')
        old_env=os.environ.get('IG_APP_SECRET');os.environ['IG_APP_SECRET']='sec-ig-2'
        def sr(uid,key=b'sec-ig-2'):
            body=_b.urlsafe_b64encode(_j.dumps({'algorithm':'HMAC-SHA256','user_id':uid}).encode()).decode().rstrip('=')
            return _b.urlsafe_b64encode(_h.new(key,body.encode(),hashlib.sha256).digest()).decode().rstrip('=')+'.'+body
        def n():
            with self.core.conn() as db:return db.execute('SELECT COUNT(*) FROM ig_links WHERE company_id=?',(cid,)).fetchone()[0]
        try:
            with self.core.conn() as db:db.execute("INSERT OR REPLACE INTO ig_links(company_id,ig_id,creds,created) VALUES(?,?,?,?)",(cid,'7001','x','2026-10-18'))
            c=self.client()
            self.assertEqual(c.post('/biz/hook/instagram/deauth',data={'signed_request':sr('7001',b'wrong')}).status_code,400)
            self.assertEqual(c.post('/biz/hook/instagram/deauth',data={'signed_request':'junk'}).status_code,400)
            self.assertEqual(n(),1)
            self.assertEqual(c.post('/biz/hook/instagram/deauth',data={'signed_request':sr('7001')}).status_code,200)
            self.assertEqual(n(),0)
            with self.core.conn() as db:db.execute("INSERT OR REPLACE INTO ig_links(company_id,ig_id,creds,created) VALUES(?,?,?,?)",(cid,'7001','x','2026-10-18'))
            d=c.post('/biz/hook/instagram/delete',data={'signed_request':sr('7001')}).get_json()
            self.assertTrue(d['url'].endswith('/data-deletion'));self.assertEqual(len(d['confirmation_code']),16);self.assertEqual(n(),0)
        finally:
            if old_env is None:os.environ.pop('IG_APP_SECRET',None)
            else:os.environ['IG_APP_SECRET']=old_env

    def test_cafe24_app_billing(self):
        """카페24 앱 결제: 운영자가 켜면 연결 권한에 앱 결제가 들어가고, 카페24로 연결한 사장님은 카페24 주문 -> 결제 화면 -> 돌아오면 카페24에 직접 확인해 켠다.
        카페24 결제 화면 주소가 카페24가 아니면 보내지 않는다. 매달 결제는 카페24가 하고(우리 cron은 결제 안 함), 웹훅은 카페24에 다시 물어 맞춘다."""
        import json as _j
        bl=sys.modules['billing'];shops=sys.modules['shops'];c24=sys.modules['cafe24']
        b,o,cid=self.signup_and_approve('카페24결제상점','c24pay@example.com')
        env={'CAFE24_CLIENT_ID':'cid','CAFE24_CLIENT_SECRET':'csec'};old_env={k:os.environ.get(k) for k in env};os.environ.update(env)
        calls=[];st={'url':'https://myshop.cafe24.com/disp/common/myapps/order?signature=x','pays':[]}
        def http(method,url,headers=None,body=None,**kw):
            calls.append((method,url,_j.loads(body) if body else None))
            if url.endswith('/admin/appstore/orders') and method=='POST':return 201,{'order':{'order_id':'cafe24-20261018-1','confirmation_url':st['url']}}
            if '/admin/appstore/payments' in url:return 200,{'payments':st['pays']}
            if url.endswith('/billing-key'):raise AssertionError('카페24 결제 회사에 포트원 결제를 하면 안 돼요')
            return 404,{}
        old=shops.http;shops.http=http
        def row():
            with self.core.conn() as db:return db.execute('SELECT * FROM billing WHERE company_id=?',(cid,)).fetchone()
        def plan_of():
            with self.core.conn() as db:return db.execute('SELECT plan FROM companies WHERE id=?',(cid,)).fetchone()[0]
        try:
            self.post(o,'/biz/ops/billing',{'name':'베이직','price':'29000'})
            with self.core.conn() as db:c24.store(db,cid,'myshop',{'access_token':'A1','refresh_token':'R1','expires_at':'2099-01-01T00:00:00','scopes':c24.SCOPES.split(',')})
            self.assertNotIn('카페24로 결제하고',b.get('/biz/billing').get_data(as_text=True))  # 꺼져 있으면 안 보임
            self.assertNotIn('application',c24.scopes())
            self.post(o,'/biz/ops/billing',{'act':'c24','on':'1'});self.assertTrue(bl.c24_on());self.assertIn('mall.write_application',c24.scopes())
            self.assertIn('카페24 다시 연결하기',b.get('/biz/billing').get_data(as_text=True))  # 결제 권한이 없는 예전 연결
            with self.core.conn() as db:c24.store(db,cid,'myshop',{'access_token':'A1','refresh_token':'R1','expires_at':'2099-01-01T00:00:00','scopes':c24.scopes().split(',')})
            self.assertIn('카페24로 결제하고 시작하기',b.get('/biz/billing').get_data(as_text=True))
            st['url']='https://evil.example.com/pay'
            r=self.post(b,'/biz/billing/cafe24',{},'/biz/billing');self.assertTrue(r.headers['Location'].endswith('/biz/billing'))  # 카페24가 아닌 결제 주소는 보내지 않는다
            st['url']='https://myshop.cafe24.com/disp/common/myapps/order?signature=x'
            r=self.post(b,'/biz/billing/cafe24',{},'/biz/billing');self.assertEqual(r.headers['Location'],st['url'])
            req=[c for c in calls if c[1].endswith('/admin/appstore/orders')][-1][2]['request']
            self.assertEqual((req['order_amount'],req['automatic_payment']),('29000','T'));self.assertTrue(req['return_url'].endswith('/biz/billing/cafe24/done'))
            b.get('/biz/billing/cafe24/done');self.assertEqual(plan_of(),'pilot')  # 아직 결제 전
            st['pays']=[{'payment_id':'P1','payment_status':'paid','payment_amount':'29000.00','approval_no':'A-1','pay_date':'2026-10-18T10:00:00+09:00','expiration_date':'2026-11-18T00:00:00+09:00'}]
            b.get('/biz/billing/cafe24/done');b.get('/biz/billing/cafe24/done')
            r_=row();self.assertEqual((r_['status'],r_['source'],r_['next_charge']),('active','cafe24','2026-11-18'));self.assertEqual(plan_of(),'paid')
            with self.core.conn() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM billing_payments WHERE company_id=? AND status='done'",(cid,)).fetchone()[0],1)
            self.assertIn('해지는 카페24 관리자',b.get('/biz/billing').get_data(as_text=True))
            with self.core.conn() as db:db.execute("UPDATE billing SET next_charge=? WHERE company_id=?",(bl.today().isoformat(),cid))
            bl.renew_all()  # 우리 cron은 카페24 결제 회사를 결제하지 않는다
            hook=lambda ev:self.client().post('/biz/hook/cafe24',json={'event_no':ev,'resource':{'mall_id':'myshop','client_id':'cid'}})
            st['pays'][0]['expiration_date']='2099-01-01';hook(90078);self.assertEqual(row()['status'],'active')  # 가짜 만료 웹훅: 카페24엔 기간이 남아 있어 그대로
            st['pays']=[];hook(90078);self.assertEqual((row()['status'],plan_of()),('ended','pilot'))
        finally:
            shops.http=old
            with self.core.conn() as db:db.execute("DELETE FROM settings WHERE key IN ('billing_plan','c24_billing')")  # 다른 시험에 요금제가 남지 않게
            for k,v in old_env.items():
                if v is None:os.environ.pop(k,None)
                else:os.environ[k]=v

    def test_portone_billing(self):
        """포트원 정기결제: 키·요금제가 없으면 준비 중, 카드 등록하면 첫 달 결제, 남의 빌링키는 거절, 결제일엔 하루 한 번만, 3번 실패하면 멈춤, 해지하면 결제일에 끝."""
        import json as _j, datetime as _d
        bl=sys.modules['billing'];shops=sys.modules['shops']
        b,o,cid=self.signup_and_approve('결제상점','pay-co@example.com')
        self.assertIn('요금제를 준비하고 있어요',b.get('/biz/billing').get_data(as_text=True))
        self.assertEqual(self.client().get('/biz/billing').status_code,302)
        env={'PORTONE_STORE_ID':'store-abc','PORTONE_CHANNEL_KEY':'channel-key-xyz','PORTONE_API_SECRET':'po-secret-1'};old_env={k:os.environ.get(k) for k in env};os.environ.update(env)
        calls=[];res={'pay':(200,{'payment':{'pgTxId':'pg-1','paidAt':'2026-10-18T00:00:00Z'}}),'owner':None}
        def http(method,url,headers=None,body=None,**kw):
            calls.append((method,url,headers,_j.loads(body) if body else None))
            if '/billing-keys/' in url and method=='GET':
                return 200,{'status':'ISSUED','billingKey':url.split('/billing-keys/')[1].split('?')[0],'customer':{'id':res['owner']},
                            'methods':[{'type':'BillingKeyPaymentMethodCard','card':{'name':'신한카드','number':'1234-****-****-5678'}}]}
            if method=='DELETE':return 200,{'deletedAt':'x'}
            if url.endswith('/billing-key'):return res['pay']
            if '/payments/' in url and method=='GET':return 200,{'status':'PAID','receiptUrl':'https://receipt.example/1'}
            return 404,{}
        old=shops.http;shops.http=http
        def st():
            with self.core.conn() as db:return db.execute('SELECT * FROM billing WHERE company_id=?',(cid,)).fetchone()
        def plan_of():
            with self.core.conn() as db:return db.execute('SELECT plan FROM companies WHERE id=?',(cid,)).fetchone()[0]
        def pays(status):
            with self.core.conn() as db:return db.execute('SELECT COUNT(*) FROM billing_payments WHERE company_id=? AND status=?',(cid,status)).fetchone()[0]
        def due_today(**kw):
            with self.core.conn() as db:
                db.execute('UPDATE billing SET next_charge=? WHERE company_id=?',(bl.today().isoformat(),cid))
                for k,v in kw.items():db.execute(f'UPDATE billing SET {k}=? WHERE company_id=?',(v,cid))
        def pay_calls():return [c for c in calls if c[1].endswith('/billing-key')]
        try:
            self.assertIn('요금제를 준비하고 있어요',b.get('/biz/billing').get_data(as_text=True))  # 키만 있고 요금제가 없으면 아직
            self.post(o,'/biz/ops/billing',{'name':'베이직','price':'50'})
            self.assertIsNone(bl.plan())
            self.post(o,'/biz/ops/billing',{'name':'베이직','price':'33,000'})
            self.assertEqual(bl.plan(),{'name':'베이직','price':33000})
            h=b.get('/biz/billing').get_data(as_text=True)
            self.assertIn('data-card',h);self.assertIn('cdn.portone.io/v2/browser-sdk.js',h);self.assertIn('channel-key-xyz',h);self.assertNotIn('po-secret-1',h)
            key=st()['customer_key'];self.assertTrue(key.startswith('cs_'))
            # 다른 고객 키로 발급된 빌링키는 받지 않는다
            res['owner']='cs_someone_else';b.get('/biz/billing/done?billingKey=bk-other')
            self.assertEqual(st()['status'],'none');self.assertEqual(st()['creds'],'');self.assertEqual(pay_calls(),[])
            res['owner']=key;b.get('/biz/billing/done?billingKey=bk-secret-1')
            g=[c for c in calls if c[0]=='GET' and '/billing-keys/bk-secret-1' in c[1]][0]
            self.assertIn('storeId=store-abc',g[1]);self.assertEqual(g[2]['Authorization'],'PortOne po-secret-1')
            p1=pay_calls()[0][3];self.assertEqual(p1['billingKey'],'bk-secret-1');self.assertEqual(p1['amount'],{'total':33000});self.assertEqual(p1['currency'],'KRW')
            self.assertEqual(p1['customer']['id'],key);self.assertEqual(p1['storeId'],'store-abc')
            s=st();self.assertEqual(s['status'],'active');self.assertNotIn('bk-secret-1',s['creds']);self.assertEqual(s['card'],'신한카드 1234-****-****-5678')
            self.assertEqual(s['next_charge'],bl.add_month(bl.today()).isoformat());self.assertEqual(plan_of(),'paid');self.assertEqual(pays('done'),1)
            self.assertIn('https://receipt.example/1',b.get('/biz/billing').get_data(as_text=True))
            self.assertEqual(bl.add_month(_d.date(2026,1,31)),_d.date(2026,2,28));self.assertEqual(bl.add_month(_d.date(2026,12,5)),_d.date(2027,1,5))
            # 카드 바꾸기: 새 빌링키로 바꾸고 예전 것은 포트원에서 지운다 (결제는 하지 않음)
            n=len(pay_calls());b.get('/biz/billing/done?billingKey=bk-secret-2')
            self.assertEqual(len(pay_calls()),n);self.assertTrue(any(c[0]=='DELETE' and '/billing-keys/bk-secret-1' in c[1] for c in calls))
            # 등록 창에서 취소하면 실패 안내
            self.assertIn('/biz/billing',b.get('/biz/billing/done?code=FAILURE_TYPE_PG&message=x').headers['Location'])
            # 결제일: 운영자가 바꾼 금액으로, 하루 한 번만
            self.post(o,'/biz/ops/billing',{'name':'베이직','price':'44000'})
            self.assertIn('44,000',b.get('/biz/billing').get_data(as_text=True))
            due_today();self.assertEqual(bl.renew_all(),1);self.assertEqual(pay_calls()[-1][3]['amount'],{'total':44000});self.assertEqual(pay_calls()[-1][3]['billingKey'],'bk-secret-2')
            self.assertEqual(pays('done'),2);self.assertEqual(st()['next_charge'],bl.add_month(bl.today()).isoformat())
            n=len(pay_calls());due_today();self.assertEqual(bl.renew_all(),0);self.assertEqual(len(pay_calls()),n)  # 같은 날 두 번 결제하지 않는다
            # 실패: 결제 실패 -> 3번째에 멈추고 무료 시범으로
            res['pay']=(400,{'type':'PG_PROVIDER','message':'PG사 오류','pgCode':'CARD_REJECT','pgMessage':'카드사에서 거절했어요'})
            due_today(last_try='');bl.renew_all();s=st()
            self.assertEqual((s['status'],s['fails']),('past_due',1));self.assertIn('카드사에서 거절',s['note']);self.assertEqual(plan_of(),'paid');self.assertEqual(pays('fail'),1)
            due_today(last_try='',fails=2);bl.renew_all();s=st()
            self.assertEqual(s['status'],'stopped');self.assertEqual(plan_of(),'pilot')
            res['pay']=(200,{'payment':{'pgTxId':'pg-2','paidAt':'2026-10-18T00:00:00Z'}})
            self.post(b,'/biz/billing',{'act':'retry'});self.assertEqual(st()['status'],'active');self.assertEqual(plan_of(),'paid')
            # 해지: 결제일까지 쓰고 그날 끝 (빌링키도 지움), 이어 쓰기도 된다
            self.post(b,'/biz/billing',{'act':'cancel'});self.assertEqual(st()['status'],'canceled')
            self.post(b,'/biz/billing',{'act':'resume'});self.assertEqual(st()['status'],'active')
            self.post(b,'/biz/billing',{'act':'cancel'});n=len(pay_calls())
            due_today(last_try='');bl.renew_all();s=st()
            self.assertEqual((s['status'],s['creds']),('ended',''));self.assertEqual(plan_of(),'pilot');self.assertEqual(len(pay_calls()),n)
            self.assertTrue(any(c[0]=='DELETE' and '/billing-keys/bk-secret-2' in c[1] for c in calls))
            self.assertIn('결제상점',o.get('/biz/ops/billing').get_data(as_text=True))
        finally:
            shops.http=old
            with self.core.conn() as db:db.execute("DELETE FROM settings WHERE key='billing_plan'")
            for k,v in old_env.items():
                if v is None:os.environ.pop(k,None)
                else:os.environ[k]=v

    def test_followup_in_same_chat_gets_alert_and_ai(self):
        """같은 대화방(DM 등)에 고객이 이어서 물으면, 사장님이 직접 답하던 대화나 승인을 기다리던 문의라도 알림이 뜨고 AI가 앞 대화까지 보고 답한다.
        AI가 답을 만드는 사이에 고객이 또 쓰면 그 답은 버리고 다음 차례가 대화 전체에 답한다."""
        bot=sys.modules['chatbot'];shops=sys.modules['shops']
        b,o,cid=self.signup_and_approve('이어묻기상점','followup@example.com')
        with self.core.conn() as db:
            co=self.core.company(db,cid);t=self.core.iso()
            case=db.execute("""INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel)
                VALUES(?,?,?,1,'기타','안녕하세요','안녕하세요','기타','','','','','x',1,'seen','direct',?,?,?,'','','인스타그램')""",(self.core.new_case_no(db),cid,co['name'],t,t,t)).lastrowid
            db.execute("INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,'instagram','u:1',?)",(cid,case))
        said=[];extra=[]
        def fake_answer(co,facts,text,history=None,**k):
            said.append(text)
            if extra:  # 답을 만드는 사이에 고객이 또 씀
                with self.core.conn() as db:c=db.execute('SELECT * FROM cases WHERE id=?',(case,)).fetchone();self.core.add_event(db,case,'me',extra[0]);bot.again(db,c,extra.pop())
            return {'answer':'SPF50+예요.','category':None,'handoff':False,'lookup':False,'summary':''}
        bot.BACKGROUND=False
        with patch.object(bot,'ready',lambda:True),patch.object(bot,'answer',fake_answer),patch.object(shops,'post_reply',lambda *a:''):
            with self.core.conn() as db:
                c=db.execute('SELECT * FROM cases WHERE id=?',(case,)).fetchone();self.core.add_event(db,case,'me','선크림 SPF 몇이에요?');self.assertTrue(bot.again(db,c,'선크림 SPF 몇이에요?'))
            extra.append('민감성 피부도 돼요?')
            bot.auto_reply_all()
            with self.core.conn() as db:
                r=db.execute('SELECT * FROM cases WHERE id=?',(case,)).fetchone()
                self.assertEqual((r['decision'],r['ai_tried']),('ai',''))  # 첫 답은 버렸다
                self.assertTrue(db.execute("SELECT 1 FROM biz_alerts WHERE company_id=? AND kind='msg'",(cid,)).fetchone())  # 사장님께 알림
            bot.auto_reply_all()
            with self.core.conn() as db:
                r=db.execute('SELECT * FROM cases WHERE id=?',(case,)).fetchone()
                self.assertEqual((r['status'],r['decision']),('answered','auto'))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE case_id=? AND kind='co'",(case,)).fetchone()[0],1)
        self.assertIn('민감성 피부도 돼요?',said[-1])

    def test_ai_guides_then_owner_decides(self):
        """AI는 늘 먼저 응대한다: 불만이 커도 짧은 응대는 보내고 사장님께. '답도 내 승인 후'로 고른 유형만 보내지 않는다.
        답은 검색 없이 먼저 만들고, AI가 확신이 없다고 할 때만 검색으로 다시 묻는다."""
        bot=sys.modules['chatbot'];shops=sys.modules['shops']
        b,o,cid=self.signup_and_approve('먼저응대상점','guide-first@example.com')
        def mk(title,ext):
            with self.core.conn() as db:
                co=self.core.company(db,cid);t=self.core.iso()
                case=db.execute("""INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel)
                    VALUES(?,?,?,1,'기타',?,?,'기타','','','','','x',1,'forwarded','ai','2099-01-01 00:00:00',?,?,'','','인스타그램')""",(self.core.new_case_no(db),cid,co['name'],title,title,t,t)).lastrowid
                db.execute("INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,'instagram',?,?)",(cid,ext,case))
            return case
        angry=mk('세 번째 문의예요 너무 화나요','u:a');swap=mk('사이즈 교환하고 싶어요','u:b')
        replies={'세 번째':{'answer':'불편을 드려 정말 죄송해요. 담당자가 바로 이어서 답드릴게요.','category':None,'handoff':True,'lookup':False,'summary':'반복 문의 불만'},
                 '교환':{'answer':'교환은 7일 안에 신청하실 수 있어요.','category':'교환','handoff':False,'action':True,'lookup':False,'summary':'사이즈 교환'}}
        posted=[]
        with self.core.conn() as db:db.execute("INSERT INTO rules(company_id,category,auto,ai_ok) VALUES(?,'교환',0,'0')",(cid,))  # 교환은 답도 내 승인 후
        bot.BACKGROUND=False
        with patch.object(bot,'ready',lambda:True),patch.object(bot,'answer',lambda co,facts,text,history=None,**k:next(v for key,v in replies.items() if key in text)),\
             patch.object(shops,'post_reply',lambda db,co,c,text:posted.append(text) or ''):
            bot.auto_reply_all()
        with self.core.conn() as db:
            a=db.execute('SELECT * FROM cases WHERE id=?',(angry,)).fetchone();s_=db.execute('SELECT * FROM cases WHERE id=?',(swap,)).fetchone()
        self.assertEqual(posted,['불편을 드려 정말 죄송해요. 담당자가 바로 이어서 답드릴게요.'])
        self.assertEqual((a['status'],a['decision']),('seen','pending'));self.assertIn('AI가 먼저 응대했어요',a['ai_why'])
        self.assertEqual((s_['status'],s_['decision']),('forwarded','pending'));self.assertIn('답도 승인 후',s_['ai_why'])
        # 검색은 확신이 없을 때만
        aim=sys.modules['ai'];webs=[]
        def fake_chat(system,msgs,**k):
            webs.append(k.get('web'));return '{"answer":"네","sure":%s}'%('true' if k.get('web') else 'false')
        with patch.object(aim,'ready',lambda:True),patch.object(aim,'chat',fake_chat):
            r=bot.answer({'id':cid,'name':'x','tone':'polite'},'','선크림 몇 ml예요?')
        self.assertEqual((webs,r['answer']),([False,True],'네'))

    def test_chat_inbox(self):
        """상담 화면: 대화방 목록(결정 필요 표시), 대화 열기(확인 처리), 새 말 받기, 대화방에서 답·메모, 남의 대화방은 못 연다."""
        b,o,cid=self.signup_and_approve('상담방상점','chatinbox@example.com')
        with self.core.conn() as db:
            co=self.core.company(db,cid);t=self.core.iso()
            case=db.execute("""INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel,ai_why,ai_draft)
                VALUES(?,?,?,1,'환불','환불해 주세요','환불해 주세요','환불','','김고객','','','x',1,'forwarded','pending','2099-01-01 00:00:00',?,?,'','','인스타그램','환불 요청','확인 후 안내드릴게요.')""",(self.core.new_case_no(db),cid,co['name'],t,t)).lastrowid
        side=b.get('/biz/').get_data(as_text=True).split('class="bside"')[1].split('</nav>')[0];self.assertIn('href="/biz/chat"',side)  # 컴퓨터 옆 메뉴에도 상담
        j=b.get('/biz/chat/list.json').get_json()['rows']
        self.assertEqual([(r['id'],r['need'],r['mark'][0]) for r in j],[(case,True,'IG')])
        h=b.get(f'/biz/chat/{case}').get_data(as_text=True)
        self.assertIn('환불해 주세요',h);self.assertIn('확인 후 안내드릴게요.',h);self.assertIn('id="cxDec"',h)
        with self.core.conn() as db:self.assertEqual(db.execute('SELECT status FROM cases WHERE id=?',(case,)).fetchone()[0],'seen')
        m=b.get(f'/biz/chat/{case}/msgs').get_json();self.assertTrue(m['need']);last=m['last']
        r=self.post(b,f'/biz/chat/{case}/send',{'text':'사진 보내 주실 수 있을까요?'},f'/biz/chat/{case}')
        self.assertEqual(r.get_json(),{'ok':True})
        new=b.get(f'/biz/chat/{case}/msgs?after={last}').get_json()['msgs']
        self.assertEqual([(x['who'],x['text']) for x in new if x['who']=='co'],[('co','사진 보내 주실 수 있을까요?')])
        r=self.post(b,f'/biz/case/{case}',{'act':'note','note':'사진 받으면 교환','back':'chat'},f'/biz/chat/{case}')
        self.assertTrue(r.headers['Location'].endswith(f'/biz/chat/{case}'))
        self.assertIn('사진 받으면 교환',b.get(f'/biz/chat/{case}').get_data(as_text=True))
        self.assertEqual(self.post(b,f'/biz/chat/{case}/send',{'text':''},f'/biz/chat/{case}').status_code,400)
        b2,_,_=self.signup_and_approve('남의상점','chatother@example.com')
        self.assertEqual(b2.get(f'/biz/chat/{case}').status_code,404)
        self.assertEqual(b2.get('/biz/chat/list.json').get_json()['rows'],[])

    def test_instagram_dm(self):
        """인스타그램 DM: 키가 없으면 연동 대기, 로그인으로 잇고, 서명 맞는 웹훅만 받고, 같은 고객은 이어 붙고, 답장은 눌러야 간다."""
        import instagram, hmac as _h, hashlib, json as _j, urllib.parse as up
        b,o,cid=self.signup_and_approve('인스타상점','ig-co@example.com')
        self.assertIn('메타 앱 준비를 마치면',b.get('/biz/connect/instagram').get_data(as_text=True))
        env={'IG_APP_ID':'app1','IG_APP_SECRET':'sec-ig-1','IG_VERIFY_TOKEN':'verify-1'};old_env={k:os.environ.get(k) for k in env};os.environ.update(env)
        calls=[];reply={'fail':None}
        def call(method,url,params=None,form=None,token=None):
            calls.append((method,url,params,form,token))
            if 'oauth/access_token' in url:return 200,{'access_token':'short-tok','user_id':'111'}
            if url.endswith('/access_token'):return 200,{'access_token':'long-tok','expires_in':5184000}
            if url.endswith('/me'):return 200,{'user_id':'9001','username':'inssa_shop'}
            if url.endswith('/subscribed_apps'):return 200,{'success':True}
            if url.endswith('/me/messages'):return (400,{'error':{'code':10,'error_subcode':2534022,'message':'outside window'}}) if reply['fail'] else (200,{'message_id':'mid.out1'})
            return 200,{'username':'gogaek_kim'}
        old=instagram._call;instagram._call=call
        try:
            # 메타의 콜백 주소 확인
            self.assertEqual(b.get('/biz/hook/instagram?hub.mode=subscribe&hub.verify_token=verify-1&hub.challenge=ch42').get_data(as_text=True),'ch42')
            self.assertEqual(b.get('/biz/hook/instagram?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=x').status_code,403)
            r=self.post(b,'/biz/connect/instagram',{'act':'connect'},'/biz/connect/instagram')
            self.assertTrue(r.headers['Location'].startswith('https://www.instagram.com/oauth/authorize'))
            st=up.parse_qs(up.urlparse(r.headers['Location']).query)['state'][0]
            b.get('/biz/connect/instagram/callback?code=abc%23_&state='+up.quote(st))
            with self.core.conn() as db:
                lk=instagram.link(db,cid);self.assertEqual((lk['ig_id'],lk['username'],lk['status']),('9001','inssa_shop','ok'));self.assertNotIn('long-tok',lk['creds'])
            self.assertIn('@inssa_shop',b.get('/biz/connect').get_data(as_text=True))
            def hook(msgs,sig=None):
                raw=_j.dumps({'object':'instagram','entry':[{'id':'9001','time':1,'messaging':msgs}]}).encode()
                sig=sig or 'sha256='+_h.new(b'sec-ig-1',raw,hashlib.sha256).hexdigest()
                return self.client().post('/biz/hook/instagram',data=raw,headers={'X-Hub-Signature-256':sig,'Content-Type':'application/json'})
            m=lambda mid,text,frm='555',**k:{'sender':{'id':frm},'recipient':{'id':'9001'},'timestamp':1,'message':dict(mid=mid,text=text,**k)}
            self.assertEqual(hook([m('a1','교환 되나요? 사이즈가 커요')],sig='sha256=00').status_code,403)
            self.assertEqual(hook([m('a1','교환 되나요? 사이즈가 커요')]).status_code,200)
            hook([m('a1','교환 되나요? 사이즈가 커요')])  # 같은 메시지 두 번
            hook([m('a2','주문번호는 1234예요'),m('e1','우리 답장',frm='9001',is_echo=True)])
            with self.core.conn() as db:
                rows=db.execute("SELECT * FROM cases WHERE company_id=? AND channel='인스타그램 DM'",(cid,)).fetchall()
                self.assertEqual(len(rows),1);c=rows[0];self.assertEqual(c['name'],'gogaek_kim')
                self.assertEqual([e[0] for e in db.execute("SELECT text FROM events WHERE case_id=? AND kind='me'",(c['id'],))],['주문번호는 1234예요'])
            self.assertIn('누르면 고객에게 인스타그램 DM으로 바로 가요',b.get(f'/biz/case/{c["id"]}').get_data(as_text=True))  # '답변하기'가 바로 DM으로 보낸다
            self.assertFalse([x for x in calls if x[1].endswith('/me/messages')])  # 누르기 전에는 안 나간다
            self.post(b,f'/biz/case/{c["id"]}',{'act':'reply','msg':'네, 교환 가능해요. 반품 신청해 주세요.'},f'/biz/case/{c["id"]}')
            self.assertEqual(len([x for x in calls if x[1].endswith('/me/messages')]),1)
            sent=[x for x in calls if x[1].endswith('/me/messages')][-1]
            self.assertEqual(sent[3],{'recipient':{'id':'555'},'message':{'text':'네, 교환 가능해요. 반품 신청해 주세요.'}});self.assertEqual(sent[4],'long-tok')
            reply['fail']=True
            self.post(b,f'/biz/case/{c["id"]}',{'act':'post_shop'},f'/biz/case/{c["id"]}')
            with self.core.conn() as db:
                last=db.execute("SELECT text FROM events WHERE case_id=? AND kind='sys' ORDER BY id DESC",(c['id'],)).fetchone()[0]
            self.assertIn('24시간',last)
            # 앱: 같은 '답변하기'가 DM으로 바로 가고, 고객이 더 보내면 휴대폰 알림, 대화 끝내기도 된다
            a=self.client();tok=a.post('/biz/api/v1/login',json={'login_id':'ig-co@example.com','password':'longpassword1'}).get_json()['token'];auth={'Authorization':'Bearer '+tok}
            self.assertTrue(a.post('/biz/api/v1/push',json={'push_token':'ExponentPushToken[ig-1]'},headers=auth).get_json()['ok'])
            pushed=[];old_push=self.core.expo_push;self.core.expo_push=lambda toks,title,body,data,table:pushed.append((toks,title,body,data))
            try:
                self.core._msg_push.clear();hook([m('a4','언제 와요?')])
                self.assertEqual(pushed[-1][0],['ExponentPushToken[ig-1]']);self.assertTrue(pushed[-1][1].startswith('고객 메시지'));self.assertEqual(pushed[-1][3],{'case_id':c['id']})
                hook([m('a5','빨리요')]);self.assertEqual(len(pushed),1)  # 같은 요청은 1분에 한 번만
            finally:self.core.expo_push=old_push
            d=a.get(f'/biz/api/v1/cases/{c["id"]}',headers=auth).get_json()
            self.assertEqual((d['channel'],d['send_via'],d['can']['close_chat']),('인스타그램 DM','누르면 고객에게 인스타그램 DM으로 바로 가요',True))
            d=a.post(f'/biz/api/v1/cases/{c["id"]}',json={'act':'reply','msg':'오늘 보내요'},headers=auth).get_json()
            self.assertIn('24시간',d['warn']);self.assertEqual(d['message'],'')  # 못 보내면 앱에 빨갛게 알린다
            reply['fail']=None;n_sent=len([x for x in calls if x[1].endswith('/me/messages')])
            d=a.post(f'/biz/api/v1/cases/{c["id"]}',json={'act':'reply','msg':'오늘 보내요'},headers=auth).get_json()
            self.assertEqual(d['message'],'인스타그램 DM으로 답변을 보냈어요');self.assertEqual(len([x for x in calls if x[1].endswith('/me/messages')]),n_sent+1)
            d=a.post(f'/biz/api/v1/cases/{c["id"]}',json={'act':'close_chat'},headers=auth).get_json()
            self.assertEqual(d['status'],'closed');self.assertFalse(d['can']['close_chat'])
            # 끝낸 요청은 다시 열 수 있다 (앱·웹)
            self.assertTrue(d['can']['reopen'])
            d=a.post(f'/biz/api/v1/cases/{c["id"]}',json={'act':'reopen'},headers=auth).get_json()
            self.assertEqual(d['status'],'answered');self.assertTrue(d['can']['close_chat']);self.assertFalse(d['can']['reopen'])
            self.post(b,f'/biz/case/{c["id"]}',{'act':'close_chat'},f'/biz/case/{c["id"]}')
            self.assertIn('다시 열기',b.get(f'/biz/case/{c["id"]}').get_data(as_text=True))
            self.post(b,f'/biz/case/{c["id"]}',{'act':'reopen'},f'/biz/case/{c["id"]}')
            with self.core.conn() as db:self.assertEqual(db.execute('SELECT status FROM cases WHERE id=?',(c['id'],)).fetchone()[0],'answered')
            # 끝낸 뒤 같은 고객이 또 DM하면 새 요청이 생기고, 새 요청에서도 답변하기가 DM으로 간다 (예전엔 답장 상대가 저장되지 않았다)
            self.post(b,f'/biz/case/{c["id"]}',{'act':'close_chat'},f'/biz/case/{c["id"]}')
            hook([m('b1','반품하고 싶어요')])
            with self.core.conn() as db:
                rows=db.execute("SELECT * FROM cases WHERE company_id=? AND channel='인스타그램 DM' ORDER BY id",(cid,)).fetchall()
                self.assertEqual(len(rows),2);c2=rows[1]
            self.assertIn('누르면 고객에게 인스타그램 DM으로 바로 가요',b.get(f'/biz/case/{c2["id"]}').get_data(as_text=True))
            self.post(b,f'/biz/case/{c2["id"]}',{'act':'reply','msg':'반품 접수해 드릴게요.'},f'/biz/case/{c2["id"]}')
            sent=[x for x in calls if x[1].endswith('/me/messages')][-1];self.assertEqual(sent[3]['recipient'],{'id':'555'})
            hook([m('b2','감사해요')])  # 새 요청에 이어 붙는다
            with self.core.conn() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM cases WHERE company_id=? AND channel='인스타그램 DM'",(cid,)).fetchone()[0],2)
                self.assertEqual([e[0] for e in db.execute("SELECT text FROM events WHERE case_id=? AND kind='me'",(c2['id'],))],['감사해요'])
            self.post(b,f'/biz/case/{c["id"]}',{'act':'reopen'},f'/biz/case/{c["id"]}')
            n_sent=len([x for x in calls if x[1].endswith('/me/messages')])
            self.post(b,f'/biz/case/{c["id"]}',{'act':'post_shop'},f'/biz/case/{c["id"]}')  # 예전 요청도 여전히 같은 고객에게 간다
            self.assertEqual(len([x for x in calls if x[1].endswith('/me/messages')]),n_sent+1)
            # 답장 상대가 없는 인스타 요청(예전 버그로 생긴 것)에 답해도 오류 없이 기록만 남는다
            with self.core.conn() as db:
                db.execute("DELETE FROM shop_seen WHERE case_id=?",(c2['id'],))
            r=self.post(b,f'/biz/case/{c2["id"]}',{'act':'reply','msg':'기록용 답변이에요'},f'/biz/case/{c2["id"]}')
            self.assertLess(r.status_code,500)
            # 앱 답변 템플릿: 만들면 요청 화면에 고객 이름이 채워져 나오고, 골라 보내면 쓴 횟수가 오른다
            self.assertEqual(a.post('/biz/api/v1/macros',json={'name':'','body':''},headers=auth).status_code,400)
            ms=a.post('/biz/api/v1/macros',json={'name':'배송 안내','body':'{고객명}님, 오늘 보내요','tags':'배송'},headers=auth).get_json();mid=ms['macros'][0]['id']
            self.assertIn('{고객명}',ms['vars'])
            d=a.get(f'/biz/api/v1/cases/{c["id"]}',headers=auth).get_json()
            self.assertEqual([x['id'] for x in d['macros']],[mid]);self.assertNotIn('{고객명}',d['macros'][0]['body'])
            a.post(f'/biz/api/v1/cases/{c["id"]}',json={'act':'reply','msg':d['macros'][0]['body'],'macro':str(mid)},headers=auth)
            self.assertEqual(a.get('/biz/api/v1/macros',headers=auth).get_json()['macros'][0]['used'],1)
            self.assertEqual(a.post('/biz/api/v1/macros',json={'act':'delete','id':mid},headers=auth).get_json()['macros'],[])
            # 앱 교환·반품: 웹과 같은 네 단계, 홈은 오늘 들어온 요청 수와 처리 방법을 준다
            r=a.get('/biz/api/v1/returns',headers=auth).get_json()
            self.assertEqual([x['key'] for x in r['stages']],['new','back','next','done'])
            h=a.get('/biz/api/v1/home',headers=auth).get_json();self.assertIn('today',h['counts']);self.assertTrue(h['hello']);self.assertTrue(h['brief'])
            self.assertIn('plan_title',a.get('/biz/api/v1/cases?f=all',headers=auth).get_json()['cases'][0])
            self.post(b,'/biz/connect/instagram',{'act':'delete'},'/biz/connect/instagram')
            with self.core.conn() as db:self.assertIsNone(instagram.link(db,cid))
            self.assertEqual(hook([m('a3','또 문의')]).status_code,200)  # 끊긴 계정의 DM은 받지 않는다
            with self.core.conn() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE case_id=? AND text='또 문의'",(c['id'],)).fetchone()[0],0)
        finally:
            instagram._call=old
            for k,v in old_env.items():
                if v is None:os.environ.pop(k,None)
                else:os.environ[k]=v

    def test_data_deletion_page(self):
        """메타 앱 설정에 넣는 데이터 삭제 안내 페이지가 열리고, 연결 끊기와 요청 방법이 적혀 있다."""
        r=self.client().get('/data-deletion');page=r.get_data(as_text=True)
        self.assertEqual(r.status_code,200);self.assertIn('연결 끊기',page);self.assertIn('Data deletion',page);self.assertIn('id="account"',page);self.assertIn('회원 탈퇴',page)  # 구글 플레이 계정 삭제 안내 주소

    def test_chat_law_grounding(self):
        """상담창: 법률 질문이면 찾은 법령 원문을 '[관련 법령 원문]'으로 주고 인터넷 검색을 끈다. 일반 질문에는 조문을 넣지 않는다."""
        b,o,cid=self.signup_and_approve('법령마켓','lawshop@example.com')
        me=self.client();page=me.get(f'/to/{cid}').get_data(as_text=True);ctok=re.search(r'data-csrf="([^"]+)"',page).group(1)
        seen=[]
        def fake(url,headers,body,timeout):
            seen.append((url,body))
            content='{"category": "반품·환불", "answer": "받으신 날부터 7일 안이면 반품하실 수 있어요.", "handoff": false, "summary": ""}'
            if url.endswith('/responses'):return 200,{'output':[{'type':'message','content':[{'type':'output_text','text':content}]}]}
            return 200,{'choices':[{'message':{'content':content}}]}
        aim=sys.modules['ai']
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(aim,'post',fake):
            j=me.post(f'/chat/{cid}',data={'csrf':ctok,'text':'받은 지 5일 됐는데 단순 변심으로 환불 되나요?'}).get_json()
        self.assertEqual(j['answer'],'받으신 날부터 7일 안이면 반품하실 수 있어요.')
        url,body=seen[-1]
        self.assertTrue(url.endswith('/chat/completions'))  # 검색(Responses API) 없이
        self.assertNotIn('tools',body)
        system=body['messages'][0]['content']
        self.assertIn('[관련 법령 원문]',system);self.assertIn('[회사 정보]',system)
        self.assertIn('전자상거래법 제17조 (청약철회등)',system)
        self.assertIn('7일',system.split('[관련 법령 원문]')[-1])
        self.assertLess(system.index('[회사 정보]'),system.index('[관련 법령 원문]'))
        # 법과 상관없는 일반 질문은 조문을 넣지 않는다 (검색은 AI가 확신이 없다고 할 때만)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(aim,'post',fake):
            me.post(f'/chat/{cid}',data={'csrf':ctok,'text':'비타민C 세럼은 아침에 써도 돼요?'})
        url,body=seen[-1]
        self.assertNotIn('[관련 법령 원문]',body.get('instructions') or body['messages'][0]['content'])


class LawCorpusTest(unittest.TestCase):
    """법령 원문 모음(law_corpus.json)과 찾기(law_corpus.py), 원문 나누기(law_corpus_build.py)."""
    @classmethod
    def setUpClass(cls):
        def load(name):
            spec=importlib.util.spec_from_file_location('t_'+name,ROOT/'platform_app'/(name+'.py'))
            m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
        cls.lc=load('law_corpus');cls.build=load('law_corpus_build')

    def test_corpus_articles(self):
        data=json.loads((ROOT/'platform_app'/'law_corpus.json').read_text(encoding='utf-8'))
        self.assertEqual(set(data),{'cosmetics','terms','adlabel','civil','ecom_dec','foodlabel','food','basic','kca','ecom','easylaw'})
        ecom=data['ecom'];self.assertEqual((ecom['no'],ecom['effective'],ecom['kind']),('21312','2026-07-21','법률'))
        self.assertGreater(len(data['civil']['articles']),1000);self.assertEqual(len(data['kca']['articles']),4)
        # 공식 원문 미러에서 뽑은 law_texts.json의 제17조와 글자가 같다 (띄어쓰기·항·호 줄바꿈만 다를 수 있음)
        texts=json.loads((ROOT/'platform_app'/'law_texts.json').read_text(encoding='utf-8'))
        for key,art in (('ecom','제17조'),('ecom','제21조'),('basic','제16조')):
            a=texts[key]['articles'][art]
            flat=''.join(p['n']+p['text']+''.join(i['n']+'.'+i['text']+''.join(s['n']+'.'+s['text'] for s in i.get('subs',[])) for i in p['items']) for p in a['paras'])
            got=data[key]['articles'][art]
            self.assertEqual(got['title'],a['title'])
            self.assertEqual(re.sub(r'\s','',got['text']),re.sub(r'\s','',flat),art)
        t17=data['ecom']['articles']['제17조']['text']
        self.assertIn('\n③ 소비자는 제1항 및 제2항에도 불구하고 재화등의 내용이 표시ㆍ광고의 내용과 다르거나',t17)
        self.assertIn('\n  1. 제13조제2항에 따른 계약내용에 관한 서면을 받은 날부터 7일.',t17)
        for law in data.values():  # 쪽 머리글·연혁 표시는 남지 않는다
            for a in law['articles'].values():
                self.assertNotIn('국가법령정보센터',a['text']);self.assertNotRegex(a['text'],r'<(개정|신설)')
        self.assertIn('사용기한 또는 개봉 후 사용기간',data['cosmetics']['articles']['제10조']['text'])

    def test_build_parser(self):
        raw=('법제처 1 국가법령정보센터\n시험법\n \n시험법\n[시행 2026. 1. 2.] [법률 제12345호, 2025. 7. 1., 일부개정]\n시험부 (시험과) 044-000-0000\n'
             ' 제1장 총칙\n제1조(목적) 이 법은 소비자의 권익을 보호하고 시장의 신뢰도를 높여 국민경제의 건전한 발전에 이바지함을 목적으로 한\n다. <개정 2020. 1. 1.>\n'
             '제2조(청약철회) ① 소비자는 다음 각 호의 기간 이내에 청약철회를 할 수 있다. <개정 2021. 3.\n4.>\n1. 서면을 받은 날부터 7일\n'
             '2. 공급받은 날부터 7일. 다만, 다음 각 목의 경우는 제외한다.\n가. 소비자가 재화를\n\n법제처 2 국가법령정보센터\n시험법\n훼손한 경우\n'
             '② 사업자는 소비자에게 위약금을 청구할 수 없다.\n[본조신설 2012. 2. 17.]\n제3조 삭제 <2020. 1. 1.>\n \n부칙 <제12345호,2025. 7. 1.>\n제1조(시행일) 이 법은 공포한 날부터 시행한다.\n')
        lines=raw.splitlines()
        (name,_,block),=self.build.split_laws(lines)
        arts=self.build.parse_law(name,block,self.build.Joiner(lines))
        self.assertEqual(list(arts),['제1조','제2조','제3조'])  # 부칙의 제1조는 넣지 않는다
        self.assertEqual(arts['제1조'],{'title':'목적','text':'이 법은 소비자의 권익을 보호하고 시장의 신뢰도를 높여 국민경제의 건전한 발전에 이바지함을 목적으로 한다.'})
        self.assertEqual(arts['제2조']['text'],'① 소비자는 다음 각 호의 기간 이내에 청약철회를 할 수 있다.\n  1. 서면을 받은 날부터 7일\n'
                         '  2. 공급받은 날부터 7일. 다만, 다음 각 목의 경우는 제외한다.\n    가. 소비자가 재화를 훼손한 경우\n② 사업자는 소비자에게 위약금을 청구할 수 없다.')
        self.assertEqual(self.build.meta(name,block),('법률','12345','2026-01-02','2025-07-01'))

    def test_search(self):
        lc=self.lc
        hits=lc.search('환불 7일 청약철회')
        self.assertIn('ecom:제17조',[h['ref'] for h in hits[:2]])
        h=[x for x in hits if x['ref']=='ecom:제17조'][0]
        self.assertEqual(h['label'],'전자상거래법 제17조 (청약철회등)');self.assertIn('7일',h['text'])
        self.assertEqual(lc.label('ecom:제17조'),'전자상거래법 제17조 (청약철회등)');self.assertIn('청약철회등을 할 수 있다',lc.text('ecom:제17조'))
        self.assertTrue(lc.source('ecom:제17조').startswith('https://www.law.go.kr/법령/'))
        hits=lc.search('화장품 사용기한 표시')
        self.assertTrue(all(h['ref'].startswith('cosmetics:') for h in hits[:3]));self.assertEqual(hits[0]['ref'],'cosmetics:제10조')
        self.assertEqual([h['ref'].split(':')[0] for h in lc.search('사용기한 표시',laws=['food'])][:1],['food'])
        # 법률 질문인지: 조문이 충분히 맞을 때만
        self.assertTrue(lc.is_legal(lc.search('청약철회 기간이 며칠이에요?'),'청약철회 기간이 며칠이에요?'))
        for q in ('선크림 있어요?','비타민C 세럼은 아침에 써도 돼요?','사이즈 추천해 주세요'):
            self.assertFalse(lc.is_legal(lc.search(q),q),q);self.assertEqual(lc.grounding_block(q),'',q)
        block=lc.grounding_block('받은 지 5일 됐는데 단순 변심으로 환불 되나요?')
        self.assertIn('전자상거래법 제17조 (청약철회등)',block)
        block=lc.grounding_block('환불 7일 청약철회',ids=True);self.assertIn('[corpus:ecom:제17조] 전자상거래법 제17조',block)


if __name__=='__main__':unittest.main()
