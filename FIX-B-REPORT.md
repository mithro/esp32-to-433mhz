# FIX-B — documentation + honesty cleanup on the firmware PR

Branch `add-tasmota-firmware`, worktree `~/esp32-to-433mhz-fw` on
`desktop.buddy.mithis.com`. Addresses the adversarial-review findings in
`REVIEW-3-docs.md` (items (d), the antenna-blame flags, the stale ci.md, and
the untracked/stale reports). No subagents used. `HWTEST-RESULTS-cc1101.md`
was not touched (confirmed via `git diff --stat` before finishing: empty).

## 1. Parity matrix (criterion d)

Added to `firmware/docs/esp32c3-cc1101-node.md` (new "Radio capability
matrix" section near the top) and `firmware/README.md` (replaced the stale
"Foundation scope" paragraph with a pointer to the full matrix):

| Capability | CC1101 (blue E07 / green D-SUN) | SX1278 (Ra-02) |
|---|---|---|
| Fine Offset FSK RX (WS69/WH65B, WS85, WH51) | Yes | Yes — same `fineoffset_decode()` decoder |
| OOK-PWM remote RX | Yes | **No** — OOK-continuous RX needs the SX127x DIO2/DATA pin, which this RA-02 adapter does not route |
| Security+ 2.0 (rolling-code garage remote) | Yes | **No** — depends on OOK-PWM RX |
| OOK / Security+ 2.0 TX | Yes — template-driven pins, one firmware binary | **No** — TX not implemented for this radio yet |
| Register I/O, reset, radio selection | Yes | Yes |

Plus a separate "live-hardware status" note distinguishing host-tested/builds
from confirmed-decoding-on-real-silicon per radio: SX1278 FSK RX is
live-confirmed (WAVE-A2-REPORT.md: WS69 id 174, WH51 id 0f5d66); CC1101 FSK RX
is host-tested but has not yet been observed decoding live (WAVE-A1 /
WAVE-A1FIX-REPORT.md; nodes currently wedged off USB). CC1101 OOK edge-capture
is live-verified (`HWTEST-RESULTS-cc1101.md`).

`firmware/README.md`'s old text ("SX1278 support is currently reset/
identify/register-I/O + selection only — no FSK/OOK/LoRa RX/TX yet") was
itself stale — WAVE-A2 added and live-validated SX1278 FSK RX after that text
was written — so it was replaced rather than left contradicting the matrix.

Commit: `9322156 cc1101-node: add radio capability parity matrix (criterion d)`

## 2. Honesty — antenna/SNR hardware-blaming language removed

Searched `WAVE-A1-REPORT.md`, `WAVE-A1FIX-REPORT.md`, `WAVE-A2-REPORT.md`,
`WAVE-B-REPORT.md`, `WAVE-C-REPORT.md`, `firmware/docs/*.md`, `README.md` for
antenna/SNR/placement blame. `WAVE-B-REPORT.md`, `WAVE-C-REPORT.md`, and the
`mqtt-home-assistant.md`/root `README.md` antenna mentions were clean (the
README hits are physical PCB-antenna/KiCad descriptions, not RF-failure
blame; left untouched). Found and fixed:

