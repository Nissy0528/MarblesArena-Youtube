---
name: edit_video
description: input/ の長尺録画（マーブルラン素材）から「煽り表示→球が動き出す→結果表示」の3段構成でYouTube Shorts用（尺は可変、目安20〜30秒）に自動編集する。
---

# 動画編集スキル（Marbles Arena / 予想系Shorts）

## 入力
- `input/` にある長尺録画（MP4、実測：1080×1920px / 60fps / H.264 / AAC 48kHz、約60〜61秒）
- `bgm/` にある既存BGM（前回動画から引き続き使用。新規選定はせず、フォルダ内の既存ファイルをそのまま使う）
- 煽りテキスト・結果発表テキスト（基本は固定文言、本ファイル内テンプレートを参照）

## 完成形の構成（実例 s2p11=20秒／s2p8=28秒 に準拠。**尺は固定ではなく可変**）
1. **煽りフェーズ**：「3秒で入る球予想してね！」の煽りテキストを表示。球が動き出す直前の場面に重ねる
2. **レースフェーズ**：球が動き出し、コースを転がっていく本編。不自然にカットせず、球の動きが自然に見える尺を確保する（ここの長さが動画ごとの尺の差になる）
3. **結果フェーズ**：どの色の球が入ったか結果が分かるカットで締める。「正解は最後！」に矛盾しないよう、結果が明確に映る瞬間で終わる
4. 合計尺は**目安20〜30秒程度**。60秒の上限にこだわらず、球が動き出してから結果が出るまでの実時間に合わせる

## 処理手順（半自動フロー：CLAUDE.md「見どころ区間の切り出しルール」に準拠）
1. **情報確認**：`ffprobe` で入力動画の長さ・解像度・fpsを確認する
2. **仮切り出し（自動）**：球が動き出す直前と推定される位置（初期ルール：**末尾から30秒**）〜末尾までを候補区間として自動でトリミングする
3. **確認提示**：仮切り出しした候補区間（またはプレビュー用の静止画数枚）をユーザーに提示し、以下を確認してもらう
   - 球が動き出す瞬間から結果までが過不足なく含まれているか
   - 煽りフェーズを重ねる位置（球が動く直前の場面）が適切か
   - 結果が決まる瞬間がちゃんと含まれているか
4. **調整（必要な場合のみ）**：ズレの指摘があれば開始位置・各フェーズの切り替え位置を調整し、再度候補を提示する。確定するまで本編集には進まない
5. **確定後の本編集**：
   a. フレームレート変換（60fps → 30fps）
   b. 縦型統一（1080×1920以外の場合はクロップ＋パディング。今回の素材は通常不要）
   c. 煽りフェーズの区間に「3秒で入る球予想してね！」を `drawtext` で焼き込む
   d. （任意）結果フェーズの区間に結果を強調するテキストを焼き込む
   e. 緊張感を煽るBGMを `volume=0.3` 程度でミックス
6. **出力**：`output/YYYYMMDD_HHMMSS.mp4` として保存（既存ファイルを上書きしない）

## FFmpegコマンドテンプレート

### Step1: 候補区間の仮切り出し（確認用、末尾から30秒）
```bash
# 総尺を取得
DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 input/{ファイル名}.mp4)
START=$(echo "$DURATION - 30" | bc)

ffmpeg -ss $START -i input/{ファイル名}.mp4 \
  -c:v libx264 -preset veryfast -crf 23 \
  -c:a aac \
  output/_preview_{ファイル名}.mp4
```
このプレビューをユーザーに提示し、開始位置・煽りフェーズの重ね位置を確認・調整してから Step2 に進む。

### Step2: 確定した区間で本エンコード＋30fps化
開始位置（`{確定した開始秒数}`）と終了位置（`{確定した終了秒数}`、通常は素材の末尾）はStep1の確認結果に基づいて決める。長さは固定しない。
```bash
ffmpeg -ss {確定した開始秒数} -to {確定した終了秒数} -i input/{ファイル名}.mp4 \
  -vf "fps=30" \
  -c:v libx264 -preset medium -crf 20 \
  -c:a aac -ar 44100 -b:a 128k \
  -movflags +faststart \
  output/{YYYYMMDD_HHMMSS}_raw.mp4
```

### 煽りテキストの焼き込み（煽りフェーズの区間、目安0〜3秒程度に表示）
```bash
ffmpeg -i output/{YYYYMMDD_HHMMSS}_raw.mp4 \
  -vf "drawtext=fontfile=fonts/NotoSansJP.ttf:text='3秒で入る球予想してね！':\
fontcolor=white:fontsize=64:box=1:boxcolor=black@0.5:boxborderw=10:\
x=(w-text_w)/2:y=100:enable='between(t,{煽り開始秒},{煽り終了秒})'" \
  -c:v libx264 -preset medium -crf 20 \
  -c:a copy \
  output/{YYYYMMDD_HHMMSS}_text.mp4
```

### （任意）結果フェーズのテキスト焼き込み
結果を強調したい場合は、同様に `drawtext` を追加し `enable='between(t,{結果開始秒},{結果終了秒})'` で結果フェーズの区間にのみ表示する。

### BGM合成（最終出力、動画の全尺に合わせる）
```bash
ffmpeg -i output/{YYYYMMDD_HHMMSS}_text.mp4 -i bgm/{BGMファイル名}.mp3 \
  -filter_complex "[1:a]volume=0.3,atrim=0:{動画の全尺秒数}[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]" \
  -map 0:v -map "[aout]" \
  -c:v copy \
  -c:a aac -ar 44100 -b:a 128k \
  -movflags +faststart \
  output/{YYYYMMDD_HHMMSS}.mp4
```
※ 中間ファイル（`_raw.mp4`, `_text.mp4`）は最終出力生成後に削除してよい

## エラー時の対処
- 見どころ区間がうまく特定できない → `-ss` の候補を複数試し、静止画（`-vframes 1`）で書き出して目視確認してから本エンコードする
- フォントが見つからない → `fonts/NotoSansJP.ttf` の存在とパスを確認
- 音声がずれる → `-async 1` オプションを追加
- 球の動きが不自然に途切れる → レースフェーズを削りすぎている可能性があるため、開始位置をより早めに調整する
