# Development and releases

## Project structure

```text
omnipdf/           Application, icons, PDF, OCR, printing and updates
tests/             Automated tests
windows_print/     Windows system print component
requirements/      Application and build dependencies
scripts/           Launch, build and release verification scripts
docs/              Documentation
.github/workflows/ GitHub Actions
```

## Run from source

Install Python 3.14 and run the following from the project root:

```cmd
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements\runtime.txt
.venv\Scripts\python.exe -m omnipdf
```

You can also double-click `OmniPDF.cmd` or run it from Command Prompt.

## Verification

```cmd
.venv\Scripts\python.exe -m unittest discover -v
```

Set `RUN_WINDOWS_OCR=1` to run the integration test against the installed Windows OCR languages. UI tests run without displaying windows.

## Builds and releases

`VERSION` in `omnipdf/app_info.py` is the source of truth for the version number, in `MAJOR.MINOR.PATCH` format. Working branches and pull requests target `main`; temporary files, virtual environments, builds and personal documents are excluded from the repository.

GitHub Actions runs Windows tests on pushes to `main` and pull requests. Pushes to `main` and manual runs also build the portable EXE. A `vMAJOR.MINOR.PATCH` tag runs tests, verifies the portable app and its in-place updater, and publishes `OmniPDF-windows-x64.exe` as the release's sole uploaded asset. The tag must match `VERSION` exactly. Existing releases are preserved.

To publish a release, update `omnipdf/app_info.py` and `docs/CHANGELOG.md`, test the change, merge it into `main`, then create a tag:

```cmd
git tag v0.2.0
git push origin v0.2.0
```

A local Windows build requires Python 3.14 x64 and the .NET 10 SDK.

```cmd
.venv\Scripts\python.exe -m pip install -r requirements\runtime.txt -r requirements\build.txt
.venv\Scripts\python.exe scripts\build_windows.py
```

The output is written to `release/`. To check packaged resources, Qt, the PDF engine and OCR, run `OmniPDF.exe --smoke-test --output smoke.json`.
