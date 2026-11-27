# 설정 가이드 (최초 1회)

전체 흐름: **Google Cloud 프로젝트 만들기 → 자격증명 발급 → GitHub Secrets 저장 → 시트 만들기 → 테스트 실행**

계정이 두 개 등장합니다.

| 이름 | 하는 일 | 인증 방법 |
|---|---|---|
| **YouTube 계정** | 영상이 올라갈 채널의 소유 계정 | OAuth refresh token (`YT_REFRESH_TOKEN`) |
| **드라이브 계정** | 공유 드라이브(영상 폴더)와 관리 시트에 접근 | ① 서비스 계정 JSON (`DRIVE_SERVICE_ACCOUNT_JSON`) 또는 ② 그 계정의 OAuth refresh token (`DRIVE_REFRESH_TOKEN`) |

> 두 계정이 같다면 refresh token 하나(`--for both`)로 둘 다 쓸 수 있습니다.

---

## 1. Google Cloud 프로젝트 준비

1. https://console.cloud.google.com 접속 → 상단 프로젝트 선택 → **새 프로젝트** (예: `drive-to-youtube`)
   - 어떤 계정으로 만들어도 됩니다. 보통 YouTube 계정으로 만듭니다.
2. **API 및 서비스 → 라이브러리**에서 아래 3개를 각각 검색해 **사용** 클릭
   - YouTube Data API v3
   - Google Drive API
   - Google Sheets API

## 2. OAuth 동의 화면 + OAuth 클라이언트

1. **API 및 서비스 → OAuth 동의 화면**(또는 *Google 인증 플랫폼*)
   - 사용자 유형: **외부(External)** (Workspace 계정이고 모든 계정이 같은 조직이면 *내부*도 가능)
   - 앱 이름, 지원 이메일만 입력하고 저장
   - **대상(Audience) → 앱 게시(Publish app)** 를 눌러 **프로덕션 단계(In production)** 로 바꿉니다.
     ⚠️ *테스트* 상태로 두면 refresh token 이 **7일 뒤 만료**되어 자동화가 멈춥니다.
     (검증 신청은 필요 없습니다. 로그인할 때 "확인되지 않은 앱" 경고가 뜨면 **고급 → (앱 이름)(으)로 이동** 을 누르면 됩니다.)
2. **사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID**
   - 애플리케이션 유형: **데스크톱 앱**
   - 만든 뒤 **JSON 다운로드** → `client_secret.json` 으로 저장
   - 여기의 *클라이언트 ID*, *클라이언트 보안 비밀번호* 가 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` 입니다.

## 3. YouTube refresh token 발급 (내 PC에서 1회)

```bash
git clone https://github.com/ikmedical/youtube && cd youtube
pip install -r requirements.txt
python -m uploader.get_refresh_token --client-secret /경로/client_secret.json --for youtube
```

브라우저가 열리면 **YouTube 채널 소유 계정**으로 로그인합니다. (브랜드 계정 채널이면 채널 선택 화면에서 해당 채널 선택)
출력된 `YT_REFRESH_TOKEN` 값을 복사해 둡니다.

## 4. 드라이브 계정 인증 (둘 중 하나)

### ① 서비스 계정 (권장, 공유 드라이브에 외부 멤버 추가가 허용될 때)

1. Cloud 콘솔 **IAM 및 관리자 → 서비스 계정 → 서비스 계정 만들기** (이름 예: `drive-uploader`, 역할은 지정하지 않아도 됨)
2. 만든 서비스 계정 → **키 → 키 추가 → 새 키 만들기 → JSON** → 파일 다운로드
3. 서비스 계정 이메일(`...@...iam.gserviceaccount.com`)을 복사
4. **드라이브 계정**으로 Google Drive 접속 → 해당 공유 드라이브 → **멤버 관리** → 위 이메일을 **콘텐츠 관리자**로 추가
   - "조직 외부 사용자를 추가할 수 없음" 이 나오면 Workspace 관리자 설정 때문이니 ②를 쓰세요.
5. 다운로드한 JSON 파일의 **내용 전체**를 `DRIVE_SERVICE_ACCOUNT_JSON` 시크릿에 붙여 넣습니다.

### ② 드라이브 계정의 OAuth refresh token

```bash
python -m uploader.get_refresh_token --client-secret /경로/client_secret.json --for drive
```

브라우저에서 **공유 드라이브에 접근할 수 있는 계정**으로 로그인 → 출력된 `DRIVE_REFRESH_TOKEN` 저장.
(같은 OAuth 클라이언트를 씁니다. 동의 화면이 *외부* + *프로덕션* 이어야 다른 계정도 로그인됩니다.)

## 5. 폴더 ID 확인

공유 드라이브에서 영상이 올라오는 폴더를 열면 주소가
`https://drive.google.com/drive/folders/1AbCdEf...` 입니다. `folders/` 뒤가 **`DRIVE_FOLDER_ID`** 입니다.
업로드 후 파일을 옮기고 싶다면 완료 폴더를 하나 만들어 같은 방법으로 **`DONE_FOLDER_ID`** 를 확인합니다.

## 6. Google Chat 웹훅

1. Google Chat에서 알림을 받을 **스페이스** 열기 → 스페이스 이름 클릭 → **앱 및 통합(Apps & integrations)** → **웹훅 추가**
2. 이름 입력(예: `YouTube 업로더`) → 저장 → 생성된 URL 복사 → `GOOGLE_CHAT_WEBHOOK_URL`
   - 웹훅은 Google Workspace 계정에서만 사용할 수 있습니다.

## 7. GitHub에 저장

저장소 **Settings → Secrets and variables → Actions**

**Secrets** (New repository secret)

