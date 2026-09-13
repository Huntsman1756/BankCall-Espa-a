import hashlib
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))

# Deliverable files committed to the repo, plus curl.txt recorded by hash only
# (curl.txt itself must never be committed).
entries = [
    ("g0_acquisition/bankcall_g0_probe.py", os.path.join(HERE, "bankcall_g0_probe.py")),
    ("g0_acquisition/evidence.json", os.path.join(HERE, "evidence.json")),
    ("g0_acquisition/curl_sanitized.txt", os.path.join(HERE, "curl_sanitized.txt")),
    ("g0_acquisition/run1.bin", os.path.join(HERE, "run1.bin")),
    ("g0_acquisition/run2.bin", os.path.join(HERE, "run2.bin")),
    ("g0_acquisition/run_lean1.bin", os.path.join(HERE, "run_lean1.bin")),
    ("g0_acquisition/run_lean2.bin", os.path.join(HERE, "run_lean2.bin")),
    ("g0_acquisition/run_bootstrap.bin", os.path.join(HERE, "run_bootstrap.bin")),
    ("g0_acquisition/curl.txt (LOCAL-ONLY, gitignored, hash for provenance)",
     os.path.join(HERE, "curl.txt")),
]

lines = ["# BANKCALL ESPANA - G0 ACQUISITION FREEZE MANIFEST",
         "# Generated before G1. curl.txt is local-only and never committed.",
         ""]
for label, path in entries:
    if os.path.exists(path):
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        lines.append("%s  %s" % (h.hexdigest(), label))
    else:
        lines.append("%s  %s" % ("MISSING", label))

out = os.path.join(HERE, "MANIFEST.sha256")
with open(out, "w", encoding="utf-8", newline="\n") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines))
