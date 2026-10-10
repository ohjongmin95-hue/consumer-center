"""SOBORU 플랫폼 실행 진입점 (gunicorn hanq:app).

주소(도메인)로 서비스를 나눈다.
  CONSUMER_HOST (예: hanq.example.kr)    → 한큐 민원 (consumer.py)
  BUSINESS_HOST (예: business.example.kr) → SOBORU Business + /ops (business.py)
주소 설정이 없으면(개발·테스트) /biz 아래를 기업용으로 쓴다.
"""
import os, datetime
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.middleware.proxy_fix import ProxyFix
import core, consumer, business

for a,cookie in ((consumer.app,'hanq_session'),(business.app,'biz_session')):
    a.secret_key=core.SECRET
    a.config.update(SESSION_COOKIE_NAME=cookie,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.getenv('HTTPS_ONLY')=='1',MAX_CONTENT_LENGTH=16*1024*1024,PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=14))
    @a.after_request
    def headers(r):
        r.headers.setdefault('X-Content-Type-Options','nosniff');r.headers.setdefault('X-Frame-Options','DENY')
        r.headers.setdefault('Referrer-Policy','same-origin')
        if r.mimetype=='text/html':r.headers['Cache-Control']='no-store'
        return r

class ByHost:
    def __init__(self,consumer_app,business_app):self.c=consumer_app;self.b=business_app
    def __call__(self,environ,start):
        host=(environ.get('HTTP_HOST') or '').split(':')[0].lower()
        return (self.b if host==core.BUSINESS_HOST else self.c)(environ,start)

if core.BUSINESS_HOST:app=ByHost(consumer.app.wsgi_app,business.app.wsgi_app)
else:app=DispatcherMiddleware(consumer.app.wsgi_app,{'/biz':business.app.wsgi_app})
if os.getenv('TRUST_PROXY')=='1':app=ProxyFix(app,x_for=1,x_proto=1,x_host=1)
