# main.py
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
import tools
import scheduler_job

# --- 설정 ---
# 테스트용: 30초 뒤에 보고 (실제 사용 시 hours=6 으로 변경)
DELAY_SECONDS = 30
DATABASE_FILE = "jobs.sqlite"

# 1. 스케줄러 설정 (SQLite에 저장하여 프로그램이 꺼져도 기억함)
jobstores = {
    'default': SQLAlchemyJobStore(url=f'sqlite:///{DATABASE_FILE}')
}
scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()


def process_command():
    print("\n" + "=" * 40)
    print("🤖 AI 약속 비서가 대기 중입니다.")
    print("명령 예시: A그룹 조현성,김철수")
    print("=" * 40)

    while True:
        try:
            # 사용자 입력 받기
            command = input("\n명령을 입력하세요 (종료: q): ")
            if command == 'q':
                break

            parts = command.split()  # 공백으로 분리
            if len(parts) < 2:
                print("⚠️ 형식이 잘못되었습니다. (예: A그룹 친구1,친구2)")
                continue

            group_name = parts[0]
            names = parts[1].split(',')  # 쉼표로 이름 분리

            # 1. 이메일 찾기
            email_list = []
            for name in names:
                email = tools.get_email_from_name(name.strip())
                if email:
                    email_list.append(email)

            if not email_list:
                print("❌ 발송할 이메일 주소를 하나도 못 찾았습니다.")
                continue

            # 2. 약속 제안 메일 발송 (즉시)
            subject = f"[{group_name}] 휴가 때 언제 볼까?"
            body = "1월 3일부터 8일까지 휴가야. 시간 되는 날짜 알려줘! (테스트 메일)"

            print(f"📤 {len(email_list)}명에게 메일을 보냅니다...")
            tools.send_email(email_list, subject, body)

            # 3. 스케줄러에 보고 작업 등록 (핵심!)
            # 현재 시간 + 30초
            run_time = datetime.now() + timedelta(seconds=DELAY_SECONDS)

            # 사용자(나)의 이메일 가져오기
            my_profile = tools.get_services()[0].users().getProfile(userId='me').execute()
            my_email = my_profile['emailAddress']

            scheduler.add_job(
                scheduler_job.report_status,
                'date',
                run_date=run_time,
                args=[group_name, subject, my_email]
            )

            print(f"⏰ {DELAY_SECONDS}초 뒤에 결과를 보고하도록 예약했습니다.")
            print(f"   (예정 시각: {run_time.strftime('%H:%M:%S')})")

        except Exception as e:
            print(f"⛔ 오류 발생: {e}")


if __name__ == "__main__":
    try:
        process_command()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("\n비서 시스템을 종료합니다.")