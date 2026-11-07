# cpp-west-workspace

An umbrella over nine C++ repositories: **one manifest, one command to clone them, one command to build them.** It is built on [west](https://docs.zephyrproject.org/latest/develop/west/index.html), the workspace manager Zephyr uses.

```powershell
pip install west
west init -m https://github.com/IGORSVOLOHOVS/cpp-west-workspace cpp-west
cd cpp-west
west update
west build-all
```

`west update` clones the nine repositories into `projects/`, and `west build-all` builds each one natively under MSVC and prints a table of project, status and time.

## What is inside

- `west.yml` lists CppMiddleProject1 to CppMiddleProject8 and Mandelbrot-Fractal, each pinned to its real default branch. CppMiddleProject7 has no `main`: its branch is `initial`, and the manifest remembers that so a person does not have to.
- `west-commands.yml` registers two west extension commands, `build-all` and `build-one`, from `scripts/west_commands/cpp_build_commands.py`. They appear as soon as `west init` has cloned this repository.

The commands build nothing themselves. They run each project's own `scripts\build_windows.ps1`, which enters the MSVC environment, calls Conan when needed, configures CMake from `CMakePresets.json`, builds and runs ctest. The one definition of "this project builds" lives in the project.

Behaviour to rely on:

- a build does not stop at the first failure;
- the run ends with the table and the line `Итог: собрано N из M` (built N of M);
- the exit code is 1 when any requested project failed;
- the full output of every build goes to `build-logs/<project>.log` at the workspace top;
- a project that is not cloned or has lost its `scripts\build_windows.ps1` counts as a failure, not a skip.

## Use

`docs/install.md` lists what to install and `docs/manual.md` every option. `.\recipe.ps1 test` runs the tests, mypy and ruff; the tests start no build and need no workspace.

## Licence

MIT, see `LICENSE`.

## Lab requirements

This repository complies with [revision 4.0.0](http://127.0.0.1:3000/igors-lab/software-requirements/src/tag/v4.0.0/BEST_REQUIREMENTS.md) of the lab requirements, except R-02 (#8), R-09 (#9), R-37 (#10), R-41 (#11), R-42 (#12).
