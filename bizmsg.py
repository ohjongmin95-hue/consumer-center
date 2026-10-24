"""카카오 알림톡·문자를 보내는 업체(솔라피·알리고)를 한곳에 묶음. 소보루(notify.py)와 소보루CS(platform_app/core.py)가 같이 씀.

MSG_VENDOR=aligo 이면 알리고, 아니면 솔라피로 보냄. 서버 설정은 deploy/set-kakao.sh가 넣음.
알림톡 템플릿은 업체마다 따로 카카오 검수를 받으므로 템플릿 코드도 업체별로 따로 둠:
솔라피는 KAKAO_TPL_RECEIVED 같은 이름 그대로, 알리고는 앞에 ALIGO_를 붙인 이름(ALIGO_KAKAO_TPL_RECEIVED).
그래서 두 업체 값을 다 넣어 두면 MSG_VENDOR만 바꿔서 업체를 옮길 수 있음.

알리고는 템플릿 문구 전체를 같이 보내야 해서, 처음 보낼 때 알리고에서 승인된 템플릿 문구·버튼을 받아 와 변수만 채움.
"""
import datetime, hashlib, hmac, json, os, secrets, urllib.error, urllib.parse, urllib.request

NAMES = {'solapi': '솔라피', 'aligo': '알리고'}
_aligo_templates = {}  # 템플릿 코드 -> 알리고에서 받은 템플릿 (문구·강조 제목·버튼)


def env(key):
    return os.getenv(key, '').strip()


def digits(phone):
    return ''.join(c for c in phone or '' if c.isdigit())


def vendor():
    return 'aligo' if env('MSG_VENDOR').lower() == 'aligo' else 'solapi'


def template(name):
    """지금 업체의 템플릿 코드. name은 솔라피 기준 설정 이름(KAKAO_TPL_RECEIVED 등)."""
    return env('ALIGO_' + name) if vendor() == 'aligo' else env(name)


def sender():
    """문자 발신번호 (업체에 등록한 번호). 알리고는 알림톡에도 꼭 있어야 함."""
    return digits(env('ALIGO_SENDER') if vendor() == 'aligo' else env('SOLAPI_SENDER'))


def keys_ready():
    if vendor() == 'aligo':
        return bool(env('ALIGO_API_KEY') and env('ALIGO_USER_ID'))
    return bool(env('SOLAPI_API_KEY') and env('SOLAPI_API_SECRET'))


def kakao_ready():
    """알림톡 채널까지 연결됐는지 (템플릿은 따로 확인)."""
    if vendor() == 'aligo':
        return bool(keys_ready() and env('ALIGO_SENDER_KEY') and sender())
    return bool(keys_ready() and env('SOLAPI_PFID'))


def http_post(url, payload, headers=None, form=False):
    if form:
        data, headers = urllib.parse.urlencode(payload).encode(), {'Content-Type': 'application/x-www-form-urlencoded', **(headers or {})}
    else:
        data, headers = json.dumps(payload).encode(), {'Content-Type': 'application/json', **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode() or '{}')
    except urllib.error.HTTPError as e:  # 업체가 거절 이유를 본문에 담아 줌
        raise RuntimeError(f'{e.code} {e.read().decode(errors="replace")[:200]}') from None


# ---------- 솔라피 ----------
def solapi_auth():
    # 솔라피 API 인증: HMAC-SHA256(date + salt, API secret)
    date = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    salt = secrets.token_hex(16)
    sig = hmac.new(env('SOLAPI_API_SECRET').encode(), (date + salt).encode(), hashlib.sha256).hexdigest()
    return f"HMAC-SHA256 apiKey={env('SOLAPI_API_KEY')}, date={date}, salt={salt}, signature={sig}"


def solapi_send(message):
    result = http_post('https://api.solapi.com/messages/v4/send', {'message': message}, {'Authorization': solapi_auth()})
    status = str(result.get('statusCode', ''))
    if status and status not in ('2000', '3000', '4000'):
        raise RuntimeError(f"{status} {result.get('statusMessage', '')}".strip())


# ---------- 알리고 ----------
def aligo_auth():
    return {'apikey': env('ALIGO_API_KEY'), 'userid': env('ALIGO_USER_ID'), 'senderkey': env('ALIGO_SENDER_KEY')}


def aligo_template(code):
    if code not in _aligo_templates:
        result = http_post('https://kakaoapi.aligo.in/akv10/template/list/', dict(aligo_auth(), tpl_code=code), form=True)
        found = [t for t in result.get('list') or [] if t.get('templtCode') == code]
        if str(result.get('code')) != '0' or not found:
            raise RuntimeError(f"알리고 템플릿 {code}: {result.get('message') or '없음'}"[:200])
        _aligo_templates[code] = found[0]
    return _aligo_templates[code]


def fill(text, variables):
    for key, value in variables.items():
        text = text.replace(key, str(value))
    return text


def aligo_check(result, ok_key, ok_value):
    if str(result.get(ok_key)) != ok_value:
        raise RuntimeError(f"{result.get(ok_key)} {result.get('message', '')}".strip()[:200])


# ---------- 보내기 ----------
def alimtalk(phone, code, variables, fallback=False):
    """알림톡 1건. fallback이면 알림톡이 안 될 때 발신번호로 같은 내용을 문자로 대신 보냄."""
    phone = digits(phone)
    if vendor() == 'aligo':
        tpl = aligo_template(code)
        text = fill(tpl.get('templtContent', ''), variables)
        data = dict(aligo_auth(), tpl_code=code, sender=sender(), receiver_1=phone, subject_1=tpl.get('templtName') or code, message_1=text)
        if tpl.get('templtTitle'):  # 강조표기형 제목
            data['emtitle_1'] = fill(tpl['templtTitle'], variables)
        buttons = [{k: fill(b.get(k) or '', variables) for k in ('name', 'linkType', 'linkTypeName', 'linkMo', 'linkPc', 'linkIos', 'linkAnd') if b.get(k)}
                   for b in tpl.get('buttons') or []]
        if buttons:
            data['button_1'] = json.dumps({'button': buttons}, ensure_ascii=False)
        if fallback:
            data.update(failover='Y', fsubject_1=tpl.get('templtName') or code, fmessage_1=text)
        if env('ALIGO_TEST') == 'Y':
            data['testMode'] = 'Y'
        aligo_check(http_post('https://kakaoapi.aligo.in/akv10/alimtalk/send/', data, form=True), 'code', '0')
        return
    message = {'to': phone, 'kakaoOptions': {'pfId': env('SOLAPI_PFID'), 'templateId': code, 'disableSms': not (fallback and sender()), 'variables': variables}}
    if sender():  # 대신 보내는 문자는 솔라피가 템플릿 내용 그대로 씀
        message['from'] = sender()
    solapi_send(message)


def sms(phone, text):
    """문자 1건. 길이에 따라 단문/장문은 업체가 알아서 고름. 발신번호는 업체에 등록된 번호여야 함."""
    if vendor() == 'aligo':
        data = {'key': env('ALIGO_API_KEY'), 'user_id': env('ALIGO_USER_ID'), 'sender': sender(), 'receiver': digits(phone), 'msg': text}
        if env('ALIGO_TEST') == 'Y':
            data['testmode_yn'] = 'Y'
        aligo_check(http_post('https://apis.aligo.in/send/', data, form=True), 'result_code', '1')
        return
    solapi_send({'to': digits(phone), 'from': sender(), 'text': text})