| 이름 | 값 |
|---|---|
| `GOOGLE_CLIENT_ID` | 2단계 클라이언트 ID |
| `GOOGLE_CLIENT_SECRET` | 2단계 클라이언트 보안 비밀번호 |
| `YT_REFRESH_TOKEN` | 3단계 |
| `DRIVE_SERVICE_ACCOUNT_JSON` *또는* `DRIVE_REFRESH_TOKEN` | 4단계 |
| `DRIVE_FOLDER_ID` | 5단계 |
| `GOOGLE_CHAT_WEBHOOK_URL` | 6단계 |
| `SHEET_ID` | 8단계에서 만든 뒤 저장 |
| `DONE_FOLDER_ID` | (선택) 완료 폴더 |

**Variables** (선택, 비우면 기본값)

| 이름 | 기본값 | 설명 |
|---|---|---|
| `YT_PRIVACY_STATUS` | `private` | `private` / `unlisted` / `public` |
| `YT_TITLE_TEMPLATE` | `{stem}` | 사용 가능: `{stem}`(확장자 뺀 파일명) `{name}` `{date}` `{datetime}` `{created_date}` |
| `YT_DESCRIPTION_TEMPLATE` | (빈 값) | 같은 치환자 사용, 줄바꿈은 `\n` |
| `YT_TAGS` | (빈 값) | 쉼표로 구분 |
| `YT_CATEGORY_ID` | `22` | 22=People & Blogs, 27=Education, 28=Science & Technology |
| `YT_MADE_FOR_KIDS` | `false` | 아동용 여부 |
| `MAX_UPLOADS_PER_RUN` | `3` | 한 번 실행에 올릴 최대 개수 |
| `MAX_ATTEMPTS` | `3` | 실패 시 최대 재시도 횟수 |
| `MIN_FILE_AGE_MINUTES` | `10` | 최근 N분 내 수정된 파일은 아직 올라오는 중으로 보고 다음 실행으로 미룸 |
| `AFTER_UPLOAD` | `keep` | `keep`(그대로 둠) / `move`(`DONE_FOLDER_ID` 로 이동) |
| `INCLUDE_SUBFOLDERS` | `false` | 하위 폴더까지 찾을지 |
| `TIMEZONE` | `Asia/Seoul` | 시트·제목의 시간대 |
| `SHEET_TAB` | `uploads` | 시트 탭 이름 |

## 8. 관리 시트 만들기

**Actions → "업로드 관리 시트 만들기 (최초 1회)" → Run workflow**

- 드라이브 계정 권한으로 공유 드라이브 안에 `YouTube 업로드 관리` 시트를 만듭니다. (기본 위치: `DRIVE_FOLDER_ID` 폴더, 다른 폴더를 원하면 입력)
- 실행 결과 요약과 Chat 에 `SHEET_ID` 가 나옵니다 → 7단계의 `SHEET_ID` 시크릿에 저장하세요.
- 이미 있는 시트를 쓰고 싶다면 그 시트를 드라이브 계정(또는 서비스 계정)에 **편집자**로 공유하고 ID만 `SHEET_ID` 에 넣으면 됩니다. 탭과 헤더는 자동으로 만들어집니다.

## 9. 테스트

1. **Actions → "Drive → YouTube 업로드" → Run workflow → dry_run 체크** → 올릴 대상 목록만 로그로 확인
2. dry_run 해제 후 `max_uploads` 에 `1` 을 넣어 1개만 실제 업로드
3. 이상 없으면 매시간 자동 실행됩니다. 주기를 바꾸려면 `.github/workflows/drive-to-youtube.yml` 의 `cron` 수정 (UTC 기준, 한국시간 -9시간)

---

## 알아둘 제약

- **YouTube API 미심사 프로젝트는 업로드 영상이 '비공개'로 고정됩니다.** 2020-07-28 이후 만든 Cloud 프로젝트는 [YouTube API 감사(Audit)](https://support.google.com/youtube/contact/yt_api_form)를 통과해야 공개/일부공개 업로드가 됩니다. 그 전까지는 비공개로 올라가며, YouTube Studio에서 수동으로 공개 전환할 수 있습니다.
- **일일 할당량**: 기본 10,000 units/일, 업로드 1건이 약 1,600 units → **하루 약 6개**. 한도에 걸리면 해당 파일은 시트에 `queued` 로 남고 다음 실행에서 이어서 올립니다. 할당량은 미국 태평양 시간 자정(한국 오후 4~5시)에 초기화됩니다.
- **GitHub 스케줄 지연**: 예약 실행은 5~30분 늦을 수 있습니다.
- **스케줄 자동 비활성화**: 공개 저장소는 60일간 활동이 없으면 스케줄이 꺼집니다. 워크플로 마지막 단계(Keepalive)가 이를 방지합니다.
- **용량**: GitHub 러너 디스크 여유 공간은 약 14GB입니다. 그보다 큰 영상은 실패합니다.

## 시트 사용법

| status | 의미 | 사람이 할 일 |
|---|---|---|
| `success` | 업로드 완료 | - |
| `failed` | 실패, `MAX_ATTEMPTS` 까지 자동 재시도 | 계속 실패하면 `error` 확인 |
| `queued` | 할당량 초과로 대기 | - (다음 실행에서 자동 진행) |
| `uploading` | 업로드 도중 실행이 중단됨 | YouTube Studio에서 올라갔는지 확인 후 `success` 또는 `queued` 로 변경 |
| `skip` | 업로드 제외 | 올리지 않을 파일은 행을 추가하고 `drive_file_id` + `skip` 입력 |

다시 올리고 싶은 파일은 status 를 `queued` 로 바꾸면 됩니다.
