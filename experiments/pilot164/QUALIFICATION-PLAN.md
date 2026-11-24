# Qualification plan for the non-compute classes of the mini's compare lanes (DRAFT of 2026-11-24, pre-registration, for mmdbbench#164 decision 3)

Status: DRAFT. Nothing in this file has run. It is written first, as #164 asks, so that the compare lanes get their qualification for the disk and the cache and latency classes through a plan and not by relabelling a job's class. It is registered when I post it with its lock block (section 7). The pilot of `PREREG.md` does not wait for it: its legs L1 to L4 and H are designed to the record as it is. The real-cell legs L5 and L6 can use more than compare1 only after this plan has passed.

Numbers in this file are written by `build_prereg.py`: the hours come from `humemops worker lanes qualify plan --text` run offline (section 4), and the figures of the earlier plans are checked there against `docs/qualification.md` of humem-ops.

## 1. What the record says today and why a plan is needed

The mini's record `mini-2026-11-19-1b62305a8e21` (plan `1b62305a8e21`, read 2026-11-19) has a `classes` block with `compute` only: three lanes proven, QUALIFIED. A job of any other class, and a job with no class, is admitted on compare1 only, and the Tower refuses it for compare2 and compare3 (`not-qualified`). The pilot needs, for its real cells, `io_heavy` for the strict cells (every commit waits for the disk) and a class for the cache and latency cells. Neither can be given to compare2 or compare3 by naming the job `compute`. A class gets lanes only from a plan whose rows say so: `qualify classes PLAN ROWS --class NAME` builds its entry (`lanes_proven`, `bulk_loads_ok`, `verdict`) and I put the record in place.

## 2. What is already measured (do not repeat)

- Memory bandwidth (`bw_heavy`, probe `membw`): plan `8feabb577dd3` (all four probes) stopped at round 3 with NOT QUALIFIED for three lanes, and the compatibility matrix `002ff543713b` reads the `membw` victim at 0.663 beside one memory neighbour and 0.460 beside two (both NOT QUALIFIED). Another run of the same probe cannot change that physics, so there is no plan for `bw_heavy`: it stays at one lane (compare1) and a `membw` stream never runs on compare2 or compare3. I plan it only if I choose to repeat it (section 5).
- Disk (`io_heavy`, probe `io`): plan `8feabb577dd3` could not read it (the A/A control was not clean on two lanes), and the matrix reads the `io` victim at 0.911 beside two memory neighbours (NOT QUALIFIED) and 0.956 beside a bulk disk job (INCONCLUSIVE). The probe has never run on two or three compare lanes beside the `io` probe itself, and that is the case that decides how many strict cells may run at once.

## 3. Plan QP-IO (required)

