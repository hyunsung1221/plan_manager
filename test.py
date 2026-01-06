import asyncio
from fastmcp import Client

# 1. 서버 주소 설정
# 로컬 테스트 시: "http://localhost:8000/sse"
# 배포 환경 테스트 시: "https://planmanager-production.up.railway.app/sse"
# test.py 예시

# SERVER_URL = "https://planmanager-production.up.railway.app/sse"  <-- (X)
SERVER_URL = "https://planmanager-production.up.railway.app/"      # <-- (O)


async def run_test():
    # 클라이언트 초기화
    client = Client(SERVER_URL)
    print(f"🔌 서버 연결 시도: {SERVER_URL}")

    async with client:
        # =================================================================
        # [Step 1] 인증 상태 점검 및 로그인 절차 (대화형)
        # =================================================================
        print("\n🔎 [Check] 로그인 상태를 확인합니다...")

        # send_gmail 툴은 토큰이 없으면 명시적으로 에러 메시지를 반환하도록 되어 있으므로 이를 활용합니다.
        check_result = await client.call_tool(
            name="send_gmail",
            arguments={
                "recipient_names": "check_auth",
                "subject": "auth_check",
                "body": "check"
            }
        )

        # 로그인이 필요한 경우 ("login_gmail"이라는 문구가 포함된 메시지가 오면)
        if "login_gmail" in str(check_result) or "로그인이 되어있지 않습니다" in str(check_result):
            print("\n⚠️  로그인이 필요합니다. 인증 절차를 시작합니다.")

            # 1-1. 로그인 링크 요청
            auth_msg = await client.call_tool(name="login_gmail", arguments={})
            print(f"\n{'-' * 60}")
            print(auth_msg)  # 인증 링크와 안내 메시지 출력
            print(f"{'-' * 60}\n")

            # 1-2. 사용자로부터 코드 입력 받기 (터미널 입력)
            auth_code = input("👉 위 링크에서 로그인 후 발급받은 '인증 코드'를 입력하세요: ").strip()

            if not auth_code:
                print("❌ 코드가 입력되지 않아 테스트를 종료합니다.")
                return

            # 1-3. 코드 제출
            print("⏳ 인증 코드를 서버로 전송 중...")
            auth_result = await client.call_tool(
                name="submit_auth_code",
                arguments={"code": auth_code}
            )
            print(f"결과: {auth_result}")

            if "성공" not in str(auth_result):
                print("❌ 인증에 실패했습니다. 코드를 다시 확인해주세요.")
                return
        else:
            print("✅ 이미 로그인이 되어 있습니다.")

        # =================================================================
        # [Step 2] 실제 기능 테스트
        # =================================================================

        # 2-1. 이메일 주소 찾기
        target_name = "조현성"  # ⚠️ 주소록에 있는 실제 이름으로 변경
        print(f"\n[Test 1] '{target_name}' 이메일 검색 중...")

        email_result = await client.call_tool(
            name="find_contact_email",
            arguments={"name": target_name}
        )
        print(f"결과: {email_result}")

        # 2-2. 이메일 보내기
        print(f"\n[Test 2] 이메일 전송 시도 중...")
        send_result = await client.call_tool(
            name="send_gmail",
            arguments={
                "recipient_names": target_name,
                "subject": "FastMCP 클라이언트 테스트 (OAuth)",
                "body": "인증 기능이 포함된 클라이언트에서 보낸 테스트 메일입니다.",
                "enable_report": False
            }
        )
        print(f"결과: {send_result}")

if __name__ == "__main__":
    asyncio.run(run_test())