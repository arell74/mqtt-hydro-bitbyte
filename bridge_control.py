import json, time
import joblib, pandas as pd
import paho.mqtt.client as mqtt

# ================= PENGATURAN =================
BROKER = "broker.hivemq.com"
BASE   = "hidroponik/bitbyte_uniku/"        # samakan dengan ID_PERANGKAT di ESP32

KONTROL = True       # False = SHADOW MODE (hanya memprediksi). True = benar-benar kirim perintah.

BATAS_PRA_AKTIF = 34.0   # prediksi >= ini -> kipas dinyalakan lebih awal
BATAS_LEPAS     = 33.0   # prediksi < ini  -> kipas dikembalikan ke AUTO
HEARTBEAT       = 300    # detik (waktu ESP32): kirim ulang ON, karena firmware membatalkan override setelah 15 menit
# JENDELA_TREN    = 300    # tren suhu dihitung dari 5 menit terakhir
JENDELA_TREN = 30    # khusus demo dengan slider diam; kembalikan ke 300 untuk data sungguhan
# ===============================================

paket = joblib.load("model_suhu.pkl")
model, FITUR = paket["model"], paket["fitur"]

riwayat = []             # [(uptime_detik, suhu)]
ai_menyalakan = False    # True jika kipas sedang di-ON-kan oleh AI
t_kirim = 0


def hitung_tren(up, suhu):
    """Selisih suhu sekarang dengan ±5 menit lalu (pakai waktu ESP32, bukan jam laptop)."""
    riwayat.append((up, suhu))
    while len(riwayat) > 1 and up - riwayat[1][0] >= JENDELA_TREN:   # buang data yang lebih tua dari 5 menit
        riwayat.pop(0)
    umur = up - riwayat[0][0]
    if umur < JENDELA_TREN:
        return None, umur
    return suhu - riwayat[0][1], umur


def kirim(c, nilai):
    if KONTROL:
        c.publish(BASE + "cmd/kipas", nilai)
        print(f"   >>> DIKIRIM: cmd/kipas = {nilai}")
    else:
        print(f"   [SHADOW] seharusnya kirim: cmd/kipas = {nilai}  (belum dikirim)")


def on_connect(c, userdata, flags, reason_code, properties):
    print("Terhubung ke broker:", reason_code)
    c.subscribe(BASE + "telemetry")


def on_message(c, userdata, msg):
    global ai_menyalakan, t_kirim
    d = json.loads(msg.payload)
    suhu, hum = d.get("suhu"), d.get("hum")
    if suhu is None or hum is None:
        print("Sensor DHT error, dilewati"); return

    up = d["uptime"]
    if riwayat and up < riwayat[-1][0]:         # ESP32 restart -> riwayat tidak berlaku lagi
        riwayat.clear()

    tren, umur = hitung_tren(up, suhu)
    if tren is None:
        print(f"Mengumpulkan riwayat... {umur}/{JENDELA_TREN} detik"); return

    x = pd.DataFrame([[suhu, hum, d["lux"], d["kipas"], tren]], columns=FITUR)
    pred = model.predict(x)[0]
    print(f"suhu={suhu:.1f} hum={hum:.0f} lux={d['lux']} kipas={d['kipas']} "
          f"tren5={tren:+.2f} -> prediksi 30 mnt: {pred:.1f} C | mode_kipas={d['mode_kipas']}")

    # ---------- keputusan ----------
    if not ai_menyalakan:
        if pred >= BATAS_PRA_AKTIF and d["mode_kipas"] == "AUTO":
            print("   AI: suhu diprediksi naik -> nyalakan kipas lebih awal")
            kirim(c, "ON"); ai_menyalakan = True; t_kirim = up
    else:
        if KONTROL and d["mode_kipas"] != "ON":   # ada pihak lain yang mengambil alih / override habis
            ai_menyalakan = False
        elif pred < BATAS_LEPAS:
            print("   AI: suhu aman -> kembalikan ke AUTO")
            kirim(c, "AUTO"); ai_menyalakan = False
        elif up - t_kirim >= HEARTBEAT:
            kirim(c, "ON"); t_kirim = up        # perpanjang override


c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.on_connect = on_connect
c.on_message = on_message
print("Mode:", "KONTROL AKTIF" if KONTROL else "SHADOW (hanya prediksi)")
c.connect(BROKER, 1883, keepalive=60)
c.loop_forever()