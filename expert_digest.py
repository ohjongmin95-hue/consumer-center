"""운영자 2026-11-03: 새 제보를 자문단(변호사·교수)에게 하루 한 번 메일로 알림. update.sh가 /etc/cron.d/soboru-expert-digest로 매일 저녁 6시에 부름.
사용법: python expert_digest.py [--dry]   (--dry는 보내지 않고 받을 사람과 글만 보여 줌)"""
import os, sys


def main(argv):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import app as site
    with site.app.app_context():
        n = site.app.extensions['experts_digest'](dry='--dry' in argv)
    print('자문단 새 제보 알림:', n, '명')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
