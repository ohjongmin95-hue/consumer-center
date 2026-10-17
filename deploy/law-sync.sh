#!/bin/bash
# 국가법령정보 Open API에서 현행 법령 원문·시행일을 받아 AI 소비자 상담(새 버전) 법령 모음에 넣고,
# 바뀐 조문만 검색용 임베딩을 다시 만듭니다. 올린 PDF가 현행보다 옛 판이면 '개정됨, 확인 필요'로 알려 줘요.
# 사용법: sudo bash /opt/soboru/app/deploy/law-sync.sh           지금 한 번 받기
#        sudo bash /opt/soboru/app/deploy/law-sync.sh install   매일 새벽 자동으로 받게 등록 (/etc/cron.daily)
#        sudo bash /opt/soboru/app/deploy/law-sync.sh remove    자동 받기 끄기
# 인증키(LAW_OC)는 deploy/set-law.sh로 /etc/soboru.env에 넣은 값을 씁니다. 키는 화면·로그에 찍지 않아요.
set -euo pipefail
APP_DIR=/opt/soboru/app; VENV=/opt/soboru/venv; ENV_FILE=/etc/soboru.env
CRON=/etc/cron.daily/soboru-law-sync; LOG=/var/log/soboru-law-sync.log
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
case "${1:-}" in
  install)
    cat > "$CRON" <<CRONJOB
#!/bin/bash
# 소보루: 매일 현행 법령 받기 (deploy/law-sync.sh install 로 만듦)
bash $APP_DIR/deploy/law-sync.sh >> $LOG 2>&1
CRONJOB
    chmod 755 "$CRON"
    echo "등록했어요. 매일 새벽 cron.daily로 돌고, 기록은 $LOG 에 남아요."
    exit 0;;
  remove) rm -f "$CRON"; echo "자동 받기를 껐어요."; exit 0;;
esac
grep -qE '^LAW_OC=.' "$ENV_FILE" || echo "주의: LAW_OC가 없어요. sudo bash $APP_DIR/deploy/set-law.sh 로 먼저 넣어 주세요. (임베딩만 만들어요)"
echo "[$(date '+%Y-%m-%d %H:%M')] 현행 법령 받기"
# 설정 파일을 읽어 서비스 계정(soboru)으로 돌림. 키를 명령줄에 붙이지 않아 ps에도 안 보임
(set -a; . "$ENV_FILE"; set +a; cd "$APP_DIR" && sudo -E -u soboru "$VENV/bin/python" "$APP_DIR/lawsync.py") || { echo "일부 법령을 받지 못했어요. 위 메시지를 확인해 주세요."; exit 1; }
echo "끝났어요. 관리자 > 법령 학습 > 현행 여부에서 확인할 수 있어요."