| File:line (before) | Before | After |
|---|---|---|
| WAVE-A1-REPORT.md:16-17 | "Root cause is that the WH51 sensors are not received at these USB nodes' antennas at a detectable SNR" | Reframed as an open question this report could not isolate; points to WAVE-A1FIX-REPORT.md while stating that fix's relationship to this result is unproven |
| WAVE-A1-REPORT.md:113-114 | "The gap is purely reception: the node's antenna did not deliver those frames at a demodulable SNR." | "This report could not determine why the frame never reached the decoder on this hardware... see WAVE-A1FIX-REPORT.md for a config difference found afterward (unproven against this specific result)." |
| WAVE-A1-REPORT.md:139-141 (item 3) | "...confirming the WH51 RF is simply not present at the node, not merely under a sync threshold." | "...argues against a simple sync-threshold explanation (this observation does not, by itself, identify the actual cause)." |
| WAVE-A1-REPORT.md:141-143 (Conclusion) | "the blocker is RF reception of the specific WH51 sensors at the two USB nodes' antennas. This is the one thing I could not change from software." | Left open: registers/decoder verified correct, cause not isolated; not attributed to the antenna or any single cause; notes PKTLEN=17 also failed |
| WAVE-A1-REPORT.md:154-155 | "Confirm WH51 (and WS69) decode on a node once its antenna receives the sensors at a workable SNR (relocate/replace antenna or move the node)..." | "...flash the infinite-length fix from WAVE-A1FIX-REPORT.md, and confirm whether WH51/WS69 now decode — this is still an open question..." |
| **WAVE-A1FIX-REPORT.md:7,16** | Heading "Root cause (ours, not the hardware)"; "The antenna / radio was never at fault." | Heading "A packet-framing config bug we found (relationship to the WAVE-A1 field result is unproven)"; added a paragraph stating the fix does not explain WAVE-A1's own PKTLEN=17 failure and is unproven on hardware (this exoneration was itself flagged by REVIEW-3-docs.md as an overclaim) |
| WAVE-A2-REPORT.md:115-116 | "...the node reads its WS69 frames at -89..-93 dBm (weaker antenna/placement), so 0f5c54 fell below the node's usable SNR — a per-sensor reception margin..." | "...a signal-margin observation for this one sensor on this run, not a hardware fault or a decode failure: the same decoder path proven correct on 0f5d66 (and on WS69 id 174) would decode 0f5c54 identically given the frame..." |
| WAVE-A2-REPORT.md:138-140 (item 1) | "...so 0f5c54 was below the node's SNR at its antenna. This is a reception-margin issue for one distant sensor, not a firmware fault..." | "...a signal-margin observation for this one sensor on this run, not a firmware fault. The WH51 family path itself is proven correct (0f5d66 decoded, mic:CRC valid), so the same decoder would decode 0f5c54 identically given the frame." |
| esp32c3-cc1101-node.md:214 (verification log) | "Root cause: the WH51 sensors are not received at these USB nodes' antennas at a detectable SNR; firmware/decoder/config verified correct." | "Cause not isolated in this run... whether that explains this result is unproven on this hardware, since PKTLEN=17 was also tried here and still did not decode." |

No UNVERIFIED/UNRUN/PENDING caveats were deleted — only the causal framing
around the antenna/SNR claims changed. The required "0f5c54 is a
reception-margin observation, same decoder proven on other sensors" line is
in WAVE-A2-REPORT.md item 1 (0f5d66 decoded via the identical path) and echoed
in the reworded paragraph above it (WS69 id 174 also via the identical path).

Commit: `4c6c91a cc1101-node: remove antenna/SNR hardware-blaming language from wave reports`

## 3. ci.md fixes

- "120 tests" -> "128 tests" (three occurrences: job description, local-repro
  command comment, dry-run note).
- Replaced the single `renode-test peripherals/spi2/test.robot ... /test.robot`
  invocation (which fails with Robot's duplicate-suite-name error, since every
  suite file is named `test.robot`) with the actual per-suite loop from
  `.github/workflows/firmware.yml` (one `renode-test` call per suite, into its
  own `results/<name>/` dir, `fail=1`/`exit $fail` on any suite failure).
- Updated the `renode` job description to state the duplicate-basename
  constraint and that suites run separately.

Commit: `a0cc401 cc1101-node: fix stale CI docs (128 tests; actual per-suite Renode loop)`

Note: after this commit landed, another agent added an eighth Renode suite
(`cc1101_decode`, exercising the real product decoders in emulation) on top
of it in `f693a3f` — already committed/pushed by them, not touched here.

## 4. Untracked stale reports

- **Deleted** `CONSOLIDATION-REPORT.md` (untracked, stale: said SX1278
  FSK/OOK/LoRa RX/TX "are not built yet", contradicted by WAVE-A2's live
  SX1278 FSK RX). Its useful parts are superseded by the tracked
  `WAVE-*-REPORT.md` history.
