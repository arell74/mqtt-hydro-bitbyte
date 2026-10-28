import numpy as np, pandas as pd, joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error

rng = np.random.default_rng(42)
HARI = 60
N = HARI * 1440                       # 1 baris = 1 menit

menit = np.arange(N)
jam   = (menit % 1440) / 60.0
hari  = menit // 1440

# --- cuaca sintetis ---
offset_hari = rng.normal(0, 2.0, HARI)          # hari lebih panas / lebih sejuk
awan_hari   = rng.uniform(0.3, 1.0, HARI)       # 1 = cerah, 0.3 = mendung
suhu_luar   = 26 + 5*np.sin((jam-8)/24*2*np.pi) + offset_hari[hari]   # puncak jam 14
matahari    = np.clip(np.sin((jam-6)/12*np.pi), 0, None)              # 06:00-18:00
cahaya      = matahari * awan_hari[hari]
lux = np.clip(30000*cahaya*(1+rng.normal(0, 0.1, N)), 0, None)

# --- suhu greenhouse: menuju suhu target, kipas mendinginkan ---
suhu = np.empty(N); kipas = np.zeros(N, dtype=int)
suhu[0] = suhu_luar[0]; fan = False
for t in range(1, N):
    target = suhu_luar[t] + 9*cahaya[t] - (9 if fan else 0)
    suhu[t] = suhu[t-1] + (target - suhu[t-1])/15 + rng.normal(0, 0.05)
    if suhu[t] > 36:    fan = True       # aturan yang sama dengan firmware
    elif suhu[t] <= 32: fan = False
    kipas[t] = fan

hum = np.clip(110 - 2*suhu + rng.normal(0, 2.5, N), 35, 95)

df = pd.DataFrame({"suhu": suhu.round(1), "hum": hum.round(1),
                   "lux": lux.round(0), "kipas": kipas})
df["tren5"]  = df.suhu - df.suhu.shift(5)       # perubahan suhu 5 menit terakhir
df["target"] = df.suhu.shift(-30)               # suhu 30 menit ke depan
df = df.dropna()
df.to_csv("data_sintetis.csv", index=False)

FITUR = ["suhu", "hum", "lux", "kipas", "tren5"]
potong = int(len(df) * 0.8)                     # split berurutan, BUKAN acak
tr, te = df.iloc[:potong], df.iloc[potong:]

model = RandomForestRegressor(n_estimators=100, min_samples_leaf=5,
                              n_jobs=-1, random_state=0)
model.fit(tr[FITUR], tr["target"])
pred = model.predict(te[FITUR])

print(f"MAE baseline (suhu sekarang) : {mean_absolute_error(te.target, te.suhu):.2f} C")
print(f"MAE model Random Forest      : {mean_absolute_error(te.target, pred):.2f} C")

nyata = te.target >= 34; tebak = pred >= 34
print(f"Kejadian >=34C: {nyata.sum()} | terdeteksi model: {(nyata & tebak).sum()}"
      f" | alarm palsu: {(~nyata & tebak).sum()}")
print(f"Terdeteksi baseline: {(nyata & (te.suhu >= 34)).sum()}")

joblib.dump({"model": model, "fitur": FITUR}, "model_suhu.pkl")