# Install

## To build the nine projects

| tool | what for | check |
| --- | --- | --- |
| Visual Studio 2022 with Desktop development with C++ | MSVC and `vcvars64.bat` | `where cl` in a Developer PowerShell |
| CMake 3.25 or newer | the presets in `CMakePresets.json` | `cmake --version` |
| Ninja | the generator the presets use | `ninja --version` |
| Conan 2 | Boost, OpenSSL and GTest | `conan --version` |
| Python 3.9 or newer, and west | the workspace itself | `west --version` |
| Git | cloning | `git --version` |

There is no need to start a Developer PowerShell: each project's `build_windows.ps1` finds Visual Studio through `vswhere` and enters the MSVC environment in its own process.

`pip install west` on Windows puts `west.exe` in `%APPDATA%\Python\Python3XX\Scripts`, which may not be on PATH. Add it, or call `python -m west`, which works the same.

CppMiddleProject8 is a clang tool and needs the developer distribution of LLVM/Clang 19 or newer, with its headers and `lib\cmake\clang\ClangConfig.cmake`. The usual `LLVM-<version>-win64.exe` installer is not enough; take `clang+llvm-<version>-x86_64-pc-windows-msvc.tar.xz` from the same release page and unpack it with `python -m tarfile -e <archive> C:\LLVM`, because the `tar.exe` of Windows 10 has no LZMA.

## To work on the commands

1. Install [uv](https://docs.astral.sh/uv/) and Python 3.13.
2. Clone this repository and run `uv sync --frozen` at its root. That installs west at the version `uv.lock` pins.
3. `.\recipe.ps1 test` runs the tests, mypy and ruff. `.\recipe.ps1 run <arguments>` runs `python -m west` with them.

`.\recipe.ps1 build` packs `cpp_build_commands.py` into a wheel in `dist\`. west itself does not use the wheel: it loads the file from this repository through `west-commands.yml`.
