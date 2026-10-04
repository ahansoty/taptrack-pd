import logging, json, time, tempfile, pathlib
logging.basicConfig(level=logging.INFO)
from taptrack.storage import Storage
from taptrack.bridge import Bridge
from taptrack.device import FreeWiliDevice
st = Storage(url="", sqlite_path=pathlib.Path(tempfile.mkdtemp())/"s.db")
ev=[]
dev = FreeWiliDevice()
assert dev.open(), "no device"
b = Bridge(st, ev.append, device=dev, duration_scale=0.5, auto_advance=True)
b._attach(dev)
t0=time.perf_counter(); dev.pump(3)
from taptrack.device import accel_arrays
rows=[r for r in dev.accel if r[0]>=t0]; t,x=accel_arrays(rows)
print("idle accel samples", len(rows), "rate", round((len(t)-1)/(t[-1]-t[0]),1), "g-mag", round(float((x**2).sum(1).mean()**.5),3))
row = b.run_check()
print(json.dumps({k: row["results"][k] for k in row["results"]}, default=float, indent=0)[:1500])
print("score", row["score"], row["tests"])
dev.close()
