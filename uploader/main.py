"""공유 드라이브 폴더의 새 영상을 YouTube 에 올리고, 시트에 기록하고, Google Chat 으로 알린다.

실행: python -m uploader.main
"""
from __future__ import annotations

import logging
import os
import re
import sys
import unicodedata
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .chat import Chat
from .config import Config
from .description import clean
from .drive import Drive, DriveFile
from .schedule import date_key, next_free_slot, parse_schedule, to_rfc3339_utc
from .google_auth import drive_credentials, youtube_credentials
from .sheet import Row, Sheet, decide
from .youtube import QuotaExceeded, YouTube

log = logging.getLogger("uploader")


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render(template: str, f: DriveFile, tz: ZoneInfo, description: str = "") -> str:
    stem, _ = os.path.splitext(f.name)
    created = f.created_time and datetime.fromisoformat(f.created_time.replace("Z", "+00:00")).astimezone(tz)
    now = datetime.now(tz)
    values = _SafeDict(
        name=f.name,
        stem=stem,
        date=now.strftime("%Y-%m-%d"),
        datetime=now.strftime("%Y-%m-%d %H:%M"),
        created_date=created.strftime("%Y-%m-%d") if created else "",
        description="{description}",
    )
    out = template.replace("\\n", "\n").format_map(values)
    # 설명 파일 내용은 마지막에 넣어 내용 속 { } 가 치환되지 않게 한다
    return out.replace("{description}", description).strip()


