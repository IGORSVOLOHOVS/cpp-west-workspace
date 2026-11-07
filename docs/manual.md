# Manual

Both commands run inside a west workspace made by `west init -m <this repository>` and `west update`.

## west build-all

```powershell
west build-all [--only NAME[,NAME...]] [-j N] [--build-type Release|Debug] [--clean] [--skip-tests]
```

| option | what it does |
| --- | --- |
| `--only NAME` | build only the named projects; repeat the flag or separate names with commas. Case does not matter; an unknown name stops the command and lists the known ones |
| `-j N`, `--jobs N` | build N projects at once, 1 by default. Above 1 the build output goes only to `build-logs/`, and the projects share one Conan cache |
| `--build-type` | `Release` by default. `Debug` builds Boost and OpenSSL from source in several projects, which takes hours |
| `--clean` | delete each build folder before configuring |
| `--skip-tests` | do not run ctest after the build |

With `-j 1` the build output streams to the terminal as it comes.

## west build-one

```powershell
west build-one PROJECT [--build-type Release|Debug] [--clean] [--skip-tests]
```

The same for one project, with the same table and exit code.

## The result

Each project ends in one of four states: `OK`, `ПРОВАЛ` (the script exited non-zero or could not start), `НЕТ СКРИПТА` (no `scripts\build_windows.ps1`) or `НЕ СКЛОНИРОВАН` (not cloned; run `west update`). Only `OK` is a success. The table is followed by `Итог: собрано N из M` and the folder of the logs. The exit code is 1 when any project is not `OK`.

Each project's script is called through `powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command`, with the console output encoding set to UTF-8 first so that its Russian progress messages survive, and `exit $LASTEXITCODE` last so that its exit code is the verdict. `pwsh` is used when Windows PowerShell is absent; with neither, the command stops.
