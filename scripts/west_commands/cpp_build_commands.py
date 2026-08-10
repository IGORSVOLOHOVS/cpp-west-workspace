"""West extension commands that build the C++ projects of this workspace.

Every repository listed in ``west.yml`` ships the same native Windows
entry point, ``scripts\\build_windows.ps1``, which enters the MSVC
environment, resolves Conan dependencies, configures CMake from
``CMakePresets.json``, builds and runs the tests. These commands do not
reimplement any of that. They only walk the manifest, invoke each
project's own script, and turn nine separate build sessions into one
command with one verdict.

Why both commands live in this single file: west imports an extension
command file with ``importlib`` straight from its path and deliberately
does not add the containing directory to ``sys.path``. A second module
placed next to this one could therefore not be imported from here, so
shared helpers and both command classes have to share a module.
"""

# Deliberately no "from __future__ import annotations" here. West imports
# this file with importlib.util.module_from_spec and never registers the
# result in sys.modules, so sys.modules[cls.__module__] is None for every
# class defined below. With string annotations, @dataclass tries exactly
# that lookup to resolve them and dies with "NoneType has no attribute
# __dict__" before west can even print --help. Evaluated annotations cost
# nothing here and keep the commands loadable.
import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from west.commands import CommandError, WestCommand
from west.manifest import ManifestProject, Project

#: Path of the native Windows build entry point inside every project.
#: All nine repositories agreed on this location; a project that loses
#: it is reported as broken rather than silently skipped, because a
#: skipped project that still counts as success is how a red build gets
#: reported green.
RELATIVE_BUILD_SCRIPT_PATH = Path("scripts") / "build_windows.ps1"

#: Directory, relative to the west workspace top level, where the full
#: output of every build is kept. Terminal output of a parallel run is
#: unreadable and the terminal scrollback of a serial run is finite, so
#: the log file is the authoritative record of what a build actually
#: printed.
RELATIVE_BUILD_LOG_DIRECTORY = Path("build-logs")

# Outcome of a single project build. These are the only four states, and
# three of them are failures: "the script was missing" and "the project
# was never cloned" both mean the requested build did not happen, and a
# build that did not happen must not be able to produce exit code 0.
BUILD_OUTCOME_SUCCEEDED = "OK"
BUILD_OUTCOME_FAILED = "ПРОВАЛ"
BUILD_OUTCOME_SCRIPT_MISSING = "НЕТ СКРИПТА"
BUILD_OUTCOME_NOT_CLONED = "НЕ СКЛОНИРОВАН"


@dataclass
class ProjectBuildResult:
    """What happened to one project during a build-all / build-one run."""

    project_name: str
    outcome: str
    duration_seconds: float
    detail: str
    log_file_path: Optional[Path] = None

    @property
    def succeeded(self) -> bool:
        return self.outcome == BUILD_OUTCOME_SUCCEEDED


def format_duration(duration_seconds: float) -> str:
    """Render a duration the way a person reads it, not as raw seconds.

    Builds here range from three seconds to over an hour (Boost and LLVM
    are compiled from source in some projects), so a single unit would
    be either unreadable or imprecise at one end of that range.
    """
    total_seconds = int(round(duration_seconds))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}ч {minutes:02d}м {seconds:02d}с"
    if minutes:
        return f"{minutes}м {seconds:02d}с"
    return f"{seconds}с"


def decode_console_bytes(raw_bytes: bytes) -> str:
    """Decode one line of build output into text.

    The build scripts are asked to emit UTF-8 (see
    ``build_powershell_command_line``), so UTF-8 is tried first. Native
    tools invoked by those scripts - cl.exe, cmake, conan - write to the
    same handle directly, bypassing PowerShell's encoder, and use the
    console OEM code page instead; that is the fallback. The last resort
    never raises, because a garbled byte in a compiler message must not
    crash the umbrella command that exists to report on it.
    """
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if os.name == "nt":
        try:
            return raw_bytes.decode("oem", errors="replace")
        except LookupError:  # pragma: no cover - non-Windows Python build
            pass
    return raw_bytes.decode("utf-8", errors="replace")


def quote_for_powershell_single_quotes(text: str) -> str:
    """Wrap text in PowerShell single quotes, escaping embedded ones.

    Single quotes are used rather than double quotes because PowerShell
    performs no expansion inside them: a workspace checked out under a
    path containing ``$`` or a backtick must not be reinterpreted.
    """
    return "'" + text.replace("'", "''") + "'"


