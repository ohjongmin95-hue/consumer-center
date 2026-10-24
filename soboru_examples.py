"""소보루 커뮤니티 예시 글 (운영자 요청 2026-10-24): 후기·골라주세요·수다방·사장님 소식이 비어 보이지 않게 넣는 글.

진짜 이용자 글로 보이지 않게 글쓴이는 모두 '소보루 예시'이고 본문 끝에 예시 글이라고 적는다. 공감·조회·투표 수는 0에서 시작하고
영수증 인증·포인트는 없다. 소비자 제보(소비자의 소리)에는 넣지 않는다.

  python -m soboru_examples add      예시 글 넣기 (이미 있으면 건너뜀)
  python -m soboru_examples remove   예시 글 모두 지우기

배포하면 사이트가 뜰 때 auto()가 한 번만 넣는다 (운영자 요청 2026-10-24: 예시 글이 있어야 사람들이 따라 씀).
한 번 넣은 뒤에는 remove로 지워도 다시 넣지 않는다. SOBORU_EXAMPLES=0이면 넣지 않는다(시험용).
"""
import datetime, sys
from soboru_cm import guess_biz

NICK = '소보루 예시'
MARK = 'example'  # ip_hash 자리에 넣어 지울 때 찾음
NOTE = '\n\n※ 소보루가 기능을 보여 드리려고 올린 예시 글이에요.'