def natural_key(name: str):
    """'2강' 이 '10강' 보다 앞에 오도록 숫자를 숫자로 비교."""
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", unicodedata.normalize("NFC", name))]


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
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and not (cfg.drive_folder_id and cfg.sheet_id):
        # 아직 설정 전이면 예약 실행은 조용히 건너뜀 (매시간 실패 메일 방지)
        log.info("DRIVE_FOLDER_ID / SHEET_ID 가 아직 설정되지 않아 예약 실행을 건너뜁니다.")
        return 0
    try:
        cfg.validate_for_run()
        return _run(cfg, chat, tz)
    except SystemExit as e:
        chat.send(f"❌ *Drive→YouTube 설정 오류*\n{e}\n{run_url()}", mention=True)
        raise
    except Exception as e:  # noqa: BLE001
        log.error("치명적 오류\n%s", traceback.format_exc())
        chat.send(f"❌ *Drive→YouTube 실행 실패*\n`{type(e).__name__}: {str(e)[:500]}`\n{run_url()}", mention=True)
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
    if cfg.video_order == "name":
        videos.sort(key=lambda v: natural_key(v.name))
    log.info("드라이브 영상 %d개, 시트 기록 %d건", len(videos), len(rows))

    today = datetime.now(tz).date()
    tomorrow = (today + timedelta(days=1)).isoformat()
    todo: list[tuple[DriveFile, Row | None, str]] = []
    waiting: list[DriveFile] = []
    for v in videos:
        row = rows.get(v.id)
        ok, reason = decide(row, cfg.max_attempts, today.isoformat())
        if not ok:
            if row is not None and row.status == "uploading":
                log.warning("건너뜀 %s: %s", v.name, reason)
            continue
        if not Drive.is_stable(v, cfg.min_file_age_minutes):
            log.info("건너뜀 %s: 최근 %d분 내 수정됨(업로드 중일 수 있음)", v.name, cfg.min_file_age_minutes)
            continue
        if cfg.require_description_file and not v.description_file:
            log.info("대기 %s: 같은 이름의 설명 파일이 없음 → %s 에 다시 확인", v.name, tomorrow)
            if not cfg.dry_run:
                if row is None:
                    row = sheet.new_row()
                    row.set("drive_file_id", v.id)
                row.set("file_name", v.name)
                row.set("size_mb", f"{v.size / 1024 / 1024:.1f}")
                row.set("drive_created", v.created_time)
                row.set("status", "waiting")
                row.set("next_try_date", tomorrow)
                row.set("error", "같은 이름의 설명 파일(.docx/Google 문서/.txt) 없음")
                row.set("finished_at", now_str(tz))
                sheet.save(row)
                waiting.append(v)
            continue
        todo.append((v, row, reason))

    if waiting:
        names = "\n".join(f"• {w.name}  →  필요한 파일: {os.path.splitext(w.name)[0]}.docx" for w in waiting[:20])
        more = f"\n…외 {len(waiting) - 20}개" if len(waiting) > 20 else ""
        chat.send(
            "📝 *설명 파일이 없어 업로드를 보류했습니다*\n"
            f"{names}{more}\n"
            f"같은 폴더에 같은 이름의 워드 파일을 올려 주세요. {tomorrow} 에 다시 확인합니다.",
            mention=True,
        )

    log.info("업로드 대상 %d개 (이번 실행 최대 %d개)", len(todo), cfg.max_uploads_per_run)
    if cfg.dry_run:
        for v, _, reason in todo[: cfg.max_uploads_per_run]:
            log.info("[DRY RUN] 업로드 예정: %s (%s) → 제목 '%s'", v.name, reason, render(cfg.title_template, v, tz))
        return 0
    if not todo:
        return 0

    sched = parse_schedule(cfg.publish_schedule)
    yt = YouTube(youtube_credentials(cfg))
    # 한 주에 한 개: 이미 예약된 날짜(시트 + 채널에 걸려 있는 예약)는 건너뛴다
    occupied: set[str] = set()
    if sched:
        for r in rows.values():
            if r.status in ("success", "uploading"):
                k = date_key(r.get("publish_at"), tz)
                if k:
                    occupied.add(k)
        try:
            for pa in yt.scheduled_publish_times():
                k = date_key(pa, tz)
                if k:
                    occupied.add(k)
        except Exception as e:  # noqa: BLE001
            log.warning("채널의 기존 예약 조회 실패(시트 기록만 사용): %s", e)
        log.info("이미 예약된 날짜: %s", ", ".join(sorted(occupied)) or "(없음)")
    uploaded = failed = 0
    for v, row, reason in todo[: cfg.max_uploads_per_run]:
        if row is None:
            row = sheet.new_row()
            row.set("drive_file_id", v.id)
        title = render(cfg.title_template, v, tz)
        desc_text = ""
        desc_note = ""
        if v.description_file:
            try:
                desc_text = clean(drive.read_text(v.description_file))
                desc_note = v.description_file["name"]
            except Exception as e:  # noqa: BLE001
                log.warning("설명 파일 읽기 실패 %s: %s", v.description_file["name"], e)
                desc_note = f"읽기 실패: {v.description_file['name']} ({str(e)[:100]})"
        description = render(cfg.description_template, v, tz, desc_text)
        row.set("file_name", v.name)
        row.set("size_mb", f"{v.size / 1024 / 1024:.1f}")
        row.set("drive_created", v.created_time)
        row.set("title", title)
        row.set("description_file", desc_note or "(없음)")
        row.set("status", "uploading")
        row.set("attempts", row.attempts + 1)
        row.set("started_at", now_str(tz))
        row.set("finished_at", "")
        row.set("error", "")
        row.set("next_try_date", "")
        sheet.save(row)
        log.info("▶ %s (%s, %.1fMB)", v.name, reason, v.size / 1024 / 1024)

        publish_dt = next_free_slot(sched, tz, occupied) if sched else None
        row.set("publish_at", publish_dt.strftime("%Y-%m-%d %H:%M") if publish_dt else "")
        tmpdir = tempfile.mkdtemp(prefix="d2y-")
        path = os.path.join(tmpdir, "video" + os.path.splitext(v.name)[1])
        try:
            drive.download(v.id, path)
            video_id = yt.upload(
                path, v.mime_type, title, description, cfg.tags,
                cfg.category_id, cfg.privacy_status, cfg.made_for_kids,
                to_rfc3339_utc(publish_dt) if publish_dt else None,
            )
            url = f"https://youtu.be/{video_id}"
            row.set("status", "success")
            if publish_dt:
                occupied.add(publish_dt.strftime("%Y-%m-%d"))
            row.set("youtube_video_id", video_id)
            row.set("youtube_url", url)
            row.set("finished_at", now_str(tz))
            sheet.save(row)
            uploaded += 1
            log.info("✔ 완료 %s → %s", v.name, url)
            notes = ""
            playlist_id = cfg.playlist_map.get(v.folder_name) or cfg.playlist_id
            if playlist_id:
                try:
                    yt.add_to_playlist(video_id, playlist_id)
                    row.set("playlist_id", playlist_id)
                    sheet.save(row)
                    notes += "\n재생목록에 추가함"
                except Exception as e:  # noqa: BLE001
                    log.warning("재생목록 추가 실패 %s: %s", playlist_id, e)
                    row.set("error", f"재생목록 추가 실패({playlist_id}): {str(e)[:300]}")
                    sheet.save(row)
                    notes += f"\n⚠️ 재생목록 추가 실패: {str(e)[:200]}"
            if cfg.after_upload == "move" and cfg.done_folder_id:
                try:
                    drive.move(v, cfg.done_folder_id)
                    if v.description_file:
                        drive.move(v.description_file, cfg.done_folder_id)
                    notes += "\n(완료 폴더로 이동함)"
                except Exception as e:  # noqa: BLE001
                    notes += f"\n⚠️ 완료 폴더 이동 실패: {e}"
            visibility = (
                f"비공개 → {publish_dt.strftime('%m/%d')}({'월화수목금토일'[publish_dt.weekday()]}) {publish_dt.strftime('%H:%M')} 공개 예약" if publish_dt else cfg.privacy_status
            )
            if not v.description_file:
                notes += "\nℹ️ 같은 이름의 설명 파일이 없어 기본 설명으로 올렸습니다."
            elif not desc_text:
                notes += f"\n⚠️ 설명 파일을 읽지 못했거나 비어 있습니다: {desc_note}"
            chat.send(
                f"✅ *YouTube 업로드 완료* ({visibility})\n파일: {v.name}\n제목: {title}\n{url}{notes}",
                mention="⚠️" in notes,  # 재생목록·이동·설명 읽기 실패 등 확인이 필요할 때만 태그
            )
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
                f"❌ *YouTube 업로드 실패*\n파일: {v.name}\n`{type(e).__name__}: {str(e)[:300]}`\n{retry_note}\n{run_url()}",
                mention=True,
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
