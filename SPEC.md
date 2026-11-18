# cpp-west-workspace - software requirements specification

Reverse-engineered on 2026-11-18 from commit `63be24b`. Every requirement cites the line that implements it.
Inferences are labelled. Paths without a directory refer to `scripts/west_commands/cpp_build_commands.py`.

<!-- jira-sync:start -->
Jira: KAN-93

## Tasks

This list is one ticket in Jira project KAN, [KAN-93](https://igorsvolohovs.atlassian.net/browse/KAN-93). Each line is a checkbox there: tick it in Jira and the sync ticks it here; add a checkbox there and it is appended here. Done items are the features described in section 3; open items are what the project declares but the code does not do yet.

- [x] Manifest and registration (section 3) <!-- spec-manifest-and-registration -->
- [x] Project selection (section 3) <!-- spec-project-selection -->
- [x] Invocation of a project build (section 3) <!-- spec-invocation-of-a-project-build -->
- [x] Outcome of one project (section 3) <!-- spec-outcome-of-one-project -->
- [x] Logging and terminal output (section 3) <!-- spec-logging-and-terminal-output -->
- [x] Running several builds (section 3) <!-- spec-running-several-builds -->
- [x] Summary and verdict (section 3) <!-- spec-summary-and-verdict -->
- [x] Repository standard (section 3) <!-- spec-repository-standard -->
- [ ] `west.yml:11-16` and `README.md:17` state that each revision is the repository's real default branch and that (declared, not implemented) <!-- spec-west-yml-11-16-and-readme-md-17-state-that-each-re -->
- [ ] `west.yml:7-9` says `west update` reproduces the tree "on the right revisions, every time". (declared, not implemented) <!-- spec-west-yml-7-9-says-west-update-reproduces-the-tree- -->
- [ ] The build behaviour described in `README.md:20` (Conan, CMake preset, ctest) belongs to the projects' scripts and (declared, not implemented) <!-- spec-the-build-behaviour-described-in-readme-md-20-cona -->

<!-- jira-sync:end -->

## 1. Purpose and scope

The system is the manifest repository of a west workspace of nine C++ repositories, plus two west extension
commands that build those repositories on Windows and report one verdict (`README.md:3-13`).

In scope:

- the workspace manifest `west.yml` and the command registration `west-commands.yml`;
- the commands `west build-all` and `west build-one` in `cpp_build_commands.py`: project selection, invocation of
  each project's build script, logging, the summary table and the exit code.

Out of scope:

- the C++ code and the build logic of the nine projects. The MSVC environment, Conan, CMake presets and ctest are
  handled by each project's `scripts\build_windows.ps1`, which is not in this repository (`README.md:20`,
  `cpp_build_commands.py:3-9`, `:316-324`);
- builds on Linux/macOS, which the error text sends to each project's `.devcontainer` (`:410-414`);
- the cloning itself, which west performs from `west.yml`.

## 2. Context

| actor or system | role | source |
| --- | --- | --- |
| developer | runs `west init`, `west update`, `west build-all`, `west build-one` | `README.md:5-11` |
| west (Python package) | reads the manifest, clones the projects, imports the command module by path, provides `WestCommand`, `CommandError`, `ManifestProject`, `Project` and the loaded manifest | `west.yml:63-72`, `cpp_build_commands.py:37-38` |
| GitHub, remote `IGORSVOLOHOVS` | hosts the nine repositories | `west.yml:18-23` |
| Windows PowerShell or `pwsh` | runs each `build_windows.ps1` | `:145-154`, `:166-216` |
| `scripts\build_windows.ps1` of each project | performs the build; its exit code is the verdict | `:40-45`, `:376-390` |

Runtime environment: Windows with PowerShell; Python with west (`docs/install.md:11` says Python 3.9 or newer for
the workspace; development uses Python 3.13, `pyproject.toml`). The workspace layout is `projects/<name>` for the
nine projects, `cpp-west-workspace` for this repository, and `build-logs/` at the workspace top (`west.yml:28-72`,
`:47-52`).

