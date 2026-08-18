# -*- coding: utf-8 -*-
"""
hose_3tang.py — Watchlist mua ngay: Trend + Chat luong + Entry pullback
=========================================================================
Tang 1 (trend, trang thai)   : SMA50 > SMA200 va gia > SMA200
Tang 2 (chat luong)          : GTGD binh quan 20 phien, P/E, P/B
Tang 3 (entry, su kien)      : gia pullback ve quanh SMA50 + RSI ngoc len
Tang 0 (market regime)       : VN-Index tren SMA200 -> moi bat tang 3

Cac ham lay du lieu (lay_danh_sach_hose, tai_lich_su_gia, lay_pe_pb) copy
nguyen tu hose_screener.py da chay thanh cong tren may nguoi dung — KHONG
doi cach goi API vnstock, chi doi phan tinh chi bao va them tang 3.

Chay (Windows, trong thu muc chua venv):
    venv\\Scripts\\activate
    python hose_3tang.py               # ca san
    python hose_3tang.py --gioi-han 30 # chay thu

Tren GitHub Actions: dat secrets TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
KHONG can VNSTOCK_API_KEY — script goc khong goi ham khai key nao (nguon
VCI/TCBS mien phi). Neu gap loi xac thuc thi bao lai de xu ly tiep.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd

# ============================================================
CONFIG = {
    "nguon_du_lieu": "VCI",
    "ma_chi_so": "VNINDEX",          # dung de kiem tra market regime

    "so_phien_lich_su": 550,         # can du 200+ phien cho SMA200
    "sma_ngan": 50,
    "sma_dai": 200,

    "min_gia_tri_gd_ty": 20.0,       # GTGD binh quan 20 phien (ty VND)
    "pe_max": 20.0,
    "pb_max": 3.0,

    "khoang_cach_sma50": 0.03,       # tang 3: gia cach SMA50 +/-3%
    "rsi_min": 40,
    "rsi_max": 55,
    "rsi_phai_ngoc_len": True,

    "bat_regime_filter": True,

    "nghi_giua_2_ma_giay": 0.6,
    "thu_muc_cache": "cache_3tang",
    "thu_muc_ket_qua": "ket_qua_3tang",
}
# ============================================================


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ---------- Cac ham lay du lieu — copy nguyen tu hose_screener.py ----------

def lay_danh_sach_hose(nguon: str) -> list:
    from vnstock import Listing
    listing = Listing(source=nguon)
    try:
        symbols = listing.symbols_by_group("HOSE")
        ds = list(pd.Series(symbols).dropna().astype(str))
    except Exception:
        df = listing.symbols_by_exchange()
        col_ex = next(c for c in df.columns if "exchange" in c.lower())
        col_sym = next(c for c in df.columns if "symbol" in c.lower() or "ticker" in c.lower())
        col_type = next((c for c in df.columns if "type" in c.lower()), None)
        mask = df[col_ex].astype(str).str.upper().str.contains("HOSE|HSX")
        if col_type is not None:
            mask &= df[col_type].astype(str).str.upper().str.contains("STOCK|CS")
        ds = list(df.loc[mask, col_sym].astype(str))
    ds = sorted({s.strip().upper() for s in ds if len(s.strip()) == 3 and s.strip().isalpha()})
    return ds


def tai_lich_su_gia(ma: str, nguon: str, so_ngay: int, thu_muc_cache: str):
    hom_nay = datetime.now().strftime("%Y-%m-%d")
    duong_dan = os.path.join(thu_muc_cache, f"{ma}_{hom_nay}.csv")
    if os.path.exists(duong_dan):
        return pd.read_csv(duong_dan, parse_dates=["time"])

    from vnstock import Quote
    start = (datetime.now() - timedelta(days=int(so_ngay * 1.6))).strftime("%Y-%m-%d")
    try:
        q = Quote(symbol=ma, source=nguon)
        df = q.history(start=start, end=hom_nay, interval="1D")
        if df is None or len(df) == 0:
            return None
        df.columns = [c.lower() for c in df.columns]
        can_thiet = {"time", "close", "volume"}
        if not can_thiet.issubset(set(df.columns)):
            return None
        df["time"] = pd.to_datetime(df["time"])
        df = df.sort_values("time").reset_index(drop=True)
        df.to_csv(duong_dan, index=False)
        return df
    except Exception as e:
        print(f"  [!] {ma}: loi tai du lieu ({type(e).__name__}: {e})", file=sys.stderr)
        return None


def lay_pe_pb(danh_sach: list, nguon: str, thu_muc_cache: str, nghi_giay: float = 0.6) -> pd.DataFrame:
    from vnstock import Finance
    hom_nay = datetime.now().strftime("%Y-%m-%d")
    dong = []
    for i, ma in enumerate(danh_sach, 1):
        try:
            cache_path = os.path.join(thu_muc_cache, f"ratio_{ma}_{hom_nay}.csv")
            if os.path.exists(cache_path):
                df = pd.read_csv(cache_path)
            else:
                fin = Finance(symbol=ma, source=nguon, show_log=False)
                df = fin.ratio(period="quarter", lang="en", dropna=True)
                if df is None or len(df) == 0:
                    continue
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [str(c[-1]) for c in df.columns]
                df.to_csv(cache_path, index=False)
                time.sleep(nghi_giay)

            cols = {str(c).strip().upper(): c for c in df.columns}
            col_pe = next((cols[k] for k in ("P/E", "PE", "PE_RATIO") if k in cols), None)
            col_pb = next((cols[k] for k in ("P/B", "PB", "PB_RATIO") if k in cols), None)
            if col_pe is None and col_pb is None:
                continue

            col_nam = next((c for c in df.columns if "year" in str(c).lower()), None)
            col_ky = next((c for c in df.columns if "length" in str(c).lower()
                           or "quarter" in str(c).lower()), None)
            if col_nam is not None:
                sap = [col_nam] + ([col_ky] if col_ky else [])
                df = df.sort_values(sap)
                row = df.iloc[-1]
            else:
                row = df.iloc[0]

            pe = pd.to_numeric(row[col_pe], errors="coerce") if col_pe is not None else None
            pb = pd.to_numeric(row[col_pb], errors="coerce") if col_pb is not None else None
            dong.append({"ma": ma, "pe": pe, "pb": pb})
        except Exception as e:
            print(f"  [!] {ma}: khong lay duoc dinh gia ({type(e).__name__})", file=sys.stderr)
            continue
        if i % 10 == 0:
            print(f"      ... dinh gia {i}/{len(danh_sach)} ma")
    if not dong:
        return pd.DataFrame(columns=["ma", "pe", "pb"])
    return pd.DataFrame(dong).drop_duplicates("ma")


# ---------------------- Gui Telegram ----------------------

def gui_telegram(text, duong_dan_file=None):
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[Telegram] Thieu TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — bo qua gui.")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=20,
        )
        if duong_dan_file and os.path.exists(duong_dan_file):
            with open(duong_dan_file, "rb") as f:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": chat_id},
                    files={"document": f},
                    timeout=60,
                )
        print("[Telegram] Da gui.")
    except Exception as e:
        print(f"[Telegram] Loi khi gui: {e}")


# ---------------------- Tinh chi bao 3 tang ----------------------

def tinh_chi_bao(df: pd.DataFrame, cfg: dict):
    n_dai = cfg["sma_dai"]
    if len(df) < n_dai + 10:
        return None

    close = df["close"].astype(float)
    volume = df["volume"].astype(float)

    sma50 = close.rolling(cfg["sma_ngan"]).mean()
    sma200 = close.rolling(n_dai).mean()
    rsi = wilder_rsi(close, 14)

    gtgd_ty = (close * 1000 * volume).rolling(20).mean().iloc[-1] / 1e9

    gia = close.iloc[-1]
    r_cuoi, r_truoc = rsi.iloc[-1], rsi.iloc[-2]

    trend = bool(sma50.iloc[-1] > sma200.iloc[-1] and gia > sma200.iloc[-1])
    cach_sma50 = (gia - sma50.iloc[-1]) / sma50.iloc[-1]
    pullback = abs(cach_sma50) <= cfg["khoang_cach_sma50"]
    rsi_vung = cfg["rsi_min"] <= r_cuoi <= cfg["rsi_max"]
    rsi_ngoc = (not cfg["rsi_phai_ngoc_len"]) or bool(r_cuoi > r_truoc)

    return {
        "gia": round(gia, 2),
        "sma50": round(sma50.iloc[-1], 2),
        "sma200": round(sma200.iloc[-1], 2),
        "rsi14": round(float(r_cuoi), 1),
        "cach_sma50_%": round(cach_sma50 * 100, 1),
        "gtgd_bq20_ty": round(float(gtgd_ty), 1),
        "trend": trend,
        "pullback_sma50": pullback,
        "rsi_vung": rsi_vung,
        "rsi_ngoc_len": rsi_ngoc,
        "entry": bool(trend and pullback and rsi_vung and rsi_ngoc),
    }


def kiem_tra_regime(cfg):
    if not cfg["bat_regime_filter"]:
        return True, "Regime filter dang TAT"
    df = tai_lich_su_gia(cfg["ma_chi_so"], cfg["nguon_du_lieu"],
                         cfg["so_phien_lich_su"], cfg["thu_muc_cache"])
    if df is None or len(df) < cfg["sma_dai"]:
        return True, f"Khong lay duoc {cfg['ma_chi_so']} — bo qua regime filter"
    close = df["close"].astype(float)
    sma200 = close.rolling(cfg["sma_dai"]).mean().iloc[-1]
    gia = close.iloc[-1]
    ok = gia > sma200
    return ok, (f"{cfg['ma_chi_so']} {gia:,.1f} {'TREN' if ok else 'DUOI'} "
               f"SMA200 ({sma200:,.1f})")


def luu_csv(df_luu, duong_dan):
    try:
        df_luu.to_csv(duong_dan, index=False, encoding="utf-8-sig")
        return duong_dan
    except PermissionError:
        goc, duoi = os.path.splitext(duong_dan)
        thay_the = f"{goc}_{datetime.now():%H%M%S}{duoi}"
        df_luu.to_csv(thay_the, index=False, encoding="utf-8-sig")
        print(f"  [!] File dang mo trong Excel — da luu thanh {thay_the}")
        return thay_the


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gioi-han", type=int, default=None)
    args = parser.parse_args()
    cfg = CONFIG
    os.makedirs(cfg["thu_muc_cache"], exist_ok=True)
    os.makedirs(cfg["thu_muc_ket_qua"], exist_ok=True)

    print("=" * 60)
    print(f"HOSE 3-TANG SCREENER — {datetime.now():%d/%m/%Y %H:%M}")
    print("=" * 60)

    regime_ok, regime_msg = kiem_tra_regime(cfg)
    print(f"\n[Tang 0] {regime_msg}")

    print("\n[1/3] Lay danh sach ma HOSE...")
    danh_sach = lay_danh_sach_hose(cfg["nguon_du_lieu"])
    if args.gioi_han:
        danh_sach = danh_sach[: args.gioi_han]
    print(f"      -> {len(danh_sach)} ma")

    print("\n[2/3] Tai lich su gia va tinh chi bao...")
    dong = []
    for i, ma in enumerate(danh_sach, 1):
        df = tai_lich_su_gia(ma, cfg["nguon_du_lieu"], cfg["so_phien_lich_su"], cfg["thu_muc_cache"])
        if df is not None:
            cb = tinh_chi_bao(df, cfg)
            if cb is not None:
                cb["ma"] = ma
                dong.append(cb)
        if i % 25 == 0:
            print(f"      ... {i}/{len(danh_sach)} ma")
        time.sleep(cfg["nghi_giua_2_ma_giay"])

    bang = pd.DataFrame(dong)
    if bang.empty:
        print("\nKhong tai duoc du lieu. Kiem tra mang / doi nguon_du_lieu sang 'TCBS'.")
        sys.exit(1)

    print(f"\nPheu loc tren {len(bang)} ma:")
    buoc = [
        (f"GTGD bq20 >= {cfg['min_gia_tri_gd_ty']} ty", bang["gtgd_bq20_ty"] >= cfg["min_gia_tri_gd_ty"]),
        ("Tang 1: trend (SMA50>SMA200 & gia>SMA200)", bang["trend"]),
        (f"Tang 3a: gia cach SMA50 +/-{cfg['khoang_cach_sma50']*100:.0f}%", bang["pullback_sma50"]),
        (f"Tang 3b: RSI {cfg['rsi_min']}-{cfg['rsi_max']}", bang["rsi_vung"]),
        ("Tang 3c: RSI ngoc len", bang["rsi_ngoc_len"]),
    ]
    loc = pd.Series(True, index=bang.index)
    for ten, dk in buoc:
        dk = dk.fillna(False)
        loc &= dk
        print(f"  - {ten:<45} rieng le: {int(dk.sum()):>4} | luy ke: {int(loc.sum()):>4}")

    # Watchlist tang 1+2: thanh khoan + trend (chua can entry)
    watchlist = bang[(bang["gtgd_bq20_ty"] >= cfg["min_gia_tri_gd_ty"]) & bang["trend"]].copy()
    print(f"\n      -> {len(watchlist)} ma trong watchlist (tang 1+2, truoc dinh gia)")

    print("\n[3/3] Lay P/E, P/B cho watchlist...")
    if len(watchlist):
        dinh_gia = lay_pe_pb(list(watchlist["ma"]), cfg["nguon_du_lieu"],
                             cfg["thu_muc_cache"], cfg["nghi_giua_2_ma_giay"])
        watchlist = watchlist.merge(dinh_gia, on="ma", how="left")
    else:
        watchlist["pe"] = None
        watchlist["pb"] = None

    pe_so = pd.to_numeric(watchlist.get("pe"), errors="coerce")
    pb_so = pd.to_numeric(watchlist.get("pb"), errors="coerce")
    loc_dinh_gia = (pe_so.isna() | ((pe_so > 0) & (pe_so <= cfg["pe_max"]))) & \
                   (pb_so.isna() | ((pb_so > 0) & (pb_so <= cfg["pb_max"])))
    watchlist = watchlist[loc_dinh_gia].sort_values("entry", ascending=False).reset_index(drop=True)

    cot = ["ma", "gia", "sma50", "sma200", "cach_sma50_%", "rsi14", "pe", "pb",
           "gtgd_bq20_ty", "entry"]
    cot = [c for c in cot if c in watchlist.columns]

    print(f"\n{'=' * 60}\nWATCHLIST (tang 1+2 qua dinh gia): {len(watchlist)} ma\n{'=' * 60}")
    if len(watchlist):
        print(watchlist[cot].to_string(index=False))

    ung_vien = watchlist[watchlist["entry"]] if regime_ok else watchlist.iloc[0:0]
    print(f"\nUNG VIEN VAO LENH TUAN NAY (tang 3, regime {'BAT' if regime_ok else 'TAT'}): {len(ung_vien)} ma")
    if len(ung_vien):
        print(ung_vien[cot].to_string(index=False))

    hom_nay = datetime.now().strftime("%Y%m%d")
    file_kq = os.path.join(cfg["thu_muc_ket_qua"], f"watchlist_{hom_nay}.csv")
    if len(watchlist):
        file_kq = luu_csv(watchlist[cot], file_kq)
        print(f"\nDa luu: {file_kq}")

    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        dong_tin = [f"<b>HOSE Screener — {datetime.now():%d/%m/%Y}</b>", regime_msg, ""]
        dong_tin.append(f"Watchlist (tang 1+2): {len(watchlist)} ma")
        dong_tin.append(f"Ung vien vao lenh: {len(ung_vien)} ma")
        for _, r in ung_vien.iterrows():
            dong_tin.append(f"• {r['ma']}: gia {r['gia']:,.0f}, RSI {r['rsi14']}, "
                            f"cach SMA50 {r['cach_sma50_%']}%")
        gui_telegram("\n".join(dong_tin), file_kq if len(watchlist) else None)

    print("\nLuu y: ket qua chi mang tinh sang loc thong tin, khong phai khuyen nghi dau tu.")


if __name__ == "__main__":
    main()