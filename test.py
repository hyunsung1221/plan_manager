import asyncio
from fastmcp import Client

# 1. 서버 주소 설정
# 로컬 테스트 시: "http://localhost:8000/sse"
# 배포 환경 테스트 시: "https://planmanager-production.up.railway.app/sse"
SERVER_URL = "https://planmanager-production.up.railway.app/sse"


async def run_test():
    # 클라이언트 초기화
    client = Client(SERVER_URL)

    print(f"🔌 서버 연결 시도: {SERVER_URL}")

    try:
        async with client:
            # ---------------------------------------------------------
            # 테스트 1: 이메일 주소 찾기 (find_contact_email)
            # ---------------------------------------------------------
            target_name = "테스트"  # ⚠️ 실제 주소록에 있는 이름으로 변경하세요
            print(f"\n[Test 1] '{target_name}' 이메일 검색 중...")

            email_result = await client.call_tool(
                name="find_contact_email",
                arguments={"name": target_name}
            )
            print(f"결과: {email_result}")

            # ---------------------------------------------------------
            # 테스트 2: 이메일 보내기 (send_gmail)
            # ---------------------------------------------------------
            print(f"\n[Test 2] 이메일 전송 시도 중...")

            # 서버의 send_gmail 함수 정의:
            # def send_gmail(recipient_names: str, subject: str, body: str, ...)
            send_args = {
                "recipient_names": target_name,  # 받는 사람 이름
                "subject": "FastMCP 클라이언트 테스트",  # 제목
                "body": "안녕하세요, Python 클라이언트에서 보낸 테스트 메일입니다.",  # 본문
                "enable_report": False  # (선택) 답장 체크 리포트 활성화 여부
            }

            send_result = await client.call_tool(
                name="send_gmail",
                arguments=send_args
            )
            print(f"결과: {send_result}")

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")


if __name__ == "__main__":
    asyncio.run(run_test())