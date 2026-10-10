# SOBORU 플랫폼 (한큐 민원 + SOBORU Business)

소비자제보센터 홈페이지와 분리된 별도 서비스예요. 같은 서버, 같은 저장소를 쓰지만 DB·주소·서비스가 따로예요.

| 주소 | 서비스 | 누가 |
|---|---|---|
| `hanq.consumerjebo.co.kr` | 한큐 민원 | 소비자: 어느 기업이든 접수, 진행 확인, 해결 여부 응답 |
| `business.consumerjebo.co.kr` | SOBORU Business | 입점 기업: 승인 카드, 전체 민원, 자동 처리 규칙, 설정 |
| `business.consumerjebo.co.kr/ops` | 운영 | 센터: 기업 가입 승인, 비입점 기업 민원 처리 |

코드: `platform_app/` (`hanq.py`가 실행 진입점, `core.py` 공통, `consumer.py` 소비자, `business.py` 기업·운영). 테스트: `tests/test_platform.py`.

## 처리 흐름

1. 소비자가 기업 → 유형 → 내용 → 원하는 해결 → 연락처 순서로 접수 (한 화면에 질문 하나)
2. **입점 기업 + 전달 동의**: 기업 화면으로 바로 전달, 답변 목표일 2일
   - 그 유형의 자동 처리를 켜 둔 기업이면 즉시 추천 조치 실행 + 답변
   - 아니면 승인 카드로 올라감: 승인(추천 조치 실행 + 답변) / 보류 / 자료 요청
3. **비입점 기업**: 운영 화면에서 공식 연락처로 전달 시도 기록 → 회신 기록 또는 회신 없음(피해구제 안내)
4. 소비자는 휴대폰 번호 + 조회 비밀번호로 어느 기기에서든 확인, 답변 후 해결됐어요 / 아직이에요
5. 미해결이거나 답변 목표일이 지나면 1372·한국소비자원 피해구제 안내

## 서버에 설치

1. 가비아 DNS에서 `hanq`, `business` 두 호스트를 consumerjebo.co.kr과 같은 서버 IP로 연결 (A 레코드)
2. 최신 코드 받기: `sudo bash /opt/soboru/app/deploy/update.sh` (main에 합쳐진 뒤)
3. 설치: `sudo bash /opt/soboru/app/deploy/platform-setup.sh hanq.consumerjebo.co.kr business.consumerjebo.co.kr 이메일`
   - 운영 화면 비밀번호를 물어봐요 (12자 이상)
   - DNS가 반영돼 있으면 HTTPS까지 자동 설정, 아니면 반영 뒤 같은 명령을 다시 실행
4. 설정 파일 `/etc/soboru-platform.env`: 메일 알림(SMTP), `PLATFORM_MODE=live`(시범 운영 띠 끄기)
5. 이후 업데이트는 기존과 같이 `update.sh` 한 번이면 두 서비스 모두 다시 시작돼요

## 아직 남은 것

- 개인정보 처리방침·기업 이용약관 법률 검토 (지금 문구는 초안) → 끝나면 `PLATFORM_MODE=live`
- 카카오 알림톡 (지금은 이메일만)
- 자동 처리의 실제 연동: 택배 송장 조회, 스마트스토어·카페24 주문/회수 API (지금은 처리 기록만 남김)
- 기업 담당자 여러 명, 담당자 배정
- 홈페이지(소비자제보센터) 제보와 연결
