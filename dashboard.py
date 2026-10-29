"""Dashboard pemantauan hidroponik selada (Bit&Byte).

Jalankan:  streamlit run dashboard.py
Butuh:     pip install streamlit paho-mqtt pandas plotly
Data:      dikirim ESP32 (Wokwi atau alat asli) lewat MQTT.
"""
import json
import time
import uuid
from collections import deque
from datetime import datetime

import pandas as pd
import paho.mqtt.client as mqtt
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Pemantauan Hidroponik", page_icon="🌱", layout="wide")

# Gaya: hanya memperbesar angka agar mudah dibaca.
st.markdown(
    "<style>[data-testid='stMetricValue']{font-size:2.6rem}</style>",
    unsafe_allow_html=True,
)

# Batas mengikuti README: suhu/kelembapan (kipas), jarak air (pompa), pH 5.5-6.5, PPM 560-840.
# k = nama data, n = nama di layar, h = penjelasan singkat, u = satuan, d = jumlah angka desimal
M = [
    dict(k="suhu", n="Suhu udara", h="Panas atau dinginnya ruangan", u="°C", d=1, safe=(18, 32), band=[36],
         st=lambda v: "bad" if v > 36 else "warn" if v > 32 else "ok"),
    dict(k="hum", n="Kelembapan udara", h="Lembap atau keringnya udara", u="%", d=0, safe=(40, 65), band=[78],
         st=lambda v: "bad" if v > 78 else "warn" if v > 65 else "ok"),
    dict(k="lux", n="Cahaya", h="Terang atau gelapnya ruangan", u="lux", d=0, safe=None, band=[],
         st=lambda v: "ok"),
    dict(k="jarak", n="Jarak ke permukaan air", h="Makin besar angkanya, makin sedikit air di tandon",
         u="cm", d=0, safe=(100, 180), band=[200], sub="status_air",
         st=lambda v: "bad" if v >= 200 else "warn" if v > 180 else "ok"),
    dict(k="ph", n="pH air", h="Tingkat asam atau basa air", u="", d=2, safe=(5.5, 6.5), band=[5.5, 6.5],
         sub="status_ph",
         st=lambda v: "bad" if v < 5.5 or v > 6.5 else "warn" if v < 5.7 or v > 6.3 else "ok"),
    dict(k="ppm", n="Nutrisi dalam air (PPM)", h="Seberapa pekat pupuk dalam air", u="ppm", d=0,
         safe=(560, 840), band=[560, 840], sub="status_ppm",
         st=lambda v: "bad" if v < 560 or v > 840 else "warn" if v < 600 or v > 800 else "ok"),
]

# nama di layar, penjelasan fungsi
AKTUATOR = [
    ("kipas", "Kipas", "Mendinginkan ruangan"),
    ("pompa", "Pompa air", "Mengisi air ke tandon"),
    ("lampu", "Lampu", "Cahaya tambahan untuk tanaman"),
]
MODE_TEKS = {
    "AUTO": "Otomatis: alat mengatur sendiri.",
    "ON": "Dinyalakan manual. Kembali otomatis dalam 15 menit.",
    "OFF": "Dimatikan manual. Kembali otomatis dalam 15 menit.",
}

WARNA = {"ok": "green", "warn": "orange", "bad": "red", "na": "red"}
TEKS = {"ok": "Normal", "warn": "Hati-hati", "bad": "Di luar batas aman", "na": "Sensor tidak terbaca"}


def rentang_aman(m):
    if not m["safe"]:
        return "Tidak ada batas"
    lo, hi = m["safe"]
    return f"Aman: {lo:g} sampai {hi:g} {m['u']}".strip()


class State:
    """Data bersama antara thread MQTT dan tampilan Streamlit."""

    def __init__(self):
        self.hist = deque(maxlen=1500)
        self.log = deque(maxlen=50)
        self.alarms = {}
        self.last = None
        self.last_ts = 0.0
        self.online = None
        self.mqtt_ok = False
        self.pred = None

    def alarm(self, key, label, on, msg=""):
        if self.alarms.get(key, False) == on:
            return
        self.alarms[key] = on
        jam = datetime.now().strftime("%H:%M:%S")
        self.log.appendleft((jam, "bad" if on else "ok", msg if on else f"Kembali normal: {label}"))

    def cek(self, d):
        for m in M:
            v = d.get(m["k"])
            if v is None:
                self.alarm(m["k"], m["n"], True, f"{m['n']}: sensor tidak terbaca")
            else:
                extra = " (air hampir habis)" if m["k"] == "jarak" else ""
                self.alarm(m["k"], m["n"], m["st"](v) == "bad",
                           f"{m['n']} {v:.{m['d']}f} {m['u']} di luar batas aman{extra}")


