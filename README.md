# youtube

Google 공유 드라이브 폴더에 올라온 새 영상을 **YouTube 에 자동 업로드**하고, 결과를 **Google 시트에 기록**하며 **Google Chat 으로 알림**을 보내는 GitHub Actions 작업입니다.

```
[매시간 GitHub Actions]
   └─ 공유 드라이브 폴더의 영상 목록 조회 (드라이브 계정)
   └─ 관리 시트와 비교해 아직 안 올린 파일만 선택 (중복 방지)
   └─ 다운로드 → YouTube 업로드 (채널 계정)
   └─ 시트에 결과 기록 (video id, URL, 시간, 오류)
   └─ Google Chat 웹훅으로 성공/실패 알림
```

- 설정 방법: [docs/SETUP.md](docs/SETUP.md)
- 워크플로
  - `.github/workflows/drive-to-youtube.yml` : 매시간 실행 + 수동 실행(dry run 지원)
  - `.github/workflows/setup-sheet.yml` : 관리 시트 최초 생성
- 코드: `uploader/` (Python)
- 테스트: `python -m pytest tests`

모든 자격증명은 GitHub Actions **Secrets** 에만 저장하며, 저장소에는 커밋하지 않습니다.
