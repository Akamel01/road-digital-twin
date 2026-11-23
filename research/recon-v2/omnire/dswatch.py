"""Watch a drivestudio train log: emit every EVERY steps (psnr, gaussians, it/s), WARN when psnr drops vs the
previous check, STALL when no step line for STALL_S while the unit is active, errors, and END."""
import re
import subprocess
import sys
import time

log, unit, every, stall_s = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
pat = re.compile(r"\[\s*(\d+)/(\d+)\].*?elapsed: (\S+).*?train_metrics/psnr: \S+ \((\S+)\).*?gaussian_num_Background: (\S+)")
bad = re.compile(r"Traceback|Error|out of memory|Killed", re.IGNORECASE)
pos, last_t, prev_psnr, nxt = 0, time.time(), None, int(sys.argv[5]) if len(sys.argv) > 5 else every
def active():
    return subprocess.run(["systemctl", "--user", "is-active", "-q", unit], check=False).returncode == 0
while True:
    with open(log, errors="replace") as f:
        f.seek(pos); chunk = f.read(); pos = f.tell()
    for line in chunk.splitlines():
        if bad.search(line) and "Warning" not in line and "vis_error" not in line:
            print("ERROR", line[:300], flush=True)
        m = pat.search(line)
        if m:
            last_t = time.time(); step = int(m[1])
            if step >= nxt:
                psnr = float(m[4])
                warn = " WARN psnr falling" if prev_psnr is not None and psnr < prev_psnr - 0.3 else ""
                print(f"step {step}/{m[2]} elapsed {m[3]} running-mean psnr {psnr:.2f} bg_gaussians {float(m[5]):.0f}{warn}", flush=True)
                prev_psnr, nxt = psnr, nxt + every
    if not active():
        print("END unit inactive; last:", chunk.strip().splitlines()[-1][:200] if chunk.strip() else "", flush=True); break
    if time.time() - last_t > stall_s:
        print(f"STALL no step line for {stall_s:.0f}s", flush=True); last_t = time.time()
    time.sleep(10)
