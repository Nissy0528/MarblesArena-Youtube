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
ASSETS_DIR = PROJECT_ROOT / "assets"  # 再利用するオーバーレイ動画（購読ボタン・Thank you等）
FONT_REL = "fonts/NotoSansJP.ttf"  # drawtext はプロジェクトルート起点の相対パスで渡す（Windowsのドライブ文字対策）

# テキスト（イメージ動画 026_N016 準拠）
AORI_TEXT = "何色が入る？？"
ENGLISH_SUBTITLE = "Which ball color goes into the goal?"

BGM_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg")
PREVIEW_TAIL_SECONDS = 30.0  # 仮切り出しの初期ルール: 末尾から30秒

# 額縁レイアウト
INNER_SCALE = 0.91  # 内側に置くゲーム映像の横幅比率（外周はぼかし背景）

# SUBSCRIBE / Thank you の垂直中心の既定値（下部）。--sub-y で調整可。両者をこの高さに揃える。
CTA_CENTER_Y_DEFAULT = 1560

# オーバーレイ動画のデフォルト（assets/ → input/ の順に探す）
SUBSCRIBE_CANDIDATES = ["サブスクライブ素材｜英語・シンプル・Youtube.mp4"]
THANKYOU_CANDIDATES = ["67183_1280x720.mp4"]
CHROMAKEY_GREEN = "0x1efc1e"  # 購読ボタン素材のグリーンバック


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


