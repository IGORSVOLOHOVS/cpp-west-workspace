param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('build', 'install', 'uninstall', 'clean', 'run', 'publish', 'info', 'test')]
    [string]$Verb,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RunArgs
)

# Everything down to $OverridePhrase is read as TEXT by the git hooks and the
# pipeline: one literal per line, no variables, no concatenation.
$Name    = 'cpp-west-workspace'  # the repository, lower-case kebab-case
$Code    = 'cww'                 # the project code; the first word of every branch
$Version = '1.0.0'
$Summary = 'West workspace manifest and extension commands that clone and build nine C++ repositories with one command each.'
$Needs   = @()                   # other lab projects, name@tag - this one depends on none
$Tools   = @()                   # toolchains the lab must fetch - uv is on the machine

# A console tool with no window goes as a library: no $App, no installer.
$Provides = @('scripts/west_commands/cpp_build_commands.py')  # what the wheel in dist\ carries; one file, so the wiki has no API pages

$CommitTypes  = @('feat', 'fix', 'docs', 'refactor', 'test', 'build', 'ci', 'chore')
$CommitScopes = @('core', 'build', 'ci', 'docs', 'deps')
$BranchTypes  = @('feat', 'fix', 'docs', 'refactor', 'test', 'build', 'ci', 'chore', 'hotfix', 'experiment')
$Reviewers    = @('igors')
$OverridePhrase = '1234567890'   # section 8 - the owner's override; a mark, not a password

# Native tools report on stderr and their exit code is the verdict, so a line on stderr must not stop the verb.
$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot

# ValueFromRemainingArguments leaves $RunArgs null when nothing follows the verb.
if ($null -eq $RunArgs) { $RunArgs = @() }

# .claude/.env is gitignored here and never committed. A variable already set wins.
$envFile = Join-Path $PSScriptRoot '.claude\.env'
if (Test-Path $envFile) {
    foreach ($line in Get-Content -Encoding UTF8 $envFile) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$' -and
            -not (Test-Path "env:$($Matches[1])")) {
            Set-Item "env:$($Matches[1])" $Matches[2].Trim('"', "'")
        }
    }
}

Push-Location $root
try {
    switch ($Verb) {
        'build' {
            uv build --wheel --out-dir dist
            exit $LASTEXITCODE
        }
        'install' { Write-Host 'nothing to install'; exit 0 }
        'uninstall' { Write-Host 'nothing to uninstall'; exit 0 }
        'clean' {
            foreach ($path in 'dist', 'build', 'out', '.coverage') {
                if (Test-Path $path) { Remove-Item -Recurse -Force $path }
            }
            exit 0
        }
        'run' {
            uv run --frozen python -m west @RunArgs
            exit $LASTEXITCODE
        }
        'publish' {
            # Hands the wheel to the lab: the tree section 6 fixes for a $Needs entry.
            if (-not $env:LAB_SHARE) { Write-Host 'LAB_SHARE is not set, so there is nowhere to publish to'; exit 1 }
            uv build --wheel --out-dir dist
            if ($LASTEXITCODE -ne 0) { exit 1 }
            $target = Join-Path $env:LAB_SHARE "needs\$Name\v$Version"
            New-Item -ItemType Directory -Force $target | Out-Null
            Copy-Item dist\*.whl $target
            exit 0
        }
        'info' {
            Write-Host "Name    : $Name"
            Write-Host "Code    : $Code"
            Write-Host "Version : $Version"
            Write-Host "Summary : $Summary"
            Write-Host "Provides: $($Provides -join ', ')"
            exit 0
        }
        'test' {
            # Section 6: $Version is the one that counts, and this verb fails when
            # pyproject.toml's [project] version disagrees with it.
            $inProject = $false
            $pyVersion = $null
            foreach ($line in (Get-Content -Encoding UTF8 'pyproject.toml')) {
                if ($line -match '^\s*\[') { $inProject = ($line.Trim() -eq '[project]') }
                elseif ($inProject -and $null -eq $pyVersion -and $line -match '^\s*version\s*=\s*"([^"]+)"') { $pyVersion = $Matches[1] }
            }
            if ($pyVersion -ne $Version) {
                Write-Host "Version mismatch: recipe.ps1 says $Version, pyproject.toml says $pyVersion."
                exit 1
            }
            # The git hooks next (section 10), so a fresh clone has them too.
            git -C $root config core.hooksPath .claude/hooks/git
            if ($LASTEXITCODE -ne 0) { exit 1 }
            # The coverage floor and every pytest option live in pyproject.toml.
            uv run --frozen python -m pytest
            if ($LASTEXITCODE -ne 0) { exit 1 }
            uv run --frozen python -m mypy
            if ($LASTEXITCODE -ne 0) { exit 1 }
            uv run --frozen python -m ruff check .
            if ($LASTEXITCODE -ne 0) { exit 1 }
            # In place, never --check: the gate runs git diff --exit-code after this verb.
            uv run --frozen python -m ruff format .
            if ($LASTEXITCODE -ne 0) { exit 1 }
            exit 0
        }
    }
}
finally {
    Pop-Location
}