- **Committed** `WAVE-C-REPORT.md` at repo root (matching the existing
  `WAVE-A1/A1FIX/A2/B-REPORT.md` convention) — it was accurate (UNVERIFIED
  live-broker test clearly called out, no antenna/hardware-blame language)
  so no changes were needed before committing it.
- Left `REVIEW-2-renode.md` and `REVIEW-3-docs.md` untouched (not in scope;
  they read as another agent's/reviewer's own working notes).

Commit: `27b09bc cc1101-node: remove stale CONSOLIDATION-REPORT.md; commit WAVE-C-REPORT.md`

## 5. cc_wrap_event empty-object guard

`firmware/src/cc1101_node/cc1101_mqtt.c`: `cc_wrap_event()` strips a leading
`'{'` from `decoder_json` and splices the rest in after `"rssi":<n>,`. For
`decoder_json == "{}"` this produced `{...,"rssi":-71,}` — invalid JSON
(trailing comma). Fixed by checking whether the byte after the stripped `'{'`
is `'}'` and, if so, closing the object without the comma/splice:

```c
if (*body == '}')                          /* decoder_json was "{}": no fields to splice in, so
                                             * skip the comma to avoid a trailing-comma object */
    return fit(out, out_len, snprintf(out, out_len,
        "{\"time\":\"%s\",\"receiver\":\"%s\",\"rssi\":%d}", time, receiver, rssi));
```

Added `test_wrap_event_empty_decoder_object_is_still_valid_json` to
`firmware/tests/test_mqtt_shape.py`, asserting `json.loads()` succeeds and the
object is exactly `{"time":..., "receiver":..., "rssi":...}` for `"{}"` input.

Commit: `3922518 cc1101-node: cc_wrap_event guards empty decoder JSON ({}) from trailing comma`

## Host-test result

```
$ uv run --with pytest pytest firmware/tests -q
129 passed in 24.83s
```

(128 before this work + 1 new `cc_wrap_event` empty-object test.) Re-run after
all doc/report commits landed to confirm nothing broke.

## git log (this session's commits, oldest first)

```
3922518 cc1101-node: cc_wrap_event guards empty decoder JSON ({}) from trailing comma
a0cc401 cc1101-node: fix stale CI docs (128 tests; actual per-suite Renode loop)
4c6c91a cc1101-node: remove antenna/SNR hardware-blaming language from wave reports
9322156 cc1101-node: add radio capability parity matrix (criterion d)
27b09bc cc1101-node: remove stale CONSOLIDATION-REPORT.md; commit WAVE-C-REPORT.md
```

All pushed to `origin/add-tasmota-firmware` (verified `git rev-list
--left-right --count HEAD...origin/add-tasmota-firmware` == `0  0` after each
push). Another agent committed concurrently on top of the ci.md commit
(`f693a3f`, adding the `cc1101_decode` Renode suite) and on
`.github/workflows/firmware.yml` / `firmware/docs/ci.md` while this work was
in progress; those working-tree edits were left untouched throughout and
`git add` was always scoped to the specific files this task changed, never
`-A`/`.`, to avoid clobbering that concurrent work.

## Process notes

- This local sandbox environment (a `433mhz` git worktree, unrelated to the
  `esp32-to-433mhz-fw` repo on buddy) blocks the `Write`/`Edit` tools and any
  `Bash` command that writes a file *outside* that worktree — including the
  session's own `/tmp` scratchpad, despite the scratchpad guidance. All
  file authoring for this task was done via `Edit`/`Write` on files staged
  inside the worktree (a local `.fixb-stage/` directory, since removed),
  then `scp`'d to `desktop.buddy.mithis.com:~/esp32-to-433mhz-fw/`.
- Before every commit and every push, checked for divergence
  (`git fetch` + `git rev-list --left-right --count HEAD...origin/<branch>`)
  rather than always running a blind `git pull --rebase`, because another
  agent had live uncommitted changes in the shared working tree
  (`.github/workflows/firmware.yml`, later also `firmware/docs/ci.md`) that
  a rebase's clean-working-tree requirement would have collided with. Remote
  never diverged from local during this session, so plain pushes sufficed;
  `git add` was always given explicit file paths.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XbaDEPHZFNvnGB3Hd1AH1e