# 후기: 상품/장소, 분류, 대상, 제목, 본문, 별점, 추천, 좋았던 점, 아쉬운 점, 가격, 다시 살래요, 어디서 샀어요(상품) 또는 (시·도, 구)(장소), 며칠 전에 샀는지
REVIEWS = [
    ('product', '디지털·가전', '보급형 무선 이어폰', '3만 원대 무선 이어폰, 출퇴근용으론 충분해요',
     '지하철에서 쓰려고 샀어요. 노이즈 캔슬링은 없지만 귀에 잘 맞아서 바깥 소리가 꽤 줄어요. 한 번 충전하면 출퇴근 일주일은 버텨요.',
     4, 1, '가볍고 배터리가 오래가요', '통화할 때 상대가 내 목소리를 작게 들어요', 34000, 1, '쿠팡', 20),
    ('product', '뷰티', '약산성 클렌징폼', '세안 후 당김이 없는 클렌징폼',
     '건성이라 세안하고 나면 늘 얼굴이 당겼는데, 이건 헹군 뒤에도 편안해요. 거품은 조금 적은 편이에요.',
     5, 1, '세안 후에도 얼굴이 안 당겨요', '거품이 적어서 처음엔 많이 짜게 돼요', 12900, 1, '올리브영', 35),
    ('product', '식품', '냉동 닭가슴살 볶음밥', '냉동 볶음밥, 간은 좋은데 양이 아쉬워요',
     '전자레인지 3분이면 돼서 점심 대용으로 샀어요. 짜지 않아서 좋은데 한 봉지로는 배가 조금 덜 차요.',
     3, 0, '짜지 않고 데우기 쉬워요', '한 봉지 양이 적어요', 15800, 0, '컬리', 10),
    ('product', '집·생활', '접이식 빨래 건조대', '좁은 베란다에 딱 맞는 접이식 건조대',
     '원룸이라 큰 건조대를 둘 데가 없었는데, 접으면 문 뒤에 들어가요. 수건 6장까지는 거뜬해요.',
     4, 1, '접으면 얇아서 보관이 쉬워요', '이불 같은 무거운 빨래는 무리예요', 27000, 1, '오늘의집', 50),
    ('place', '맛집·카페', '동네 국숫집', '혼밥하기 좋은 동네 국숫집',
     '점심에 혼자 가도 눈치 안 보이는 곳이에요. 멸치 국수 국물이 진하고, 김밥 반 줄 세트가 있어서 좋아요.',
     5, 1, '혼자 먹기 편한 자리와 세트 메뉴', '점심 12시대엔 10분쯤 기다려요', 8000, 1, ('서울', '마포구'), 7),
    ('place', '운동', '아파트 단지 앞 필라테스', '필라테스 3개월 다녀 본 솔직한 후기',
     '그룹 수업 정원이 6명이라 선생님이 자세를 하나하나 봐 줘요. 다만 예약이 금방 차서 저녁 시간은 잡기 어려워요.',
     4, 1, '소수 정원이라 자세 교정을 꼼꼼히 해 줘요', '저녁 수업 예약이 금방 차요', 240000, 1, ('경기', '성남시'), 95),
]
# 수다방: 말머리, 제목, 본문
SUDA = [
    ('지름', '드디어 무선 청소기 샀어요', '유선 청소기 코드 꽂았다 뺐다 하는 게 귀찮아서 결국 질렀어요. 다들 무선 청소기 먼지통 얼마나 자주 비우세요?'),
    ('질문', '온라인으로 산 옷, 택 떼면 반품 안 되나요?', '입어 보려고 택을 뗐는데 사이즈가 안 맞아요. 판매자가 택 떼면 반품이 안 된다고 하는데 정말 그런가요?'),
    ('정보', '정기 구독 해지할 때 확인할 것 3가지', '1. 다음 결제일이 언제인지\n2. 해지하면 남은 기간을 쓸 수 있는지\n3. 해지 완료 문자나 메일이 왔는지\n\n해지 버튼만 누르고 끝내지 말고 완료 안내까지 꼭 확인해 두세요.'),
    ('잡담', '요즘 장 볼 때 다들 얼마 정도 쓰세요?', '둘이 사는데 일주일 장보기가 10만 원을 훌쩍 넘네요. 다들 어떻게 아끼시는지 궁금해요.'),
    ('직장', '점심값 아끼려고 도시락 싸 다닌 지 한 달', '한 달 해 보니 생각보다 많이 아껴져요. 대신 전날 밤에 반찬 준비하는 게 일이에요. 간단한 도시락 메뉴 추천받아요!'),
]
# 골라주세요: 분류, 제목, 본문, A, B, 며칠 뒤 마감
POLLS = [
    ('가전·디지털', '자취방 첫 청소기, 뭘 살까요?', '원룸이고 바닥은 장판이에요.', '무선 청소기', '로봇 청소기', 7),
    ('먹거리', '야근한 날 저녁, 뭐 먹을까요?', '', '치킨', '떡볶이', 3),
    ('선물', '부모님 결혼기념일 선물 고민돼요', '예산은 10만 원 안쪽이에요.', '꽃다발과 케이크', '안마기', 7),
]
# 사장님 소식: 말머리, 가게, 제목, 본문
OWNERS = [
    ('할인', '소보루 예시 빵집', '이번 주 금요일, 식빵 전 품목 20% 할인', '금요일 하루 식빵을 모두 20% 할인해요. 오후 2시에 새로 구운 식빵이 나와요.'),
    ('오픈', '소보루 예시 꽃집', '동네에 작은 꽃집을 열었어요', '첫 주에는 꽃다발을 사시면 작은 화분을 하나 더 드려요. 문 여는 시간은 오전 10시부터 저녁 8시까지예요.'),
]


def ago(days=0, hours=0):
    return (datetime.datetime.now() - datetime.timedelta(days=days, hours=hours)).isoformat(timespec='seconds')


