"""제보자에게 진행 상황 알림 보내기: 카카오 알림톡(솔라피·알리고, bizmsg.py)과 이메일(SMTP).
새 제보가 들어오면 운영자에게 텔레그램(TELEGRAM_BOT_TOKEN·TELEGRAM_CHAT_ID, 무료), 메일(ADMIN_ALERT_EMAIL),
카카오 알림톡(ADMIN_ALERT_PHONE·KAKAO_TPL_ADMIN, 없으면 문자)으로 알림.

서버 설정(/etc/soboru.env)에 값이 있을 때만 켜지고, 없으면 조용히 건너뜀.
보내는 일은 뒤에서(스레드) 처리해서 화면이 느려지지 않게 하고, 결과는 notifications 표에 남김.
카카오 알림톡 문구는 카카오 심사를 받은 템플릿과 글자 하나까지 같아야 함 -> docs/notifications.md
"""
import datetime, json, os, smtplib, threading, urllib.error, urllib.request
from email.message import EmailMessage
from email.utils import formataddr

import bizmsg

ASYNC = True  # 테스트에서는 False로 바꿔 바로 실행


def site_name():
    """메일·알림에 쓰는 사이트 이름. app.py가 시작할 때 관리자 설정(사이트 이름·브랜드)을 읽는 함수로 바꿔 끼움 (soboru.py)."""
    return '소비자제보센터'


def branded(text):
    """기본 문구 속 '소비자제보센터'를 지금 사이트 이름으로 바꿈."""
    name = site_name()
    return text if name == '소비자제보센터' else text.replace('소비자제보센터', name)
EVENTS = {'received': '제보 접수', 'status': '진행 단계 변경', 'message': '센터 답변', 'company': '기업 답변', 'supplement': '보완 요청', 'seen': '기업 전달 확인',
          'admin_answer': '운영자: 기업 답변', 'admin_request': '운영자: 정정·삭제·이의', 'admin_risk': '운영자: 개인정보 위험',
          'company_notice': '기업 공식 안내', 'company_new': '기업: 새 제보', 'company_opinion': '기업: 제보자 추가 의견', 'company_files': '기업: 추가 자료', 'company_nudge': '기업: 제보자 독촉'}

# 이메일 본문. 카카오 템플릿과 같은 내용 + 조회 주소
EMAIL_TEXT = {
    'received': ('[{site}] 제보가 접수됐습니다',
                 '{name}님, 제보가 접수됐습니다.\n\n■ 접수번호: {receipt}\n■ 제목: {subject}\n\n'
                 "진행 상황은 '내 제보 조회'에서 휴대폰 번호와 조회 비밀번호로 확인할 수 있습니다.\n{link}"),
    'status': ('[{site}] 제보 진행 상황이 바뀌었습니다',
               '{name}님의 제보 진행 단계가 바뀌었습니다.\n\n■ 접수번호: {receipt}\n■ 제목: {subject}\n■ 현재 단계: {status}\n\n'
               "자세한 내용은 '내 제보 조회'에서 확인해 주세요.\n{link}"),
    'message': ('[{site}] 제보에 센터 답변이 등록됐습니다',
                '{name}님의 제보에 센터 답변이 등록됐습니다.\n\n■ 접수번호: {receipt}\n■ 제목: {subject}\n\n'
                "답변 내용은 '내 제보 조회'에서 확인해 주세요.\n{link}"),
    'company': ('[{site}] 업체가 제보에 답변했습니다',
                '{name}님의 제보에 업체가 답변했습니다.\n\n■ 접수번호: {receipt}\n■ 제목: {subject}\n\n'
                "답변 내용은 '내 제보 조회'에서 확인해 주세요. 답변을 받고 해결됐는지도 알려 주세요.\n{link}"),
    'supplement': ('[{site}] 제보 내용 보완을 요청드립니다',
                   '{name}님의 제보를 확인하려면 내용이나 자료 보완이 필요합니다.\n\n■ 접수번호: {receipt}\n■ 제목: {subject}\n\n'
                   "요청 내용은 '내 제보 조회'에서 확인하고, 그 화면에서 설명이나 자료를 더해 주세요.\n{link}"),
    'seen': ('[{site}] 업체가 제보를 확인했습니다',
             '{name}님의 제보를 업체 담당자가 열어 확인했습니다.\n\n■ 접수번호: {receipt}\n■ 제목: {subject}\n\n'
             "업체가 답변하면 다시 알려 드립니다. 답변 여부와 내용은 업체가 정합니다.\n{link}"),
}
KAKAO_TEMPLATE_ENV = {'received': 'KAKAO_TPL_RECEIVED', 'status': 'KAKAO_TPL_STATUS', 'message': 'KAKAO_TPL_MESSAGE', 'company': 'KAKAO_TPL_COMPANY',
                      'supplement': 'KAKAO_TPL_SUPPLEMENT', 'seen': 'KAKAO_TPL_SEEN'}


