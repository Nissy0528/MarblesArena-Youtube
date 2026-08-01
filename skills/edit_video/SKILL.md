---
name: edit_video
description: input/ の長尺録画（マーブルラン素材）から、額縁フレーム＋日英テキスト＋SUBSCRIBE/Thank youオーバーレイ＋BGMのみ音声のYouTube Shorts（尺は可変、目安20〜30秒）を scripts/edit.py で半自動編集する。
---

# 動画編集スキル（Marbles Arena / 予想系Shorts）

## 方針（重要）
理想の完成形は After Effects 製の動画（`input/026_N016_...mp4`）。**そのAEプロジェクトは別PC・別ユーザーの管理でアクセス不可**のため、本スキルでは `scripts/edit.py`（Python + FFmpeg）で**AE版の見た目を最大限“近似”する**。高度なモーショングラフィックスの1:1再現は目指さない。

## 入力
- `input/` の長尺録画（MP4、実測：1080×1920 / 60fps / H.264 / AAC 48kHz、約60〜61秒）
- `bgm/` の既存BGM（前回動画から引き続き使用。新規選定はしない）
- `assets/` のオーバーレイ動画（再利用素材、著作権フリー）
  - SUBSCRIBEボタン：グリーンバック（例 `サブスクライブ素材｜英語・シンプル・Youtube.mp4`）
  - Thank you：黒背景の筆記体アニメ（例 `67183_1280x720.mp4`）
- `fonts/NotoSansJP.ttf`（日本語フォント。可変フォントの場合はこの名前でコピーを用意）

## 完成形の構成（`input/026_N016` を目標に近似）
- **額縁フレーム**：ゲーム映像を横幅約91%で中央配置、外周は同映像のぼかし＋暗め背景
- **日英テキスト（導入0〜4秒）**：上部に煽り「何色が入る？？」（黒帯・ピンク）、下部に英語字幕「Which ball color goes into the goal?」（白）
- **SUBSCRIBEオーバーレイ**：レース中盤に数秒、下部に合成（グリーンバックをクロマキー＋despillで抜く）
- **Thank youオーバーレイ**：SUBSCRIBEの直後、SUBSCRIBEと同じ高さに合成（黒背景をcolorkeyで抜く）
- **音声：元素材はミュートし、BGMのみ**（volume=0.5基準）
- 尺は可変（目安20〜30秒）。球が動き出してから結果が出るまでの実時間に合わせる

## 実行環境の注意
- Windowsのため、日本語の出力・ファイル名で文字化け/例外を避けるには **`PYTHONUTF8=1 PYTHONIOENCODING=utf-8`** を付けて実行する。
- `ffmpeg` / `ffprobe` にPATHが通っていること。Python実行は仮想環境 `.venv` を使う。

## 処理フロー（半自動：CLAUDE.md「見どころ区間の切り出しルール」に準拠）
1. **情報確認**：`info` で長さ・解像度・fpsと仮切り出し候補を確認
   ```bash
   PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python scripts/edit.py info "input/{ファイル名}.mp4"
   ```
2. **仮切り出し（自動）**：`preview` で末尾30秒を候補区間として書き出し、確認用静止画も出す
   ```bash
   PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python scripts/edit.py preview "input/{ファイル名}.mp4" --stills 6
   ```
3. **確認（ユーザー必須）**：プレビュー動画／静止画を提示し、①球が動き出す瞬間〜結果が過不足なく入るか ②煽りを重ねる位置 ③結果が決まる瞬間が入るか を確認してもらう。**確定するまで本編集に進まない。**
4. **調整**：ズレがあれば `--start` を前後させて `preview` を再実行
5. **本編集**：確定した開始秒で `finalize`
   ```bash
   PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python scripts/edit.py finalize "input/{ファイル名}.mp4" --start {確定開始秒}
   ```
6. **出力**：`output/YYYYMMDD_HHMMSS.mp4`（既存は上書きしない。中間テキストは自動削除）

## finalize が内部で行うこと（単一の filter_complex で1パス処理）
1. トリム（`--start`〜`--end`、既定は末尾まで）＋ `fps=30` 化
2. 額縁：`[bg]=scale(fill)+crop+boxblur+eq(暗く)`、`[fg]=scale(横幅91%)` を中央 `overlay`
3. 日英 `drawtext`（textfile経由でエスケープ回避。表示区間は `enable='between(t,0,4)'`）
4. SUBSCRIBE：`chromakey`（緑抜き）＋`despill`（緑スピル除去）＋`scale`＋`setpts=PTS-STARTPTS+開始/TB`（表示区間の頭から再生）→ `overlay`（`enable` で区間指定）
5. Thank you：`colorkey`（黒抜き）＋`scale`＋`setpts`（同上）→ `overlay`（SUBSCRIBEと同じ垂直中心）
6. 音声：`[bgm]volume=0.5,atrim=0:尺,asetpts` のみを `-map`（元素材の音声は使わない＝ミュート）
7. `libx264 -crf 20 -preset medium` / `aac 44100 128k` / `+faststart`

## 主なオプション（調整用、既定値）
- `--start`（必須） / `--end`：切り出し区間
- `--aori-start 0 --aori-end 4 --aori-color 0xff2fd0`：煽り・英語字幕の表示区間と色
- `--sub-start`（既定：尺の45%）`--sub-dur 3.5`：SUBSCRIBEの表示開始・秒数
- `--sub-width 1500`：SUBSCRIBEの大きさ（大きいほど額縁との左右隙間が狭まる）
- `--sub-y 1560`：SUBSCRIBE/Thank youの垂直中心（両者で共有＝同じ高さ）
- `--sub-similarity 0.12 --sub-blend 0.02 --sub-despill 0.7`：クロマキー調整（緑残り/半透明の対策）
- `--ty-start`（既定：SUBSCRIBE直後）`--ty-dur 4`：Thank youの表示開始・秒数
- `--subscribe / --thankyou`：オーバーレイ素材のパス（省略時は assets/→input/ から自動検出）
- `--no-subscribe / --no-thankyou`：各オーバーレイを入れない
- `--bgm`（省略時 bgm/ 自動選択）`--bgm-volume 0.5`
- `--keep-temp`：中間テキストを残す

## エラー時の対処
- **文字化け/`UnicodeEncodeError: cp932`** → `PYTHONUTF8=1 PYTHONIOENCODING=utf-8` を付けて実行
- **フォントが見つからない** → `fonts/NotoSansJP.ttf` の存在を確認（可変フォントはこの名前でコピー）
- **SUBSCRIBEに緑が残る** → `--sub-despill` を上げる／`--sub-similarity` を少し上げる
- **SUBSCRIBEが半透明になる** → `--sub-similarity` を下げる（緑以外＝無彩色まで抜けている）
- **オーバーレイが表示区間で出ない/尽きる** → `setpts` で頭出ししているのが前提。素材の尺 < 表示秒数なら `--sub-dur`/`--ty-dur` を縮める
- **音がしない/BGMが小さい** → 元素材はミュート仕様。BGMは `--bgm-volume` で調整
- **見どころ区間がずれる** → `preview --start` の候補を変えて再確認してから finalize
