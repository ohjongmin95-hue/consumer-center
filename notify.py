"""제보자에게 진행 상황 알림 보내기: 카카오 알림톡(솔라피)과 이메일(SMTP).

서버 설정(/etc/soboru.env)에 값이 있을 때만 켜지고, 없으면 조용히 건너뜀.
보내는 일은 뒤에서(스레드) 처리해서 화면이 느려지지 않게 하고, 결과는 notifications 표에 남김.
카카오 알림톡 문구는 카카오 심사를 받은 템플릿과 글자 하나까지 같아야 함 -> docs/notifications.md
"""
import datetime, hashlib, hmac, json, os, secrets, smtplib, threading, urllib.error, urllib.request
from email.message import EmailMessage
from email.utils import formataddr

ASYNC = True  # 테스트에서는 False로 바꿔 바로 실행
EVENTS = {'received': '제보 접수', 'status': '진행 단계 변경', 'message': '센터 답변'}

# 이메일 본문. 카카오 템플릿과 같은 내용 + 조회 주소
EMAIL_TEXT = {
    'received': ('[소비자제보센터] 제보가 접수됐습니다',
                 '{name}님, 제보가 접수됐습니다.\n\n■ 접수번호: {receipt}\n■ 제목: {subject}\n\n'
                 "진행 상황은 '내 제보 조회'에서 휴대폰 번호와 조회 비밀번호로 확인할 수 있습니다.\n{link}"),
    'status': ('[소비자제보센터] 제보 진행 상황이 바뀌었습니다',
               '{name}님의 제보 진행 단계가 바뀌었습니다.\n\n■ 접수번호: {receipt}\n■ 제목: {subject}\n■ 현재 단계: {status}\n\n'
               "자세한 내용은 '내 제보 조회'에서 확인해 주세요.\n{link}"),
    'message': ('[소비자제보센터] 제보에 센터 답변이 등록됐습니다',
                '{name}님의 제보에 센터 답변이 등록됐습니다.\n\n■ 접수번호: {receipt}\n■ 제목: {subject}\n\n'
                "답변 내용은 '내 제보 조회'에서 확인해 주세요.\n{link}"),
}
KAKAO_TEMPLATE_ENV = {'received': 'KAKAO_TPL_RECEIVED', 'status': 'KAKAO_TPL_STATUS', 'message': 'KAKAO_TPL_MESSAGE'}


def env(key):
    return os.getenv(key, '').strip()


def email_ready():
    return bool(env('SMTP_HOST') and env('SMTP_USER') and env('SMTP_PASSWORD'))


def kakao_ready(event=None):
    base = env('SOLAPI_API_KEY') and env('SOLAPI_API_SECRET') and env('SOLAPI_PFID')
    return bool(base and (event is None or env(KAKAO_TEMPLATE_ENV[event])))


def digits(phone):
    return ''.join(c for c in phone or '' if c.isdigit())


def mask(target):
    if '@' in target:
        user, _, host = target.partition('@')
        return user[:2] + '***@' + host
    return target[:3] + '****' + target[-4:] if len(target) >= 8 else '****'


def short(text, limit=30):
    text = ' '.join((text or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def send_email(to, subject, body):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = formataddr((env('MAIL_FROM_NAME') or '소비자제보센터', env('MAIL_FROM') or env('SMTP_USER')))
    msg['To'] = to
    msg.set_content(body)
    port = int(env('SMTP_PORT') or 465)
    if port == 465:
        server = smtplib.SMTP_SSL(env('SMTP_HOST'), port, timeout=15)
    else:
        server = smtplib.SMTP(env('SMTP_HOST'), port, timeout=15)
        server.starttls()
    with server:
        server.login(env('SMTP_USER'), env('SMTP_PASSWORD'))
        server.send_message(msg)


def solapi_auth():
    # 솔라피 API 인증: HMAC-SHA256(date + salt, API secret)
    date = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    salt = secrets.token_hex(16)
    sig = hmac.new(env('SOLAPI_API_SECRET').encode(), (date + salt).encode(), hashlib.sha256).hexdigest()
    return f"HMAC-SHA256 apiKey={env('SOLAPI_API_KEY')}, date={date}, salt={salt}, signature={sig}"


def http_post(url, payload, headers):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', **headers}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode() or '{}')
    except urllib.error.HTTPError as e:  # 솔라피는 거절 이유를 본문에 담아 줌
        raise RuntimeError(f'{e.code} {e.read().decode(errors="replace")[:200]}') from None


def send_kakao(phone, event, values):
    message = {'to': phone, 'kakaoOptions': {
        'pfId': env('SOLAPI_PFID'), 'templateId': env(KAKAO_TEMPLATE_ENV[event]), 'disableSms': True,
        'variables': {'#{이름}': values['name'], '#{접수번호}': values['receipt'], '#{제목}': values['subject'], '#{단계}': values['status']}}}
    if env('SOLAPI_SENDER'):
        message['from'] = digits(env('SOLAPI_SENDER'))
    result = http_post('https://api.solapi.com/messages/v4/send', {'message': message}, {'Authorization': solapi_auth()})
    status = str(result.get('statusCode', ''))
    if status and status not in ('2000', '3000', '4000'):
        raise RuntimeError(f"{status} {result.get('statusMessage', '')}".strip())


def plan(case, event, link):
    """보낼 알림 목록을 만듦: [(채널, 받는 곳, 보내는 함수)]. 요청 안에서 부름(DB·주소 정보가 필요)."""
    values = {'name': short(case['reporter_name'] or '제보자', 20), 'receipt': case['receipt'], 'subject': short(case['subject']),
              'status': case['status'], 'link': link}
    jobs = []
    phone = digits(case['phone'])
    if phone.startswith('01') and kakao_ready(event):
        jobs.append(('kakao', phone, lambda: send_kakao(phone, event, values)))
    email = (case['contact'] or '').strip()
    if email and email_ready():
        subject, body = EMAIL_TEXT[event]
        jobs.append(('email', email, lambda: send_email(email, subject, body.format(**values))))
    return jobs


def dispatch(conn, case, event, link):
    """알림을 뒤에서 보내고 결과를 기록. conn은 DB 연결을 여는 함수."""
    jobs = plan(case, event, link)
    if not jobs:
        return 0

    def run():
        for channel, target, send in jobs:
            try:
                send()
                status, detail = 'sent', ''
            except Exception as e:  # 발송 실패는 기록만 하고 제보 처리는 계속
                status, detail = 'failed', str(e)[:300]
            with conn() as db:
                db.execute('INSERT INTO notifications(case_id,channel,event,target,status,detail,created) VALUES(?,?,?,?,?,?,?)',
                           (case['id'], channel, event, mask(target), status, detail, datetime.datetime.now().isoformat(timespec='seconds')))

    if ASYNC:
        threading.Thread(target=run, daemon=True).start()
    else:
        run()
    return len(jobs)