def env(key):
    return os.getenv(key, '').strip()


def email_ready():
    return bool(env('SMTP_HOST') and env('SMTP_USER') and env('SMTP_PASSWORD'))


def kakao_ready(event=None):
    return bool(bizmsg.kakao_ready() and (event is None or bizmsg.template(KAKAO_TEMPLATE_ENV[event])))


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


def send_email(to, subject, body, html=None, headers=None, from_name=None):
    # html이 있으면 글(body)과 HTML 두 가지를 함께 보냄. headers는 List-Unsubscribe 같은 머리글 (소보루 레터)
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = formataddr((from_name or env('MAIL_FROM_NAME') or site_name(), env('MAIL_FROM') or env('SMTP_USER')))
    msg['To'] = to
    for key, value in (headers or {}).items():
        msg[key] = value
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype='html')
    port = int(env('SMTP_PORT') or 465)
    if port == 465:
        server = smtplib.SMTP_SSL(env('SMTP_HOST'), port, timeout=15)
    else:
        server = smtplib.SMTP(env('SMTP_HOST'), port, timeout=15)
        server.starttls()
    with server:
        server.login(env('SMTP_USER'), env('SMTP_PASSWORD'))
        server.send_message(msg)


def http_post(url, payload, headers):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', **headers}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode() or '{}')
    except urllib.error.HTTPError as e:  # 거절 이유가 본문에 담겨 옴
        raise RuntimeError(f'{e.code} {e.read().decode(errors="replace")[:200]}') from None


def send_kakao(phone, event, values):
    bizmsg.alimtalk(phone, bizmsg.template(KAKAO_TEMPLATE_ENV[event]),
                    {'#{이름}': values['name'], '#{접수번호}': values['receipt'], '#{제목}': values['subject'], '#{단계}': values['status']})


def send_sms(phone, text):
    # 운영자 알림 문자. 발신번호는 업체(솔라피·알리고)에 등록된 번호여야 함
    bizmsg.sms(phone, text)


def send_admin_kakao(phone, values):
    # 운영자 알림톡. 템플릿 심사가 끝나기 전이거나 실패하면 발신번호가 있을 때 같은 내용을 문자로 대신 보냄
    bizmsg.alimtalk(phone, bizmsg.template('KAKAO_TPL_ADMIN'),
                    {'#{접수번호}': values['receipt'], '#{이름}': values['name'], '#{연락처}': values['phone'], '#{업체}': values['company'], '#{제목}': values['subject']},
                    fallback=True)


