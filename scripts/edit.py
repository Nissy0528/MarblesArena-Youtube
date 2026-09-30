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
import math
import os
import random
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "input"
BGM_DIR = PROJECT_ROOT / "bgm"
OUTPUT_DIR = PROJECT_ROOT / "output"
ASSETS_DIR = PROJECT_ROOT / "assets"  # 再利用するオーバーレイ動画（購読ボタン・Thank you等）
# drawtext はプロジェクトルート起点の相対パスで渡す（Windowsのドライブ文字対策）
FONT_REL = "fonts/CherryBombOne-Regular.ttf"   # 既定フォント（英字・かな。漢字グリフは持たない）
FONT_KANJI_REL = "fonts/NotoSansJP.ttf"        # 漢字を含むテキスト用（煽り「何色が入る？？」）

# テキスト（イメージ動画 026_N016 準拠）
AORI_TEXT = "何色が入る？？"
AORI_GROW = 0.4                  # 煽り：背景が中央から左右に伸びきるまでの秒数
AORI_HGROW = 0.4                 # 煽り：背景の縦幅が定寸法に収まるまでの秒数
AORI_FLASH_END = 0.3             # 煽り：背景の黄/黒の点滅が終わる秒数（以降は黒）
AORI_TEXT_GROW = 0.3             # 煽り：文字が上から出きるまでの秒数
AORI_APPEAR_DUR = max(AORI_GROW, AORI_HGROW, AORI_FLASH_END, AORI_TEXT_GROW)  # 出現演出の全体
# 煽りと同時に左上へ出す装飾文字「MARBLE」（3段・黒の中抜き文字・右上がりに傾ける・画面外へはみ出す）
MARBLE_TEXT = "MARBLE"
MARBLE_FONTSIZE = 170
MARBLE_ROW_PITCH = 150           # 3段の縦ピッチ（回転前）
MARBLE_STROKE = 3                # 輪郭線の太さ
MARBLE_CANVAS = 1400             # 回転用の透明キャンバスの一辺
MARBLE_CENTER_X, MARBLE_CENTER_Y = 240, 250   # 文字ブロック中心の画面座標（左上へはみ出す位置）
MARBLE_ANGLE_DEG = 45            # 右上がりに傾ける角度
MARBLE_MOVE_PX = 40              # 文字から見て下→上へ動かす量（画面上では右下→左上）
MARBLE_ANIM_DUR = AORI_APPEAR_DUR  # フェードイン・下段の上→下表示・上への移動を同時に行う秒数
# 結果表示の背景バナー（弾が画面から全て消えたら表示。横長の長方形・黄/黒の点滅・下から上へ高さが広がる）
RESULT_BANNER_W = 900
RESULT_BANNER_H = 130
RESULT_BANNER_MIN_H = 6          # 出始めの潰れた高さ
RESULT_GROW = 0.3                # 高さが広がりきるまでの秒数
RESULT_FLASH_END = 0.3           # 黄→黒→黄→黒の点滅が終わる秒数（以降は黒）
RESULT_Y_DEFAULT = 560           # バナー中心の縦位置（画面中央960より上。バナー3個分）
RESULT_BAND_PAD = 100            # 帯レイヤーをバナーの上下に広げる余白（当たり色の文字ぶん）
RESULT_LABEL_FONTSIZE = 110      # 当たりの穴に入った玉の色を示す文字の大きさ
RESULT_LABEL_REVEAL = 0.3        # 当たり色の文字が生えきるまでの秒数
RESULT_LABEL_GAP = 4             # バナーの縁と当たり色の文字のすき間
# 当たりが1色だけのとき（バナーは上から下へ伸び、色名は下から上へ出現して短く点滅）
SINGLE_RISE = 0.12               # 色名が下から上へ出現しきるまでの秒数（速め）
SINGLE_FLASH_STEP = 0.06         # 白/色の切り替え間隔（短め）
SINGLE_FLASH_DUR = 0.36          # 点滅を続ける秒数（短め）
# バナー左下の「＞＞＞」（フォントではなく図形として描く。黒→半透明→…と変化しながら左右に揺れる）
CHEV_COUNT = 3
CHEV_PITCH = 99                  # 3つの間隔px
CHEV_INSET = 10                  # バナー左端からの寄せ幅px
CHEV_HALF_H = 40                 # 縦の半分の長さpx
CHEV_ARM = 39                    # 先端が右に出る長さpx
CHEV_THICK = 16                  # 帯の太さの半分px
CHEV_OUTLINE = 2                 # 黄色の枠線の太さpx
CHEV_AA = 1.2                    # 輪郭のぼかし幅px（ギザつき防止）
CHEV_OUTLINE_COLOR = (241, 196, 15)   # 枠線の色（バナーの黄色と同じ）
CHEV_SWAY_PX = 10                # 左右に揺れる幅px
CHEV_SWAY_PERIOD = 1.2           # 揺れ1往復の秒数
CHEV_SWAY_DELAY = 0.12           # 左から順に揺れ始めを遅らせる秒数
CHEV_PHASE = 0.28                # 色の演出1段階の秒数（段階から段階への間隔）
CHEV_STEP = 0.07                 # 1段階のなかで左から1つずつずらす秒数
CHEV_TRANS = 0.15                # 1つぶんの色変化にかける秒数
# バナー中央の「GOAL!GOAL!GOAL!」（白・奥から手前へ拡大・真ん中の「GOAL!」だけ上にずれて見切れた状態から下りてくる）
GOAL_TEXT = "GOAL!GOAL!GOAL!"
GOAL_FONTSIZE = 90               # 全体幅809px・高さ62px（バナー900x130pxに収まる）
GOAL_ZOOM_FROM = 0.2             # 奥にいるときの大きさ（原寸比）
GOAL_ZOOM_MID = 0.5              # 一旦止まる大きさ
GOAL_ZOOM1_DUR = 0.4             # 奥→半分の大きさまでの秒数
GOAL_ZOOM1_EASE = 5              # 奥→半分の減速の強さ（大きいほど最初速く、だんだんゆっくり）
GOAL_HOLD = 0.3                  # 半分の大きさで止まり、その間に真ん中の「GOAL!」が他の文字の高さへ下りる秒数
GOAL_ZOOM2_DUR = 0.25            # 半分→原寸までの秒数（この開始と同時にバナーを出す）
GOAL_FLASH_RGB = (255, 0, 0)     # 2色のときの点滅色（白⇔赤）。3色のときは3色目の色⇔白になる
GOAL_FLASH_STEP = 0.1            # 文字が出てから拡大しきるまでの白/赤の切り替え間隔（秒）。30fpsで3コマずつ
GOAL_MOVE_IDX = (5, 9)           # 上にずらして動かす文字の範囲（真ん中の「GOAL!」）
GOAL_MOVE_CUT = 2 / 3            # 真ん中の「GOAL!」が見切れる割合（文字の高さに対して）。上にずらして枠の上辺より上に出す
ENGLISH_SUBTITLE = "Which ball color goes into the goal?"
ENG_FONTSIZE = 46                # 英語字幕のフォントサイズ
ENG_Y = 1540                     # 英語字幕の描画Y（上端）
ENG_STRETCH = 20.8               # 字幕アニメの初期の縦倍率
ENG_ORDER_SEED = 7               # 伸縮順のランダム化シード（固定して再現性を保つ）
ENG_CHAR_DUR = 0.30              # 1文字が元サイズに戻るまでの秒数
ENG_ANIM_TOTAL = 2.0             # 全文字の伸縮が終わるまでの秒数（開始をこの範囲に散らす）
ENG_BLUR = 20.0                  # 伸縮開始時のブラー強さ（終了に向けて0＝くっきりへ）
ENG_FADE_START = 0.12            # フェード開始（1文字の伸縮時間に対する比。それ以前は完全に透明）
ENG_FADE_END = 0.75              # フェード完了＝ブラーが消える比（伸縮の終わりを待たず不透明にする）
ENG_OUT_CHAR_DUR = 0.30          # 退場：1文字がブラー＋フェードアウトで消えるまでの秒数
ENG_OUT_TOTAL = 1.0              # 退場：左端の文字が消え始めてから右端が消え切るまでの秒数
ENG_BLUR_GAIN = 9.0              # ブラー版のアルファ補正（ぼかしで薄まったぶんを戻す。実測値ベース）
# 退場用のブラーは登場より控えめにする。登場と同じ強いブラー×9倍補正だと、ぼかしのすそ野まで
# 明るくなり、1文字ごとの帯で切られて「文字の後ろに光る四角」が出るため（検証で決定）。
ENG_OUT_BLUR = 40.0              # 退場：消えるときのブラー強さ（文字の形が読めなくなるくらい）
ENG_OUT_BLUR_GAIN = 4.0          # 退場：ブラー版のアルファ補正（σ40で濃さ約25%→元の濃さに戻す）
ENG_OUT_BLUR_RAMP = 0.35         # 退場：1文字の消え始めからこの比率でブラーを強め切る（フェードより先）

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
SUBSCRIBE_LEAD_IN = 0.23      # 購読ボタン素材の先頭にある緑だけの区間（秒）。切り詰めて表示開始と同時にボタンを出す
SUBSCRIBE_ANIM_END = 3.7      # 購読ボタン素材（先頭を切り詰めた後）の演出が止まる秒数（クリック→SUBSCRIBED→ベルが落ち着くまで）
SUBSCRIBE_FADE_OUT = 0.5      # 演出が止まった後、フェードアウトで退場させる秒数

# 色選択肢カードの色定義: colorkey -> (英語ラベル, ふりがな, 塗り色, 文字色)
COLOR_MAP = {
    "black":       ("BLACK", "くろ", "0x1a1a1a", "white"),
    "white":       ("WHITE", "しろ", "0xe8e8e8", "0x222222"),
    "pink":        ("PINK", "ピンク", "0xe0289f", "white"),
    "purple":      ("PURPLE", "むらさき", "0x7b2fbf", "white"),
    "red":         ("RED", "あか", "0xe01e1e", "white"),
    "green":       ("GREEN", "みどり", "0x27ae35", "white"),
    "orange":      ("ORANGE", "オレンジ", "0xff8c00", "white"),
    "blue":        ("BLUE", "あお", "0x2e6fdb", "white"),
    "yellow":      ("YELLOW", "きいろ", "0xf1c40f", "0x222222"),
    "lightblue":   ("LIGHT BLUE", "みずいろ", "0x4fc3f7", "0x222222"),
}
# ファイル名の色ラベル → colorkey（長い語を先に並べて貪欲マッチ。黃/黄の表記ゆれに対応）
# ※このゲームでは「黃緑/黄緑/きみどり」表記の球は実際は黄色（yellow）として扱う（きみどりは使用しない）
COLOR_KEYWORDS = [
    ("むらさき", "purple"), ("みずいろ", "lightblue"), ("きみどり", "yellow"),
    ("黄緑", "yellow"), ("黃緑", "yellow"), ("オレンジ", "orange"),
    ("ピンク", "pink"), ("みどり", "green"), ("きいろ", "yellow"), ("水色", "lightblue"),
    ("紫", "purple"), ("黒", "black"), ("白", "white"), ("赤", "red"),
    ("緑", "green"), ("青", "blue"), ("黄", "yellow"),
]


