#!/usr/bin/env python3
import argparse, subprocess, tempfile, shutil, re
from pathlib import Path

ASSERT_RE = re.compile(r'^\s*assert\s', re.MULTILINE)

def verify(path: Path) -> bool:
    # Adjust flags if you need: --compile:0 to speed up, etc.
    proc = subprocess.run(["dafny", "verify", str(path)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return proc.returncode == 0

def main():
    ap = argparse.ArgumentParser(description="Remove unnecessary Dafny asserts by re-verification.")
    ap.add_argument("file", help="Path to .dfy")
    ap.add_argument("--write-in-place", action="store_true", help="Overwrite the input file if changes help")
    args = ap.parse_args()

    src = Path(args.file).resolve()
    text = src.read_text()

    # collect assert spans (start,end)
    spans = []
    for m in ASSERT_RE.finditer(text):
        i = m.start()
        # naive: kill this line only
        j = text.find('\n', i)
        if j == -1: j = len(text)
        spans.append((i, j))

    if not spans:
        print("No asserts found."); return

    print(f"Found {len(spans)} asserts. Testing necessity...")
    cur = text
    tmpdir = Path(tempfile.mkdtemp(prefix="dafny-clean-"))
    tmpfile = tmpdir / src.name
    tmpfile.write_text(cur)
    baseline_ok = verify(tmpfile)
    if not baseline_ok:
        print("Baseline does not verify; aborting (run after a successful solve).")
        shutil.rmtree(tmpdir); return

    removed = 0
    # process from bottom to top to keep spans stable
    for i,(s,e) in enumerate(sorted(spans, key=lambda x:x[0], reverse=True), 1):
        candidate = cur[:s] + "// REMOVED: " + cur[s:e].replace("\n", "\n// ") + cur[e:]
        tmpfile.write_text(candidate)
        ok = verify(tmpfile)
        print(f"[{i}/{len(spans)}] {'KEEP-REMOVED' if ok else 'RESTORE'} at {s}-{e}")
        if ok:
            cur = candidate
            removed += 1
        else:
            tmpfile.write_text(cur)  # restore

    if args.write_in_place:
        src.write_text(cur)
        print(f"Done. Removed {removed} asserts. Wrote in place: {src}")
    else:
        out = src.with_suffix(".clean.dfy")
        out.write_text(cur)
        print(f"Done. Removed {removed} asserts. Wrote: {out}")

    shutil.rmtree(tmpdir)

if __name__ == "__main__":
    main()


''''
example run: 
(venv) rheakarty@MacBookPro vfp % cat > test_clean_assert.dfy <<'DFY'
// A tiny file with asserts that aren't needed for verification.
// The cleaner should remove them and the program should still verify.

method Inc(x: int) returns (y: int)
  ensures y > x
{
  y := x + 1;
  assert y == x + 1;          // <-- unnecessary
  assert x + 1 > x;           // <-- unnecessary (obvious arithmetic)
}

method Max2(a: int, b: int) returns (m: int)
  ensures m >= a && m >= b
  ensures m == a || m == b
{
  if a >= b {
    m := a;
    assert m == a;            // <-- unnecessary (just assigned)
  } else {
    m := b;
    assert m == b;            // <-- unnecessary
  }
}
DFY

(venv) rheakarty@MacBookPro vfp % dafny verify test_clean_assert.dfy


Dafny program verifier finished with 2 verified, 0 errors
(venv) rheakarty@MacBookPro vfp % ./clean_asserts.py test_clean_assert.dfy
# → writes test_clean_assert.clean.dfy
dafny verify test_clean_assert.clean.dfy

Found 4 asserts. Testing necessity...
[1/4] KEEP-REMOVED at 542-590
[2/4] KEEP-REMOVED at 454-518
[3/4] KEEP-REMOVED at 254-323
[4/4] KEEP-REMOVED at 205-253
Done. Removed 4 asserts. Wrote: /Users/rheakarty/Desktop/dafny-sketcher/vfp/test_clean_assert.clean.dfy
+:465: maximum nested function level reached; increase FUNCNEST?
(venv) rheakarty@MacBookPro vfp % 
'''