def send_telegram(chat_id, text):
    # 텔레그램 봇 메시지 (무료). 봇 토큰은 @BotFather에서 받음
    result = http_post(f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/sendMessage", {'chat_id': chat_id, 'text': text, 'disable_web_page_preview': True}, {})
    if not result.get('ok'):
        raise RuntimeError(str(result.get('description', 'telegram error'))[:200])


def fmt_phone(phone):
    d = digits(phone)
    return f'{d[:3]}-{d[3:-4]}-{d[-4:]}' if len(d) in (10, 11) else (phone or '-')


def admin_targets():
    """운영자 알림 받을 곳: (이메일 목록, 휴대폰 목록, 휴대폰 채널). 쉼표로 여러 개 적을 수 있음.
    휴대폰 채널은 알림톡 템플릿(KAKAO_TPL_ADMIN)이 있으면 'kakao', 발신번호만 있으면 'sms'."""
    emails = [e.strip() for e in env('ADMIN_ALERT_EMAIL').split(',') if '@' in e] if email_ready() else []
    channel = 'kakao' if bizmsg.kakao_ready() and bizmsg.template('KAKAO_TPL_ADMIN') else 'sms' if bizmsg.keys_ready() and bizmsg.sender() else ''
    phones = [digits(p) for p in env('ADMIN_ALERT_PHONE').split(',') if digits(p).startswith('01')] if channel else []
    return emails, phones, channel


def admin_plan(case, link):
    """새 제보 운영자 알림. 제보자 이름·연락처도 함께 보내 바로 연락할 수 있게 함."""
    emails, phones, channel = admin_targets()
    name, phone = short(case['reporter_name'] or '-', 20), fmt_phone(case['phone'])
    subject = f'[{site_name()}] 새 제보: ' + short(case['subject'])
    body = (f"새 제보가 들어왔습니다.\n\n■ 접수번호: {case['receipt']}\n■ 제보자: {name} ({phone})\n■ 분야: {case['category']}\n■ 업체: {short(case['company'])}\n"
            f"■ 제목: {short(case['subject'], 60)}\n\n관리자 화면에서 확인해 주세요.\n{link}")
    text = f"[{site_name()}] 새 제보\n{name} {phone}\n{case['receipt']} · {short(case['company'], 15)}\n{short(case['subject'], 30)}"
    jobs = [('admin_email', e, lambda e=e: send_email(e, subject, body)) for e in emails]
    if env('TELEGRAM_BOT_TOKEN'):
        jobs += [('admin_telegram', c, lambda c=c: send_telegram(c, body)) for c in env('TELEGRAM_CHAT_ID').replace(' ', '').split(',') if c]
    values = {'receipt': case['receipt'], 'name': name, 'phone': phone, 'company': short(case['company'], 20), 'subject': short(case['subject'])}
    if channel == 'kakao':
        jobs += [('admin_kakao', p, lambda p=p: send_admin_kakao(p, values)) for p in phones]
    else:
        jobs += [('admin_sms', p, lambda p=p: send_sms(p, text)) for p in phones]
    return jobs


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
        subject = subject.format(site=site_name())
        jobs.append(('email', email, lambda: send_email(email, subject, body.format(**values))))
    return jobs


def dispatch(conn, case, event, link, admin_link=None):
    """알림을 뒤에서 보내고 결과를 기록. conn은 DB 연결을 여는 함수. admin_link가 있으면 운영자에게도 보냄."""
    jobs = plan(case, event, link) + (admin_plan(case, admin_link) if admin_link else [])
    return run_jobs(conn, case, event, jobs)


def admin_alert(conn, case, event, subject, body):
    """운영자에게 메일(ADMIN_ALERT_EMAIL)·텔레그램으로 알림. 기업 답변, 정정·삭제·이의 신청, 개인정보 위험 등."""
    emails = admin_targets()[0]
    jobs = [('admin_email', e, lambda e=e: send_email(e, subject, body)) for e in emails]
    if env('TELEGRAM_BOT_TOKEN'):
        jobs += [('admin_telegram', c, lambda c=c: send_telegram(c, subject + '\n' + body)) for c in env('TELEGRAM_CHAT_ID').replace(' ', '').split(',') if c]
    return run_jobs(conn, case, event, jobs)


def company_email(conn, case, event, to, subject, body):
    """기업에 메일 한 통. 보낼 수 있는지(설정·수신 거부·빈도)는 부르는 쪽에서 먼저 확인."""
    if not (to and email_ready()):
        return 0
    return run_jobs(conn, case, event, [('company_email', to, lambda: send_email(to, subject, body))])


def run_jobs(conn, case, event, jobs):
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
