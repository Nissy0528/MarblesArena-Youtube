# -*- coding: utf-8 -*-
"""Marbles Arena Shorts 編集スクリプト（skills/edit_video/SKILL.md 準拠）

半自動フロー:
  1. info     : ffprobe で素材の長さ・解像度・fps を確認する
  2. preview  : 仮切り出し（初期ルール: 末尾から30秒〜末尾）を出力し、ユーザー確認用に提示する
  3. finalize : 確定した区間で本編集（30fps化 → 煽りテキスト焼き込み → BGM合成）を行う

使用例:
  python scripts/edit.py info "input/N021_ピンク黃緑オレンジ_ピンクオレンジ_緑場外.mp4"
  python scripts/edit.py preview "input/N021_....mp4"                # 末尾から30秒で仮切り出し
  python scripts/edit.py preview "input/N021_....mp4" --start 28.5   # 開始位置を手動調整して再提示
  python scripts/edit.py preview "input/N021_....mp4" --stills 4     # 確認用静止画も出力
  python scripts/edit.py finalize "input/N021_....mp4" --start 31.0  # 確定後の本編集
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "input"
BGM_DIR = PROJECT_ROOT / "bgm"
OUTPUT_DIR = PROJECT_ROOT / "output"
FONT_REL = "fonts/NotoSansJP.ttf"  # drawtext はプロジェクトルート起点の相対パスで渡す（Windowsのドライブ文字対策）

AORI_TEXT = "3秒で入る球予想してね！"
BGM_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg")
PREVIEW_TAIL_SECONDS = 30.0  # 仮切り出しの初期ルール: 末尾から30秒


def run_ffmpeg(args, description):
    """ffmpeg/ffprobe をプロジェクトルート起点で実行する。失敗時は stderr 末尾を表示して終了。"""
    print(f"[edit] {description}")
    proc = subprocess.run(args, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.splitlines()[-15:])
        print(f"[edit] コマンド失敗: {' '.join(args)}\n{tail}", file=sys.stderr)
        sys.exit(1)
    return proc


def probe(path):
    """素材の duration / width / height / fps を返す。"""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate:format=duration",
         "-of", "json", str(path)],
        cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(f"[edit] ffprobe 失敗: {path}\n{proc.stderr}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(proc.stdout)
    stream = data["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    return {
        "duration": float(data["format"]["duration"]),
        "width": stream["width"],
        "height": stream["height"],
        "fps": float(num) / float(den),
    }


def resolve_input(name):
    path = Path(name)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        candidate = INPUT_DIR / Path(name).name
        if candidate.exists():
            path = candidate
        else:
            print(f"[edit] 入力ファイルが見つかりません: {name}", file=sys.stderr)
            sys.exit(1)
    return path


def unique_output(stem, suffix=".mp4"):
    """output/ に既存ファイルを上書きしない一意なパスを返す。"""
    path = OUTPUT_DIR / f"{stem}{suffix}"
    n = 2
    while path.exists():
        path = OUTPUT_DIR / f"{stem}_{n}{suffix}"
        n += 1
    return path


def pick_bgm(explicit=None):
    """bgm/ の既存音源を使う（新規選定はしない）。複数ある場合は名前順の先頭。"""
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            print(f"[edit] BGMファイルが見つかりません: {explicit}", file=sys.stderr)
            sys.exit(1)
        return path
    candidates = sorted(p for p in BGM_DIR.iterdir() if p.suffix.lower() in BGM_EXTS) if BGM_DIR.exists() else []
    if not candidates:
        print("[edit] bgm/ にBGM素材がありません。既存BGMを bgm/ に配置してください。", file=sys.stderr)
        sys.exit(1)
    return candidates[0]


def drawtext_filter(textfile_rel, start, end, fontsize=64, y="100"):
    return (
        f"drawtext=fontfile={FONT_REL}:textfile={textfile_rel}:"
        f"fontcolor=white:fontsize={fontsize}:box=1:boxcolor=black@0.5:boxborderw=10:"
        f"x=(w-text_w)/2:y={y}:enable='between(t,{start:g},{end:g})'"
    )


def cmd_info(args):
    path = resolve_input(args.file)
    info = probe(path)
    print(f"ファイル      : {path.name}")
    print(f"長さ          : {info['duration']:.2f} 秒")
    print(f"解像度        : {info['width']}x{info['height']}")
    print(f"フレームレート: {info['fps']:.2f} fps")
    start = max(info["duration"] - PREVIEW_TAIL_SECONDS, 0.0)
    print(f"仮切り出し候補: {start:.2f} 秒 〜 末尾（末尾から{PREVIEW_TAIL_SECONDS:g}秒ルール）")


def cmd_preview(args):
    path = resolve_input(args.file)
    info = probe(path)
    duration = info["duration"]
    start = args.start if args.start is not None else max(duration - PREVIEW_TAIL_SECONDS, 0.0)
    if start >= duration:
        print(f"[edit] 開始位置 {start:g} 秒が総尺 {duration:.2f} 秒を超えています。", file=sys.stderr)
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)
    preview_path = unique_output(f"_preview_{path.stem}")
    run_ffmpeg(
        ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(path),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac",
         str(preview_path)],
        f"仮切り出し中（{start:.2f}秒〜末尾、約{duration - start:.1f}秒）")

    stills = []
    if args.stills:
        span = duration - start
        for i in range(args.stills):
            t = start + span * i / max(args.stills - 1, 1)
            t = min(t, duration - 0.1)
            still = unique_output(f"_preview_{path.stem}_{i + 1:02d}", ".jpg")
            run_ffmpeg(
                ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(path), "-vframes", "1", str(still)],
                f"静止画書き出し（{t:.2f}秒地点）")
            stills.append(still)

    print()
    print(f"仮切り出しプレビュー: {preview_path.relative_to(PROJECT_ROOT)}")
    for s in stills:
        print(f"確認用静止画        : {s.relative_to(PROJECT_ROOT)}")
    print()
    print("【確認事項】")
    print(" 1. 球が動き出す瞬間から結果までが過不足なく含まれているか")
    print(" 2. 煽りフェーズを重ねる位置（球が動く直前の場面）が適切か")
    print(" 3. 結果が決まる瞬間がちゃんと含まれているか")
    print("問題なければ以下で本編集に進んでください:")
    print(f'  python scripts/edit.py finalize "{args.file}" --start {start:.2f}')
    print("ズレがある場合は --start を前後に調整して preview を再実行してください。")


def cmd_finalize(args):
    path = resolve_input(args.file)
    info = probe(path)
    duration = info["duration"]
    start = args.start
    end = args.end if args.end is not None else duration
    if not (0 <= start < end <= duration + 0.5):
        print(f"[edit] 区間指定が不正です（start={start:g}, end={end:g}, 総尺={duration:.2f}）。", file=sys.stderr)
        sys.exit(1)
    clip_len = end - start
    if not 15 <= clip_len <= 35:
        print(f"[edit] 注意: 切り出し尺が {clip_len:.1f} 秒です（目安は20〜30秒）。意図した区間か確認してください。")

    font_path = PROJECT_ROOT / FONT_REL
    if not font_path.exists():
        print(f"[edit] フォントが見つかりません: {FONT_REL}", file=sys.stderr)
        sys.exit(1)
    bgm = pick_bgm(args.bgm)

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = OUTPUT_DIR / f"{stamp}_raw.mp4"
    text_path = OUTPUT_DIR / f"{stamp}_text.mp4"
    final_path = unique_output(stamp)
    temp_files = [raw_path, text_path]

    # Step2: 確定区間の本エンコード＋30fps化
    run_ffmpeg(
        ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(path),
         "-vf", "fps=30",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-c:a", "aac", "-ar", "44100", "-b:a", "128k",
         "-movflags", "+faststart",
         str(raw_path)],
        f"本エンコード中（{start:.2f}〜{end:.2f}秒、30fps化）")

    # 煽りテキスト（＋任意で結果テキスト）の焼き込み。
    # 日本語テキストはエスケープ問題を避けるため textfile で渡す。
    aori_txt = OUTPUT_DIR / f"{stamp}_aori.txt"
    aori_txt.write_text(AORI_TEXT, encoding="utf-8")
    temp_files.append(aori_txt)
    filters = [drawtext_filter(aori_txt.relative_to(PROJECT_ROOT).as_posix(), args.aori_start, args.aori_end)]
    if args.result_text:
        result_txt = OUTPUT_DIR / f"{stamp}_result.txt"
        result_txt.write_text(args.result_text, encoding="utf-8")
        temp_files.append(result_txt)
        result_start = args.result_start if args.result_start is not None else max(clip_len - 3.0, 0.0)
        result_end = args.result_end if args.result_end is not None else clip_len
        filters.append(drawtext_filter(result_txt.relative_to(PROJECT_ROOT).as_posix(),
                                       result_start, result_end, y="h-300"))
    run_ffmpeg(
        ["ffmpeg", "-y", "-i", str(raw_path),
         "-vf", ",".join(filters),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-c:a", "copy",
         str(text_path)],
        "テキスト焼き込み中")

    # BGM合成（volume=0.3 基準、動画の全尺に合わせる。BGMが短い場合はループ）
    run_ffmpeg(
        ["ffmpeg", "-y", "-i", str(text_path), "-stream_loop", "-1", "-i", str(bgm),
         "-filter_complex",
         f"[1:a]volume={args.bgm_volume},atrim=0:{clip_len:.3f}[bgm];"
         f"[0:a][bgm]amix=inputs=2:duration=first[aout]",
         "-map", "0:v", "-map", "[aout]",
         "-c:v", "copy",
         "-c:a", "aac", "-ar", "44100", "-b:a", "128k",
         "-movflags", "+faststart",
         str(final_path)],
        f"BGM合成中（{bgm.name}, volume={args.bgm_volume}）")

    if not args.keep_temp:
        for tmp in temp_files:
            tmp.unlink(missing_ok=True)

    out_info = probe(final_path)
    print()
    print(f"完成: {final_path.relative_to(PROJECT_ROOT)}")
    print(f"  長さ: {out_info['duration']:.2f} 秒 / {out_info['width']}x{out_info['height']} / {out_info['fps']:.0f}fps")
    print(f"  BGM : {bgm.name}（volume={args.bgm_volume}）")


def main():
    parser = argparse.ArgumentParser(description="Marbles Arena Shorts 編集スクリプト")
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="素材の長さ・解像度・fpsを確認する")
    p_info.add_argument("file", help="input/ 内の素材ファイル")
    p_info.set_defaults(func=cmd_info)

    p_prev = sub.add_parser("preview", help="候補区間を仮切り出しして確認用に出力する")
    p_prev.add_argument("file", help="input/ 内の素材ファイル")
    p_prev.add_argument("--start", type=float, help="候補開始秒（省略時は末尾から30秒）")
    p_prev.add_argument("--stills", type=int, help="確認用静止画の枚数（例: 4）")
    p_prev.set_defaults(func=cmd_preview)

    p_fin = sub.add_parser("finalize", help="確定した区間で本編集する（ユーザー確認後にのみ実行）")
    p_fin.add_argument("file", help="input/ 内の素材ファイル")
    p_fin.add_argument("--start", type=float, required=True, help="確定した開始秒")
    p_fin.add_argument("--end", type=float, help="確定した終了秒（省略時は素材の末尾）")
    p_fin.add_argument("--aori-start", type=float, default=0.0, help="煽りテキスト表示開始秒（切り出し後基準、既定0）")
    p_fin.add_argument("--aori-end", type=float, default=3.0, help="煽りテキスト表示終了秒（既定3）")
    p_fin.add_argument("--result-text", help="結果フェーズに焼き込むテキスト（任意）")
    p_fin.add_argument("--result-start", type=float, help="結果テキスト表示開始秒（省略時は末尾3秒前）")
    p_fin.add_argument("--result-end", type=float, help="結果テキスト表示終了秒（省略時は末尾）")
    p_fin.add_argument("--bgm", help="使用するBGMファイル（省略時は bgm/ の既存音源を自動選択）")
    p_fin.add_argument("--bgm-volume", type=float, default=0.3, help="BGM音量（既定0.3）")
    p_fin.add_argument("--keep-temp", action="store_true", help="中間ファイル（_raw/_text）を残す")
    p_fin.set_defaults(func=cmd_finalize)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
