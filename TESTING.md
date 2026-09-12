# Validation and release checklist

## Results — 2026-09-12

**This repository is an experimental prototype. A successful fresh real installation is still unverified.**

- 11 automated tests pass using Python's standard library. They exercise real filesystem copying, menu generation, staged updates, rollback, failed-update restoration, interrupted-transaction recovery, lock contention, archive rejection, checksum mismatch, monitor sizing and preservation of customized menu entries.
- Wine/UMU execution and release downloads are simulated in those automated tests. The simulated newer version `1.55.7` is a fixture, not an assertion that an upstream release exists.
- A separate real installer attempt fetched and verified official HDT 1.55.6, cloned the original standalone Battle.net prefix with independent copy-on-write files, and invoked the matched winetricks through UMU using a disposable copy of the Steam runtime.
- Inside the agent sandbox, the .NET setup did not finish even though the process reported success. Registry inspection caught the missing .NET installation. The installer now verifies the .NET 4.8 Release registry value before marking a destination ready; the incomplete real test prefix was correctly rejected and the existing working installation passed that same check.
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
