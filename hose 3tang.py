# -*- coding: utf-8 -*-
"""
hose_3tang.py
Screener HOSE 3 tang — tao watchlist ung vien vao lenh trong tuan.

Tang 0 (regime): VN-Index phai dang tren SMA200 — neu khong, tang 3 tat,
                 script chi in danh sach tang 1+2 de theo doi.
Tang 1 (trend) : SMA50 > SMA200 va gia > SMA200 (trang thai, khong can cross).
Tang 2 (chat luong): GTGD TB20 >= nguong, P/E <= nguong, P/B <= nguong
                 (ma thieu du lieu dinh gia van qua, cot pe/pb de trong).
Tang 3 (entry) : pullback ve SMA50 — gia cach SMA50 trong +/-3%,
                 RSI(14) trong 40-55 va dang ngoc len (RSI hom nay > hom qua).

Cach chay (Windows, thu muc C:\\Users\\dientd\\Desktop\\HOSE):
    venv\\Scripts\\activate
    python hose_3tang.py               # chay ca san
    python hose_3tang.py --gioi-han 30 # chay thu
"""

import argparse
import datetime as dt
import os
import time

import pandas as pd

# ============================ CONFIG ============================
CONFIG = {
    "NGUON": "VCI",                   # doi sang "TCBS" neu VCI bi chan
    "SO_NGAY_LICH_SU": 550,           # can du ~250 phien cho SMA200
    "SO_PHIEN_TOI_THIEU": 220,

    # Tang 0 — market regime
    "BAT_REGIME_FILTER": True,        # False = bo qua kiem tra VN-Index
    "MA_CHI_SO": "VNINDEX",

    # Tang 2 — chat luong
    "GTGD_TB20_TOI_THIEU": 20e9,      # >= 20 ty VND
    "PE_TOI_DA": 20,
    "PB_TOI_DA": 3,

    # Tang 3 — entry pullback
    "KHOANG_CACH_SMA50": 0.03,        # gia cach SMA50 trong +/-3%
    "RSI_MIN": 40,
    "RSI_MAX": 55,
    "RSI_PHAI_NGOC_LEN": True,        # RSI hom nay > hom qua

    "THU_MUC_CACHE": "cache_3tang",
    "FILE_KET_QUA": "watchlist_3tang.xlsx",
    "NGHI_GIUA_2_MA": 0.3,

    # Gui ket qua qua Telegram (dung khi chay tren GitHub Actions)
    "GUI_TELEGRAM": os.environ.get("TELEGRAM_BOT_TOKEN") is not None,
}
# ================================================================


def gui_telegram(text, duong_dan_file=None):
    """Gui tin nhan (va kem file neu co) qua Telegram bot.
    Doc token/chat_id tu bien moi truong TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID —
    KHONG bao gio ghi cung vao code, luon truyen qua GitHub Secrets."""
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


# ---------------------- Tien ich chung ----------------------

def duong_dan_cache(ma):
    hom_nay = dt.date.today().isoformat()
    thu_muc = os.path.join(CONFIG["THU_MUC_CACHE"], hom_nay)
    os.makedirs(thu_muc, exist_ok=True)
    return os.path.join(thu_muc, f"{ma}.csv")


def tai_lich_su(ma):
    """Tai lich su gia, cache theo ngay."""
    f = duong_dan_cache(ma)
    if os.path.exists(f):
        return pd.read_csv(f, parse_dates=["time"])
    from vnstock import Vnstock
    end = dt.date.today()
    start = end - dt.timedelta(days=CONFIG["SO_NGAY_LICH_SU"])
    stock = Vnstock().stock(symbol=ma, source=CONFIG["NGUON"])
    df = stock.quote.history(start=start.isoformat(), end=end.isoformat(),
                             interval="1D")
    if df is None or df.empty:
        return None
    df = df.reset_index() if "time" not in df.columns else df
    df.to_csv(f, index=False)
    time.sleep(CONFIG["NGHI_GIUA_2_MA"])
    return df