def resolve_overlay(explicit, candidates):
    """オーバーレイ動画を assets/ → input/ の順に探す。見つからなければ None（その要素はスキップ）。"""
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path if path.exists() else None
    for name in candidates:
        for base in (ASSETS_DIR, INPUT_DIR):
            cand = base / name
            if cand.exists():
                return cand
    return None


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
    subscribe = None if args.no_subscribe else resolve_overlay(args.subscribe, SUBSCRIBE_CANDIDATES)
    thankyou = None if args.no_thankyou else resolve_overlay(args.thankyou, THANKYOU_CANDIDATES)
    if not args.no_subscribe and subscribe is None:
        print("[edit] 注意: SUBSCRIBEオーバーレイ素材が見つかりません（この要素はスキップします）。")
    if not args.no_thankyou and thankyou is None:
        print("[edit] 注意: Thank youオーバーレイ素材が見つかりません（この要素はスキップします）。")

    # テロップ表示区間（切り出し後の秒数基準）
    aori_start, aori_end = args.aori_start, args.aori_end
    sub_start = args.sub_start if args.sub_start is not None else round(clip_len * 0.45, 2)
    sub_end = min(sub_start + args.sub_dur, clip_len)
    # Thank you は既定で SUBSCRIBE の直後に表示（購読が無い場合のみ末尾）
    if args.ty_start is not None:
        ty_start = args.ty_start
    elif subscribe is not None:
        ty_start = sub_end
    else:
        ty_start = max(clip_len - args.ty_dur, 0.0)
    ty_end = min(ty_start + args.ty_dur, clip_len)

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_path = unique_output(stamp)

    # 日本語・記号を含むテキストはエスケープ問題を避けるため textfile で渡す
    aori_txt = OUTPUT_DIR / f"{stamp}_aori.txt"
    eng_txt = OUTPUT_DIR / f"{stamp}_eng.txt"
    aori_txt.write_text(AORI_TEXT, encoding="utf-8")
    eng_txt.write_text(ENGLISH_SUBTITLE, encoding="utf-8")
    temp_files = [aori_txt, eng_txt]

    inner_w = round(1080 * INNER_SCALE / 2) * 2
    inner_h = round(1920 * INNER_SCALE / 2) * 2

    # 入力: 0=元素材(トリム), 1=BGM(ループ), 以降=オーバーレイ動画
    inputs = ["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(path),
              "-stream_loop", "-1", "-i", str(bgm)]
    next_idx = 2
    sub_idx = ty_idx = None
    if subscribe is not None:
        inputs += ["-i", str(subscribe)]
        sub_idx = next_idx
        next_idx += 1
    if thankyou is not None:
        inputs += ["-i", str(thankyou)]
        ty_idx = next_idx
        next_idx += 1

    aori_rel = aori_txt.relative_to(PROJECT_ROOT).as_posix()
    eng_rel = eng_txt.relative_to(PROJECT_ROOT).as_posix()

    # 額縁フレーム（外周ぼかし背景＋内側にゲーム映像）＋日英テキスト
    chain = [
        "[0:v]fps=30,split=2[a][b]",
        "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "boxblur=25:2,eq=brightness=-0.22[bg]",
        f"[b]scale={inner_w}:{inner_h}[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[v0]",
        f"[v0]drawtext=fontfile={FONT_REL}:textfile={aori_rel}:fontcolor={args.aori_color}:"
        f"fontsize=76:box=1:boxcolor=black@0.85:boxborderw=28:x=(w-text_w)/2:y=210:"
        f"enable='between(t,{aori_start:g},{aori_end:g})'[v1]",
        f"[v1]drawtext=fontfile={FONT_REL}:textfile={eng_rel}:fontcolor=white:fontsize=46:"
        f"borderw=3:bordercolor=black@0.6:x=(w-text_w)/2:y=1540:"
        f"enable='between(t,{aori_start:g},{aori_end:g})'[v2]",
    ]
    cur = "v2"
    # SUBSCRIBEオーバーレイ（グリーンバックをクロマキー）。
    # setpts で素材の再生開始を表示区間の頭に合わせる（区間到達時に素材が尽きるのを防ぐ）。
    if sub_idx is not None:
        # chromakey で緑背景を抜き、despill でボタン周囲に残る緑のフチ（スピル）を除去
        chain.append(f"[{sub_idx}:v]chromakey={CHROMAKEY_GREEN}:{args.sub_similarity:g}:{args.sub_blend:g},"
                     f"despill=type=green:mix={args.sub_despill:g}:expand=0.3,"
                     f"scale={args.sub_width}:-1,setpts=PTS-STARTPTS+{sub_start:g}/TB,format=rgba[sub]")
        chain.append(f"[{cur}][sub]overlay=(W-w)/2:{args.sub_y:g}-h/2:eof_action=pass:"
                     f"enable='between(t,{sub_start:g},{sub_end:g})'[v3]")
        cur = "v3"
    # Thank youオーバーレイ（黒背景を除去）
    if ty_idx is not None:
        # Thank you は SUBSCRIBE と同じ垂直中心（--sub-y）に配置
        ty_y = f"{args.sub_y:g}-h/2" if subscribe is not None else "(H-h)/2"
        chain.append(f"[{ty_idx}:v]colorkey=0x000000:0.18:0.08,scale=840:-1,"
                     f"setpts=PTS-STARTPTS+{ty_start:g}/TB,format=rgba[ty]")
        chain.append(f"[{cur}][ty]overlay=(W-w)/2:{ty_y}:eof_action=pass:"
                     f"enable='between(t,{ty_start:g},{ty_end:g})'[vout]")
        cur = "vout"
    # 音声: 元素材はミュートし、BGMのみを尺に合わせて乗せる
    chain.append(f"[1:a]volume={args.bgm_volume},atrim=0:{clip_len:.3f},asetpts=PTS-STARTPTS[aout]")

    run_ffmpeg(
        ["ffmpeg", "-y", *inputs,
         "-filter_complex", ";".join(chain),
         "-map", f"[{cur}]", "-map", "[aout]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-c:a", "aac", "-ar", "44100", "-b:a", "128k",
         "-movflags", "+faststart",
         str(final_path)],
        f"本編集中（額縁＋日英テキスト＋オーバーレイ合成、音声はBGMのみ volume={args.bgm_volume}）")

    if not args.keep_temp:
        for tmp in temp_files:
            tmp.unlink(missing_ok=True)

    out_info = probe(final_path)
    print()
    print(f"完成: {final_path.relative_to(PROJECT_ROOT)}")
    print(f"  長さ  : {out_info['duration']:.2f} 秒 / {out_info['width']}x{out_info['height']} / {out_info['fps']:.0f}fps")
    print(f"  音声  : BGMのみ {bgm.name}（volume={args.bgm_volume}、元素材の音声はミュート）")
    print(f"  煽り  : 「{AORI_TEXT}」+ 英語字幕（{aori_start:g}〜{aori_end:g}秒）")
    print(f"  購読  : {'合成あり（%g〜%g秒）' % (sub_start, sub_end) if sub_idx is not None else 'なし'}")
    print(f"  締め  : {'Thank you 合成あり（%g〜%g秒）' % (ty_start, ty_end) if ty_idx is not None else 'なし'}")


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
    p_fin.add_argument("--aori-start", type=float, default=0.0, help="煽り・英語字幕の表示開始秒（切り出し後基準、既定0）")
    p_fin.add_argument("--aori-end", type=float, default=4.0, help="煽り・英語字幕の表示終了秒（既定4）")
    p_fin.add_argument("--aori-color", default="0xff2fd0", help="煽りテキストの色（既定ピンク 0xff2fd0）")
    p_fin.add_argument("--sub-start", type=float, help="SUBSCRIBE表示開始秒（省略時は尺の45パーセント地点）")
    p_fin.add_argument("--sub-dur", type=float, default=3.5, help="SUBSCRIBE表示秒数（既定3.5）")
    p_fin.add_argument("--sub-width", type=int, default=1500, help="SUBSCRIBEオーバーレイの横幅px（既定1500。大きいほど大サイズ）")
    p_fin.add_argument("--sub-y", type=float, default=CTA_CENTER_Y_DEFAULT, help=f"SUBSCRIBE/Thank youの垂直中心px（既定{CTA_CENTER_Y_DEFAULT}）")
    p_fin.add_argument("--sub-similarity", type=float, default=0.12, help="SUBSCRIBEクロマキーの類似度しきい値（低いほど緑だけを抜き、ボタンは不透明。既定0.12）")
    p_fin.add_argument("--sub-blend", type=float, default=0.02, help="SUBSCRIBEクロマキーのブレンド（縁のなじませ。既定0.02）")
    p_fin.add_argument("--sub-despill", type=float, default=0.7, help="SUBSCRIBE緑スピル除去の強さ（0〜1、緑フチ消し。既定0.7）")
    p_fin.add_argument("--subscribe", help="SUBSCRIBEオーバーレイ動画（省略時は assets/→input/ から自動検出）")
    p_fin.add_argument("--no-subscribe", action="store_true", help="SUBSCRIBEオーバーレイを入れない")
    p_fin.add_argument("--ty-start", type=float, help="Thank you表示開始秒（省略時はSUBSCRIBE直後、購読なしなら末尾）")
    p_fin.add_argument("--ty-dur", type=float, default=4.0, help="Thank you表示秒数（既定4）")
    p_fin.add_argument("--thankyou", help="Thank youオーバーレイ動画（省略時は assets/→input/ から自動検出）")
    p_fin.add_argument("--no-thankyou", action="store_true", help="Thank youオーバーレイを入れない")
    p_fin.add_argument("--bgm", help="使用するBGMファイル（省略時は bgm/ の既存音源を自動選択）")
    p_fin.add_argument("--bgm-volume", type=float, default=0.5, help="BGM音量（既定0.5、元素材ミュートのためBGMが唯一の音声）")
    p_fin.add_argument("--keep-temp", action="store_true", help="中間テキストファイルを残す")
    p_fin.set_defaults(func=cmd_finalize)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