def add(site):
    from werkzeug.security import generate_password_hash
    with site.conn() as db:
        if db.execute('SELECT 1 FROM posts WHERE ip_hash=? AND nickname=?', (MARK, NICK)).fetchone():
            print('예시 글이 이미 있어요. 다시 넣으려면 먼저 remove.'); return 0
        pw = generate_password_hash(datetime.datetime.now().isoformat())  # 아무도 모르는 비밀번호: 지우기는 운영자만
        with site.app.test_request_context():
            site.g.lists = site.load_lists(); story = site.story_categories()[0]
        n = 0
        for i, (t, c, target, title, body, rating, rec, pros, cons, price, again, where, days) in enumerate(REVIEWS):
            shop, (sido, gu) = (where, ('', '')) if t == 'product' else ('', where)
            db.execute('INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,kind,target,rating,pros,cons,recommend,rv_type,rv_cat,price,bought,again,shop,sido,gu)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (story, NICK, pw, title, body + NOTE, MARK, ago(hours=2 + i * 5), 'review', target, rating, pros, cons, rec, t, c, price,
                        ago(days)[:10], again, shop, sido, gu)); n += 1
        for i, (head, title, body) in enumerate(SUDA):
            kind = {'질문': 'question', '정보': 'tip'}.get(head, 'post')
            db.execute('INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,kind,head) VALUES(?,?,?,?,?,?,?,?,?)',
                       (story, NICK, pw, title, body + NOTE, MARK, ago(hours=1 + i * 4), kind, head)); n += 1
        for i, (cat, title, body, a, b, days) in enumerate(POLLS):
            ends = (datetime.datetime.now() + datetime.timedelta(days=days)).isoformat(timespec='seconds')
            db.execute('INSERT INTO vs_polls(cat,title,body,a,b,user_id,nickname,ends,ip_hash,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (cat, title, (body + NOTE).strip(), a, b, None, NICK, ends, MARK, ago(hours=1 + i * 3))); n += 1
        for i, (head, shop, title, body) in enumerate(OWNERS):
            db.execute('INSERT INTO owner_news(user_id,nickname,shop,head,title,body,link,ip_hash,created,biz) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (0, NICK, shop, head, title, body + NOTE, '', MARK, ago(hours=3 + i * 6), guess_biz(shop))); n += 1
    print(f'예시 글 {n}개를 넣었어요.'); return 0


def remove(site):
    with site.conn() as db:
        ids = [r[0] for r in db.execute('SELECT id FROM posts WHERE ip_hash=? AND nickname=?', (MARK, NICK))]
        for pid in ids:
            for table in ('comments', 'saves'): db.execute(f'DELETE FROM {table} WHERE post_id=?', (pid,))
            db.execute('DELETE FROM posts WHERE id=?', (pid,))
        polls = [r[0] for r in db.execute('SELECT id FROM vs_polls WHERE ip_hash=? AND nickname=?', (MARK, NICK))]
        for poll in polls:
            for table in ('vs_votes', 'vs_comments'): db.execute(f'DELETE FROM {table} WHERE poll_id=?', (poll,))
            db.execute('DELETE FROM vs_polls WHERE id=?', (poll,))
        news = db.execute('DELETE FROM owner_news WHERE ip_hash=? AND nickname=?', (MARK, NICK)).rowcount
    print(f'예시 글을 지웠어요: 후기·수다 {len(ids)}개, 골라주세요 {len(polls)}개, 사장님 소식 {news}개.'); return 0


def auto(site):
    import os
    if os.getenv('SOBORU_EXAMPLES', '1') == '0': return 0
    with site.conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS soboru_flags(key TEXT PRIMARY KEY,created TEXT NOT NULL)')
        # 여러 프로세스가 같이 떠도 한 곳만 넣게: 표시를 먼저 차지한 쪽만
        first = db.execute("INSERT OR IGNORE INTO soboru_flags(key,created) VALUES('examples',?)", (ago(),)).rowcount
    if not first: return 0
    try:
        return add(site)
    except Exception as e:  # 예시 글 때문에 사이트가 안 뜨면 안 됨
        print('예시 글을 넣지 못했어요:', e); return 1


def main(argv):
    if not argv or argv[0] not in ('add', 'remove'):
        print(__doc__); return 2
    import app as site
    return (add if argv[0] == 'add' else remove)(site)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