def he_so_gia(df):
    """VCI thuong tra gia nghin dong; tu phat hien de tinh GTGD dung."""
    return 1000.0 if df["close"].median() < 500 else 1.0


def wilder_rsi(gia, chu_ky=14):
    delta = gia.diff()
    tang = delta.clip(lower=0)
    giam = -delta.clip(upper=0)
    avg_tang = tang.ewm(alpha=1 / chu_ky, min_periods=chu_ky).mean()
    avg_giam = giam.ewm(alpha=1 / chu_ky, min_periods=chu_ky).mean()
    rs = avg_tang / avg_giam
    return 100 - 100 / (1 + rs)


def lay_danh_sach_hose():
    from vnstock import Listing
    df = Listing(source=CONFIG["NGUON"]).symbols_by_exchange()
    cot_san = "exchange" if "exchange" in df.columns else "comGroupCode"
    cot_loai = "type" if "type" in df.columns else None
    df_hose = df[df[cot_san].astype(str).str.upper().isin(["HSX", "HOSE"])]
    if cot_loai:
        df_hose = df_hose[df_hose[cot_loai].astype(str).str.upper() == "STOCK"]
    ma = sorted(df_hose["symbol"].dropna().unique().tolist())
    return [m for m in ma if len(m) == 3]


# ---------------------- Tang 0: regime ----------------------

def kiem_tra_regime():
    """VN-Index co dang tren SMA200 khong? Loi tai chi so -> coi nhu OK
    nhung in canh bao (khong chan ca pipeline vi mot loi mang)."""
    if not CONFIG["BAT_REGIME_FILTER"]:
        return True, "Regime filter dang TAT trong CONFIG"
    try:
        df = tai_lich_su(CONFIG["MA_CHI_SO"])
        if df is None or len(df) < 200:
            return True, "Khong du du lieu VN-Index — bo qua regime filter"
        df = df.sort_values("time")
        sma200 = df["close"].rolling(200).mean().iloc[-1]
        gia = df["close"].iloc[-1]
        ok = gia > sma200
        return ok, (f"VN-Index {gia:,.0f} {'TREN' if ok else 'DUOI'} "
                    f"SMA200 ({sma200:,.0f})")
    except Exception as e:
        return True, f"Loi lay VN-Index ({e}) — bo qua regime filter"


# ---------------------- Tang 2: dinh gia ----------------------

def lay_pe_pb(ma):
    """Lay P/E, P/B ky quy moi nhat qua Finance.ratio.
    Chi goi cho nhom da qua tang 1 (tiet kiem API call)."""
    try:
        from vnstock import Finance
        fin = Finance(symbol=ma, source=CONFIG["NGUON"])
        df = fin.ratio(period="quarter")
        if df is None or df.empty:
            return None, None
        # Ten cot khac nhau giua cac ban vnstock — do tim mem deo
        cols = {c.lower(): c for c in df.columns}
        pe_col = next((cols[k] for k in cols if "p/e" in k or k == "pe"
                       or "price_to_earning" in k), None)
        pb_col = next((cols[k] for k in cols if "p/b" in k or k == "pb"
                       or "price_to_book" in k), None)
        hang = df.iloc[0]  # ky moi nhat thuong o dau; neu nguoc, doi iloc[-1]
        pe = float(hang[pe_col]) if pe_col and pd.notna(hang[pe_col]) else None
        pb = float(hang[pb_col]) if pb_col and pd.notna(hang[pb_col]) else None
        time.sleep(CONFIG["NGHI_GIUA_2_MA"])
        return pe, pb
    except Exception:
        return None, None


# ---------------------- Danh gia tung ma ----------------------

