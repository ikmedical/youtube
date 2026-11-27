"""공유 드라이브 폴더의 새 영상을 YouTube 에 올리고, 시트에 기록하고, Google Chat 으로 알린다.

실행: python -m uploader.main
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .chat import Chat
from .config import Config
from .drive import Drive, DriveFile
from .google_auth import drive_credentials, youtube_credentials
from .sheet import Row, Sheet, decide
from .youtube import QuotaExceeded, YouTube

log = logging.getLogger("uploader")


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render(template: str, f: DriveFile, tz: ZoneInfo) -> str:
    stem, _ = os.path.splitext(f.name)
    created = f.created_time and datetime.fromisoformat(f.created_time.replace("Z", "+00:00")).astimezone(tz)
    now = datetime.now(tz)
    values = _SafeDict(
        name=f.name,
        stem=stem,
        date=now.strftime("%Y-%m-%d"),
        datetime=now.strftime("%Y-%m-%d %H:%M"),
        created_date=created.strftime("%Y-%m-%d") if created else "",
    )
    return template.replace("\\n", "\n").format_map(values)


def run_url() -> str:
    server, repo, run_id = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{run_id}" if server and repo and run_id else ""


def now_str(tz: ZoneInfo) -> str:
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.from_env()
    chat = Chat(cfg.chat_webhook_url)
    tz = ZoneInfo(cfg.timezone)
    try:
        cfg.validate_for_run()
        return _run(cfg, chat, tz)
    except SystemExit as e:
        chat.send(f"❌ *Drive→YouTube 설정 오류*\n{e}\n{run_url()}")
        raise
    except Exception as e:  # noqa: BLE001
        log.error("치명적 오류\n%s", traceback.format_exc())
        chat.send(f"❌ *Drive→YouTube 실행 실패*\n`{type(e).__name__}: {str(e)[:500]}`\n{run_url()}")
        return 1


def _run(cfg: Config, chat: Chat, tz: ZoneInfo) -> int:
    dcreds = drive_credentials(cfg)
    drive = Drive(dcreds)
    sheet = Sheet(dcreds, cfg.sheet_id, cfg.sheet_tab)
    if not cfg.dry_run:
        sheet.ensure_ready()
    rows = sheet.load()

    exclude = {cfg.done_folder_id} if cfg.done_folder_id else set()
    videos = drive.list_videos(cfg.drive_folder_id, cfg.include_subfolders, exclude)
    log.info("드라이브 영상 %d개, 시트 기록 %d건", len(videos), len(rows))

    todo: list[tuple[DriveFile, Row | None, str]] = []
    for v in videos:
        row = rows.get(v.id)
        ok, reason = decide(row, cfg.max_attempts)
        if not ok:
            if row is not None and row.status == "uploading":
                log.warning("건너뜀 %s: %s", v.name, reason)
            continue
        if not Drive.is_stable(v, cfg.min_file_age_minutes):
            log.info("건너뜀 %s: 최근 %d분 내 수정됨(업로드 중일 수 있음)", v.name, cfg.min_file_age_minutes)
            continue
        todo.append((v, row, reason))

    log.info("업로드 대상 %d개 (이번 실행 최대 %d개)", len(todo), cfg.max_uploads_per_run)
    if cfg.dry_run:
        for v, _, reason in todo[: cfg.max_uploads_per_run]:
            log.info("[DRY RUN] 업로드 예정: %s (%s) → 제목 '%s'", v.name, reason, render(cfg.title_template, v, tz))
        return 0
    if not todo:
        return 0

    yt = YouTube(youtube_credentials(cfg))
    uploaded = failed = 0
    for v, row, reason in todo[: cfg.max_uploads_per_run]:
        if row is None:
            row = sheet.new_row()
            row.set("drive_file_id", v.id)
        title = render(cfg.title_template, v, tz)
        description = render(cfg.description_template, v, tz)
        row.set("file_name", v.name)
        row.set("size_mb", f"{v.size / 1024 / 1024:.1f}")
        row.set("drive_created", v.created_time)
        row.set("title", title)
        row.set("status", "uploading")
        row.set("attempts", row.attempts + 1)
        row.set("started_at", now_str(tz))
        row.set("finished_at", "")
        row.set("error", "")
        sheet.save(row)
        log.info("▶ %s (%s, %.1fMB)", v.name, reason, v.size / 1024 / 1024)

        tmpdir = tempfile.mkdtemp(prefix="d2y-")
        path = os.path.join(tmpdir, "video" + os.path.splitext(v.name)[1])
        try:
            drive.download(v.id, path)
            video_id = yt.upload(
                path, v.mime_type, title, description, cfg.tags,
                cfg.category_id, cfg.privacy_status, cfg.made_for_kids,
            )
            url = f"https://youtu.be/{video_id}"
            row.set("status", "success")
            row.set("youtube_video_id", video_id)
            row.set("youtube_url", url)
            row.set("finished_at", now_str(tz))
            sheet.save(row)
            uploaded += 1
            log.info("✔ 완료 %s → %s", v.name, url)
            moved = ""
            if cfg.after_upload == "move" and cfg.done_folder_id:
                try:
                    drive.move(v, cfg.done_folder_id)
                    moved = "\n(완료 폴더로 이동함)"
                except Exception as e:  # noqa: BLE001
                    moved = f"\n⚠️ 완료 폴더 이동 실패: {e}"
            chat.send(f"✅ *YouTube 업로드 완료* ({cfg.privacy_status})\n파일: {v.name}\n제목: {title}\n{url}{moved}")
        except QuotaExceeded as e:
            row.set("status", "queued")
            row.set("attempts", max(0, row.attempts - 1))  # 할당량 초과는 시도 횟수에서 제외
            row.set("error", f"할당량 초과: {e}")
            row.set("finished_at", now_str(tz))
            sheet.save(row)
            log.warning("YouTube 할당량 초과, 이번 실행 중단: %s", e)
            chat.send(
                f"⏸️ *YouTube 업로드 한도 도달* - 다음 실행에서 이어서 올립니다.\n파일: {v.name}\n`{e}`\n{run_url()}"
            )
            break
        except Exception as e:  # noqa: BLE001
            log.error("✘ 실패 %s\n%s", v.name, traceback.format_exc())
            row.set("status", "failed")
            row.set("error", f"{type(e).__name__}: {str(e)[:450]}")
            row.set("finished_at", now_str(tz))
            sheet.save(row)
            failed += 1
            retry_note = (
                f"다음 실행에서 재시도합니다 ({row.attempts}/{cfg.max_attempts})."
                if row.attempts < cfg.max_attempts
                else "최대 재시도 횟수에 도달해 더 이상 시도하지 않습니다. 시트에서 status 를 failed→queued 로 바꾸면 다시 시도합니다."
            )
            chat.send(
                f"❌ *YouTube 업로드 실패*\n파일: {v.name}\n`{type(e).__name__}: {str(e)[:300]}`\n{retry_note}\n{run_url()}"
            )
        finally:
            try:
                if os.path.exists(path):
                    os.remove(path)
                os.rmdir(tmpdir)
            except OSError:
                pass

    log.info("완료: 성공 %d, 실패 %d, 남은 대상 %d", uploaded, failed, max(0, len(todo) - cfg.max_uploads_per_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
