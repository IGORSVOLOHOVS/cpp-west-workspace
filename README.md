# cpp-west-workspace

Зонтик над девятью C++-репозиториями: **один манифест, одна команда клонирования,
одна команда сборки.** Сделано на [west](https://docs.zephyrproject.org/latest/develop/west/index.html)
— том же менеджере воркспейсов, что и у Zephyr.

```powershell
pip install west
west init -m https://github.com/IGORSVOLOHOVS/cpp-west-workspace cpp-west
cd cpp-west
west update
west build-all
```

Всё. `west update` клонирует девять репозиториев в `projects/`, `west build-all`
собирает каждый нативно под MSVC и печатает таблицу «проект — статус — время».

## Что внутри

| Проект | Ветка | Путь после `west update` |
| --- | --- | --- |
| CppMiddleProject1 | `main` | `projects/CppMiddleProject1` |
| CppMiddleProject2 | `main` | `projects/CppMiddleProject2` |
| CppMiddleProject3 | `main` | `projects/CppMiddleProject3` |
| CppMiddleProject4 | `main` | `projects/CppMiddleProject4` |
| CppMiddleProject5 | `main` | `projects/CppMiddleProject5` |
| CppMiddleProject6 | `main` | `projects/CppMiddleProject6` |
| CppMiddleProject7 | **`initial`** | `projects/CppMiddleProject7` |
| CppMiddleProject8 | `main` | `projects/CppMiddleProject8` |
| Mandelbrot-Fractal | `main` | `projects/Mandelbrot-Fractal` |

У CppMiddleProject7 ветки `main` не существует — ветка по умолчанию называется
`initial`. Ровно ради таких мелочей и нужен манифест: помнить это должен файл,
а не человек.

Итоговое дерево:

```
cpp-west/
├── .west/                     служебный каталог west
├── cpp-west-workspace/        этот репозиторий (манифест + команды)
├── build-logs/                полный вывод каждой сборки
└── projects/
    ├── CppMiddleProject1/
    ├── ...
    └── Mandelbrot-Fractal/
```

## Команды

`west build-all` и `west build-one` — это расширения west, объявленные в
`west-commands.yml` этого репозитория. Они появляются сразу после `west init`,
отдельно ставить их не нужно.

```powershell
west build-all                          # все девять, Release
west build-all --only CppMiddleProject1 # один проект
west build-all --only CppMiddleProject1,Mandelbrot-Fractal
west build-all --jobs 3                 # три проекта одновременно
west build-all --skip-tests --clean
west build-one CppMiddleProject5        # то же для одного проекта
west build-all --help
```

Поведение, на которое можно полагаться:

* сборка **не останавливается** на первом провале — нужно знать состояние всех
  девяти, а не только первого сломанного;
* в конце печатается таблица и строка `Итог: собрано N из M`;
* код возврата **1**, если провалился хотя бы один проект (годится для CI);
* полный вывод каждой сборки пишется в `build-logs/<Проект>.log`;
* при `--jobs 1` (по умолчанию) вывод сборки идёт в терминал живьём; при `--jobs N`
  — только в лог-файлы, потому что перемешанный вывод трёх компиляторов читать
  невозможно;
* проект, который не склонирован или потерял `scripts\build_windows.ps1`,
  считается провалом, а не пропуском: несостоявшаяся сборка не должна давать
  зелёный код возврата.

Ничего своего эти команды не собирают. Они запускают `scripts\build_windows.ps1`
каждого проекта — тот самый скрипт, который вносит окружение MSVC, при
необходимости зовёт Conan, конфигурирует CMake по `CMakePresets.json`, собирает и
прогоняет ctest. Единственное определение «этот проект собирается» живёт в самом
проекте.

## Что нужно поставить заранее

| Инструмент | Зачем | Проверка |
| --- | --- | --- |
| **Visual Studio 2022** (Desktop development with C++) | компилятор MSVC и `vcvars64.bat` | `where cl` внутри Developer PowerShell |
| **CMake ≥ 3.25** | пресеты из `CMakePresets.json` | `cmake --version` |
| **Ninja** | генератор, который используют пресеты | `ninja --version` |
| **Conan 2** | зависимости (Boost, OpenSSL, GTest) | `conan --version` |
| **Python 3.9+ и west** | сам воркспейс | `west --version` |
| **Git** | клонирование | `git --version` |

Отдельно входить в Developer PowerShell не нужно: `build_windows.ps1` каждого
проекта сам находит Visual Studio через `vswhere` и вносит окружение MSVC в свой
процесс.

Один проект требует большего. **CppMiddleProject8** — это clang-tool, ему нужна
девелоперская поставка LLVM/Clang 19+ (заголовки и `lib\cmake\clang\ClangConfig.cmake`).
Обычного установщика `LLVM-<версия>-win64.exe` не хватает: в нём только `clang.exe`
и C API. Нужен архив `clang+llvm-<версия>-x86_64-pc-windows-msvc.tar.xz` с той же
страницы релиза; распаковать куда угодно и указать путь через переменную окружения
`CT_CLANG_INSTALL_DIR`. Без этого `west build-all` соберёт восемь проектов из девяти
и честно покажет `ПРОВАЛ` на восьмом.

Первый `west build-all` заметно дольше последующих: Conan скачивает пакеты, а
часть зависимостей в некоторых проектах собирается из исходников (Boost, LLVM) —
это часы, а не минуты. `--build-type Debug` дольше `Release`: готовых Debug-бинарников
для MSVC в conan-center нет.

## Docker никуда не делся

`.devcontainer` в каждом из девяти проектов **не тронут и продолжает работать**.
Windows-сборку добавили *рядом*, а не *вместо*: на Linux и в VS Code Remote
Containers всё собирается ровно как раньше, через контейнер. Этот воркспейс —
второй путь к тем же бинарникам, для тех, у кого под рукой Windows и Visual
Studio, а не Docker.

## Как это устроено

* `west.yml` — манифест: remote `IGORSVOLOHOVS`, девять проектов с реальными
  ветками и путями внутри `projects/`. Секция `self` подключает `west-commands.yml`.
* `west-commands.yml` — регистрация расширений west.
* `scripts/west_commands/cpp_build_commands.py` — реализация обеих команд. Обе
  лежат в одном файле намеренно: west импортирует файл расширения по пути и не
  добавляет его каталог в `sys.path`, так что соседний модуль оттуда не
  импортировался бы.

Обновить набор проектов после изменения манифеста:

```powershell
cd cpp-west-workspace
git pull
cd ..
west update
```

## Лицензия

MIT, см. [LICENSE](LICENSE).
