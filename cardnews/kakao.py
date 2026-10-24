"""카카오톡 '나에게 보내기': 다 만든 카드뉴스(표지 이미지 + 캡션)를 내 카톡으로 받는다.

- 준비(한 번): developers.kakao.com에서 앱을 만들고 REST API 키를 설정에 넣는다. 카카오 로그인을 켜고
  Redirect URI에 http://127.0.0.1:5050/kakao/callback, 동의 항목에 '카카오톡 메시지 전송(talk_message)'을 켠다.
  설정 화면의 '카카오 로그인 연결'을 누르면 토큰을 받아 config.json에 둔다 (액세스 토큰은 몇 시간, 리프레시 토큰으로 자동 연장).
- 보내기: POST https://kapi.kakao.com/v2/api/talk/memo/default/send (Bearer 사용자 토큰, form template_object=JSON).
  표지 이미지는 메시지 이미지 업로드 API로 먼저 올려 카카오 주소를 받는다. 올리기에 실패하면 글 메시지로만 보낸다.
- 받는 사람은 '나'뿐이다 (친구·채널 발송은 하지 않음).
"""
import json, secrets, time, urllib.error, urllib.parse, urllib.request

AUTH = 'https://kauth.kakao.com'
API = 'https://kapi.kakao.com'


def redirect_uri(port): return f'http://127.0.0.1:{port}/kakao/callback'


def ready(cfg): return bool(cfg.get('kakao_key') and (cfg.get('kakao_token') or {}).get('refresh'))


def http(method, url, data=None, headers=None, body=None, timeout=20):
    """(상태 코드, JSON). 테스트에서 바꿔 끼운다."""
    if data is not None: body = urllib.parse.urlencode(data).encode(); headers = dict(headers or {}, **{'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'})
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, json.loads(r.read().decode('utf-8') or '{}')
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode('utf-8') or '{}')
        except ValueError: return e.code, {}
    except (urllib.error.URLError, OSError, ValueError): return 0, {}


def login_url(cfg, port, state):
    return AUTH + '/oauth/authorize?' + urllib.parse.urlencode({'client_id': cfg['kakao_key'], 'redirect_uri': redirect_uri(port), 'response_type': 'code',
                                                                 'scope': 'talk_message', 'state': state})


def _token(cfg, data):
    if cfg.get('kakao_secret'): data['client_secret'] = cfg['kakao_secret']
    st, res = http('POST', AUTH + '/oauth/token', data=dict(data, client_id=cfg['kakao_key']))
    if st != 200 or not res.get('access_token'):
        raise RuntimeError('카카오 로그인이 끝나지 않았어요 (' + str(res.get('error_description') or res.get('error') or st) + ')')
    old = cfg.get('kakao_token') or {}
    return {'access': res['access_token'], 'expires': int(time.time()) + int(res.get('expires_in') or 3600) - 60,
            'refresh': res.get('refresh_token') or old.get('refresh', '')}


def exchange(cfg, code, port):
    """로그인하고 돌아온 code → 토큰 dict (config에 저장할 것)"""
    return _token(cfg, {'grant_type': 'authorization_code', 'redirect_uri': redirect_uri(port), 'code': code})


def access(cfg, save):
    """쓸 수 있는 액세스 토큰. 만료됐으면 리프레시 토큰으로 새로 받고 save(token)로 저장."""
    tok = cfg.get('kakao_token') or {}
    if not tok.get('refresh'): raise RuntimeError("카카오 로그인 연결이 안 돼 있어요. '설정'에서 연결해 주세요")
    if tok.get('access') and tok.get('expires', 0) > time.time(): return tok['access']
    tok = _token(cfg, {'grant_type': 'refresh_token', 'refresh_token': tok['refresh']})
    save(tok); return tok['access']


def upload_image(cfg, png):
    """PNG 바이트 → 카카오 메시지용 이미지 주소 ('' = 실패). 메시지 이미지 업로드 API (REST API 키)"""
    b = 'cn' + secrets.token_hex(8)
    body = (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="cover.png"\r\nContent-Type: image/png\r\n\r\n').encode() + png + f'\r\n--{b}--\r\n'.encode()
    st, res = http('POST', API + '/v2/api/talk/message/image/upload', headers={'Authorization': 'KakaoAK ' + cfg['kakao_key'], 'Content-Type': f'multipart/form-data; boundary={b}'}, body=body)
    url = ((res.get('infos') or {}).get('original') or {}).get('url', '') if st == 200 else ''
    return url if url.startswith('https://') else ''


def send(cfg, save, template):
    """나에게 보내기 (기본 템플릿)"""
    st, res = http('POST', API + '/v2/api/talk/memo/default/send', data={'template_object': json.dumps(template, ensure_ascii=False)},
                   headers={'Authorization': 'Bearer ' + access(cfg, save)})
    if st != 200 or res.get('result_code', 0) != 0:
        if st == 403 or res.get('code') == -402: raise RuntimeError("카카오톡 메시지 보내기 동의가 없어요. '설정'에서 카카오 로그인을 다시 연결해 주세요")
        raise RuntimeError('카카오톡으로 보내지 못했어요 (' + str(res.get('msg') or st) + ')')


def link(url):
    u = url if (url or '').startswith(('https://', 'http://')) else 'https://www.instagram.com'
    return {'web_url': u, 'mobile_web_url': u}


def send_card(cfg, save, title, caption, url, png=None):
    """카드뉴스 한 개: 표지 이미지(올릴 수 있으면) + 제목 → 이어서 캡션 글. 돌려주는 값: 이미지를 넣었는지"""
    img = upload_image(cfg, png) if png else ''
    if img:
        send(cfg, save, {'object_type': 'feed', 'content': {'title': title[:200], 'description': '민주의 카드뉴스 제작 프로그램', 'image_url': img,
                                                            'image_width': 1080, 'image_height': 1350, 'link': link(url)},
                         'buttons': [{'title': '기사 보기', 'link': link(url)}]})
    else:
        send(cfg, save, {'object_type': 'text', 'text': ('🗞 ' + title)[:200], 'link': link(url), 'button_title': '기사 보기'})
    send(cfg, save, {'object_type': 'text', 'text': caption[:195] + ('…' if len(caption) > 195 else ''), 'link': link(url), 'button_title': '기사 보기'})
    return bool(img)


def send_note(cfg, save, text, url=''):
    """짧은 알림 글 (매일 자동 초안이 만들어졌을 때)"""
    send(cfg, save, {'object_type': 'text', 'text': text[:200], 'link': link(url), 'button_title': '열어 보기'})