def run_ffmpeg(args, description):
    """ffmpeg/ffprobe をプロジェクトルート起点で実行する。失敗時は stderr 末尾を表示して終了。
    filter_complex は一時ファイルに書き出して -/filter_complex で渡す。アニメの式が長く、そのまま渡すと
    Windows のコマンドライン長の上限（約32,000文字）を超えてプロセスを起動できないため。"""
    print(f"[edit] {description}")
    args = list(args)
    fc_file = None
    if "-filter_complex" in args:
        i = args.index("-filter_complex")
        OUTPUT_DIR.mkdir(exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="_fc_", suffix=".txt", dir=OUTPUT_DIR)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(args[i + 1])
        fc_file = Path(name)
        args[i:i + 2] = ["-/filter_complex", str(fc_file)]
    proc = subprocess.run(args, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.splitlines()[-15:])
        keep = f"（フィルタ定義は {fc_file.name} に残しています）" if fc_file else ""
        print(f"[edit] コマンド失敗{keep}: {' '.join(args)}\n{tail}", file=sys.stderr)
        sys.exit(1)
    if fc_file is not None:
        fc_file.unlink(missing_ok=True)
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


def tokenize_colors(text):
    """色名の連結文字列（例 'ピンク黃緑オレンジ'）を colorkey のリストに分解。色以外が混じれば None。"""
    keys = []
    i = 0
    while i < len(text):
        for kw, ck in COLOR_KEYWORDS:
            if text.startswith(kw, i):
                keys.append(ck)
                i += len(kw)
                break
        else:
            return None
    return keys or None


def parse_colors_from_filename(stem):
    """ファイル名の各セグメントから、色のみで構成された最初のセグメントを色リストとして返す。"""
    for seg in stem.split("_"):
        keys = tokenize_colors(seg)
        if keys and len(keys) >= 2:
            deduped = []
            for k in keys:
                if k not in deduped:
                    deduped.append(k)
            return deduped
    return []


def hex_to_rgb(color):
    """COLOR_MAP の "0xrrggbb" 形式を (r, g, b) に変換する。"""
    v = int(color, 16)
    return (v >> 16) & 255, (v >> 8) & 255, v & 255


def parse_result_colors(stem):
    """ファイル名から「当たりの穴に入った玉の色」を返す。
    例: N021_ピンク黃緑オレンジ_ピンクオレンジ_緑場外 → 1つ目=レースに絡む玉、2つ目=入った玉 → [pink, orange]"""
    segs = []
    for seg in stem.split("_"):
        keys = tokenize_colors(seg)
        if not keys:
            continue
        deduped = []
        for k in keys:
            if k not in deduped:
                deduped.append(k)
        segs.append(deduped)
    return segs[1] if len(segs) >= 2 else []


CARD_W, CARD_H = 400, 116        # 高さは基準96の約1.2倍
CARD_LINE_EXT = 24               # 白線をピルより左右に伸ばす量（片側12px）
CARD_MARGIN = 76                 # 1カード内のピル下〜次カードまでの余白（白線+ふりがな+マージン）
CARD_ROW_PITCH = CARD_H + CARD_MARGIN   # 行の縦ピッチ（ピル高に連動）
CARD_TOP = 250                   # 先頭カードの上端Y
CARD_REVEAL = 0.3                # 各段が左→右に伸びきるまでの秒数（小さいほど速い）
CARD_B_DELAY = 0.5               # ②ピルが伸び始めるまでの秒数（①白線＋ふりがなの後）
CARD_C_DELAY = CARD_B_DELAY + 0.6 * CARD_REVEAL   # ③英語ラベル（ピルが約6割伸びたら開始）
CARD_ANIM_TOTAL = CARD_C_DELAY + CARD_REVEAL      # 登場アニメ全体の秒数
# 退場は右→左へ縮める。①白線＋ふりがな が先に縮み、8割縮んだら②ピル（＋その上の
# ③英語ラベル）が続く。ラベルはピルと一体に見せるため同時に縮める。
CARD_EXIT_A = 0.0                                 # ①白線＋ふりがな
CARD_EXIT_B = 0.8 * CARD_REVEAL                   # ②ピル（①が8割縮んだら）
CARD_EXIT_C = CARD_EXIT_B                         # ③英語ラベル（ピルと同時）
CARD_EXIT_TOTAL = CARD_EXIT_B + CARD_REVEAL       # 退場アニメ全体の秒数


def card_layer_height(n):
    """色カードの行数から、カード描画用透明レイヤーの高さを算出（geqの処理量を抑えるため必要分だけ）。"""
    rows = (n + 1) // 2
    h = min(1920, CARD_TOP + (rows - 1) * CARD_ROW_PITCH + CARD_H + CARD_MARGIN)
    return h + (h % 2)


