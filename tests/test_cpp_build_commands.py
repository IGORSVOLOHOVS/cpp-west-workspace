"""Tests for the west build-all and build-one commands.

No build runs here: `subprocess.Popen` and `shutil.which` are replaced inside the
module, the manifest is a small fake, and every log goes under pytest's tmp_path.
"""

import argparse
import importlib.util
import os
from pathlib import Path

import cpp_build_commands as cbc
import pytest
from west.commands import CommandError

MODULE_FILE = Path(cbc.__file__).resolve()


class FakeProject:
    def __init__(self, name: str, abspath: Path, cloned: bool = True) -> None:
        self.name = name
        self.abspath = str(abspath)
        self.cloned = cloned

    def is_cloned(self) -> bool:
        return self.cloned


class FakeManifestProject(FakeProject):
    pass


class FakeManifest:
    def __init__(self, projects: list[FakeProject]) -> None:
        self.projects = projects


class FakeConfig:
    """What WestCommand reads from the workspace configuration: only whether to colour its output."""

    def getboolean(self, option: str, default: bool = False) -> bool:
        return False


class FakeProcess:
    def __init__(self, lines: list[bytes], code: int) -> None:
        self.stdout = iter(lines)
        self.code = code

    def wait(self) -> int:
        return self.code


def make_project(tmp_path: Path, name: str, script: bool = True, cloned: bool = True) -> FakeProject:
    folder = tmp_path / "projects" / name
    if cloned:
        (folder / "scripts").mkdir(parents=True)
        if script:
            (folder / "scripts" / "build_windows.ps1").write_text("exit 0", encoding="utf-8")
    return FakeProject(name, folder, cloned)


def make_command(command: cbc.WindowsNativeBuildCommandBase, tmp_path: Path, projects: list[FakeProject]):
    command.manifest = FakeManifest([FakeManifestProject("manifest", tmp_path), *projects])
    command.topdir = str(tmp_path)
    command.config = FakeConfig()
    return command


@pytest.fixture(autouse=True)
def fake_manifest_project_class(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cbc, "ManifestProject", FakeManifestProject)