def write_text_to_stdout(text: str) -> None:
    """Write already-decoded text to stdout without ever raising.

    The terminal encoding may be narrower than the text produced by a
    build (a UTF-8 log line printed to a cp866 console, for example).
    Losing a character is acceptable; losing the whole build run to a
    UnicodeEncodeError is not.
    """
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        sys.stdout.write(text.encode(encoding, errors="replace").decode(encoding))
    sys.stdout.flush()


def find_powershell_executable() -> Optional[str]:
    """Locate the interpreter able to run the projects' build scripts.

    Windows PowerShell is preferred over PowerShell 7 because that is
    what the per-project scripts declare (``#Requires -Version 5.1``)
    and what they were tested against; ``pwsh`` is accepted as a
    fallback so the commands still work on a machine where only the
    cross-platform build is installed.
    """
    return shutil.which("powershell") or shutil.which("pwsh")


@dataclass
class BuildInvocationOptions:
    """The knobs forwarded to every project's build_windows.ps1."""

    build_type: str
    clean: bool
    skip_tests: bool


def build_powershell_command_line(
    powershell_executable: str,
    build_script_path: Path,
    options: BuildInvocationOptions,
) -> list[str]:
    """Compose the command line that runs one project's build script.

    Why ``-Command`` and not the more obvious ``-File``: with ``-File``
    the script's Russian progress output is destroyed before this
    process can read it. Redirected Windows PowerShell output is encoded
    with the console OEM code page, which on a Latin-locale machine
    cannot represent Cyrillic, so every message arrives as a row of
    question marks - and no decoding on this side can recover it.
    ``-Command`` allows ``[Console]::OutputEncoding`` to be set to UTF-8
    *before* the script runs, which fixes the output at the source.

    The price of ``-Command`` is that the script's exit code no longer
    becomes the process exit code automatically, hence the explicit
    ``exit $LASTEXITCODE``. ``$LASTEXITCODE`` is pre-set to 0 so that a
    script which finishes without running any native command is reported
    as success rather than inheriting a stale value. A script that dies
    from an unhandled terminating error never reaches that line, and
    PowerShell then exits 1 on its own - which is the outcome we want.
    """
    script_arguments = ["-BuildType", options.build_type]
    if options.clean:
        script_arguments.append("-Clean")
    if options.skip_tests:
        script_arguments.append("-SkipTests")

    powershell_statements = "; ".join(
        [
            "$global:LASTEXITCODE = 0",
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
            "& "
            + quote_for_powershell_single_quotes(str(build_script_path))
            + " "
            + " ".join(script_arguments),
            "exit $LASTEXITCODE",
        ]
    )

    return [
        powershell_executable,
        "-NoProfile",
        "-NonInteractive",
        # Projects are checked out fresh by "west update" and are
        # therefore unsigned local scripts; without this the default
        # execution policy refuses to run them.
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        powershell_statements,
    ]