## 3. Functional requirements

### Manifest and registration

- **FR-1.** The system shall define one remote with URL base `https://github.com/IGORSVOLOHOVS` and make it the
  default remote. Source: `west.yml:18-23`. Verification: no test.
- **FR-2.** The system shall list nine projects, CppMiddleProject1 to CppMiddleProject8 and Mandelbrot-Fractal,
  each at path `projects/<name>`, at revision `main` except CppMiddleProject7 at `initial`. Source:
  `west.yml:25-61`. Verification: no test.
- **FR-3.** The system shall describe itself at path `cpp-west-workspace` and register `west-commands.yml` as its
  extension-command file. Source: `west.yml:70-72`. Verification: no test.
- **FR-4.** The system shall register `build-all` as `BuildAllProjectsCommand` and `build-one` as
  `BuildOneProjectCommand`, both from `scripts/west_commands/cpp_build_commands.py`. Source:
  `west-commands.yml:12-20`. Verification: `test_the_file_loads_the_way_west_loads_it` (class names only, not
  the YAML).
- **FR-5.** The system shall stay loadable when imported from its file path without an entry in `sys.modules`,
  including its dataclasses. Source: `:18-24`, `:64-76`. Verification: `test_the_file_loads_the_way_west_loads_it`.

### Project selection

- **FR-6.** The system shall exclude the manifest repository from the buildable projects and keep manifest order.
  Source: `:262-270`. Verification: `test_selection_skips_the_manifest_repository_and_matches_any_case`.
- **FR-7.** The system shall match requested project names case-insensitively, drop repeated names and keep the
  order of the request. Source: `:272-291`. Verification:
  `test_selection_skips_the_manifest_repository_and_matches_any_case`.
- **FR-8.** The system shall stop with exit code 1 and list the known project names when a requested name is not
  in the manifest. Source: `:286-288`. Verification: `test_an_unknown_name_stops_the_command` (exit code 1 and
  the requested name in the message; the list of known names is not asserted).
- **FR-9.** `build-all` shall accept `--only` repeated and as comma-separated lists, trimming spaces and dropping
  empty items. Source: `:294-302`, `:544-550`, `:569-571`. Verification: `test_split_comma_separated_names`,
  `test_build_all_with_only_builds_the_named_projects`.
- **FR-10.** `build-all` without `--only` shall select every manifest project. Source: `:572-573`. Verification:
  `test_build_all_reports_every_project_and_fails_on_one`.
- **FR-11.** `build-one` shall select exactly one project given as a positional argument. Source: `:609-618`.
  Verification: `test_build_one_succeeds_with_debug`.

### Invocation of a project build

- **FR-12.** The system shall use `powershell` when it is on PATH and `pwsh` otherwise. Source: `:145-154`.
  Verification: `test_find_powershell_prefers_windows_powershell`.
- **FR-13.** The system shall stop with an error when neither `powershell` nor `pwsh` is found. Source:
  `:408-414`. Verification: `test_build_all_needs_powershell`.
- **FR-14.** The system shall run `<shell> -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command` with four
  statements: `$global:LASTEXITCODE = 0`, console output encoding set to UTF-8, the call of the script, and
  `exit $LASTEXITCODE`. Source: `:166-216`. Verification: `test_command_line_forwards_the_options_and_the_exit_code`.
- **FR-15.** The system shall always pass `-BuildType <Release|Debug>` (default `Release`) and pass `-Clean` and
  `-SkipTests` only when `--clean` and `--skip-tests` are given. Source: `:190-194`, `:237-256`. Verification:
  `test_command_line_forwards_the_options_and_the_exit_code`, `test_command_line_without_flags`,
  `test_build_one_succeeds_with_debug`.
- **FR-16.** The system shall put the script path in PowerShell single quotes, doubling any embedded single quote.
  Source: `:119-126`, `:200`. Verification: `test_quote_for_powershell_doubles_single_quotes`.
- **FR-17.** The system shall run each script with the project directory as working directory and stderr merged
  into stdout. Source: `:354-359`. Verification: no dedicated test (the fake `Popen` in the tests ignores the
  stream arguments).