@st.cache_resource
def registry():
    return {}


@st.cache_resource
def mulai(host, port, dev):
    """Satu koneksi MQTT per kombinasi broker + ID perangkat."""
    reg = registry()
    if reg.get("client"):  # hentikan koneksi lama saat pengaturan diganti
        reg["client"].loop_stop()
        reg["client"].disconnect()
    S, base = State(), f"hidroponik/{dev}/"
    cid = "dash_" + uuid.uuid4().hex[:6]
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
    except AttributeError:  # paho-mqtt 1.x
        c = mqtt.Client(client_id=cid)

    def on_connect(c, u, f, rc, p=None):
        S.mqtt_ok = True
        c.subscribe(base + "#")

    def on_disconnect(c, u, *a):
        S.mqtt_ok = False

    def on_message(c, u, msg):
        t, p = msg.topic[len(base):], msg.payload.decode(errors="ignore").strip()
        try:
            if t == "telemetry":
                d = json.loads(p)
                S.last, S.last_ts, S.online = d, time.time(), True
                S.hist.append({"ts": datetime.now(), **d})
                S.alarm("dev", "Alat", False)
                S.cek(d)
            elif t == "status":
                S.online = p == "online"
                S.alarm("dev", "Alat", not S.online, "Alat mati atau tidak terhubung")
            elif t == "prediksi":
                S.pred = json.loads(p)
        except Exception:
            pass

    c.on_connect, c.on_disconnect, c.on_message = on_connect, on_disconnect, on_message
    c.connect_async(host, port, 60)
    c.loop_start()
    reg["client"] = c
    return S, c, base


def kirim(c, base, aktuator, perintah):
    c.publish(f"{base}cmd/{aktuator}", perintah)


def grafik(S, m, menit):
    df = pd.DataFrame(list(S.hist))
    if df.empty or m["k"] not in df or df[m["k"]].dropna().empty:
        st.info("Grafik akan muncul setelah data masuk.")
        return
    df = df[df["ts"] >= datetime.now() - pd.Timedelta(minutes=menit)].dropna(subset=[m["k"]])
    fig = go.Figure(go.Scatter(x=df["ts"], y=df[m["k"]], mode="lines", name=m["n"], line=dict(width=3)))
    if m["safe"]:
        fig.add_hrect(y0=m["safe"][0], y1=m["safe"][1], fillcolor="green", opacity=0.10, line_width=0)
    for b in m["band"]:
        fig.add_hline(y=b, line_dash="dash", line_color="red")
    nilai = list(df[m["k"]]) + m["band"]
    lo, hi = min(nilai), max(nilai)
    pad = (hi - lo or 1) * 0.15
    fig.update_yaxes(range=[lo - pad, hi + pad], title=m["u"])
    fig.update_xaxes(title="Waktu")
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10), showlegend=False, font=dict(size=14))
    st.plotly_chart(fig)
    if m["safe"] or m["band"]:
        st.caption("Area hijau = rentang aman. Garis merah putus-putus = batas yang tidak boleh dilewati.")


def detail_teknis(S, base, umur):
    with st.expander("Detail teknis (untuk pengelola)"):
        st.write(f"Server MQTT: {'tersambung' if S.mqtt_ok else 'terputus'}")
        st.write("Alat: " + {True: "online", False: "offline", None: "belum diketahui"}[S.online])
        st.write("Data terakhir: " + ("belum ada" if umur is None else f"{int(umur)} detik lalu"))
        st.write(f"Topik data: `{base}telemetry`")


