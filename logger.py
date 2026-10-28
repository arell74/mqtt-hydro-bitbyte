import csv, json, os, time
import paho.mqtt.client as mqtt

BASE = "hidroponik/bitbyte_uniku/"
FILE = "data_hidroponik.csv"
KOLOM = ["ts", "suhu", "hum", "lux", "jarak", "ph", "ppm", "kipas", "pompa", "lampu"]

def on_connect(c, userdata, flags, reason_code, properties):
    print("Terhubung:", reason_code)
    c.subscribe(BASE + "telemetry")      # subscribe di sini agar otomatis ulang saat reconnect

def on_message(c, userdata, msg):
    d = json.loads(msg.payload)
    d["ts"] = int(time.time())           # pakai jam laptop, bukan RTC Wokwi
    baru = not os.path.exists(FILE)
    with open(FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=KOLOM, extrasaction="ignore")
        if baru:
            w.writeheader()
        w.writerow(d)
    print(d["ts"], d.get("suhu"), d.get("hum"), d.get("lux"))

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.on_connect = on_connect
c.on_message = on_message
c.connect("broker.hivemq.com", 1883)
c.loop_forever()