def danh_gia_ky_thuat(ma):
    """Tang 1 + thanh khoan + tin hieu tang 3 (chua co dinh gia)."""
    kq = {
        "ma": ma, "du_du_lieu": False, "thanh_khoan": False,
        "trend": False, "pullback_sma50": False, "rsi_vung": False,
        "rsi_ngoc_len": False, "entry": False,
        "gia": None, "sma50": None, "sma200": None, "rsi": None,
        "cach_sma50_pct": None, "gtgd_tb20_ty": None,
    }
    try:
        df = tai_lich_su(ma)
    except Exception as e:
        print(f"  [loi] {ma}: {e}")
        return kq
    if df is None or len(df) < CONFIG["SO_PHIEN_TOI_THIEU"]:
        return kq
    kq["du_du_lieu"] = True

    df = df.sort_values("time").reset_index(drop=True)
    hs = he_so_gia(df)

    gtgd = (df["close"] * hs * df["volume"]).rolling(20).mean().iloc[-1]
    kq["gtgd_tb20_ty"] = round(gtgd / 1e9, 1)
    kq["thanh_khoan"] = gtgd >= CONFIG["GTGD_TB20_TOI_THIEU"]

    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()
    df["rsi"] = wilder_rsi(df["close"])
    cuoi, truoc = df.iloc[-1], df.iloc[-2]

    kq["gia"] = round(cuoi["close"] * hs)
    kq["sma50"] = round(cuoi["sma50"] * hs)
    kq["sma200"] = round(cuoi["sma200"] * hs)
    kq["rsi"] = round(cuoi["rsi"], 1)

    # Tang 1: trend
    kq["trend"] = bool(cuoi["sma50"] > cuoi["sma200"]
                       and cuoi["close"] > cuoi["sma200"])

    # Tang 3: entry pullback
    cach = (cuoi["close"] - cuoi["sma50"]) / cuoi["sma50"]
    kq["cach_sma50_pct"] = round(cach * 100, 1)
    kq["pullback_sma50"] = abs(cach) <= CONFIG["KHOANG_CACH_SMA50"]
    kq["rsi_vung"] = CONFIG["RSI_MIN"] <= cuoi["rsi"] <= CONFIG["RSI_MAX"]
    kq["rsi_ngoc_len"] = (not CONFIG["RSI_PHAI_NGOC_LEN"]) or \
                         bool(cuoi["rsi"] > truoc["rsi"])
    kq["entry"] = kq["pullback_sma50"] and kq["rsi_vung"] and kq["rsi_ngoc_len"]
    return kq


# ---------------------- Pheu loc ----------------------

def in_pheu_loc(ds, regime_ok):
    tong = len(ds)
    df = pd.DataFrame(ds)
    buoc = [
        ("Du du lieu (>=220 phien)", "du_du_lieu"),
        (f"GTGD TB20 >= {CONFIG['GTGD_TB20_TOI_THIEU']/1e9:.0f} ty", "thanh_khoan"),
        ("Tang 1: SMA50>SMA200 & gia>SMA200", "trend"),
        (f"Tang 3a: gia cach SMA50 +/-{CONFIG['KHOANG_CACH_SMA50']*100:.0f}%", "pullback_sma50"),
        (f"Tang 3b: RSI {CONFIG['RSI_MIN']}-{CONFIG['RSI_MAX']}", "rsi_vung"),
        ("Tang 3c: RSI ngoc len", "rsi_ngoc_len"),
    ]
    print("\n===== PHEU LOC (tong so ma quet: %d) =====" % tong)
    print(f"{'Tieu chi':42s} {'Rieng le':>9s} {'Luy ke':>8s}")
    mask = pd.Series(True, index=df.index)
    for ten, cot in buoc:
        mask = mask & df[cot]
        print(f"{ten:42s} {int(df[cot].sum()):>9d} {int(mask.sum()):>8d}")
    print("(P/E, P/B kiem tra o buoc sau, chi cho nhom qua ky thuat)")
    print("Regime:", "VN-Index TREN SMA200 — tang 3 BAT" if regime_ok
          else "VN-Index DUOI SMA200 — tang 3 TAT, chi in watchlist theo doi")
    print("=" * 62)


def luu_ket_qua(df_out, ten_file):
    try:
        df_out.to_excel(ten_file, index=False)
    except PermissionError:
        gio = dt.datetime.now().strftime("%H%M%S")
        ten_file = ten_file.replace(".xlsx", f"_{gio}.xlsx")
        df_out.to_excel(ten_file, index=False)
    print(f"Da luu: {ten_file}")