class WindowsNativeBuildCommandBase(WestCommand):
    """Shared machinery of ``west build-all`` and ``west build-one``.

    Kept as a base class rather than duplicated because the difference
    between the two commands is only which projects are selected; the
    invocation, the logging, the summary table and the exit code rules
    must stay identical, otherwise ``build-one`` and ``build-all`` could
    disagree about whether the same project builds.
    """

    def __init__(self, name: str, help_text: str, description: str):
        super().__init__(name, help_text, description)
        self._output_lock = threading.Lock()

    # ---------------------------------------------------------------
    # Argument plumbing
    # ---------------------------------------------------------------

    def add_shared_build_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add the options that both commands forward to the scripts."""
        parser.add_argument(
            "--build-type",
            choices=("Release", "Debug"),
            default="Release",
            help="конфигурация сборки (по умолчанию Release; Debug для "
                 "многих проектов означает сборку Boost/OpenSSL из "
                 "исходников, то есть часы работы)",
        )
        parser.add_argument(
            "--clean",
            action="store_true",
            help="удалить каталог сборки перед конфигурацией",
        )
        parser.add_argument(
            "--skip-tests",
            action="store_true",
            help="не запускать ctest после сборки",
        )

    # ---------------------------------------------------------------
    # Project selection
    # ---------------------------------------------------------------

    def list_manifest_projects(self) -> list[Project]:
        """Return the real projects of the manifest, in manifest order.

        ``Manifest.projects`` starts with the manifest repository itself
        (a ``ManifestProject``), which has no C++ code and no build
        script. Filtering it out here keeps every caller from having to
        remember that.
        """
        return [
            project
            for project in self.manifest.projects
            if not isinstance(project, ManifestProject)
        ]

    def select_projects_by_name(
        self, requested_names: Iterable[str]
    ) -> list[Project]:
        """Resolve user-supplied names to manifest projects.

        Matching is case-insensitive because the names are long and
        typed by hand. An unknown name is a hard error rather than an
        empty selection: quietly building nothing after a typo is the
        failure mode that makes a build command untrustworthy.
        """
        all_projects = self.list_manifest_projects()
        projects_by_lowercase_name = {
            project.name.lower(): project for project in all_projects
        }

        selected_projects: list[Project] = []
        for requested_name in requested_names:
            project = projects_by_lowercase_name.get(requested_name.lower())
            if project is None:
                known = ", ".join(project.name for project in all_projects)
                self.die(
                    f"проект '{requested_name}' не описан в west.yml. "
                    f"Известные проекты: {known}"
                )
            if project not in selected_projects:
                selected_projects.append(project)
        return selected_projects

    @staticmethod
    def split_comma_separated_names(raw_values: Iterable[str]) -> list[str]:
        """Accept both ``--only A --only B`` and ``--only A,B``."""
        names: list[str] = []
        for raw_value in raw_values:
            for name in raw_value.split(","):
                name = name.strip()
                if name:
                    names.append(name)
        return names

    # ---------------------------------------------------------------
    # Running one build
    # ---------------------------------------------------------------

    def build_single_project(
        self,
        project: Project,
        options: BuildInvocationOptions,
        powershell_executable: str,
        log_directory: Path,
        stream_output_to_terminal: bool,
    ) -> ProjectBuildResult:
        """Run one project's own build script and classify the result.

        The project's script is treated as the single source of truth:
        it is the thing that enters the MSVC environment, decides
        whether Conan is needed and asserts that an executable was
        actually produced. Duplicating any of those decisions here would
        create a second, subtly different definition of "this project
        builds".
        """
        started_at = time.monotonic()

        if not project.is_cloned():
            return ProjectBuildResult(
                project_name=project.name,
                outcome=BUILD_OUTCOME_NOT_CLONED,
                duration_seconds=0.0,
                detail="каталог проекта отсутствует — сначала 'west update'",
            )

        project_directory = Path(project.abspath)
        build_script_path = project_directory / RELATIVE_BUILD_SCRIPT_PATH
        if not build_script_path.is_file():
            return ProjectBuildResult(
                project_name=project.name,
                outcome=BUILD_OUTCOME_SCRIPT_MISSING,
                duration_seconds=0.0,
                detail=f"нет файла {RELATIVE_BUILD_SCRIPT_PATH}",
            )

        command_line = build_powershell_command_line(
            powershell_executable, build_script_path, options
        )

        log_directory.mkdir(parents=True, exist_ok=True)
        log_file_path = log_directory / f"{project.name}.log"

        try:
            with open(log_file_path, "wb") as log_file:
                build_process = subprocess.Popen(
                    command_line,
                    cwd=str(project_directory),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                assert build_process.stdout is not None
                for raw_line in build_process.stdout:
                    log_file.write(raw_line)
                    if stream_output_to_terminal:
                        write_text_to_stdout(decode_console_bytes(raw_line))
                exit_code = build_process.wait()
        except OSError as error:
            return ProjectBuildResult(
                project_name=project.name,
                outcome=BUILD_OUTCOME_FAILED,
                duration_seconds=time.monotonic() - started_at,
                detail=f"не удалось запустить сборку: {error}",
                log_file_path=log_file_path,
            )

        duration_seconds = time.monotonic() - started_at
        if exit_code == 0:
            return ProjectBuildResult(
                project_name=project.name,
                outcome=BUILD_OUTCOME_SUCCEEDED,
                duration_seconds=duration_seconds,
                detail="",
                log_file_path=log_file_path,
            )
        return ProjectBuildResult(
            project_name=project.name,
            outcome=BUILD_OUTCOME_FAILED,
            duration_seconds=duration_seconds,
            detail=f"build_windows.ps1 вернул код {exit_code}",
            log_file_path=log_file_path,
        )

    # ---------------------------------------------------------------
    # Running many builds
    # ---------------------------------------------------------------

    def build_projects(
        self,
        projects: list[Project],
        options: BuildInvocationOptions,
        job_count: int,
    ) -> list[ProjectBuildResult]:
        """Build the given projects, never stopping at the first failure.

        Stopping early would hide the state of every project after the
        broken one, and the question this command exists to answer is
        "which of the nine are healthy", not "is the first one healthy".
        """
        powershell_executable = find_powershell_executable()
        if powershell_executable is None:
            self.die(
                "не найден powershell. Эти команды собирают проекты "
                "нативно под Windows через scripts\\build_windows.ps1; "
                "на Linux/macOS пользуйтесь .devcontainer каждого проекта."
            )

        log_directory = Path(self.topdir) / RELATIVE_BUILD_LOG_DIRECTORY

        # Serial runs stream the build output live, because a silent
        # terminal during an hour-long Boost build is indistinguishable
        # from a hang. Parallel runs cannot stream: interleaved output
        # from several compilers is worse than no output, so there the
        # log files are the record.
        stream_output_to_terminal = job_count == 1

        if job_count == 1:
            results: list[ProjectBuildResult] = []
            for position, project in enumerate(projects, start=1):
                self.inf(
                    f"\n=== [{position}/{len(projects)}] Собираю "
                    f"{project.name} ==="
                )
                result = self.build_single_project(
                    project,
                    options,
                    powershell_executable,
                    log_directory,
                    stream_output_to_terminal=True,
                )
                self.report_finished_build(result)
                results.append(result)
            return results

        def build_and_report(project: Project) -> ProjectBuildResult:
            with self._output_lock:
                self.inf(f"--> старт: {project.name}")
            result = self.build_single_project(
                project,
                options,
                powershell_executable,
                log_directory,
                stream_output_to_terminal=False,
            )
            with self._output_lock:
                self.report_finished_build(result)
            return result

        with ThreadPoolExecutor(max_workers=job_count) as executor:
            # list() over map() keeps the results in manifest order, so
            # the summary table does not shuffle between runs.
            return list(executor.map(build_and_report, projects))

    def report_finished_build(self, result: ProjectBuildResult) -> None:
        """Announce one finished build as soon as it is known."""
        message = (
            f"<-- {result.project_name}: {result.outcome} "
            f"({format_duration(result.duration_seconds)})"
        )
        if result.succeeded:
            self.inf(message)
        else:
            self.wrn(f"{message} — {result.detail}")

    # ---------------------------------------------------------------
    # Reporting
    # ---------------------------------------------------------------

    def print_summary_table(self, results: list[ProjectBuildResult]) -> None:
        """Print the pass/fail table that is the point of the command."""
        if not results:
            self.wrn("нечего собирать: выборка проектов пуста")
            return

        name_column_width = max(
            len("ПРОЕКТ"), max(len(result.project_name) for result in results)
        )
        outcome_column_width = max(
            len("СТАТУС"), max(len(result.outcome) for result in results)
        )

        write_text_to_stdout("\n")
        write_text_to_stdout("=" * (name_column_width + outcome_column_width + 24))
        write_text_to_stdout("\n")
        write_text_to_stdout(
            f"{'ПРОЕКТ':<{name_column_width}}  "
            f"{'СТАТУС':<{outcome_column_width}}  ВРЕМЯ\n"
        )
        write_text_to_stdout("-" * (name_column_width + outcome_column_width + 24))
        write_text_to_stdout("\n")
        for result in results:
            line = (
                f"{result.project_name:<{name_column_width}}  "
                f"{result.outcome:<{outcome_column_width}}  "
                f"{format_duration(result.duration_seconds)}"
            )
            if result.detail:
                line += f"  ({result.detail})"
            write_text_to_stdout(line + "\n")
        write_text_to_stdout("=" * (name_column_width + outcome_column_width + 24))
        write_text_to_stdout("\n")

        succeeded_count = sum(1 for result in results if result.succeeded)
        write_text_to_stdout(
            f"Итог: собрано {succeeded_count} из {len(results)}\n"
        )
        log_paths = [
            result.log_file_path for result in results if result.log_file_path
        ]
        if log_paths:
            write_text_to_stdout(
                f"Полные логи: {log_paths[0].parent}\n"
            )

    def finish_with_exit_code(self, results: list[ProjectBuildResult]) -> None:
        """Fail the command if a single requested build did not succeed.

        Raised as ``CommandError`` rather than ``sys.exit`` so that west
        handles it the way it handles every other command failure, and
        so the summary table above has already been printed.
        """
        failed_results = [result for result in results if not result.succeeded]
        if failed_results:
            raise CommandError(returncode=1)


class BuildAllProjectsCommand(WindowsNativeBuildCommandBase):
    """``west build-all`` — build every project the manifest describes."""

    def __init__(self):
        super().__init__(
            "build-all",
            "собрать все проекты воркспейса нативно под Windows (MSVC)",
            """\