### Outcome of one project

- **FR-18.** The system shall report `НЕ СКЛОНИРОВАН`, duration 0, without starting anything, when the project is
  not cloned. Source: `:327-333`. Verification: `test_a_project_not_cloned_is_a_failure`.
- **FR-19.** The system shall report `НЕТ СКРИПТА` when `scripts/build_windows.ps1` is not a file in the project.
  Source: `:338-345`. Verification: `test_a_project_without_its_script_is_a_failure`.
- **FR-20.** The system shall report `ПРОВАЛ` with the error text when the process cannot be started (`OSError`).
  Source: `:366-373`. Verification: `test_a_build_that_cannot_start_fails`.
- **FR-21.** The system shall report `OK` for exit code 0 and `ПРОВАЛ` with "build_windows.ps1 вернул код N" for any
  other code. Source: `:375-390`. Verification: `test_a_build_that_exits_0_succeeds_and_is_logged`,
  `test_a_build_that_exits_non_zero_fails`.
- **FR-22.** The system shall treat only `OK` as success. Source: `:54-61`, `:74-76`. Verification:
  `test_a_project_not_cloned_is_a_failure`, `test_a_project_without_its_script_is_a_failure`.

### Logging and terminal output

- **FR-23.** The system shall write every output byte of a started build to `<workspace top>/build-logs/<name>.log`,
  creating the directory and replacing an earlier file. Source: `:47-52`, `:349-362`, `:418`. Verification:
  `test_a_build_that_exits_0_succeeds_and_is_logged`.
- **FR-24.** The system shall decode output lines as UTF-8, then (on Windows) with the OEM code page, then as UTF-8
  with replacement characters, without raising. Source: `:96-116`. Verification: `test_decode_prefers_utf8`,
  `test_decode_never_raises_on_bytes_that_are_not_utf8`, `test_decode_falls_back_to_replacement_off_windows`.
- **FR-25.** The system shall replace characters that the console encoding cannot represent instead of failing.
  Source: `:129-142`. Verification: `test_write_text_to_stdout_replaces_what_the_console_cannot_encode`.

### Running several builds

- **FR-26.** The system shall build every selected project even after a failure. Source: `:396-457`.
  Verification: `test_build_all_reports_every_project_and_fails_on_one`.
- **FR-27.** With `--jobs 1` the system shall build in selection order, print `=== [i/N] Собираю <name> ===` before
  each project and stream its output to the terminal. Source: `:425-438`. Verification:
  `test_build_all_reports_every_project_and_fails_on_one[1]`, `test_a_build_that_exits_0_succeeds_and_is_logged`.
- **FR-28.** With `--jobs N > 1` the system shall build up to N projects at once in threads, print only start and
  finish lines, and return results in selection order. Source: `:440-457`. Verification:
  `test_build_all_reports_every_project_and_fails_on_one[2]`.
- **FR-29.** The system shall refuse `--jobs` below 1. Source: `:566-567`. Verification:
  `test_build_all_refuses_zero_jobs`.
- **FR-30.** The system shall print `<-- <name>: <outcome> (<duration>)` when a project finishes, as a warning with
  the detail when it did not succeed. Source: `:459-465`. Verification: no dedicated test.
- **FR-31.** `build-all` shall print the number of projects, the configuration and the job count before starting.
  Source: `:580`. Verification: no test.

### Summary and verdict

- **FR-32.** The system shall print a table with columns `ПРОЕКТ`, `СТАТУС`, `ВРЕМЯ` in result order, with the
  detail in parentheses when present, then `Итог: собрано N из M`, then `Полные логи: <dir>` when at least one log
  was written. Source: `:471-502`. Verification: `test_build_all_reports_every_project_and_fails_on_one`.
- **FR-33.** The system shall print the warning `нечего собирать: выборка проектов пуста` instead of the table when
  the selection is empty. Source: `:473-475`. Verification: `test_an_empty_selection_warns_instead_of_printing_a_table`.
