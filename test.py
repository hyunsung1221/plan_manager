# test.py
import asyncio
from fastmcp import Client

# 서버 주소 (배포 환경 또는 로컬)
# SERVER_URL = "http://localhost:8000"
SERVER_URL = "https://planmanager-production.up.railway.app"


async def run_test():
    print(f"🔌 서버 연결 시도: {SERVER_URL}")
    print("✨ 브라우저가 열리면 Google 로그인을 진행해주세요.")

    # auth="oauth"를 설정하면 FastMCP 클라이언트가 로그인 흐름을 자동 처리
    async with Client(SERVER_URL, auth="oauth") as client:
        print("\n✅ 인증 완료! 기능을 테스트합니다.")

        # 1. 이메일 주소 찾기
        target_name = "조현성"  # 테스트할 이름
        print(f"\n[Test 1] '{target_name}' 이메일 검색 중...")

        try:
            email_result = await client.call_tool(
                name="find_contact_email",
                arguments={"name": target_name}
            )
            print(f"결과: {email_result}")
        except Exception as e:
            print(f"검색 실패: {e}")

        # 2. 이메일 보내기
        print(f"\n[Test 2] 이메일 전송 시도 중...")
        try:
            send_result = await client.call_tool(
                name="send_gmail",
                arguments={
                    "recipient_names": target_name,
                    "subject": "FastMCP GoogleProvider 테스트",
                    "body": "FastMCP의 내장 GoogleProvider를 통한 자동 인증 테스트 메일입니다."
                }
            )
            print(f"결과: {send_result}")
        except Exception as e:
            print(f"전송 실패: {e}")


if __name__ == "__main__":
    asyncio.run(run_test())