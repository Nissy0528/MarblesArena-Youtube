---
name: upload_youtube
description: output/ フォルダの完成動画をYouTube Data API v3で自動投稿する。タイトルはs{season}p{part}形式で自動採番し、説明・タグはtemplates/metadata.jsonから読み込む。
---

# YouTubeアップロードスキル（Marbles Arena）

## 前提条件
- `.env` に以下が設定済みであること
  - `YOUTUBE_CLIENT_SECRET_PATH`（OAuthクライアントシークレットJSONのパス）
  - `YOUTUBE_TOKEN_PATH`（初回認証後に保存されるトークンファイルのパス）
- `output/` に投稿対象の完成動画（約20秒）がある
- Pythonライブラリ：`google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` がインストール済み

## アップロード設定（実例 s2p11 に準拠）
- タイトル形式：「3秒で入る球予想してね！（正解は最後！) s{season}p{part} #shorts」
  - `season` / `part` は `uploaded_log.csv` の最新レコードから自動採番（下記「採番ロジック」参照）
- 説明文の構成（1行目は動画ごとに手動入力、2行目以降は固定）：
  - **1行目（可変・毎回ユーザーに確認して入力）**：動画ごとの一言コメント
    - 例：「のびてぇぇ」（s2p8）、「背景動かしたいなと思いつつ、難しいものです」（s2p11）
  - **2行目以降（固定）**：
    ```
    どの色が入るか予想しよう！チャンネル登録よろしくお願いします！ #marblerun #marblerunrace #marblerace #ゲーム #marble
    ```
  - アップロード実行前に、Claudeは毎回「今回の一言コメントは何にしますか？」とユーザーに確認してから説明文を組み立てる
- タグ：`ゲーム, game, IndieGame, インディーゲーム, marble, race, 沼, ルーレット, カイジ`
- カテゴリID：`20`（Gaming）
- 公開設定：`public`
- サムネイル：`templates/thumbnail.png`（あれば `videos.thumbnails.set` で設定。なければ省略可）

## templates/metadata.json の例
```json
{
  "title_template": "3秒で入る球予想してね！（正解は最後！) s{season}p{part} #shorts",
  "description_footer": "どの色が入るか予想しよう！チャンネル登録よろしくお願いします！ #marblerun #marblerunrace #marblerace #ゲーム #marble",
  "tags": ["ゲーム", "game", "IndieGame", "インディーゲーム", "marble", "race", "沼", "ルーレット", "カイジ"],
  "category_id": "20",
  "privacy_status": "public"
}
```
※ `description_footer` が固定の2行目以降。実際の説明文は `{一言コメント}\n{description_footer}` の形で組み立てる（一言コメントは毎回ユーザーへ確認）

## 採番ロジック（season固定・partのみ自動採番）
1. `season` は固定値として `templates/metadata.json` 等の設定値で管理する（**現在は `season=3`**）
2. **今回の切り替え対応**：前回投稿から間が空いたため、次回投稿から `season=3` に変更する。次回投稿は `s3p1` から開始する（1回限りの手動対応）
3. 2本目以降は `uploaded_log.csv` の最新レコード（`season=3`の行）から `part` のみ +1 して採番する（例：s3p1 → s3p2 → s3p3 ...）
4. 将来的に `season` を切り替える場合は、その都度ユーザーに確認してから設定値を手動変更する（自動繰り上げは実装しない）

## 実行手順
1. `output/` を走査し、`uploaded_log.csv` と突き合わせて未投稿ファイルのみを対象にする
2. `uploaded_log.csv` の最新レコードから次の `season` / `part` を算出する
3. **投稿する動画ごとに、説明文1行目の「一言コメント」をユーザーに確認する**（例：「のびてぇぇ」のような短い感想・つぶやき）
4. `templates/metadata.json` の `description_footer` と、確認した一言コメントを組み合わせて説明文を組み立て、タイトル・タグと合わせてメタデータを生成する
5. `scripts/upload.py` を実行し、YouTube Data API の `videos.insert` でアップロードする（`privacyStatus: public`）
6. アップロード成功後、返却された動画ID・投稿日時・`season`/`part` を `uploaded_log.csv` に追記する
7. サムネイルがあれば `videos.thumbnails.set` で設定する
8. 失敗した場合はリトライせずログに失敗理由を記録し、次回実行時に再対象化する（採番を二重に進めないよう注意）

## scripts/upload.py の骨子
```python
import os
import csv
import json
from datetime import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
LOG_PATH = "uploaded_log.csv"

def get_authenticated_service():
    creds = None
    token_path = os.environ["YOUTUBE_TOKEN_PATH"]
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            os.environ["YOUTUBE_CLIENT_SECRET_PATH"], SCOPES
        )
        creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)

CURRENT_SEASON = 3  # seasonは固定運用。切り替える場合はユーザー確認の上でここを変更する

def get_next_season_part():
    if not os.path.exists(LOG_PATH):
        return CURRENT_SEASON, 1  # 今回のシーズン切り替え後、初回はs3p1から開始
    with open(LOG_PATH, newline="") as f:
        rows = list(csv.DictReader(f))
    # 現在のシーズン(CURRENT_SEASON)のログのみを対象に最新partを探す
    current_season_rows = [r for r in rows if int(r["season"]) == CURRENT_SEASON]
    if not current_season_rows:
        return CURRENT_SEASON, 1  # このシーズンでの初回投稿
    last = current_season_rows[-1]
    return CURRENT_SEASON, int(last["part"]) + 1

def upload_video(youtube, filepath, meta, season, part, comment):
    title = meta["title_template"].format(season=season, part=part)
    description = f"{comment}\n{meta['description_footer']}"
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": meta["tags"],
            "categoryId": meta["category_id"],
        },
        "status": {"privacyStatus": meta["privacy_status"]},
    }
    media = MediaFileUpload(filepath, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    return response["id"], title

def log_upload(video_id, filepath, season, part):
    file_exists = os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "filepath", "video_id", "season", "part"])
        writer.writerow([datetime.now().isoformat(), filepath, video_id, season, part])

# メイン処理：output/走査 → get_next_season_part → 一言コメントをユーザーに確認 → metadata生成 → upload_video → log_upload の流れで実装する
```

## エラー時の対処
- 認証エラー → `YOUTUBE_TOKEN_PATH` のトークンを削除して再認証を実行
- クォータ超過（quotaExceeded） → 当日の投稿を中断し、翌日以降に再実行
- 採番がずれた（同じ番号を2回使ってしまった等） → `uploaded_log.csv` を確認し、手動で正しい番号に修正してから次回実行する
- アップロード後に動画が反映されない → `privacyStatus` の設定とYouTube側の処理待ち時間を確認