Обходит все проекты из west.yml и запускает у каждого его собственный
scripts\\build_windows.ps1 (окружение MSVC, Conan, CMake-пресет, ctest).

Сборка не останавливается на первой ошибке: в конце печатается таблица
"проект — статус — время", а код возврата равен 1, если провалился хотя
бы один проект. Полный вывод каждой сборки пишется в build-logs/ в корне
воркспейса.

Внимание: полная сборка всех девяти проектов занимает часы — часть
зависимостей (Boost, LLVM) собирается из исходников. Для быстрой
проверки пользуйтесь --only.""",
        )

    def do_add_parser(self, parser_adder) -> argparse.ArgumentParser:
        parser = parser_adder.add_parser(
            self.name,
            help=self.help,
            description=self.description,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument(
            "--only",
            action="append",
            default=[],
            metavar="ИМЯ",
            help="собрать только указанные проекты; можно повторять флаг "
                 "или перечислить имена через запятую",
        )
        parser.add_argument(
            "-j",
            "--jobs",
            type=int,
            default=1,
            metavar="N",
            help="сколько проектов собирать одновременно (по умолчанию 1). "
                 "Больше единицы ускоряет прогон, но параллельные проекты "
                 "делят один кеш Conan и вывод сборок перестаёт печататься "
                 "в терминал — смотрите build-logs/",
        )
        self.add_shared_build_arguments(parser)
        return parser

    def do_run(self, args: argparse.Namespace, unknown_args: list[str]) -> None:
        if args.jobs < 1:
            self.die("--jobs должен быть не меньше 1")

        if args.only:
            requested_names = self.split_comma_separated_names(args.only)
            projects = self.select_projects_by_name(requested_names)
        else:
            projects = self.list_manifest_projects()

        options = BuildInvocationOptions(
            build_type=args.build_type,
            clean=args.clean,
            skip_tests=args.skip_tests,
        )
        self.inf(
            f"Проектов к сборке: {len(projects)}; конфигурация "
            f"{options.build_type}; параллельно: {args.jobs}"
        )
        results = self.build_projects(projects, options, args.jobs)
        self.print_summary_table(results)
        self.finish_with_exit_code(results)


class BuildOneProjectCommand(WindowsNativeBuildCommandBase):
    """``west build-one <project>`` — build a single manifest project."""

    def __init__(self):
        super().__init__(
            "build-one",
            "собрать один проект воркспейса нативно под Windows (MSVC)",
            """\
Запускает scripts\\build_windows.ps1 одного проекта из west.yml и
печатает тот же итог, что и build-all. Код возврата 1, если сборка не
удалась.

Полезно, когда build-all уже показал, какой из девяти проектов красный,
и чинить надо именно его.""",
        )

    def do_add_parser(self, parser_adder) -> argparse.ArgumentParser:
        parser = parser_adder.add_parser(
            self.name,
            help=self.help,
            description=self.description,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument(
            "project",
            metavar="ПРОЕКТ",
            help="имя проекта так, как оно записано в west.yml "
                 "(регистр не важен)",
        )
        self.add_shared_build_arguments(parser)
        return parser

    def do_run(self, args: argparse.Namespace, unknown_args: list[str]) -> None:
        projects = self.select_projects_by_name([args.project])
        options = BuildInvocationOptions(
            build_type=args.build_type,
            clean=args.clean,
            skip_tests=args.skip_tests,
        )
        results = self.build_projects(projects, options, job_count=1)
        self.print_summary_table(results)
        self.finish_with_exit_code(results)