@pytest.fixture
def fake_builds(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Every project whose name contains BAD exits 3; the rest print two lines and exit 0."""
    launched: list[list[str]] = []

    def fake_popen(command_line: list[str], cwd: str, stdout: object, stderr: object) -> FakeProcess:
        launched.append(command_line)
        if "BAD" in cwd:
            return FakeProcess([b"error C2065\r\n"], 3)
        return FakeProcess(["Сборка\r\n".encode(), b"done\r\n"], 0)

    monkeypatch.setattr(cbc.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cbc.shutil, "which", lambda name: f"C:/fake/{name}.exe" if name == "powershell" else None)
    return launched


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0с"), (3.4, "3с"), (59.6, "1м 00с"), (125, "2м 05с"), (3600, "1ч 00м 00с"), (3725, "1ч 02м 05с")],
)
def test_format_duration(seconds: float, text: str) -> None:
    assert cbc.format_duration(seconds) == text


def test_decode_prefers_utf8() -> None:
    assert cbc.decode_console_bytes("Сборка".encode()) == "Сборка"


def test_decode_never_raises_on_bytes_that_are_not_utf8() -> None:
    text = cbc.decode_console_bytes(b"\xff\xfe abc")
    assert text.endswith(" abc")
    if os.name == "nt":
        assert text == b"\xff\xfe abc".decode("oem", errors="replace")


def test_decode_falls_back_to_replacement_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cbc.os, "name", "posix")
    assert cbc.decode_console_bytes(b"\xff ok") == "\ufffd ok"


def test_quote_for_powershell_doubles_single_quotes() -> None:
    assert cbc.quote_for_powershell_single_quotes("C:\\it's $here") == "'C:\\it''s $here'"


def test_write_text_to_stdout_replaces_what_the_console_cannot_encode(monkeypatch: pytest.MonkeyPatch) -> None:
    written: list[str] = []

    class NarrowStdout:
        encoding = "ascii"

        def write(self, text: str) -> None:
            text.encode(self.encoding)
            written.append(text)

        def flush(self) -> None:
            pass

    monkeypatch.setattr(cbc.sys, "stdout", NarrowStdout())
    cbc.write_text_to_stdout("ok Сборка")
    assert written == ["ok ??????"]


def test_find_powershell_prefers_windows_powershell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cbc.shutil, "which", lambda name: f"/bin/{name}")
    assert cbc.find_powershell_executable() == "/bin/powershell"
    monkeypatch.setattr(cbc.shutil, "which", lambda name: "/bin/pwsh" if name == "pwsh" else None)
    assert cbc.find_powershell_executable() == "/bin/pwsh"


def test_command_line_forwards_the_options_and_the_exit_code() -> None:
    options = cbc.BuildInvocationOptions(build_type="Debug", clean=True, skip_tests=True)
    line = cbc.build_powershell_command_line("powershell", Path("C:/w/it's/build_windows.ps1"), options)
    assert line[:6] == ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command"]
    statements = line[6].split("; ")
    assert statements[0] == "$global:LASTEXITCODE = 0"
    assert statements[1] == "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8"
    script = str(Path("C:/w/it's/build_windows.ps1")).replace("'", "''")
    assert statements[2] == f"& '{script}' -BuildType Debug -Clean -SkipTests"
    assert statements[3] == "exit $LASTEXITCODE"


def test_command_line_without_flags() -> None:
    options = cbc.BuildInvocationOptions(build_type="Release", clean=False, skip_tests=False)
    line = cbc.build_powershell_command_line("pwsh", Path("b.ps1"), options)
    assert line[6].split("; ")[2] == "& 'b.ps1' -BuildType Release"


def test_split_comma_separated_names() -> None:
    split = cbc.WindowsNativeBuildCommandBase.split_comma_separated_names
    assert split(["A, B", "C", " ,", "D,"]) == ["A", "B", "C", "D"]


def test_selection_skips_the_manifest_repository_and_matches_any_case(tmp_path: Path) -> None:
    one, two = make_project(tmp_path, "CppMiddleProject1"), make_project(tmp_path, "Mandelbrot-Fractal")
    command = make_command(cbc.BuildAllProjectsCommand(), tmp_path, [one, two])
    assert command.list_manifest_projects() == [one, two]
    assert command.select_projects_by_name(["mandelbrot-fractal", "CPPMIDDLEPROJECT1", "Mandelbrot-Fractal"]) == [
        two,
        one,
    ]


def test_an_unknown_name_stops_the_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    command = make_command(cbc.BuildAllProjectsCommand(), tmp_path, [make_project(tmp_path, "CppMiddleProject1")])
    with pytest.raises(SystemExit) as stopped:
        command.select_projects_by_name(["CppMiddleProject9"])
    assert stopped.value.code == 1
    assert "CppMiddleProject9" in capsys.readouterr().err


def build_one(tmp_path: Path, project: FakeProject, stream: bool = False) -> cbc.ProjectBuildResult:
    command = make_command(cbc.BuildOneProjectCommand(), tmp_path, [project])
    options = cbc.BuildInvocationOptions(build_type="Release", clean=False, skip_tests=False)
    return command.build_single_project(project, options, "powershell", tmp_path / "build-logs", stream)


def test_a_project_not_cloned_is_a_failure(tmp_path: Path) -> None:
    result = build_one(tmp_path, make_project(tmp_path, "P", cloned=False))
    assert result.outcome == cbc.BUILD_OUTCOME_NOT_CLONED
    assert not result.succeeded


def test_a_project_without_its_script_is_a_failure(tmp_path: Path) -> None:
    result = build_one(tmp_path, make_project(tmp_path, "P", script=False))
    assert result.outcome == cbc.BUILD_OUTCOME_SCRIPT_MISSING
    assert not result.succeeded


def test_a_build_that_exits_0_succeeds_and_is_logged(
    tmp_path: Path, fake_builds: list[list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    result = build_one(tmp_path, make_project(tmp_path, "Good"), stream=True)
    assert result.succeeded and result.detail == ""
    assert result.log_file_path == tmp_path / "build-logs" / "Good.log"
    assert result.log_file_path.read_bytes() == "Сборка\r\n".encode() + b"done\r\n"
    assert "done" in capsys.readouterr().out
    assert fake_builds[0][0] == "powershell"


def test_a_build_that_exits_non_zero_fails(tmp_path: Path, fake_builds: list[list[str]]) -> None:
    result = build_one(tmp_path, make_project(tmp_path, "BAD"))
    assert result.outcome == cbc.BUILD_OUTCOME_FAILED
    assert result.detail.endswith("3")


def test_a_build_that_cannot_start_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> FakeProcess:
        raise OSError("no such file")

    monkeypatch.setattr(cbc.subprocess, "Popen", refuse)
    result = build_one(tmp_path, make_project(tmp_path, "P"))
    assert result.outcome == cbc.BUILD_OUTCOME_FAILED
    assert "no such file" in result.detail


def parse(command: cbc.WindowsNativeBuildCommandBase, argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    command.do_add_parser(parser.add_subparsers())
    return parser.parse_args([command.name, *argv])


@pytest.mark.parametrize("jobs", ["1", "2"])
def test_build_all_reports_every_project_and_fails_on_one(
    tmp_path: Path, fake_builds: list[list[str]], capsys: pytest.CaptureFixture[str], jobs: str
) -> None:
    projects = [make_project(tmp_path, "Alpha"), make_project(tmp_path, "BAD"), make_project(tmp_path, "Gamma")]
    command = make_command(cbc.BuildAllProjectsCommand(), tmp_path, projects)
    args = parse(command, ["--jobs", jobs, "--skip-tests"])
    with pytest.raises(CommandError) as failed:
        command.do_run(args, [])
    assert failed.value.returncode == 1
    assert len(fake_builds) == 3 and all("-SkipTests" in line[6] for line in fake_builds)
    out = capsys.readouterr().out
    table = out[out.index("ПРОЕКТ") :]
    assert [line.split()[0] for line in table.splitlines()[2:5]] == ["Alpha", "BAD", "Gamma"]
    assert "Итог: собрано 2 из 3" in out
    assert f"Полные логи: {tmp_path / 'build-logs'}" in out


def test_build_all_with_only_builds_the_named_projects(tmp_path: Path, fake_builds: list[list[str]]) -> None:
    projects = [make_project(tmp_path, "Alpha"), make_project(tmp_path, "BAD"), make_project(tmp_path, "Gamma")]
    command = make_command(cbc.BuildAllProjectsCommand(), tmp_path, projects)
    command.do_run(parse(command, ["--only", "gamma,alpha", "--clean"]), [])
    assert len(fake_builds) == 2 and all("-Clean" in line[6] for line in fake_builds)
    assert "Gamma" in fake_builds[0][6] and "Alpha" in fake_builds[1][6]


def test_build_all_refuses_zero_jobs(tmp_path: Path) -> None:
    command = make_command(cbc.BuildAllProjectsCommand(), tmp_path, [])
    with pytest.raises(SystemExit):
        command.do_run(parse(command, ["--jobs", "0"]), [])


def test_build_all_needs_powershell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cbc.shutil, "which", lambda name: None)
    command = make_command(cbc.BuildAllProjectsCommand(), tmp_path, [make_project(tmp_path, "Alpha")])
    with pytest.raises(SystemExit):
        command.do_run(parse(command, []), [])


def test_an_empty_selection_warns_instead_of_printing_a_table(
    tmp_path: Path, fake_builds: list[list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    command = make_command(cbc.BuildAllProjectsCommand(), tmp_path, [])
    command.do_run(parse(command, []), [])
    captured = capsys.readouterr()
    assert "Итог" not in captured.out
    assert "нечего собирать" in captured.out + captured.err


def test_build_one_succeeds_with_debug(
    tmp_path: Path, fake_builds: list[list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    command = make_command(cbc.BuildOneProjectCommand(), tmp_path, [make_project(tmp_path, "Alpha")])
    command.do_run(parse(command, ["ALPHA", "--build-type", "Debug"]), [])
    assert len(fake_builds) == 1 and "-BuildType Debug" in fake_builds[0][6]
    assert "Итог: собрано 1 из 1" in capsys.readouterr().out


def test_the_file_loads_the_way_west_loads_it() -> None:
    """west imports the file by path and never registers it in sys.modules; the dataclasses must survive that."""
    spec = importlib.util.spec_from_file_location("loaded_by_west", MODULE_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.ProjectBuildResult(
        project_name="P", outcome=module.BUILD_OUTCOME_SUCCEEDED, duration_seconds=1.0, detail=""
    )
    assert result.succeeded
    assert module.BuildAllProjectsCommand().name == "build-all"
    assert module.BuildOneProjectCommand().name == "build-one"