- **FR-34.** The system shall format durations, rounded to whole seconds, as `Sс`, `Mм SSс` or `Hч MMм SSс`.
  Source: `:79-93`. Verification: `test_format_duration`.
- **FR-35.** The system shall end with return code 1 through `CommandError` after the table when any result is
  not `OK`. Source: `:504-513`. Verification: `test_build_all_reports_every_project_and_fails_on_one`.

### Repository standard

- **FR-36.** The repository shall carry the lab tooling of repo-quality-template, requirements revision 4.0.0,
  except R-02, R-09, R-37, R-41, R-42, and `recipe.ps1 test` shall fail when `$Version` differs from the
  `pyproject.toml` version. Source: `README.md:40`, `recipe.ps1:82-94`. Verification: `.\recipe.ps1 test`.

### Declared but not implemented, or not confirmed

- `west.yml:11-16` and `README.md:17` state that each revision is the repository's real default branch and that
  CppMiddleProject7 has never had a `main` branch. Local clones of the nine repositories made on 2026-11-18 show
  `origin/HEAD` at `release` for CppMiddleProject1 to 8 and a `main` branch in CppMiddleProject7. Not checked
  against the GitHub API.
- `west.yml:7-9` says `west update` reproduces the tree "on the right revisions, every time". Revisions are branch
  names, so the fetched commits change as the branches move (inference).
- The build behaviour described in `README.md:20` (Conan, CMake preset, ctest) belongs to the projects' scripts and
  is not implemented here.

## 4. Interfaces

### Command line

| command | arguments | effect | source |
| --- | --- | --- | --- |
| `west build-all` | `[--only NAME[,NAME...]]... [-j N] [--build-type Release\|Debug] [--clean] [--skip-tests]` | build all or the named projects | `:537-583` |
| `west build-one` | `PROJECT [--build-type Release\|Debug] [--clean] [--skip-tests]` | build one project, serially | `:602-626` |

Exit status: 0 when every selected project is `OK` (also when the selection is empty); 1 when any is not
(`:504-513`); 1 from `die` for an unknown name, `--jobs` below 1 or missing PowerShell (`:288`, `:567`, `:410`).

### Contract with each project's script

| item | value | source |
| --- | --- | --- |
| location | `<project>/scripts/build_windows.ps1` | `:45`, `:338` |
| arguments | `-BuildType Release\|Debug`, optional `-Clean`, optional `-SkipTests` | `:190-194` |
| working directory | the project directory | `:356` |
| output | stdout and stderr, any encoding; UTF-8 requested via `[Console]::OutputEncoding` | `:196-203`, `:357-358` |
| verdict | process exit code; 0 means success | `:376-390` |

### Files

| file | format | written by | source |
| --- | --- | --- | --- |
| `west.yml` | west manifest YAML | maintainer | `west.yml` |
| `west-commands.yml` | west extension-command YAML | maintainer | `west-commands.yml` |
| `build-logs/<name>.log` | raw bytes of the build output | the commands | `:349-362` |

## 5. Data

| entity | fields | source |
| --- | --- | --- |
| `ProjectBuildResult` | `project_name`, `outcome`, `duration_seconds`, `detail`, `log_file_path` (optional); `succeeded` is `outcome == "OK"` | `:64-76` |
| `BuildInvocationOptions` | `build_type`, `clean`, `skip_tests` | `:157-163` |
| outcome values | `OK`, `ПРОВАЛ`, `НЕТ СКРИПТА`, `НЕ СКЛОНИРОВАН` | `:58-61` |

Nothing is kept between runs except the log files, which the next run of the same project replaces (`:353`).

## 6. Non-functional requirements

- **NFR-1.** Both commands shall live in one Python file, because west imports it by path and a sibling module
  could not be imported. Source: `west-commands.yml:6-11`, `cpp_build_commands.py:11-15`, `pyproject.toml`
  `py-modules = ["cpp_build_commands"]`.
- **NFR-2.** Development shall use Python 3.13. Source: `pyproject.toml` `requires-python = ">=3.13,<3.14"`,
  `uv.lock:3`.