def build_color_card_layers(colors, la, lb, lc, stamp, temp_files):
    """色カードを3つの透明レイヤーに描く（表示順に対応）。
    la=白線＋ふりがな層、lb=ピル層、lc=英語ラベル層。
    drawbox/drawtextは時間で位置を動かせないため描画は固定し、左→右の伸長は overlay 側の geq で行う。
    各カードの領域ボックス(left,right,top,bottom)も返す（geqで各カードを個別に伸ばすため）。
    (filters, la_out, lb_out, lc_out, boxes) を返す。"""
    card_w, card_h = CARD_W, CARD_H
    cols_x = [118, 562]          # 2列のX座標
    center_x = (1080 - card_w) // 2
    top, row_pitch = CARD_TOP, CARD_ROW_PITCH
    en_size, furi_size = 52, 30
    line_ext = CARD_LINE_EXT
    filters = []
    boxes = []
    n = len(colors)
    for idx, ck in enumerate(colors):
        if ck not in COLOR_MAP:
            continue
        en, furi, box, _txt = COLOR_MAP[ck]
        row, col = idx // 2, idx % 2
        alone = (idx == n - 1 and n % 2 == 1)   # 最後が1枚だけなら中央寄せ
        x = center_x if alone else cols_x[col]
        y = top + row * row_pitch
        line_y = y + card_h + 18
        furi_file = OUTPUT_DIR / f"{stamp}_furi_{idx}.txt"
        furi_file.write_text(furi, encoding="utf-8")
        temp_files.append(furi_file)
        furi_rel = furi_file.relative_to(PROJECT_ROOT).as_posix()
        # ── 層A: 白線＋ふりがな（replace=1で透明レイヤー上でも不透明化）──
        nlA, nfA = f"llA{idx}", f"lfA{idx}"
        filters.append(
            f"[{la}]drawbox=x={x - line_ext // 2}:y={line_y}:w={card_w + line_ext}:h=3:"
            f"color=white:t=fill:replace=1[{nlA}]")
        filters.append(
            f"[{nlA}]drawtext=fontfile={FONT_REL}:textfile={furi_rel}:fontcolor={box}:fontsize={furi_size}:"
            f"x={x}+({card_w}-text_w)/2:y={line_y + 12}[{nfA}]")
        la = nfA
        # ── 層B: ピル ──
        nbB = f"lbB{idx}"
        filters.append(f"[{lb}]drawbox=x={x}:y={y}:w={card_w}:h={card_h}:color={box}:t=fill:replace=1[{nbB}]")
        lb = nbB
        # ── 層C: 英語ラベル ──
        ntC = f"ltC{idx}"
        filters.append(
            f"[{lc}]drawtext=fontfile={FONT_REL}:text='{en}':fontcolor=white:fontsize={en_size}:"
            f"x={x}+({card_w}-text_w)/2:y={y}+({card_h}-text_h)/2[{ntC}]")
        lc = ntC
        # このカードの領域（白線の左端〜右端、上端〜ふりがな下端）
        boxes.append((x - line_ext // 2, x + card_w + line_ext // 2, y, line_y + 12 + furi_size + 10))
    return filters, la, lb, lc, boxes


def band_select(bands, leaves, clamp=False):
    """X座標が属する文字帯の式だけを評価する式を作る（帯の外は 0）。
    36文字ぶんの式を全画素で足し合わせると非常に遅いため、帯の左端で二分探索する
    入れ子の if にする（FFmpeg の if は選ばれた側しか評価しない）。bands はX昇順・連続。
    clamp=True なら文字列の左端より左は先頭の帯、右端より右は末尾の帯の式を使う
    （ブラーのにじみが文字列の両端で縦にスパッと切れないようにする）。"""
    xv = f"clip(X,{bands[0][0]},{bands[-1][1] - 1})" if clamp else "X"

    def build(lo, hi):
        if hi - lo == 1:
            bl, br = bands[lo]
            return "0" if br <= bl else f"if(gte({xv},{bl})*lt({xv},{br}),{leaves[lo]},0)"
        mid = (lo + hi) // 2
        return f"if(lt({xv},{bands[mid][0]}),{build(lo, mid)},{build(mid, hi)})"
    return build(0, len(bands))


def build_eng_exprs(bands, eng_cy, eng_g_out):
    """英語字幕アニメの式一式を作る（すべて再生時間 T 基準）。
    登場：文字ごと（ランダム順）に縦長→元サイズ＋フェードイン＋ブラー解除
    退場：eng_g_out から左→右へブラー＋フェードアウト
    戻り値: {"ysrc", "fade", "blur_in", "blur_out"}"""
    n = len(bands)
    # 伸縮の順番はランダム（左→右ではなくバラバラに戻る）
    order = list(range(n))
    random.Random(ENG_ORDER_SEED).shuffle(order)
    rank = {ci: r for r, ci in enumerate(order)}
    # 開始時刻を 0〜(全体-1文字ぶん) にランダムな順で散らす → 終わるタイミングも文字ごとにバラバラ
    span = max(0.0, ENG_ANIM_TOTAL - ENG_CHAR_DUR) / max(1, n - 1)
    terms, fades, blurs = [], [], []                 # 文字ごとの式（帯の判定は band_select で行う）
    for i in range(n):
        d = rank[i] * span                           # 文字ごとに開始をずらす（順不同）
        prog = f"clip((T-{d:g})/{ENG_CHAR_DUR:g},0,1)"   # 伸縮の進捗 0→1
        # 縦倍率は対数補間。線形だと終盤まで3倍前後の縦長が残り、最後の1フレームで
        # 一気に元サイズへ落ちて「急に切り替わった」ように見えるため。
        scale = f"pow({ENG_STRETCH:g},1-{prog})"
        terms.append(f"(Y-{eng_cy:g})*(1/{scale}-1)")
        # フェードイン。伸縮の頭は完全に透明のまま置き、伸縮が終わる前（ENG_FADE_END）に
        # 不透明へ到達させる。曲線はスムーズステップで、出だしも終わりもなだらか。
        fs = d + ENG_FADE_START * ENG_CHAR_DUR
        fw = (ENG_FADE_END - ENG_FADE_START) * ENG_CHAR_DUR
        fp = f"clip((T-{fs:g})/{fw:g},0,1)"
        fades.append(f"({fp}*{fp}*(3-2*{fp}))")
        # 登場のブラー量（開始1→0）。不透明になる時点でブラーも消し、透けた見え方を残さない
        blurs.append(f"1-clip((T-{d:g})/{ENG_FADE_END * ENG_CHAR_DUR:g},0,1)")
    # 退場は文字の帯ごとではなく、X座標の連続関数で左→右へ進める。帯ごとに切り替えると
    # ブラーのにじみが帯の境目で縦に切れ、「文字の後ろに光る四角」が出るため。
    # 隣の文字との開始差は約0.02秒なので、見た目は1文字ずつ消えていく。
    x0, x1 = bands[0][0], bands[-1][0]
    rate = max(0.0, ENG_OUT_TOTAL - ENG_OUT_CHAR_DUR) / max(1, x1 - x0)
    op = f"clip((T-{eng_g_out:g}-(clip(X,{x0},{x1})-{x0})*{rate:g})/{ENG_OUT_CHAR_DUR:g},0,1)"
    return {
        "ysrc": "Y+" + band_select(bands, terms),    # 縦倍率sのぶんだけ元画像を縮めて拾う
        "fade": f"{band_select(bands, fades, clamp=True)}*(1-{op}*{op}*(3-2*{op}))",
        "blur_in": band_select(bands, blurs, clamp=True),
        # ブラーはフェードより先に強め切る。同じ速さで進めると、半分消えた時点でも
        # くっきりした文字が半分混ざって形が読めてしまうため。
        "blur_out": f"clip({op}/{ENG_OUT_BLUR_RAMP:g},0,1)",
    }


def eng_layer_filter(src, dst, exprs, draw_x, draw_y, text_rel, offset=0.0):
    """英語字幕のアニメ付き透明レイヤーを作るフィルタ列。
    offset はそのセグメント開始時点の経過秒（式中の T をずらし、導入・本編をまたいで継続させる）。"""
    sh = (lambda e: e.replace("T-", f"T+{offset:g}-")) if offset else (lambda e: e)
    ys, fd = sh(exprs["ysrc"]), sh(exprs["fade"])
    bi, bo = sh(exprs["blur_in"]), sh(exprs["blur_out"])
    # シャープ版・登場用ブラー版・退場用ブラー版を作り、文字ごとのブラー量で順にブレンドする。
    # ブラー版はアルファが薄まるため補正倍率で戻す（しないと不透明度が「フェード×ブラー減衰」の
    # 二重掛けになり、フェードが終わっても透けて見える）。フェードはブレンド後に一度だけ掛ける。
    return (f"[{src}]format=rgba,colorchannelmixer=aa=0,"
            f"drawtext=fontfile={FONT_REL}:textfile={text_rel}:fontcolor=white:"
            f"fontsize={ENG_FONTSIZE}:x={draw_x}:y={draw_y:g},"
            f"geq=r='r(X,{ys})':g='g(X,{ys})':b='b(X,{ys})':"
            f"a='alpha(X,{ys})',split=3[{dst}S][{dst}B0][{dst}O0];"
            f"[{dst}B0]gblur=sigma={ENG_BLUR:g},"
            f"geq=r=255:g=255:b=255:a='min(255,alpha(X,Y)*{ENG_BLUR_GAIN:g})'[{dst}B];"
            f"[{dst}O0]gblur=sigma={ENG_OUT_BLUR:g},"
            f"geq=r=255:g=255:b=255:a='min(255,alpha(X,Y)*{ENG_OUT_BLUR_GAIN:g})'[{dst}O];"
            f"[{dst}S][{dst}B]blend=all_expr='A*(1-({bi}))+B*({bi})'[{dst}M];"
            f"[{dst}M][{dst}O]blend=all_expr='A*(1-({bo}))+B*({bo})'[{dst}N];"
            f"[{dst}N]geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            f"a='alpha(X,Y)*({fd})'[{dst}]")


def marble_layer_filter(src, dst, toff, disp_start):
    """左上の装飾文字「MARBLE」の透明レイヤーを作るフィルタ列と、overlay 用の x / y 式を返す。
    フェードイン・下段の上→下表示・下から上への移動を同時に行う（回転は最初から）。
    toff: そのセグメント開始時点で経過済みのアニメ秒数 / disp_start: セグメント内での表示開始秒"""
    c, fs, pitch, sw = MARBLE_CANVAS, MARBLE_FONTSIZE, MARBLE_ROW_PITCH, MARBLE_STROKE
    tops = [round(c / 2 - 0.6 * fs + (k - 1) * pitch) for k in range(3)]   # 各段の上端（回転前）
    base = f"fontfile={FONT_REL}:text={MARBLE_TEXT}:fontsize={fs}:fontcolor=white:x=(w-text_w)/2"

    def rows(extra=""):
        return ",".join(f"drawtext={base}:y={y}{extra}" for y in tops)

    tv = f"(T+{toff:g})" if toff else "T"
    p = f"clip({tv}/{MARBLE_ANIM_DUR:g},0,1)"
    # 下段だけ上→下に表示：回転前の座標で、下段の上端〜下端（インク高さは約0.7×文字サイズ）へ境界を動かす
    split = tops[2] - sw - 2                     # これより下が下段（中段のインクとは約30px離れている）
    r_top, r_bot = tops[2] - sw, tops[2] + round(0.75 * fs) + sw
    alpha = f"alpha(X,Y)*{p}*if(gt(Y,{split}),lte(Y,{r_top}+{p}*{r_bot - r_top}),1)"
    filters = (
        f"[{src}]format=rgba,colorchannelmixer=aa=0,split=2[{dst}o0][{dst}f0];"
        # 縁取り付きの文字から縁取りなしの文字を引いて輪郭線だけを残す（drawtext の縁取りは中まで埋まるため）。
        # blend は YUV だと色成分0が緑になるので、RGB平面（gbrap）で合成して黒にする。
        f"[{dst}o0]{rows(f':borderw={sw}:bordercolor=white')},format=gbrap[{dst}o];"
        f"[{dst}f0]{rows()},format=gbrap[{dst}f];"
        f"[{dst}o][{dst}f]blend=c0_expr='0':c1_expr='0':c2_expr='0':c3_expr='max(A-B,0)',format=rgba,"
        f"geq=r=0:g=0:b=0:a='{alpha}',"
        f"rotate=a=-{MARBLE_ANGLE_DEG:g}*PI/180:c=none:ow=iw:oh=ih,"
        f"setpts=PTS-STARTPTS+{disp_start:g}/TB[{dst}]")
    anim0 = disp_start - toff                      # セグメント内でのアニメ基準時刻
    rest = f"(1-clip((t-{anim0:g})/{MARBLE_ANIM_DUR:g},0,1))"   # 残りの移動量 1→0
    # 移動は文字から見た「下→上」。右上がりに傾けているので、文字の下方向は画面上の
    # (sin, cos) 方向（右下）になる。そこから定位置へ戻す＝画面上では右下→左上に動く。
    ang = math.radians(MARBLE_ANGLE_DEG)
    dx, dy = MARBLE_MOVE_PX * math.sin(ang), MARBLE_MOVE_PX * math.cos(ang)
    x = f"{MARBLE_CENTER_X - c // 2}+{dx:.3f}*{rest}"
    y = f"{MARBLE_CENTER_Y - c // 2}+{dy:.3f}*{rest}"
    return filters, x, y


def chevron_layer_filters(src, prefix, x_left, cy, t_show, shift):
    """バナー左下の「＞＞＞」を図形（V字の帯）として1枚のレイヤーに描くフィルタ列と出力ラベルを返す。
    フォントを使わず式で形を作るので、揺らしても像が二重にならず、枠線も常に全体に付く。
    色は「黒 →(半透明→黒)→(透明→黒)→(半透明+枠線→黒)→(透明+枠線)」の順に、左から1つずつ。"""
    h, arm, th = CHEV_HALF_H, CHEV_ARM, CHEV_THICK
    b_, aa = CHEV_OUTLINE, CHEV_AA
    fills, outs = [], []
    for i in range(CHEV_COUNT):
        base_x = x_left + i * CHEV_PITCH
        sway = (f"{CHEV_SWAY_PX}*sin(2*PI*(T-{t_show + i * CHEV_SWAY_DELAY:g})"
                f"/{CHEV_SWAY_PERIOD:g})")
        cx = f"({base_x:g}+{sway})"
        vy = f"abs(Y-{cy:g})"                                  # 中心からの縦距離
        xc = f"({cx}+{arm}*(1-min({vy},{h})/{h}))"             # その高さでの帯の中心X
        dx = f"abs(X-{xc})"
        soft = lambda d, r: f"clip(({r}-{d})/{aa:g}+0.5,0,1)"   # 端を少しぼかす
        fill = f"({soft(dx, th)}*{soft(vy, h)})"
        outer = f"({soft(dx, th + b_)}*{soft(vy, h + b_)})"
        inner = f"({soft(dx, th - b_)}*{soft(vy, h - b_)})"
        s0, s1, s2, s3 = (t_show + k * CHEV_PHASE + i * CHEV_STEP for k in range(4))
        q = [f"clip((T-{sk:g})/{CHEV_TRANS:g},0,1)" for sk in (s0, s1, s2, s3)]
        fa = (f"if(lt(T,{t_show:g}),0,if(lt(T,{s0:g}),1,if(lt(T,{s1:g}),0.5+0.5*{q[0]},"
              f"if(lt(T,{s2:g}),{q[1]},if(lt(T,{s3:g}),0.5+0.5*{q[2]},1-{q[3]})))))")
        oa = f"if(lt(T,{s2:g}),0,if(lt(T,{s3:g}),1-{q[2]},{q[3]}))"
        fills.append(f"{fill}*({fa})")
        outs.append(f"max({outer}-{inner},0)*({oa})")
    fill_sum = "+".join(fills)
    out_sum = "+".join(outs)
    r, g, b = CHEV_OUTLINE_COLOR
    # 枠線がある画素は黄色、それ以外（塗りだけ）は黒。不透明度は両方の合計（重なりは上限1）
    filters = [
        f"[{src}]format=rgba,colorchannelmixer=aa=0,"
        f"geq=r='{r}*gt({out_sum},0.02)':g='{g}*gt({out_sum},0.02)':b='{b}*gt({out_sum},0.02)':"
        f"a='255*clip(({fill_sum})+({out_sum}),0,1)',{shift}[{prefix}C]",
    ]
    return filters, f"{prefix}C"


def result_layer_filters(src, res_start, result_y, goal_layout, goal_rel, labels=(),
                         move_idx=None, base_rgb=(255, 255, 255), flash_rgb=GOAL_FLASH_RGB,
                         chev=None):
    """結果の「GOAL！！」と背景バナーを、バナー周りの帯レイヤー（高さ＝バナー＋上下余白）に描くフィルタ列。
    文字：奥（小）→半分の大きさ→真ん中の「GOAL!」が他の文字の高さへ下りる→原寸。真ん中の「GOAL!」は上にずれて見切れた
    まま半分まで拡大し、止まっている間に下りきってから原寸へ拡大する。バナー：文字が再び拡大し始めたら、黄/黒の点滅＋下から上へ広がる。
    当たり色の文字：上はバナー左上に左寄せで下から上へ、下はバナー右下に右寄せで上から下へ生える。
    戻り値: (フィルタ列, 重ねる順のレイヤー名, 帯レイヤーを重ねる画面Y)"""
    pad = RESULT_BAND_PAD
    x0, x1 = (1080 - RESULT_BANNER_W) // 2, (1080 + RESULT_BANNER_W) // 2
    band_top = round(result_y - RESULT_BANNER_H / 2) - pad        # 帯レイヤー上端の画面Y
    bottom = pad + RESULT_BANNER_H                                 # 帯レイヤー内でのバナー下辺
    cyb = bottom - RESULT_BANNER_H / 2                             # 帯レイヤー内でのバナー中心Y
    shift = f"setpts=PTS-STARTPTS+{res_start:g}/TB"
    t_b = GOAL_ZOOM1_DUR + GOAL_HOLD                               # 再拡大＝バナーを出し始める秒数
    tb = f"(T-{t_b:g})"
    # バナー：黄→黒→黄→黒と点滅しながら、潰れた状態から下辺を固定して上へ高さが広がる
    is_y = f"(lt({tb},0.1)+gte({tb},0.2)*lt({tb},{RESULT_FLASH_END:g}))"
    top = (f"({bottom}-({RESULT_BANNER_MIN_H}+{RESULT_BANNER_H - RESULT_BANNER_MIN_H}"
           f"*clip({tb}/{RESULT_GROW:g},0,1)))")
    banner = f"gte(T,{t_b:g})*gte(X,{x0})*lt(X,{x1})*gte(Y,{top})*lt(Y,{bottom})"
    # 文字の大きさ：奥→半分（最初速く、だんだんゆっくり）→少し止まる→原寸（等速）
    z1 = f"clip(T/{GOAL_ZOOM1_DUR:g},0,1)"
    z2 = f"clip({tb}/{GOAL_ZOOM2_DUR:g},0,1)"
    scale = (f"({GOAL_ZOOM_FROM:g}+{GOAL_ZOOM_MID - GOAL_ZOOM_FROM:g}*(1-pow(1-{z1},{GOAL_ZOOM1_EASE:g}))"
             f"+{1 - GOAL_ZOOM_MID:g}*{z2})")
    # 真ん中の「GOAL!」：半分まで拡大しきってから等速で下り、再拡大（＝バナー開始）の前に下りきる
    bands = goal_layout["bands"]
    m_idx = move_idx or GOAL_MOVE_IDX                              # 上から下りる文字の範囲
    m_l, m_r = bands[m_idx[0]][0], bands[m_idx[1]][1]
    dq = f"clip((T-{GOAL_ZOOM1_DUR:g})/{GOAL_HOLD:g},0,1)"
    gy = cyb - (goal_layout["y1"] + goal_layout["y2"]) / 2         # インクがバナー中央に来る描画Y
    # 真ん中の「GOAL!」を上にずらす量：文字の上端を枠の上辺まで上げ、さらに高さの GOAL_MOVE_CUT ぶん上げる
    ink_top = gy + goal_layout["y1"]
    ink_h = goal_layout["y2"] - goal_layout["y1"] + 1
    raise_px = (ink_top - pad) + GOAL_MOVE_CUT * ink_h
    # 画面の(X,Y)を拡大率で割り戻して文字の座標(u,v)を拾う＝中心から拡大。見切れの境界（バナーの枠）も
    # 文字の座標で判定するので文字と一緒に拡大縮小し、上にずれた真ん中の「GOAL!」の上部だけが切れる。
    a_expr = (f"st(0,540+(X-540)/{scale});"
              f"st(1,{cyb:g}+(Y-{cyb:g})/{scale});"
              f"st(2,gte(ld(0),{x0})*lt(ld(0),{x1})*gte(ld(1),{pad})*lt(ld(1),{bottom}));"
              f"st(1,ld(1)+gte(ld(0),{m_l})*lt(ld(0),{m_r})*{raise_px:g}*(1-{dq}));"
              f"alpha(ld(0),ld(1))*ld(2)")
    # 文字が出た瞬間から原寸まで拡大しきるまで白→赤→白→赤…と点滅し、その後は白（赤＝緑と青を0にする）
    # 判定は半コマ後ろの時刻で行う。コマ時刻 n/30 をそのまま割ると境目で 2.9999… のような誤差が出て、
    # 切り替えが1コマずれ、3コマずつのはずが2〜4コマにばらつくため。
    flash = f"lt(T,{t_b + GOAL_ZOOM2_DUR:g})*mod(floor((T+{0.5 / 30:g})/{GOAL_FLASH_STEP:g}),2)"
    # 点滅は base_rgb と flash_rgb を行き来する（既定は白⇔赤。拡大しきったら base_rgb で止まる）
    rgb = [f"{b}+{f - b}*({flash})" for b, f in zip(base_rgb, flash_rgb)]
    filters = [
        f"[{src}]format=rgba,colorchannelmixer=aa=0,"
        f"split={2 + (1 if labels else 0) + (1 if chev else 0)}"
        f"[resB0][resT0]" + ("[resL0]" if labels else "") + ("[resC0]" if chev else ""),
        f"[resB0]geq=r='{is_y}*241':g='{is_y}*196':b='{is_y}*15':a='if({banner},255,0)',{shift}[resBG]",
        f"[resT0]drawtext=fontfile={FONT_REL}:textfile={goal_rel}:fontcolor=white:"
        f"fontsize={GOAL_FONTSIZE}:x={goal_layout['x']}:y={gy:g},"
        f"geq=r='{rgb[0]}':g='{rgb[1]}':b='{rgb[2]}':a='{a_expr}',{shift}[resTX]",
    ]
    layers = ["resBG", "resTX"]
    if labels:
        # 当たり色の文字：バナーの後ろに完全に隠れた位置から、上は上へ・下は下へ移動して出てくる。
        # 重ね順をバナーより後ろにしてあるので、移動中に重なっている部分はバナーに隠れる。
        t_show = t_b + RESULT_GROW
        p = f"clip((T-{t_show:g})/{RESULT_LABEL_REVEAL:g},0,1)"
        ease = f"({p}*{p}*(3-2*{p}))"
        draws, moves = [], []
        for i, lb in enumerate(labels[:2]):
            lay = lb["layout"]
            ink_l, ink_r = lay["bands"][0][0], lay["bands"][-1][1]
            ink_h = lay["y2"] - lay["y1"] + 1
            move = RESULT_LABEL_GAP + ink_h + 4            # 隠れ位置（バナーの内側）からの移動量
            if i == 0:                                     # 上：バナー左端に左寄せ、上へ出る
                dx = lay["x"] + (x0 - ink_l)
                dy = (pad - RESULT_LABEL_GAP) - lay["y2"]  # 出きった位置＝インク下端がバナー上辺のすぐ上
                sign = "-"                                 # 開始時は下（バナーの中）へずらす
            else:                                          # 下：バナー右端に右寄せ、下へ出る
                dx = lay["x"] + (x1 - ink_r)
                dy = (bottom + RESULT_LABEL_GAP) - lay["y1"]
                sign = "+"                                 # 開始時は上（バナーの中）へずらす
            draws.append(f"drawtext=fontfile={FONT_REL}:textfile={lb['rel']}:"
                         f"fontcolor={lb['color']}:fontsize={RESULT_LABEL_FONTSIZE}:x={dx:g}:y={dy:g}")
            shift_x = dx - lay["x"]
            sel = f"gte(X,{ink_l + shift_x - 4:g})*lt(X,{ink_r + shift_x + 4:g})"
            moves.append(f"{sign}({sel})*{move:g}*(1-{ease})")
        v = "Y" + "".join(moves)
        draws_str = ",".join(draws)
        filters.append(f"[resL0]{draws_str},"
                       f"geq=r='r(X,{v})':g='g(X,{v})':b='b(X,{v})':"
                       # バナーが広がりきる前は、隠れ位置でもバナーからはみ出すので完全に非表示にする
                       f"a='alpha(X,{v})*gte(T,{t_show:g})',{shift}[resLB]")
        layers.insert(0, "resLB")                          # バナーより後ろに重ねる
    if chev:
        # 「＞＞＞」はバナーの左下、下の当たり色と同じ高さに置く
        chev_fc, ch_lab = chevron_layer_filters(
            "resC0", "chev", x0 + CHEV_INSET,
            bottom + RESULT_LABEL_GAP + CHEV_HALF_H, t_b + RESULT_GROW, shift)
        filters += chev_fc
        layers.append(ch_lab)
    return filters, layers, band_top


def result_single_layer_filters(src, res_start, result_y, lay, rel, rgb, chev=False):
    """当たりが1色だけのときの結果表示。バナーは上辺を固定して下へ伸び、色名はバナーの下辺から
    上へ出現して、白と色名の色で短く点滅する。左下の「＞＞＞」は出さない（chev=True で出せる）。
    戻り値は (フィルタ列, 重ねる順のレイヤー名, 画面Y)。"""
    pad = RESULT_BAND_PAD
    x0, x1 = (1080 - RESULT_BANNER_W) // 2, (1080 + RESULT_BANNER_W) // 2
    band_top = round(result_y - RESULT_BANNER_H / 2) - pad
    bottom = pad + RESULT_BANNER_H
    cyb = bottom - RESULT_BANNER_H / 2
    shift = f"setpts=PTS-STARTPTS+{res_start:g}/TB"
    # バナー：上辺 pad を固定して下辺が下りてくる。色は黄→黒→黄→黒
    is_y = f"(lt(T,0.1)+gte(T,0.2)*lt(T,{RESULT_FLASH_END:g}))"
    low = (f"({pad}+{RESULT_BANNER_MIN_H}+{RESULT_BANNER_H - RESULT_BANNER_MIN_H}"
           f"*clip(T/{RESULT_GROW:g},0,1))")
    banner = f"gte(X,{x0})*lt(X,{x1})*gte(Y,{pad})*lt(Y,{low})"
    # 色名：バナーが出きってから下から上へ出現（バナーの内側だけ表示するので下辺から生えて見える）
    t_show = RESULT_GROW
    ih = lay["y2"] - lay["y1"] + 1
    gy = cyb - (lay["y1"] + lay["y2"]) / 2                       # インクがバナー中央に来る描画Y
    rise = bottom - (cyb - ih / 2) + 4                           # 隠れ位置（バナー下辺の下）までの距離
    p = f"clip((T-{t_show:g})/{SINGLE_RISE:g},0,1)"
    v = f"Y-{rise:g}*(1-{p})"                                   # 開始時は下（バナーの外）に置き、上へ移動
    inside = f"gte(X,{x0})*lt(X,{x1})*gte(Y,{pad})*lt(Y,{bottom})"
    # 点滅：白と色名の色を短い間隔で入れ替え、SINGLE_FLASH_DUR 後は色名の色で止まる。
    # 判定は半コマ後ろの時刻で行う（コマ時刻をそのまま割ると境目で誤差が出てコマ数がばらつくため）
    flash = (f"lt(T,{t_show + SINGLE_FLASH_DUR:g})"
             f"*mod(floor((T-{t_show:g}+{0.5 / 30:g})/{SINGLE_FLASH_STEP:g}),2)")
    cols = [f"{c}+{255 - c}*({flash})" for c in rgb]             # 色 ⇔ 白
    filters = [
        f"[{src}]format=rgba,colorchannelmixer=aa=0,split={3 if chev else 2}"
        f"[sglB0][sglT0]" + ("[sglC0]" if chev else ""),
        f"[sglB0]geq=r='{is_y}*241':g='{is_y}*196':b='{is_y}*15':a='if({banner},255,0)',{shift}[sglBG]",
        f"[sglT0]drawtext=fontfile={FONT_REL}:textfile={rel}:fontcolor=white:"
        f"fontsize={GOAL_FONTSIZE}:x={lay['x']}:y={gy:g},"
        f"geq=r='{cols[0]}':g='{cols[1]}':b='{cols[2]}':"
        f"a='alpha(X,{v})*({inside})*gte(T,{t_show:g})',{shift}[sglTX]",
    ]
    layers = ["sglBG", "sglTX"]
    if chev:
        chev_fc, ch_lab = chevron_layer_filters(
            "sglC0", "sgl", x0 + CHEV_INSET,
            bottom + RESULT_LABEL_GAP + CHEV_HALF_H, RESULT_GROW, shift)
        filters += chev_fc
        layers.append(ch_lab)
    return filters, layers, band_top


def measure_eng_bands(text, fontsize, tmp_txt):
    """英語字幕を1フレーム描画して実測し、各文字の帯（X範囲）とインクbboxを得る。
    drawtextは文字幅を教えてくれないため、prefixを順に描いて右端インク位置を測る。
    戻り値: {"x": 描画X, "bands": [(左,右), ...], "y1","y2": インクの上下（描画y基準の相対）}"""
    W, H, YY, THR = 1080, 300, 100, 60
    rel = tmp_txt.relative_to(PROJECT_ROOT).as_posix()

    def ink(sub):
        tmp_txt.write_text(sub, encoding="utf-8")
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=black:s={W}x{H}",
             "-vf", f"drawtext=fontfile={FONT_REL}:textfile={rel}:fontcolor=white:"
                    f"fontsize={fontsize}:x=0:y={YY}",
             "-frames:v", "1", "-pix_fmt", "gray", "-f", "rawvideo", "-"],
            cwd=PROJECT_ROOT, capture_output=True)
        buf = proc.stdout
        if len(buf) < W * H:
            return None
        left, right, top, bottom = W, -1, -1, -1
        for y in range(H):
            row = buf[y * W:(y + 1) * W]
            if max(row) <= THR:
                continue
            top = y if top < 0 else top
            bottom = y
            for x in range(W):
                if row[x] > THR:
                    left = min(left, x)
                    break
            for x in range(W - 1, -1, -1):
                if row[x] > THR:
                    right = max(right, x)
                    break
        return None if right < 0 else (left, right, top, bottom)

    full = ink(text)
    if full is None:
        return None
    x1, x2, y1, y2 = full
    draw_x = round((1080 - (x2 - x1 + 1)) / 2) - x1        # インクが画面中央に来る描画X
    bands, prev, last_right = [], x1 - 2, x1 - 2
    for i in range(1, len(text) + 1):
        got = ink(text[:i])
        right = last_right if got is None else got[1]
        last_right = right
        bands.append((draw_x + prev, draw_x + right + 1))
        prev = right + 1
    return {"x": draw_x, "bands": bands, "y1": y1 - YY, "y2": y2 - YY}


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

    for rel in (FONT_REL, FONT_KANJI_REL):
        if not (PROJECT_ROOT / rel).exists():
            print(f"[edit] フォントが見つかりません: {rel}", file=sys.stderr)
            sys.exit(1)
    bgm = pick_bgm(args.bgm)
    subscribe = None if args.no_subscribe else resolve_overlay(args.subscribe, SUBSCRIBE_CANDIDATES)
    thankyou = None if args.no_thankyou else resolve_overlay(args.thankyou, THANKYOU_CANDIDATES)
    if not args.no_subscribe and subscribe is None:
        print("[edit] 注意: SUBSCRIBEオーバーレイ素材が見つかりません（この要素はスキップします）。")
    if not args.no_thankyou and thankyou is None:
        print("[edit] 注意: Thank youオーバーレイ素材が見つかりません（この要素はスキップします）。")

    # 色選択肢カードに出す色（--colors 明示 → ファイル名から自動抽出）
    if args.no_cards:
        card_colors = []
    elif args.colors:
        card_colors = [c.strip() for c in args.colors.split(",") if c.strip()]
    else:
        card_colors = parse_colors_from_filename(path.stem)
    # 未知の色キーを除外
    unknown = [c for c in card_colors if c not in COLOR_MAP]
    if unknown:
        print(f"[edit] 注意: 未知の色キーを無視します: {', '.join(unknown)}（有効: {', '.join(COLOR_MAP)}）")
    card_colors = [c for c in card_colors if c in COLOR_MAP]

    # テロップ表示区間
    #   煽りは「再生時間」基準（--intro のときは導入クリップぶんを含む全体の秒数）、
    #   英語字幕・色カードは本編（切り出し後）基準。
    intro_len = args.intro_dur * 3 if args.intro else 0.0
    aori_g_start = args.aori_start
    aori_g_end = aori_g_start + args.aori_dur
    aori_start = max(0.0, aori_g_start - intro_len)      # 本編内での表示開始
    aori_end = max(0.0, aori_g_end - intro_len)          # 本編内での表示終了
    aori_toff = max(0.0, intro_len - aori_g_start)       # 本編開始時点で経過済みのアニメ秒数
    # 英語字幕は煽りの出現演出（点滅・伸長）が終わってから左→右へ1文字ずつ消していく（再生時間基準）
    eng_g_out = aori_g_start + AORI_APPEAR_DUR
    eng_g_end = eng_g_out + ENG_OUT_TOTAL
    eng_main_end = eng_g_end - intro_len                 # 本編内で字幕が消え切る時刻（0以下なら本編には出ない）
    # 色カードは煽りが消えた直後から（煽りが導入内で終わる場合は本編の頭から）
    cards_start = args.cards_start if args.cards_start is not None else aori_end
    cards_end = min(cards_start + args.cards_dur, clip_len)
    # 表示が終わったら登場演出を逆再生して消す。その尺ぶん後ろに伸ばす。
    cards_out_end = min(cards_end + CARD_EXIT_TOTAL, clip_len)
    # 結果バナーは弾が画面から全て消えた時刻（--result-start、再生時間基準）から最後まで。
    # 消える時刻は素材ごとに違い自動判定も難しいため、確認して指定する。
    res_start = None
    if args.result_start is not None:
        res_start = args.result_start - intro_len
        if res_start < 0 or res_start >= clip_len:
            print(f"[edit] 注意: --result-start {args.result_start:g} は本編の範囲外のため結果バナーを出しません。")
            res_start = None
    # SUBSCRIBE は色カードが退場し切った直後に出す（色カードが無い場合は尺の45パーセント地点）
    if args.sub_start is not None:
        sub_start = args.sub_start
    elif card_colors:
        sub_start = round(cards_out_end, 3)
    else:
        sub_start = round(clip_len * 0.45, 2)
    # 表示秒数はフェードアウト込み。既定は「演出が止まるまで＋フェードアウト」
    sub_dur = args.sub_dur if args.sub_dur is not None else SUBSCRIBE_ANIM_END + SUBSCRIBE_FADE_OUT
    sub_end = min(sub_start + sub_dur, clip_len)
    sub_fade_st = max(sub_start, sub_end - SUBSCRIBE_FADE_OUT)
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
    card_idx = None
    if card_colors:
        # カード描画用の透明レイヤー（高さ・長さとも必要分だけにして geq の処理量を抑える）
        card_lh = card_layer_height(len(card_colors))
        card_win = max(cards_out_end - cards_start, 0.1)
        inputs += ["-f", "lavfi", "-i", f"color=c=black@0.0:s=1080x{card_lh}:r=30:d={card_win:.3f}"]
        card_idx = next_idx
        next_idx += 1
    # 煽りアニメ用の透明レイヤー（背景ボックス＋文字を geq でアニメーション）
    aori_lh = min(1920, int(args.aori_y) + 200)
    aori_lh += aori_lh % 2
    aori_in_main = aori_end > aori_start
    aori_idx = None
    if aori_in_main:
        aori_win = max(aori_end - aori_start, 0.1)
        inputs += ["-f", "lavfi", "-i", f"color=c=black@0.0:s=1080x{aori_lh}:r=30:d={aori_win:.3f}"]
        aori_idx = next_idx
        next_idx += 1
        # 装飾文字「MARBLE」も煽りと同じ区間に出す
        inputs += ["-f", "lavfi", "-i",
                   f"color=c=black@0.0:s={MARBLE_CANVAS}x{MARBLE_CANVAS}:r=30:d={aori_win:.3f}"]
        marble_idx = next_idx
        next_idx += 1
    res_idx = None
    if res_start is not None:
        res_lh = RESULT_BANNER_H + 2 * RESULT_BAND_PAD
        inputs += ["-f", "lavfi", "-i",
                   f"color=c=black@0.0:s=1080x{res_lh}:r=30:d={clip_len - res_start:.3f}"]
        res_idx = next_idx
        next_idx += 1

    aori_rel = aori_txt.relative_to(PROJECT_ROOT).as_posix()
    eng_rel = eng_txt.relative_to(PROJECT_ROOT).as_posix()

    # 当たりの穴に入った玉の色：ラベルを実測して位置合わせに使う（上＝1色目、下＝2色目）
    #   3色入った場合は、中央の文字を3色目のラベル（色つき）に差し替える
    res_labels = []
    single_mode = False
    goal_text, goal_move_idx = GOAL_TEXT, GOAL_MOVE_IDX
    goal_base_rgb, goal_flash_rgb = (255, 255, 255), GOAL_FLASH_RGB
    if res_start is not None:
        keys = ([c.strip() for c in args.result_colors.split(",") if c.strip()]
                if args.result_colors else parse_result_colors(path.stem))
        unknown = [k for k in keys if k not in COLOR_MAP]
        if unknown:
            print(f"[edit] 注意: 未知の色キーを無視します: {', '.join(unknown)}")
        keys = [k for k in keys if k in COLOR_MAP]
        single_mode = len(keys) == 1
        if single_mode:
            label1, _furi1, fill1, _fg1 = COLOR_MAP[keys[0]]
            goal_text = label1                          # バナー中央に入った玉の色名だけを出す
            goal_base_rgb = hex_to_rgb(fill1)
            keys = []                                   # 左右の色名は出さない
        elif len(keys) >= 3:
            label3, _furi3, fill3, _fg3 = COLOR_MAP[keys[2]]
            goal_text = label3
            goal_base_rgb, goal_flash_rgb = hex_to_rgb(fill3), (255, 255, 255)
            mid = (len(label3) - 1) // 2                    # 真ん中2文字を上から下ろす
            goal_move_idx = (mid, min(mid + 1, len(label3) - 1))
        keys = keys[:2]
        if not keys:
            print("[edit] 注意: 当たりの玉の色が判別できないため色表示は入れません（--result-colors で指定できます）。")
        for i, key in enumerate(keys):
            label, _furi, fill, _fg = COLOR_MAP[key]
            lb_txt = OUTPUT_DIR / f"{stamp}_reslabel{i}.txt"
            lb_txt.write_text(label, encoding="utf-8")
            lb_measure = OUTPUT_DIR / f"{stamp}_reslabel{i}_measure.txt"
            temp_files += [lb_txt, lb_measure]
            lay = measure_eng_bands(label, RESULT_LABEL_FONTSIZE, lb_measure)
            if lay is None:
                print(f"[edit] 注意: 「{label}」の実測に失敗したため色表示を省きます。")
                res_labels = []
                break
            res_labels.append({"rel": lb_txt.relative_to(PROJECT_ROOT).as_posix(),
                               "color": fill, "layout": lay, "label": label})
    chev_cfg = res_start is not None          # バナー左下の「＞＞＞」（図形なので実測は不要）
    # 結果の「GOAL！！」：「AL」だけ動かすため各文字の帯を実測する
    goal_layout = goal_rel = None
    if res_start is not None:
        goal_txt = OUTPUT_DIR / f"{stamp}_goal.txt"
        goal_txt.write_text(goal_text, encoding="utf-8")
        goal_measure = OUTPUT_DIR / f"{stamp}_goal_measure.txt"
        temp_files += [goal_txt, goal_measure]
        goal_rel = goal_txt.relative_to(PROJECT_ROOT).as_posix()
        goal_layout = measure_eng_bands(goal_text, GOAL_FONTSIZE, goal_measure)
        if goal_layout is None:
            print(f"[edit] 注意: 「{goal_text}」の実測に失敗したため結果バナーを出しません。")
            res_start = None
    # 英語字幕：1文字ずつ縦長→元サイズに戻すアニメのため、各文字の帯を実測する
    measure_txt = OUTPUT_DIR / f"{stamp}_measure.txt"
    temp_files.append(measure_txt)
    print("[edit] 英語字幕の文字位置を実測中…")
    eng_layout = measure_eng_bands(ENGLISH_SUBTITLE, ENG_FONTSIZE, measure_txt)
    if eng_layout is None:
        print("[edit] 注意: 英語字幕の実測に失敗したためアニメなしで進めます。")
        eng_x, eng_anim = "(w-text_w)/2", None
    else:
        eng_x = str(eng_layout["x"])
        cy_rel = (eng_layout["y1"] + eng_layout["y2"]) / 2
        half = (eng_layout["y2"] - eng_layout["y1"] + 1) / 2 * ENG_STRETCH + 12
        eng_strip_top = max(0, int(ENG_Y + cy_rel - half))
        eng_strip_h = int(half * 2) + 4
        eng_strip_h += eng_strip_h % 2
        eng_cy = ENG_Y + cy_rel - eng_strip_top          # 伸縮の中心（帯内座標）
        eng_draw_y = ENG_Y - eng_strip_top               # 帯内での描画Y
        # 伸縮・フェード・ブラー・退場の式（検証スクリプトからも同じ関数を使う）
        eng_exprs = build_eng_exprs(eng_layout["bands"], eng_cy, eng_g_out)
        eng_main_idx = None
        if eng_main_end > 0:
            inputs += ["-f", "lavfi", "-i",
                       f"color=c=black@0.0:s=1080x{eng_strip_h}:r=30:d={eng_main_end:.3f}"]
            eng_main_idx = next_idx
            next_idx += 1

        def eng_anim(src, dst, offset=0.0):
            """英語字幕のアニメ付きレイヤー。offset はセグメント開始時点の経過秒。"""
            return eng_layer_filter(src, dst, eng_exprs, eng_x, eng_draw_y, eng_rel, offset)

    # 額縁フレーム（外周ぼかし背景＋内側にゲーム映像）
    chain = [
        "[0:v]fps=30,split=2[a][b]",
        "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "boxblur=25:2,eq=brightness=-0.22[bg]",
        f"[b]scale={inner_w}:{inner_h}[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[v0]",
    ]
    # 日本語煽り「何色が入る？？」のアニメ表示（再生時間 aori_g_start に開始）
    #   ・背景ボックスが中央から左右に伸びる／黄→黒→黄→黒に点滅／最初は縦長→定寸法
    #   ・背景が7割伸びたら文字が中央から左右に生えてくる
    ax = 540                       # 画面中央X
    acy = args.aori_y + 38         # ボックス中心Y（文字上端 aori_y ＋ フォント半分）
    bw2, bh2, ex = 300, 66, 26     # ボックス最終半幅/半高、初期の追加半高
    grow, hgrow = AORI_GROW, AORI_HGROW            # 横伸長時間 / 縦幅が収まるまでの時間
    tstart, tgrow = 0.0, AORI_TEXT_GROW            # 文字reveal開始(背景と同時)/時間
    t_range = 120                  # 文字revealの境界が下へ動く量
    move_off = 40                  # 文字が下から背景中央へ寄る量

    def aori_layers(src, prefix, toff, disp_start):
        """煽り（背景ボックス＋文字）のアニメ用フィルタを組み立てる。
        toff       : そのセグメント開始時点で経過済みのアニメ秒数（導入をまたぐ場合に使う）
        disp_start : そのセグメント内での表示開始秒
        戻り値: (フィルタ列, 文字レイヤーのoverlay y式)"""
        tv = f"(T+{toff:g})" if toff else "T"
        is_y = f"(lt({tv},0.1)+gte({tv},0.2)*lt({tv},{AORI_FLASH_END:g}))"   # 黄色の点滅バンド（それ以外は黒）
        hw = f"min({bw2},{tv}/{grow:g}*{bw2})"
        hh = f"{bh2}+{ex}*(1-min(1,{tv}/{hgrow:g}))"
        inside = f"lt(abs(X-{ax}),{hw})*lt(abs(Y-{acy:g}),{hh})"
        # 文字は上から下へ表示：時間で下へ動く境界より上(Y小)のみ残す
        tedge = f"{acy - 60:g}+min(1,max(0,{tv}-{tstart:g})/{tgrow:g})*{t_range}"
        shift = f"setpts=PTS-STARTPTS+{disp_start:g}/TB"
        anim0 = disp_start - toff                            # セグメント内でのアニメ基準時刻
        ymove = f"{move_off}*(1-min(1,max(0,t-{anim0 + tstart:g})/{tgrow:g}))"
        return ([f"[{src}]format=rgba,colorchannelmixer=aa=0,split=2[{prefix}BG0][{prefix}TX0]",
                 f"[{prefix}BG0]geq=r='{is_y}*241':g='{is_y}*196':b='{is_y}*15':"
                 f"a='if({inside},255,0)',{shift}[{prefix}BG]",
                 f"[{prefix}TX0]drawtext=fontfile={FONT_KANJI_REL}:textfile={aori_rel}:"
                 f"fontcolor={args.aori_color}:fontsize=76:x=(w-text_w)/2:y={args.aori_y:g},"
                 f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*lte(Y,{tedge})',"
                 f"{shift}[{prefix}TX]"], ymove)

    base = "v0"
    if aori_in_main and aori_idx is not None:
        aori_fc, aori_ymove = aori_layers(f"{aori_idx}:v", "aori", aori_toff, aori_start)
        mk_fc, mk_x, mk_y = marble_layer_filter(f"{marble_idx}:v", "mk", aori_toff, aori_start)
        win = f"between(t,{aori_start:g},{aori_end:g})"
        chain += [mk_fc] + aori_fc + [
            f"[v0][mk]overlay=x='{mk_x}':y='{mk_y}':enable='{win}'[v0m]",   # MARBLE は煽りの帯より後ろ
            f"[v0m][aoriBG]overlay=0:0:enable='{win}'[v0b]",
            f"[v0b][aoriTX]overlay=x=0:y='{aori_ymove}':enable='{win}'[v1]",
        ]
        base = "v1"
    # 英語字幕（導入から継続）。本編開始時点の経過時間 intro_len でアニメ式をずらして続きを描く
    if eng_main_end <= 0:
        chain.append(f"[{base}]null[v2]")                # 導入中に消え切るので本編には出さない
    elif eng_anim is not None:
        chain.append(eng_anim(f"{eng_main_idx}:v", "engM", intro_len))
        chain.append(f"[{base}][engM]overlay=0:{eng_strip_top}:"
                     f"enable='between(t,0,{eng_main_end:g})'[v2]")
    else:
        chain.append(
            f"[{base}]drawtext=fontfile={FONT_REL}:textfile={eng_rel}:fontcolor=white:"
            f"fontsize={ENG_FONTSIZE}:x={eng_x}:y={ENG_Y}:enable='between(t,0,{eng_main_end:g})'[v2]")
    cur = "v2"
    # 色選択肢カード：透明レイヤーに描き、geqの移動アルファマスクで左→右に「サイズが伸びる」表示。
    #   ① 白線＋ふりがな → ② ピル → ③ 英語ラベル の順に伸ばす
    if card_colors and card_idx is not None:
        chain.append(f"[{card_idx}:v]format=rgba,colorchannelmixer=aa=0,split=3[cardA0][cardB0][cardC0]")
        card_filters, la_out, lb_out, lc_out, card_boxes = build_color_card_layers(
            card_colors, "cardA0", "cardB0", "cardC0", stamp, temp_files)
        chain.extend(card_filters)
        reveal = CARD_REVEAL              # 各段が左→右に伸びきるまでの時間（小さいほど速い）
        rw = CARD_W + CARD_LINE_EXT       # 1カードの伸長幅
        # カードレイヤーは 0 始まりの短い尺。開始時刻もレイヤー内ローカル(0基準)で扱い、
        # 最後に setpts で cards_start へずらす。
        a_local = 0.0                     # ①白線＋ふりがな
        b_local = CARD_B_DELAY            # ②ピル
        c_local = CARD_C_DELAY            # ③英語ラベル（ピルが約6割伸びたら開始）
        # 退場は登場の逆再生。最後に出た段（③）から順に、右→左へ縮めて消す。
        out_local = cards_end - cards_start                     # レイヤー内での退場開始
        shift = f"setpts=PTS-STARTPTS+{cards_start:g}/TB"

        mb = args.card_motion_blur        # 伸長の先端をにじませる幅(px)＝モーションブラー。0でシャープ

        def grow_mask(src, start, dst, out_start):
            # 各カードを自分の左端から同時に左→右へ伸ばす。伸長の先端を mb px にじませて
            # 動き（左→右）に同期したモーションブラーにする（伸び切ると勾配が消えてシャープ）。
            # out_start 以降は同じ速度で先端を戻し（右→左）、登場の逆再生として消す。
            terms = []
            # 伸長ぶんは頭打ちにしてから退場ぶんを引く（頭打ちしないと引いても縮まない）。
            # 頭打ちは rw+mb：rw で止めるとにじみ勾配が右端 mb px に残り、伸び切っても
            # カードの右端が半透明のままになる。退場は同じ尺で 0 まで戻す。
            full = rw + mb
            edge = (f"min({full:g},(T-{start:g})/{reveal:g}*{rw})"
                    f"-max(0,T-{out_start:g})/{reveal:g}*{full:g}")
            for (l, r, tp, bt) in card_boxes:
                in_box = f"gte(X,{l})*lt(X,{r})*gte(Y,{tp})*lt(Y,{bt})"
                if mb > 0:
                    ramp = f"clip(({edge}-(X-{l}))/{mb:g},0,1)"
                else:
                    ramp = f"gt({edge}-(X-{l}),0)"
                terms.append(f"{in_box}*({ramp})")
            cond = "+".join(terms)
            return (f"[{src}]geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                    f"a='alpha(X,Y)*({cond})',{shift}[{dst}]")

        def round_pills(src, dst, radius=26):
            # ピルの四隅を角丸に。各ピル矩形の内側インセット矩形からの距離が半径以内のみ残す。
            terms = []
            for (l, r, tp, bt) in card_boxes:
                px, py = l + CARD_LINE_EXT // 2, tp          # ピル左上（白線extを戻す）
                pw, ph = CARD_W, CARD_H
                qx = f"(X-clip(X,{px + radius},{px + pw - radius}))"
                qy = f"(Y-clip(Y,{py + radius},{py + ph - radius}))"
                inside = f"lte({qx}*{qx}+{qy}*{qy},{radius * radius})"
                terms.append(f"gte(X,{px})*lt(X,{px + pw})*gte(Y,{py})*lt(Y,{py + ph})*{inside}")
            cond = "+".join(terms)
            return (f"[{src}]geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                    f"a='alpha(X,Y)*gt({cond},0)'[{dst}]")

        chain.append(grow_mask(la_out, a_local, "cardMA", out_local + CARD_EXIT_A))
        chain.append(round_pills(lb_out, "lbRound"))   # ピルを角丸に
        chain.append(grow_mask("lbRound", b_local, "cardMB", out_local + CARD_EXIT_B))
        chain.append(grow_mask(lc_out, c_local, "cardMC", out_local + CARD_EXIT_C))
        # ピルは伸び始めに少し左→右へ動かす（-slide_px から 0 へ）。退場では逆に左へ戻す。
        pill_slide_px = 40
        pb_abs = cards_start + b_local
        pe_abs = cards_start + out_local + CARD_EXIT_B
        pill_x = (f"min(0,-{pill_slide_px}+(t-{pb_abs:g})/{reveal:g}*{pill_slide_px})"
                  f"-min({pill_slide_px},max(0,t-{pe_abs:g})/{reveal:g}*{pill_slide_px})")
        # 重ね順：白線+ふりがな → ピル → 英語ラベル（ラベルが最前面）
        win = f"between(t,{cards_start:g},{cards_out_end:g})"
        chain.append(f"[{cur}][cardMA]overlay=x=0:y=0:enable='{win}'[cardvA]")
        chain.append(f"[cardvA][cardMB]overlay=x='{pill_x}':y=0:enable='{win}'[cardvB]")
        chain.append(f"[cardvB][cardMC]overlay=x=0:y=0:enable='{win}'[cardvC]")
        cur = "cardvC"
    # SUBSCRIBEオーバーレイ（グリーンバックをクロマキー）。
    # setpts で素材の再生開始を表示区間の頭に合わせる（区間到達時に素材が尽きるのを防ぐ）。
    if sub_idx is not None:
        # chromakey で緑背景を抜き、despill でボタン周囲に残る緑のフチ（スピル）を除去
        # 素材先頭の緑だけの区間（--sub-lead）は trim で落とし、表示開始の瞬間からボタンを映す
        chain.append(f"[{sub_idx}:v]trim=start={args.sub_lead:g},"
                     f"chromakey={CHROMAKEY_GREEN}:{args.sub_similarity:g}:{args.sub_blend:g},"
                     f"despill=type=green:mix={args.sub_despill:g}:expand=0.3,"
                     f"scale={args.sub_width}:-1,setpts=PTS-STARTPTS+{sub_start:g}/TB,format=rgba,"
                     f"fade=t=out:st={sub_fade_st:g}:d={SUBSCRIBE_FADE_OUT:g}:alpha=1[sub]")
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
    # 結果：背景バナー（黄/黒の点滅＋下から上へ広がる）と、その中央の「GOAL！！」
    if res_idx is not None and goal_layout is not None:
        if single_mode:
            res_fc, res_layers, band_top = result_single_layer_filters(
                f"{res_idx}:v", res_start, args.result_y, goal_layout, goal_rel, goal_base_rgb)
        else:
            res_fc, res_layers, band_top = result_layer_filters(
                f"{res_idx}:v", res_start, args.result_y, goal_layout, goal_rel, res_labels,
                goal_move_idx, goal_base_rgb, goal_flash_rgb, chev_cfg)
        win = f"gte(t,{res_start:g})"
        chain += res_fc
        for i, lab in enumerate(res_layers):
            nxt = f"vres{i}"
            chain.append(f"[{cur}][{lab}]overlay=0:{band_top}:enable='{win}'[{nxt}]")
            cur = nxt
    venc = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30"]

    def framed_fc(in_label, out_label):
        """単一入力→額縁レイアウト（外周ぼかし＋内側映像）。concat互換のため yuv420p/SAR=1 に統一。"""
        return (
            f"[{in_label}]fps=30,split=2[{out_label}a][{out_label}b];"
            f"[{out_label}a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            f"boxblur=25:2,eq=brightness=-0.22[{out_label}bg];"
            f"[{out_label}b]scale={inner_w}:{inner_h}[{out_label}fg];"
            f"[{out_label}bg][{out_label}fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p,setsar=1[{out_label}]"
        )

    if not args.intro:
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
    else:
        # 導入演出あり：①並ぶ→②転がる→③並ぶ を本編の前に連結し、BGMは全体に乗せる
        # 1) 本編（映像のみ）。concat互換のため yuv420p/SAR=1 に正規化
        main_tmp = OUTPUT_DIR / f"{stamp}_main.mp4"
        temp_files.append(main_tmp)
        run_ffmpeg(
            ["ffmpeg", "-y", *inputs,
             "-filter_complex", ";".join(chain + [f"[{cur}]format=yuv420p,setsar=1[mainout]"]),
             "-map", "[mainout]", "-an", *venc, str(main_tmp)],
            "本編（映像）を作成中")
        # 2) 導入クリップ（額縁＋英語字幕。英語字幕は最初から表示）
        #    ③は本編開始直前の素材にして本編へ継ぎ目なく連続させる
        eng_dt = (f"drawtext=fontfile={FONT_REL}:textfile={eng_rel}:fontcolor=white:fontsize={ENG_FONTSIZE}:"
                  f"x={eng_x}:y={ENG_Y}")
        cuts = [("①弾が並ぶ", args.intro_lineup),
                ("②ルーレット上で転がる", args.intro_rolling),
                ("③本編へ連続（開始直前）", max(0.0, start - args.intro_dur))]
        intro_tmps = []
        for i, (label, cut_start) in enumerate(cuts):
            it = OUTPUT_DIR / f"{stamp}_intro{i}.mp4"
            temp_files.append(it)
            # 1文字ずつ縦長→元サイズに戻すアニメ。導入①②③をまたいで継続させる
            if eng_anim is not None:
                extra_in = ["-f", "lavfi", "-i",
                            f"color=c=black@0.0:s=1080x{eng_strip_h}:r=30:d={args.intro_dur:.3f}"]
                fc = (framed_fc("0:v", "iv") + ";" + eng_anim("1:v", "engA", i * args.intro_dur)
                      + f";[iv][engA]overlay=0:{eng_strip_top}[ivt]")
            else:
                extra_in = []
                fc = (framed_fc("0:v", "iv")
                      + f";[iv]{eng_dt}:enable='lt(t,{eng_g_end - i * args.intro_dur:g})'[ivt]")
            out_label = "ivt"
            # 煽りは再生時間基準のため、導入クリップにかかる場合はここにも重ねる
            seg_g0 = i * args.intro_dur
            a0 = max(aori_g_start, seg_g0)
            a1 = min(aori_g_end, seg_g0 + args.intro_dur)
            if a1 > a0:
                extra_in += ["-f", "lavfi", "-i",
                             f"color=c=black@0.0:s=1080x{aori_lh}:r=30:d={a1 - a0:.3f}"]
                aidx = len(extra_in) // 4          # lavfi入力は4要素ずつ。素材が0番
                extra_in += ["-f", "lavfi", "-i",
                             f"color=c=black@0.0:s={MARBLE_CANVAS}x{MARBLE_CANVAS}:r=30:d={a1 - a0:.3f}"]
                midx = len(extra_in) // 4
                afc, aymove = aori_layers(f"{aidx}:v", "iA", a0 - aori_g_start, a0 - seg_g0)
                mfc, mx, my = marble_layer_filter(f"{midx}:v", "iM", a0 - aori_g_start, a0 - seg_g0)
                win = f"between(t,{a0 - seg_g0:g},{a1 - seg_g0:g})"
                fc += ";" + mfc + ";" + ";".join(afc) + (
                    f";[ivt][iM]overlay=x='{mx}':y='{my}':enable='{win}'[ivtm]"
                    f";[ivtm][iABG]overlay=0:0:enable='{win}'[ivt1]"
                    f";[ivt1][iATX]overlay=x=0:y='{aymove}':enable='{win}'[ivt2]")
                out_label = "ivt2"
            run_ffmpeg(
                ["ffmpeg", "-y", "-ss", f"{cut_start:.3f}", "-t", f"{args.intro_dur:.3f}", "-i", str(path),
                 *extra_in, "-filter_complex", fc,
                 "-map", f"[{out_label}]", "-an", *venc, str(it)],
                f"導入クリップ作成中（{label} / 素材{cut_start:g}秒から{args.intro_dur:g}秒）")
            intro_tmps.append(it)
        # 3) 連結（導入→本編）＋ BGMを全体に合成
        seg_paths = intro_tmps + [main_tmp]
        total = args.intro_dur * len(intro_tmps) + clip_len
        concat_inputs = []
        for p in seg_paths:
            concat_inputs += ["-i", str(p)]
        bgm_idx = len(seg_paths)
        concat_v = "".join(f"[{i}:v]" for i in range(len(seg_paths))) + f"concat=n={len(seg_paths)}:v=1:a=0[outv]"
        afilt = f"[{bgm_idx}:a]volume={args.bgm_volume},atrim=0:{total:.3f},asetpts=PTS-STARTPTS[aout]"
        run_ffmpeg(
            ["ffmpeg", "-y", *concat_inputs, "-stream_loop", "-1", "-i", str(bgm),
             "-filter_complex", f"{concat_v};{afilt}",
             "-map", "[outv]", "-map", "[aout]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-c:a", "aac", "-ar", "44100", "-b:a", "128k",
             "-movflags", "+faststart",
             str(final_path)],
            f"導入＋本編を連結しBGMを合成中（全体 約{total:.1f}秒）")

    if not args.keep_temp:
        for tmp in temp_files:
            tmp.unlink(missing_ok=True)

    out_info = probe(final_path)
    print()
    print(f"完成: {final_path.relative_to(PROJECT_ROOT)}")
    print(f"  長さ  : {out_info['duration']:.2f} 秒 / {out_info['width']}x{out_info['height']} / {out_info['fps']:.0f}fps")
    if args.intro:
        print(f"  導入  : ①並ぶ→②転がる→③並ぶ（各{args.intro_dur:g}秒）→ 本編")
    print(f"  音声  : BGMのみ {bgm.name}（volume={args.bgm_volume}、元素材の音声はミュート）")
    print(f"  装飾  : 左上に「{MARBLE_TEXT}」3段（煽りと同じ区間、演出{MARBLE_ANIM_DUR:g}秒）")
    print(f"  煽り  : 「{AORI_TEXT}」（再生{aori_g_start:g}〜{aori_g_end:g}秒）"
          f" / 英語字幕（再生{eng_g_out:g}秒から左→右に退場、{eng_g_end:g}秒で消え切る）")
    if card_colors:
        labels = "・".join(COLOR_MAP[c][0] for c in card_colors)
        print(f"  色カード: {labels}（本編{cards_start:g}〜{cards_end:g}秒"
              f" ＝ 再生{cards_start + intro_len:g}〜{cards_end + intro_len:g}秒"
              f"、退場アニメ{cards_out_end - cards_end:.2f}秒）")
    else:
        print("  色カード: なし")
    print(f"  購読  : {'合成あり（本編%g〜%g秒 ＝ 再生%g〜%g秒）' % (sub_start, sub_end, sub_start + intro_len, sub_end + intro_len) if sub_idx is not None else 'なし'}")
    res_note = ("／当たり色 " + "・".join(lb["label"] for lb in res_labels)) if res_idx is not None and res_labels else ""
    print(f"  結果  : {'バナー＋%s%s（本編%g秒〜 ＝ 再生%g秒〜）' % (goal_text, res_note, res_start, res_start + intro_len) if res_idx is not None else 'なし（--result-start 未指定）'}")
    print(f"  締め  : {'Thank you 合成あり（本編%g〜%g秒 ＝ 再生%g〜%g秒）' % (ty_start, ty_end, ty_start + intro_len, ty_end + intro_len) if ty_idx is not None else 'なし'}")


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
    p_fin.add_argument("--intro", action="store_true", help="冒頭に導入演出（①弾が並ぶ→②転がる→③並ぶ→本編）を付ける")
    p_fin.add_argument("--intro-lineup", type=float, default=2.0, help="導入①用『弾が並ぶ』カットの素材開始秒（既定2.0）。③は本編開始直前を自動使用")
    p_fin.add_argument("--intro-rolling", type=float, default=40.0, help="導入②用『転がる』カットの素材開始秒（既定40.0）")
    p_fin.add_argument("--intro-dur", type=float, default=1.0, help="導入各カットの長さ秒（既定1.0）")
    p_fin.add_argument("--aori-start", type=float, default=2.0, help="日本語煽り「何色が入る？？」の表示開始秒（再生時間基準。--intro のときは導入クリップを含む、既定2）")
    p_fin.add_argument("--aori-dur", type=float, default=2.0, help="煽りの表示秒数（既定2）")
    p_fin.add_argument("--aori-color", default="0xff2fd0", help="煽りテキストの色（既定ピンク 0xff2fd0）")
    p_fin.add_argument("--aori-y", type=float, default=500, help="日本語煽りの縦位置px（既定500。小さいほど上）")
    p_fin.add_argument("--result-start", type=float, help="結果バナーの表示開始秒（再生時間基準。弾が画面から全て消えた時刻。省略時は出さない）")
    p_fin.add_argument("--result-colors", help="当たりの穴に入った玉の色をカンマ区切りで明示（例: pink,orange）。省略時はファイル名の2つ目の色並びから判定")
    p_fin.add_argument("--result-y", type=float, default=RESULT_Y_DEFAULT, help="結果バナー中心の縦位置px（既定560）")
    p_fin.add_argument("--colors", help="色選択肢カードの色をカンマ区切りで明示（例: pink,yellowgreen,orange）。省略時はファイル名から自動抽出")
    p_fin.add_argument("--no-cards", action="store_true", help="色選択肢カードを入れない")
    p_fin.add_argument("--cards-start", type=float, help="色カード表示開始秒（省略時は煽り終了直後）")
    p_fin.add_argument("--cards-dur", type=float, default=8.0, help="色カード表示秒数（既定8。この後に退場アニメが入る）")
    p_fin.add_argument("--card-motion-blur", type=float, default=40.0, help="色カードの伸長先端をにじませる幅px＝モーションブラー（0でシャープ。既定40）")
    p_fin.add_argument("--sub-start", type=float, help="SUBSCRIBE表示開始秒（本編基準。省略時は色カードの退場直後、色カードなしなら尺の45パーセント地点）")
    p_fin.add_argument("--sub-lead", type=float, default=SUBSCRIBE_LEAD_IN, help="購読ボタン素材の先頭で切り詰める緑だけの区間の秒数（既定0.23。別素材を使うときに調整）")
    p_fin.add_argument("--sub-dur", type=float, default=None, help="SUBSCRIBEの表示秒数（フェードアウト込み。既定は演出が止まる3.7秒＋フェードアウト0.5秒）")
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
