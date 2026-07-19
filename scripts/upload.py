# -*- coding: utf-8 -*-
"""Marbles Arena Shorts アップロードスクリプト（skills/upload_youtube/SKILL.md 準拠）

- output/ の完成動画を YouTube Data API v3 で投稿する
- タイトルは「3秒で入る球予想してね！（正解は最後！) s{season}p{part} #shorts」形式で自動採番
  （season は templates/metadata.json の固定値、part は uploaded_log.csv から +1）
- 説明文1行目の一言コメントは毎回ユーザーに確認して --comment で渡す
- 二重投稿防止のため uploaded_log.csv と突き合わせて未投稿ファイルのみを対象にする

使用例:
  python scripts/upload.py --list                                  # 未投稿ファイルと次の採番を確認
  python scripts/upload.py --comment "のびてぇぇ" --dry-run         # メタデータの事前確認
  python scripts/upload.py --comment "のびてぇぇ"                   # 最新の未投稿ファイルを投稿
  python scripts/upload.py --file output/20260719_120000.mp4 --comment "のびてぇぇ"
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
METADATA_PATH = PROJECT_ROOT / "templates" / "metadata.json"
THUMBNAIL_PATH = PROJECT_ROOT / "templates" / "thumbnail.png"
LOG_PATH = PROJECT_ROOT / "uploaded_log.csv"
ERROR_LOG_PATH = PROJECT_ROOT / "upload_errors.log"
ENV_PATH = PROJECT_ROOT / ".env"

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
LOG_FIELDS = ["timestamp", "filename", "video_id", "season", "part"]


def load_env():
    """`.env` を読み込んで環境変数へ反映する（既存の環境変数を優先）。"""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_metadata():
    if not METADATA_PATH.exists():
        print(f"[upload] {METADATA_PATH.relative_to(PROJECT_ROOT)} がありません。", file=sys.stderr)
        sys.exit(1)
    return json.loads(METADATA_PATH.read_text(encoding="utf-8"))


def read_log_rows():
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def list_unuploaded():
    """output/ を走査し、uploaded_log.csv にない完成動画のみ返す（中間・プレビューは除外）。"""
    uploaded = {row["filename"] for row in read_log_rows()}
    candidates = []
    if OUTPUT_DIR.exists():
        for p in sorted(OUTPUT_DIR.glob("*.mp4")):
            name = p.name
            if name.startswith("_") or name.endswith(("_raw.mp4", "_text.mp4")):
                continue  # プレビュー・中間ファイルは対象外
            if name in uploaded:
                continue
            candidates.append(p)
    return candidates


def get_next_season_part(metadata):
    """season は固定値（metadata.json の "season"）。part は同シーズンの最新ログから +1。"""
    season = int(metadata["season"])
    rows = [r for r in read_log_rows() if int(r["season"]) == season]
    if not rows:
        return season, 1  # シーズン切り替え後の初回投稿（例: s3p1）
    return season, max(int(r["part"]) for r in rows) + 1


def build_body(metadata, season, part, comment):
    title = metadata["title_template"].format(season=season, part=part)
    description = f"{comment}\n{metadata['description_footer']}"
    return title, description, {
        "snippet": {
            "title": title,
            "description": description,
            "tags": metadata["tags"],
            "categoryId": metadata["category_id"],
        },
        "status": {"privacyStatus": metadata["privacy_status"]},
    }


def get_authenticated_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = os.environ.get("YOUTUBE_TOKEN_PATH")
    secret_path = os.environ.get("YOUTUBE_CLIENT_SECRET_PATH")
    if not token_path or not secret_path:
        print("[upload] .env に YOUTUBE_TOKEN_PATH / YOUTUBE_CLIENT_SECRET_PATH を設定してください。", file=sys.stderr)
        sys.exit(1)

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        Path(token_path).write_text(creds.to_json(), encoding="utf-8")
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
        creds = flow.run_local_server(port=0)
        Path(token_path).write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def upload_video(youtube, filepath, body):
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(filepath), chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    return response["id"]


def set_thumbnail(youtube, video_id):
    if not THUMBNAIL_PATH.exists():
        return False
    from googleapiclient.http import MediaFileUpload

    youtube.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(str(THUMBNAIL_PATH)),
    ).execute()
    return True


def log_upload(filename, video_id, season, part):
    file_exists = LOG_PATH.exists()
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(LOG_FIELDS)
        writer.writerow([datetime.now().isoformat(timespec="seconds"), filename, video_id, season, part])


def log_error(filename, reason):
    """失敗時はリトライせず理由を記録する（次回実行時に再対象化される）。"""
    with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')}\t{filename}\t{reason}\n")


def main():
    parser = argparse.ArgumentParser(description="Marbles Arena Shorts アップロードスクリプト")
    parser.add_argument("--file", help="投稿する動画（省略時は output/ の最新の未投稿ファイル）")
    parser.add_argument("--comment", help="説明文1行目の一言コメント（毎回ユーザーに確認した内容）")
    parser.add_argument("--dry-run", action="store_true", help="アップロードせずタイトル・説明文・採番を表示する")
    parser.add_argument("--list", action="store_true", help="未投稿ファイル一覧と次の採番を表示する")
    args = parser.parse_args()

    load_env()
    metadata = load_metadata()
    season, part = get_next_season_part(metadata)
    unuploaded = list_unuploaded()

    if args.list:
        print(f"次の採番: s{season}p{part}")
        if unuploaded:
            print("未投稿ファイル:")
            for p in unuploaded:
                print(f"  {p.relative_to(PROJECT_ROOT)}")
        else:
            print("未投稿ファイルはありません。")
        return

    # 対象ファイルの決定
    if args.file:
        target = Path(args.file)
        if not target.is_absolute():
            target = PROJECT_ROOT / target
        if not target.exists():
            candidate = OUTPUT_DIR / Path(args.file).name
            if candidate.exists():
                target = candidate
            else:
                print(f"[upload] ファイルが見つかりません: {args.file}", file=sys.stderr)
                sys.exit(1)
        # 二重投稿防止: 指定ファイルでもログを必ず確認する
        if target.name in {row["filename"] for row in read_log_rows()}:
            print(f"[upload] {target.name} は投稿済みです（uploaded_log.csv に記録あり）。中止します。", file=sys.stderr)
            sys.exit(1)
    else:
        if not unuploaded:
            print("[upload] output/ に未投稿の完成動画がありません。", file=sys.stderr)
            sys.exit(1)
        target = unuploaded[-1]  # ファイル名がタイムスタンプ形式のため、名前順の末尾が最新

    if not args.comment:
        print("[upload] --comment（説明文1行目の一言コメント）を指定してください。", file=sys.stderr)
        print("         ※ 一言コメントは動画ごとに手動で決める運用です。", file=sys.stderr)
        sys.exit(1)

    title, description, body = build_body(metadata, season, part, args.comment)

    print(f"対象ファイル: {target.relative_to(PROJECT_ROOT)}")
    print(f"タイトル    : {title}")
    print(f"説明文      :\n{description}")
    print(f"タグ        : {', '.join(metadata['tags'])}")
    print(f"公開設定    : {metadata['privacy_status']} / カテゴリID: {metadata['category_id']}")

    if args.dry_run:
        print("\n[upload] dry-run のためアップロードは行いません。")
        return

    try:
        youtube = get_authenticated_service()
        video_id = upload_video(youtube, target, body)
    except Exception as exc:  # 失敗時はリトライせず記録のみ（採番を進めない）
        log_error(target.name, repr(exc))
        print(f"[upload] アップロード失敗: {exc}", file=sys.stderr)
        print(f"[upload] 失敗理由を {ERROR_LOG_PATH.name} に記録しました。次回実行時に再対象になります。", file=sys.stderr)
        sys.exit(1)

    log_upload(target.name, video_id, season, part)
    print(f"\nアップロード成功: https://youtube.com/shorts/{video_id}")
    print(f"uploaded_log.csv に記録しました（s{season}p{part}）。")

    try:
        if set_thumbnail(youtube, video_id):
            print("サムネイルを設定しました。")
    except Exception as exc:  # サムネイル失敗は投稿自体の失敗にしない
        log_error(target.name, f"thumbnail: {exc!r}")
        print(f"[upload] サムネイル設定に失敗しました（動画は投稿済み）: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