@st.fragment(run_every=2)
def live(S, c, base):
    umur = time.time() - S.last_ts if S.last_ts else None
    basi = umur is not None and umur > 20
    S.alarm("stale", "Data", basi, "Tidak ada data masuk lebih dari 20 detik")

    d = S.last
    if not d:
        st.info("Menunggu data dari alat. Pastikan alat atau simulasi Wokwi sudah menyala, "
                "dan ID perangkat di panel kiri sama dengan yang ada di firmware.")
        detail_teknis(S, base, umur)
        return

    # --- Ringkasan: satu kalimat yang menjawab "apakah semuanya baik?" ---
    status = {m["k"]: "na" if d.get(m["k"]) is None else m["st"](d[m["k"]]) for m in M}
    bahaya = [m["n"] for m in M if status[m["k"]] in ("bad", "na")]
    hati = [m["n"] for m in M if status[m["k"]] == "warn"]
    if basi or S.online is False:
        st.error("Data dari alat tidak masuk. Cek apakah alat menyala dan tersambung internet.")
    elif bahaya:
        st.error("Perlu dicek sekarang: " + ", ".join(bahaya) + ".")
    elif hati:
        st.warning("Perlu dipantau: " + ", ".join(hati) + " hampir keluar batas aman.")
    else:
        st.success("Semua baik. Semua ukuran masih dalam batas aman.")
    st.caption("Data terakhir masuk " + (f"{int(umur)} detik lalu." if umur is not None else "belum ada."))

    # --- Kartu sensor: 3 kolom agar angka besar dan jelas ---
    for baris in (M[:3], M[3:]):
        for kol, m in zip(st.columns(3), baris):
            v = d.get(m["k"])
            s = status[m["k"]]
            with kol.container(border=True):
                st.metric(m["n"], "-" if v is None else f"{v:.{m['d']}f} {m['u']}".strip())
                st.caption(m["h"])
                st.markdown(f"**:{WARNA[s]}[{TEKS[s]}]**")
                st.caption(rentang_aman(m))
                ket = d.get(m["sub"], "") if m.get("sub") and s != "na" else ""
                if ket:
                    st.caption(f"Keterangan dari alat: {ket}")

    # --- Grafik dan perkiraan ---
    kiri, kanan = st.columns([2, 1])
    with kiri:
        st.subheader("Grafik")
        pilih = st.radio("Tampilkan", [m["k"] for m in M], horizontal=True, key="metrik",
                         format_func=lambda k: next(m["n"] for m in M if m["k"] == k))
        menit = st.radio("Rentang waktu", [5, 15, 30, 60], index=1, horizontal=True, key="menit",
                         format_func=lambda x: f"{x} menit terakhir")
        grafik(S, next(m for m in M if m["k"] == pilih), menit)
    with kanan:
        st.subheader("Perkiraan suhu 30 menit lagi")
        p = S.pred
        if p and p.get("pred30") is not None:
            suhu = d.get("suhu")
            delta = f"{p['pred30'] - suhu:+.1f} °C dari sekarang" if suhu is not None else None
            st.metric("Perkiraan suhu", f"{p['pred30']:.1f} °C", delta, delta_color="inverse")
            st.caption("Saran: " + (p.get("aksi") or "tidak perlu tindakan")
                       + (". Ini hanya saran, belum dijalankan alat." if p.get("shadow") else "."))
        else:
            st.caption("Perkiraan belum tersedia. Program bridge.py perlu menyala untuk menghitungnya.")

    # --- Kontrol alat ---
    st.subheader("Kendali alat")
    st.caption("Biarkan di mode Otomatis kecuali perlu menyalakan atau mematikan sendiri.")
    for kol, (a, nama, fungsi) in zip(st.columns(3), AKTUATOR):
        mode = d.get(f"mode_{a}", "AUTO")
        with kol.container(border=True):
            st.markdown(f"**{nama}**: {'sedang menyala' if d.get(a) == 1 else 'mati'}")
            st.caption(fungsi)
            for tombol, (cmd, label) in zip(st.columns(3), [("ON", "Nyalakan"), ("OFF", "Matikan"), ("AUTO", "Otomatis")]):
                tombol.button(label, key=f"{a}_{cmd}", on_click=kirim, args=(c, base, a, cmd),
                              type="primary" if cmd == mode else "secondary", use_container_width=True)
            st.caption(MODE_TEKS.get(mode, f"Mode: {mode}"))

    # --- Kejadian ---
    st.subheader("Kejadian terbaru")
    if S.log:
        for jam, tingkat, teks in list(S.log)[:12]:
            st.markdown(f"{jam}  :{'red' if tingkat == 'bad' else 'green'}[{teks}]")
    else:
        st.caption("Belum ada kejadian.")

    detail_teknis(S, base, umur)


# ---------- Halaman ----------
st.title("Pemantauan Hidroponik Selada")
st.caption("Bit&Byte, SIC Universitas Kuningan")

with st.sidebar:
    st.header("Pengaturan sambungan")
    host = st.text_input("Alamat server (broker)", "broker.hivemq.com")
    port = st.number_input("Port", value=1883, step=1)
    dev = st.text_input("ID perangkat", "bitbyte_uniku", help="Harus sama dengan ID_PERANGKAT di firmware")
    st.caption("Server publik tidak memakai kata sandi. Siapa pun yang tahu ID perangkat bisa melihat data "
               "dan mengirim perintah. Pakai ID yang sulit ditebak.")

S, client, base = mulai(host.strip(), int(port), dev.strip())
live(S, client, base)