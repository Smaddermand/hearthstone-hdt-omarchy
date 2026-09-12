# Hearthstone Deck Tracker on Omarchy

Experimental installer and launcher for **the Windows portable Hearthstone Deck Tracker (HDT)** on Omarchy, using UMU and GE-Proton. Start HDT from the applications menu, then use **Start Hearthstone** inside HDT.

This project supplies the Linux integration only. It is independent of HearthSim, HSReplay.net, Blizzard and Omarchy. No game, tracker binaries, Wine environments, account credentials or Microsoft components are distributed in this repository.

## Status

Experimental release **v0.1.0-alpha.1**, intended for early testing on Omarchy. This is not an AUR package. Occasional overlays appearing behind Hearthstone remain a known limitation. A monitor-sized Wine virtual desktop helped on the original machine; it does not guarantee correct stacking after every match.

The original manually configured setup used HDT **1.55.6**, **GE-Proton11-6-x86_64**, **UMU 1.4.4**, and Microsoft **.NET Framework 4.8**. Game tracking and replay uploads worked there. Automated tests use simulated Windows-runtime calls; see [TESTING.md](TESTING.md) for the distinct limits of each test.

## Requirements

- Omarchy / Arch Linux x86_64 with its graphics dependencies installed.
- Python 3.11+, GNU coreutils (`cp`), and `umu-launcher`.
- An existing, working **standalone Omarchy Battle.net installation**, with Hearthstone installed in its default Windows location. The default source is `~/Games/battlenet`.
- The tested GE-Proton directory, or an explicitly supplied compatible runner containing `proton` and `protonfixes/winetricks`. The installer does not download or upgrade Proton automatically.
- Network access for official HDT and .NET downloads. Microsoft setup may show prompts.
- Space for a second Wine environment, including the game. On filesystems supporting reflinks the initial copy shares storage until files change; otherwise it is a full copy.

Use Omarchy's existing gaming installation to install Battle.net if needed:

```sh
omarchy install gaming battlenet
```

Install Hearthstone and verify it launches before continuing. Other layouts (Lutris, Bottles, custom Windows game paths or Wine usernames) are outside this first version's supported scope.

## Install

Close Battle.net, Hearthstone, HDT and their background Wine processes. Keep the source closed while copying. Download the [experimental release](https://github.com/Smaddermand/hearthstone-hdt-omarchy/releases/tag/v0.1.0-alpha.1), or clone its tag:

```sh
git clone --branch v0.1.0-alpha.1 https://github.com/Smaddermand/hearthstone-hdt-omarchy.git
cd hearthstone-hdt-omarchy
python3 hdt.py install
```

This creates `~/Games/hearthstone-hdt-omarchy` and a **Hearthstone Deck Tracker (Omarchy)** application-menu entry. It refuses to overwrite an existing destination.

To select another source, destination or installed runner:

```sh
python3 hdt.py --prefix "$HOME/Games/my-hdt" install \
  --source "$HOME/Games/battlenet" \
  --proton "$HOME/.local/share/Steam/compatibilitytools.d/GE-Proton11-6-x86_64"
```

The installer copies the existing prefix, replaces Windows-file symlinks with writable local copies so native .NET can replace DLLs without modifying the shared Proton installation, uses UMU's matched winetricks to install `dotnet48`, restores Windows 10 compatibility, installs the verified official portable HDT release, and configures the game path. It copies a small management script into the destination so the menu continues to work if the source repository moves.

`install --no-menu` skips desktop integration. `install --version 1.55.6` chooses a specific official stable release. The default install version is pinned to the tested release; the default update target is the latest upstream stable release.

Installation failures leave the destination and `install.log` for inspection. Retry dependency setup in that incomplete copy with:

```sh
python3 hdt.py --prefix "$HOME/Games/hearthstone-hdt-omarchy" install --resume
```

Use the same version and Proton options as the original installation. Resume preserves the copied game and appends to the log; it does not recopy the source. It is refused for completed installations and unmanaged directories. If the original copy operation itself was interrupted, choose a new destination instead. No environment is automatically deleted.

## Launch

Use the menu, or:

```sh
python3 hdt.py launch
```

Start Hearthstone using HDT's button. The launcher opens only HDT. Monitor dimensions and scale come from Hyprland. Override with:

```sh
HDT_DESKTOP_SIZE=2560x1440 python3 hdt.py launch
```

Without monitor information, the fallback is 1920×1080. `launch --no-virtual-desktop` is available for diagnosis. HDT can still have overlay issues; this project currently has no topmost helper or Hyprland rule changes.

## Update and rollback

Close all applications using this environment first:

```sh
python3 hdt.py update
python3 hdt.py backups
python3 hdt.py rollback BACKUP_ID
```

Replace `BACKUP_ID` with an ID printed by `backups`. Supply the same global `--prefix` used during installation for every command when using a custom destination.

Updates download the official stable portable ZIP over HTTPS, require its GitHub asset SHA-256 digest, reject unsafe archive paths, and stage replacement application files. The old application and tracker data are backed up before replacement. Proton, .NET and the game stay at their existing versions. Settings, decks and history remain in the prefix's AppData directory.

Rollback restores **both application and tracker data** to the selected snapshot, so records created after that snapshot disappear from the active profile. The pre-rollback state is itself backed up. Backups are retained until you remove them; they can contain account credentials and should remain private.

Ordinary update errors trigger restoration. A killed process or power loss leaves a transaction marker that prevents launch/update until:

```sh
python3 hdt.py recover
```

Recovery restores the pre-transaction snapshot. Backups are local recovery aids, not protection from disk failure. Installing an older tracker also cannot guarantee compatibility with a newly updated Hearthstone.

Portable HDT checks for new versions but does not apply the Squirrel installer build's automatic updates. Battle.net updates Hearthstone normally within this environment; a new game patch may require an upstream HDT fix.

## Status, menu and removal

```sh
python3 hdt.py status
python3 hdt.py menu
python3 hdt.py uninstall
```

`menu` refreshes the installed script from the checked-out repository and recreates its menu entry. Run it after updating this repository. `uninstall` removes the script/menu integration and **retains the entire game environment, tracker data and backups**. Modified menu entries are left alone. There is deliberately no purge command.

Logs are `install.log`, `launcher.log` and `launcher.previous.log` in the destination. HDT logs are under `drive_c/users/steamuser/AppData/Roaming/HearthstoneDeckTracker/Logs`. Inspect/redact account information and local paths before attaching logs to public issues.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile hdt.py
```

Only the Python standard library is required. See [TESTING.md](TESTING.md) for manual release checks. AUR packaging is a possible future step.

## License and upstream projects

The original integration code in this repository is licensed under MIT; see [LICENSE](LICENSE). Third-party programs remain subject to their own licenses and terms. Downloading them does not grant redistribution rights.

- [Hearthstone Deck Tracker releases](https://github.com/HearthSim/Hearthstone-Deck-Tracker/releases)
- [HDT updater implementation for the tested version](https://github.com/HearthSim/Hearthstone-Deck-Tracker/blob/v1.55.6/Hearthstone%20Deck%20Tracker/Utility/Updating/Updater.Squirrel.cs)
- [UMU launcher](https://github.com/Open-Wine-Components/umu-launcher)
- [GE-Proton](https://github.com/GloriousEggroll/proton-ge-custom)
- [Winetricks](https://github.com/Winetricks/winetricks)
- [Omarchy](https://github.com/basecamp/omarchy)
