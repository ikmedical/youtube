"""내 PC 에서 1회 실행해 OAuth refresh token 을 발급받는 도우미.

사용법:
  pip install google-auth-oauthlib
  python -m uploader.get_refresh_token --client-secret client_secret.json --for youtube
  python -m uploader.get_refresh_token --client-secret client_secret.json --for drive
  python -m uploader.get_refresh_token --client-secret client_secret.json --for both

브라우저가 열리면 "해당 계정"으로 로그인해야 한다.
  --for youtube : YouTube 채널을 가진 계정
  --for drive   : 공유 드라이브에 접근하는 계정
  --for both    : 두 계정이 같은 경우 (하나의 토큰으로 둘 다 사용)
"""
from __future__ import annotations

import argparse

from google_auth_oauthlib.flow import InstalledAppFlow

from .google_auth import DRIVE_SCOPES, YOUTUBE_SCOPES


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--client-secret", required=True, help="Google Cloud 에서 받은 OAuth 클라이언트 JSON 경로")
    p.add_argument("--for", dest="target", choices=["youtube", "drive", "both"], required=True)
    p.add_argument("--port", type=int, default=0)
    args = p.parse_args()

    scopes = {
        "youtube": YOUTUBE_SCOPES,
        "drive": DRIVE_SCOPES,
        "both": YOUTUBE_SCOPES + DRIVE_SCOPES,
    }[args.target]
    flow = InstalledAppFlow.from_client_secrets_file(args.client_secret, scopes=scopes)
    creds = flow.run_local_server(port=args.port, access_type="offline", prompt="consent")
    print("\n=== 아래 값을 GitHub Secret 에 저장하세요 ===")
    if args.target == "youtube":
        print("YT_REFRESH_TOKEN =", creds.refresh_token)
    elif args.target == "drive":
        print("DRIVE_REFRESH_TOKEN =", creds.refresh_token)
    else:
        print("YT_REFRESH_TOKEN = DRIVE_REFRESH_TOKEN =", creds.refresh_token)
    print("GOOGLE_CLIENT_ID =", creds.client_id)
    print("(GOOGLE_CLIENT_SECRET 은 client_secret.json 안의 client_secret 값)")


if __name__ == "__main__":
    main()
