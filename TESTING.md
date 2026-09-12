# Validation and release checklist

## Results — 2026-09-12

**This repository is an experimental prototype. Native .NET setup and completing installation via resume have been verified in a clean test copy. The user has confirmed gameplay through the generated installation; overlay issues remain. See the final rehearsal results below.**

- 16 automated tests pass using Python's standard library. They exercise real filesystem copying, menu generation, staged updates, rollback, failed-update restoration, interrupted-transaction recovery, lock contention, protected native processes versus active Wine prefixes, archive rejection, checksum mismatch, monitor sizing and preservation of customized menu entries.
- Wine/UMU execution and release downloads are simulated in those automated tests. The simulated newer version `1.55.7` is a fixture, not an assertion that an upstream release exists.
- A separate real installer attempt fetched and verified official HDT 1.55.6, cloned the original standalone Battle.net prefix with independent copy-on-write files, and invoked the matched winetricks through UMU using a disposable copy of the Steam runtime.
- The initial .NET setup did not finish even though the process reported success. The user reproduced this outside the sandbox; attributing it to the sandbox was incorrect. Registry inspection caught the missing .NET installation. The installer now verifies the .NET 4.8 Release registry value before marking a destination ready; the incomplete real test prefix was correctly rejected and the existing working installation passed that same check.
- The disposable installation, downloads and copied runtime were removed after inspection. The real attempt used `--no-menu` and a workspace destination. The existing personal setup and its menu were not changed.
- Earlier manual testing (2026-09-11) upgraded portable HDT 1.55.5 to 1.55.6 in another disposable copy. Saved decks and account information loaded, rollback launched the old version, and a repeated new-version launch exited cleanly. That used the same GE-Proton Wine engine directly with software rendering. It was not an end-to-end test of this new installer, UMU launcher or gameplay.

## Required before a public release

Run the following in a normal desktop terminal with Battle.net/Hearthstone closed. Use a NEW destination; do not point at a valuable existing prefix.

```sh
python3 hdt.py --prefix "$HOME/Games/hdt-release-test" install --version 1.55.5
python3 hdt.py --prefix "$HOME/Games/hdt-release-test" launch
```

1. Verify .NET setup completes and the application menu opens HDT.
2. Start Hearthstone from HDT. Check deck import, play multiple games and record overlay behavior through game transitions/minimize/restore.
3. Close all Wine clients in this test environment, then run `update --version 1.55.6` with the same global `--prefix`.
4. Verify saved settings, decks and account still work. Play another game.
5. Run `backups` and `rollback BACKUP_ID`; verify the selected snapshot restores. Rollback restores tracker data too, so use a test profile.
6. Run `uninstall`; verify the menu integration disappears and game/tracker data remains.
7. Verify another machine or clean user account can repeat installation without borrowing dependencies from the original troubleshooting session. Check all external prefix symlinks resolve on that machine.

Record Omarchy, Hyprland, UMU, Proton, HDT, game build, GPU, monitor dimensions and scale. Do not claim overlay stability until that sequence passes repeatedly. A game patch may require a newer HDT even when installation is correct.

## Scope limits

Only the default Omarchy standalone prefix layout and `steamuser` Wine profile are supported. Automatic detection of arbitrary Lutris/Bottles layouts, runtime downloading, dependency repair, AUR packaging and migration of the earlier personal launcher are not implemented. User plugins in HDT's application directory are backed up, but are not automatically carried into an updated release; reinstallation may be needed.

The local transaction journal supports restoration after interrupted file replacement. It is not a guarantee against filesystem corruption or disk failure. Keep separate backups of data you cannot replace.

## .NET failure fix — 2026-09-12

The user reproduced the failure in a normal desktop terminal. Detailed MSI tracing found error 5 (access denied) when replacing `diasymreader.dll` and then `dxva2.dll`: the cloned Windows files still referenced protected shared Proton files. The MSI cabinet extraction failed and .NET rolled back with 1603 (wrapper exit 67). This was not caused solely by the agent sandbox.

The installer now materializes Windows-file symlinks as writable local files before native .NET installation. A fresh copy of the original Battle.net environment then completed the winetricks .NET 4.0 prerequisite and installed .NET 4.8; the Release registry value was 528049. The original shared files are never made writable or overwritten by the preparation step.

The new `install --resume` path completed HDT installation in that test copy, preserving the game. Verified existing .NET is skipped: UMU can return nonzero when asked to install a verb already recorded as installed. Resume is restricted to the tool's incomplete installations and the original Proton/version choice. Logs append across retries.

Regression tests cover replacing shared-file links without modifying their targets, skipping an already verified .NET installation, and resuming without recopying or overwriting a completed installation. All 16 tests pass.

The subsequent UMU launch attempt returned without creating HDT logs in the agent environment, so HDT startup/gameplay on this freshly built prefix is still not validated. The disposable diagnostic copies and verbose logs were removed after testing. The user-created failed release-test prefix was retained for `install --resume`.

## Real updater, rollback and uninstall rehearsal — 2026-09-12

The user confirmed that the generated installation opens, tracks games and works in play. Overlay behavior remains buggy but manageable manually; it is an acknowledged limitation, not a resolved defect.

A disposable copy of that installation was prepared with verified official portable HDT 1.55.5 files and matching version metadata. The actual CLI `update --version 1.55.6` completed using the official download and published SHA-256 digest. Every installed application file matched the extracted 1.55.6 release, and the complete tracker data file manifest remained byte-identical.

The actual `rollback BACKUP_ID` restored all 1.55.5 application and tracker data files. A test-only data file created after upgrade was removed from the active profile and retained in the new pre-rollback backup, along with the 1.55.6 application. No transaction journal remained.

The actual `menu` and `uninstall` commands were exercised with XDG_DATA_HOME pointed inside the disposable workspace. The test menu was removed; the copied game executable and all tracker data were preserved. The source installation's application files, tracker data, registries, management metadata and real menu entry matched their pre-test SHA-256 fingerprints.

No HDT process or match was started during this rehearsal; it verifies actual release download, replacement, data preservation, rollback and removal rather than runtime behavior across a version change. All disposable copies, release downloads and private manifests were removed afterward.
