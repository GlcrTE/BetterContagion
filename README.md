# BetterContagion (Borderlands 4)

Loveless' Contagion spreads better. When an infected enemy dies, the green orbs that carry Contagion to new enemies fly twice as fast and look for targets twice as far away.

## Changes

| NCS table | Entry | Field | Vanilla | Mod |
|---|---|---|---|---|
| `light_projectile0` | `LightProjectile_Corpohacker_Contagion_ContagionSpread` | `speed` (cm/s) | 1200 | 2400 |
| `gbx_ue_data_table0` | `DataTable_Corpohacker_ActionSkill_Contagion` | row `Contagion_MaxSpreadDistance` (cm) | 4000 | 8000 |

The spread variants `_2` to `_10` inherit their speed from the base entry, so they all get faster. The build stops if a game update gives one of them its own speed.

## Build

NCS patch files are cumulative. The mod ships full copies of the patched tables. **After every game update, run the build again.**

```
py build.py [--game "D:/Games/SteamLibrary/steamapps/common/Borderlands 4"] [--speed 2.0] [--range 2.0]
```

`--speed` and `--range` are multipliers on the vanilla values. Writes `dist/BetterContagion_1001_P.pak`. The build re-decodes the result and checks both values.

`tools/` must contain these files (they are not in the repo):

- `repak.exe`: https://github.com/trumank/repak/releases
- `ncs_parser.exe`: https://github.com/Cr4nkSt4r/Borderlands-4.NcsParser/releases
- `oo2core_9_win64.dll`: the Oodle 2.9 redist DLL

## Install

Copy `BetterContagion_1001_P.pak` to `Borderlands 4/OakGame/Content/Paks/`.

## Compatibility

`gbx_ue_data_table0.ncs` is also shipped by other mods, for example VehiclesReimagined. If exactly one installed mod ships it, the build uses that mod's copy as its base and keeps its changes. The `_1001_P` pak then loads after it. **Rebuild BetterContagion after rebuilding or updating that mod.** If several installed mods ship the table, the build stops.

Conflicts with any mod that ships its own `Nexus-Data-light_projectile0.ncs`.

## License

MIT, see [LICENSE](LICENSE).

## Credits

- [repak](https://github.com/trumank/repak) by trumank (MIT/Apache-2.0)
- [Borderlands-4.NcsParser](https://github.com/Cr4nkSt4r/Borderlands-4.NcsParser) by Cr4nkSt4r (AGPL-3.0)
- Oodle by Epic Games Tools (proprietary, not redistributed)