- **Question.** How many compare lanes may run a disk-bound job at once and still give the same figure as one lane alone (the same cases and the same pass rule as the plans of 2026-11-19)?
- **Tool.** `humemops worker lanes qualify plan --config ~/.config/humemops/worker.toml --probes io --seed 1 --rounds 10 --ladder 3,5,10 --out qp-io-plan.json` on the mini (read only), then `qualify run` in a window, rung by rung (`--rounds 1-3`, `4-5`, `6-10`), and `qualify analyze` after each rung. Seed 1, as the earlier plans. The plan has the cases alone and A/A for each lane, every pair of compare lanes, all three, and the three bulk loads, 15 runs per round. The `io` probe writes, syncs, drops the cache and reads back a 64 MiB file, again and again for 90 s, below the run directory on the data disk.
- **Thresholds (the plan carries them, unchanged from the plans of 2026-11-19).** Band 0.03, margin 0.03, interval inside 0.06, a PASS needs 10 rounds with at most 10 percent of the rounds invalid, big ratios outside 0.90 and 1.10 are listed whatever the verdict, an A/A control that is not clean makes the cell UNDECIDED. Rungs at 3, 5 and 10 rounds (3 rounds see an effect of 2 times, 5 rounds 1.3 times to 2 times, 10 rounds anything smaller).
- **What decides.** The class `io_heavy` gets `lanes_proven` N, the greatest N for which every cell of its probe passes in every case of up to N compare lanes (`pair-*` for 2, `all-compare` for 3). QUALIFIED at 3 means a strict cell may sit on any lane. At 2, on compare1 and compare2. At 1 it stays on compare1 and the real-cell leg L5 stays as it is. The bulk cases tell whether a bulk job may run beside; they change nothing for the pilot.
- **Thermal gate.** The plan's own: the package at most 70 C before every run (poll 10 s, cap 900 s, then the run goes on with `gate_ok` false and is invalid). Turbo off and governor `powersave` as the profile says, no other job on the mini during a rung, no agent work on any core, a deploy or a gate only between rungs.
- **Throttle evidence.** `qualify analyze` reads ratios, not throttle (humem-ops#480). After every rung I run `qual_throttle_check.py` on `rows.jsonl`: every run with a throttle time above 1 percent of its probe time, or with none read, is listed. A case with any such run is not read as QUALIFIED even if the analyzer says so, and the owner's decision follows the list. If more than 10 percent of the runs of a rung are throttled, the plan stops there and the cause goes to humem-ops#480.
- **How long.** the offline plan prints, as an assumption, 1.6 hours at 3 rounds, 2.7 at 5 and 5.4 at 10 (15 runs per round). The window needs the mini idle and my word (`docs/qualification.md`, "Checklist for the owner's window"); the pilot legs do not run in it.
- **Stop.** A clear NOT QUALIFIED at rung 1 or 2 is a result and ends the window. INCONCLUSIVE after 10 rounds is the result of this plan; a longer plan is a new pilot. The kill switch is the Worker's `STOP` file. A rule changed after a run is a new plan.
- **After.** If QUALIFIED for N lanes: `qualify classes qp-io-plan.json rows.jsonl --class io_heavy --out io-class.json`, `qualify host-record` with `--classes-plan` (the compute entry of 2026-11-19 stays), `qualify verify-record`, and I put the record in place. Then `plan.py build --leg L5 --lanes-proven io_heavy=N` makes the order of the strict-cell leg for N lanes, as an amendment to `PREREG.md` before its lock.

## 4. Plan QP-LAT (cache and latency, blocked)

The record's vocabulary has four cell classes: `compute`, `bw_heavy`, `io_heavy`, `paired_ab`. A cell that is neither bandwidth nor disk but point reads and traversals on a working set in RAM has no class and no probe. Two things are missing in humem-ops, and I have not filed them:

- A probe `lat` (a pointer chase over a working set larger than the L2 cache, with a fixed number of dependent loads, time boxed like the others) in `probes.py` and the lane kit's `PROBES` table.
- A class `latency` (name to be chosen by the owner) in `CELL_CLASSES`, in the record's vocabulary, and in the Tower's `cell_class` enum and `queue_add` schema.

When both exist the plan has the same shape as QP-IO with `--probes lat` and the same rules. Until then the cache and latency cells run unclassed on compare1 only, and no leg claims more for them.

## 5. Plan QP-MEMBW (not planned)

For the record, the plan that I would run to repeat the bandwidth class is the same as QP-IO with `--probes membw`: the offline plan prints, as an assumption, 1.2 hours at 3 rounds, 2.1 at 5 and 4.2 at 10 (15 runs per round). Its expected result is NOT QUALIFIED for two or three lanes. I run it only if humem-ops changes the layout or the memory path, and a new `plan_sha` and a new window are needed then.

## 6. What this plan may not claim

- That a strict cell is disturbed or not by the `io` probe: the probe measures bandwidth and sync of a 64 MiB file, and the strict cells of the pilot write a fraction of a megabyte per second and wait for a sync on every commit. The probe is the class's calibration, because admission reads classes; the pilot's leg L5 measures the real cell.
- Anything about the new host in February 2027: it repeats the plans there.

## 7. Lock block (filled in on the mini before the first run, not before)

| Item | Value |
|---|---|
| Date and time of the lock | to be filled |
| `plan_sha` and `layout_sha` of QP-IO (made on the mini with the live profile) | to be filled |
| sha256 of `qp-io-plan.json` | to be filled |
| Seed | 1 |
| sha256 of `qual_throttle_check.py` | `e56b1e8829a9f1f30e99372b3f5e79501e5c87d7e61e70e15b07f16526ae5d7a` |
| humem-ops commit the tooling comes from | `34cff29febe73628610cd6ad939d37c6c26487a7` |

The hours in section 3 were made offline, from the example profile of the mini in `docs/lanes.md` (`mini-profile-from-lanes-md.toml`, sha256 in `PREREG.md` section 12) and the topology fixture `tests/fixtures/lane/topology-mini` of humem-ops, with the same command. The plan of the mini has the live layout, so its `plan_sha` differs from the one of the offline copy.