# ---------------------- Main ----------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gioi-han", type=int, default=None)
    args = p.parse_args()

    regime_ok, regime_msg = kiem_tra_regime()
    print("Tang 0 —", regime_msg)

    print("Lay danh sach ma HOSE...")
    ds_ma = lay_danh_sach_hose()
    if args.gioi_han:
        ds_ma = ds_ma[: args.gioi_han]
    print(f"Se quet {len(ds_ma)} ma. Nguon: {CONFIG['NGUON']}")

    ket_qua = []
    for i, ma in enumerate(ds_ma, 1):
        if i % 25 == 0 or i == len(ds_ma):
            print(f"  ... {i}/{len(ds_ma)}")
        ket_qua.append(danh_gia_ky_thuat(ma))

    in_pheu_loc(ket_qua, regime_ok)
    df = pd.DataFrame(ket_qua)

    # Nhom qua tang 1 + thanh khoan -> moi lay P/E, P/B
    qua_kt = df[df["du_du_lieu"] & df["thanh_khoan"] & df["trend"]].copy()
    print(f"\nLay P/E, P/B cho {len(qua_kt)} ma qua tang 1...")
    pe_list, pb_list, dat_dg = [], [], []
    for ma in qua_kt["ma"]:
        pe, pb = lay_pe_pb(ma)
        pe_list.append(pe)
        pb_list.append(pb)
        ok_pe = (pe is None) or (0 < pe <= CONFIG["PE_TOI_DA"])
        ok_pb = (pb is None) or (0 < pb <= CONFIG["PB_TOI_DA"])
        dat_dg.append(ok_pe and ok_pb)
    qua_kt["pe"] = pe_list
    qua_kt["pb"] = pb_list
    qua_kt["dat_dinh_gia"] = dat_dg

    watchlist = qua_kt[qua_kt["dat_dinh_gia"]].copy()
    cot_ra = ["ma", "gia", "sma50", "sma200", "cach_sma50_pct", "rsi",
              "pe", "pb", "gtgd_tb20_ty", "entry"]

    print(f"\nWATCHLIST (qua tang 1+2): {len(watchlist)} ma")
    if not watchlist.empty:
        print(watchlist[cot_ra].sort_values("entry", ascending=False)
              .to_string(index=False))

    if regime_ok:
        ung_vien = watchlist[watchlist["entry"]]
        print(f"\nUNG VIEN VAO LENH TUAN NAY (tang 3): {len(ung_vien)} ma")
        if not ung_vien.empty:
            print(ung_vien[cot_ra].to_string(index=False))
    else:
        print("\nVN-Index duoi SMA200 — KHONG in ung vien vao lenh.")

    ten_file_ket_qua = CONFIG["FILE_KET_QUA"]
    if not watchlist.empty:
        luu_ket_qua(watchlist[cot_ra], ten_file_ket_qua)

    if CONFIG["GUI_TELEGRAM"]:
        hom_nay = dt.date.today().strftime("%d/%m/%Y")
        dong = [f"<b>HOSE Screener — {hom_nay}</b>", regime_msg, ""]
        dong.append(f"Watchlist (tang 1+2): {len(watchlist)} ma")
        if regime_ok:
            ung_vien = watchlist[watchlist["entry"]]
            dong.append(f"Ung vien vao lenh tuan nay: {len(ung_vien)} ma")
            if not ung_vien.empty:
                dong.append("")
                for _, r in ung_vien.iterrows():
                    dong.append(
                        f"• {r['ma']}: gia {r['gia']:,.0f}, RSI {r['rsi']}, "
                        f"cach SMA50 {r['cach_sma50_pct']}%"
                    )
        else:
            dong.append("VN-Index duoi SMA200 — khong co ung vien vao lenh.")
        noi_dung = "\n".join(dong)
        gui_telegram(noi_dung, ten_file_ket_qua if not watchlist.empty else None)


if __name__ == "__main__":
    main()