- **NFR-3.** Test coverage of `scripts/west_commands` shall be at least 99%. Source: `pyproject.toml`
  `addopts ... --cov-fail-under=99`.
- **NFR-4.** The sources shall pass ruff 0.16.1 (rules `E4`, `E7`, `E9`, `F`, `I`, line length 120) and mypy over
  `scripts/west_commands` and `tools` with no silenced modules. Source: `pyproject.toml` `[tool.ruff]`,
  `[tool.mypy]`, silence list comment.
- **NFR-5.** The scripts shall run with execution policy `Bypass`, so unsigned freshly cloned scripts are accepted.
  Source: `:209-213`.
- **NFR-6.** Tests shall start no build and need no workspace. Source: `README.md:32`,
  `tests/test_cpp_build_commands.py:1-5`.

## 7. Constraints and dependencies

| package | constraint | locked | source |
| --- | --- | --- | --- |
| west | `>=1.2` | 1.5.0 | `pyproject.toml`, `uv.lock` |
| colorama, packaging, pykwalify, pyyaml | dependencies of west | 0.4.6, 26.3, 1.8.0, 6.0.3 | `uv.lock` |
| ruff / mypy / pytest / pytest-cov / coverage | dev, pinned | 0.16.1 / 2.3.0 / 8.4.2 / 5.0.0 / 7.15.2 | `pyproject.toml`, `uv.lock` |
| setuptools | build backend | 80.9.0 (pinned in `[build-system]`, not in `uv.lock`) | `pyproject.toml` |

Tools for the projects' builds (`docs/install.md:5-18`): Visual Studio 2022 with the C++ workload, CMake 3.25+,
Ninja, Conan 2, Git, and for CppMiddleProject8 the developer distribution of LLVM/Clang 19+.

## 8. Acceptance

1. `.\recipe.ps1 test` exits 0: version check, pytest with coverage at least 99%, mypy, `ruff check`, and
   `ruff format` leaving no diff (`recipe.ps1:82-109`). This covers FR-5 to FR-35 except those marked "no test".
2. In a fresh directory, `west init -m <this repository> cpp-west`, `cd cpp-west`, `west update` produce
   `projects/` with nine clones at the revisions of FR-2, and `west build-all --help` prints the options of
   section 4 (FR-1 to FR-4).
3. `west build-all --only CppMiddleProject1 --skip-tests` ends with the table, `Итог: собрано N из 1`, a file
   `build-logs/CppMiddleProject1.log`, and an exit code that is 1 exactly when the row is not `OK`
   (FR-21, FR-23, FR-32, FR-35).
4. Renaming one project's `scripts/build_windows.ps1` and rerunning gives `НЕТ СКРИПТА` and exit code 1 (FR-19).

Steps 2 to 4 need Windows, network access and the projects' toolchains; no automated check runs them.

## 9. Open questions

- Who uses the workspace besides the owner, and on which machines, is not stated.
- Whether the revisions in `west.yml` should follow the repositories' current default branches (`release` in
  local clones of CppMiddleProject1 to 8) or stay on `main`/`initial`.
- What R-37, R-41, R-42 require and what issues #8 to #12 plan; the README names them only. Two of the five are
  answered here: R-02 puts keys in a committed `.claude/.env`, reversed by `CLAUDE.md` rule 4 and `.gitignore:20-24`;
  R-09 is the pre-lab history imported without rewording or sign-off (`CLAUDE.md:66-67`).
- Whether a Gitea runner labelled `windows` serves this repository, and whether the workflows have run.
- Expected build durations: the code says "three seconds to over an hour" (`:82-84`) and "hours" for all nine
  (`:532-534`); no target exists.
- Whether `-j` above 1 is safe with one shared Conan cache; the help text warns but nothing measures it.
- Whether `--only ,` (empty selection, exit 0) is intended, given the docstring at `:276-278` treats quietly
  building nothing as the failure to avoid.
- Whether non-Windows use with `pwsh` should be refused explicitly.
