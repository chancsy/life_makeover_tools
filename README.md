![Life Makeover Tools](https://raw.githubusercontent.com/chancsy/life_makeover_tools/assets/lifemakeover.png)

# Life Makeover Tools

ADB-based automation tools for the mobile game *Life Makeover*.

## Tools

| Folder | Description | Docs |
|---|---|---|
| [vanna_quiz/](vanna_quiz/) | Vvanna Quiz — 8-question quiz mini-game | [CHANGELOG](vanna_quiz/CHANGELOG.md) · [MODULES](vanna_quiz/MODULES.md) |
| [fun_time_wonder_connect/](fun_time_wonder_connect/) | Wonder Connect — link matching card pairs mini-game | [CHANGELOG](fun_time_wonder_connect/CHANGELOG.md) · [MODULES](fun_time_wonder_connect/MODULES.md) |

## Shared Infrastructure

```
common/
├── __init__.py
├── config.json     — shared settings (scrcpy exe, bitrate) written by setup.py
└── lm_adb.py       — shared helpers:
                        get_adb()            connect to ADB device
                        get_scrcpy()         launch/attach scrcpy window capture
                        setup_scrcpy()       interactive prompt → writes common/config.json
                        read_common_config() read common/config.json
```

scrcpy settings are stored once in `common/config.json` and reused by all tools.
Running any plugin's `setup.py` will prompt for scrcpy config if not already set.

## Adding a New Plugin

1. Create `<plugin_name>/` with `main.py`, `setup.py`, `CHANGELOG.md`, `MODULES.md`
2. Add at the top of each script:
   ```python
   import sys, os
   sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
   from common.lm_adb import get_adb, get_scrcpy, setup_scrcpy, read_common_config
   ```
3. In `setup.py`, call `setup_scrcpy()` once (skipped automatically if already configured)
4. Run `setup.py` once per device to register screen regions → `<plugin>/config.json`
5. Add an entry to this README

## Dependencies

### lib-utils

The tools depend on [chancsy/lib-utils](https://github.com/chancsy/lib-utils), a shared utility library that provides ADB helpers, window capture, and the region setup GUI.

Install directly from GitHub:

```
pip install git+https://github.com/chancsy/lib-utils.git
```

### Python packages

Each tool has its own `MODULES.md` listing its specific pip packages.

---

## Credits

**Vvanna Quiz** — question/answer bank sourced from the [Life Makeover Wiki](https://life-makeover.fandom.com/wiki/Shining_Journey/Vvanna_Quiz).
Primary contributor: [Riblam](https://life-makeover.fandom.com/wiki/User:Riblam).

## Quick Start (any plugin)

```
cd <plugin_folder>
python setup.py          # first time — configure scrcpy + define screen regions
python main.py           # run automation (scrcpy capture if configured, else adb screencap)
python main.py --adb     # force adb screencap
python main.py --debug -s screenshot.png   # debug without device
```
