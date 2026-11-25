# Vývoj a vydávanie

## Štruktúra projektu

```text
omnipdf/           Aplikácia, ikony, PDF, OCR, tlač a aktualizácie
tests/             Automatické testy
windows_print/     Komponent systémovej tlače pre Windows
packaging/         Nastavenie inštalátora
requirements/      Závislosti aplikácie a zostavovania
scripts/           Spustenie, zostavenie a overenie vydania
docs/              Dokumentácia
.github/workflows/ CI a CD na GitHube
```

## Spustenie zo zdrojového kódu

Nainštaluj Python 3.14 a v koreňovom priečinku projektu spusti:

```cmd
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements\runtime.txt
.venv\Scripts\python.exe -m omnipdf
```

Aplikáciu možno spustiť aj súborom `scripts\Spustit.cmd`.

## Overenie

```cmd
.venv\Scripts\python.exe -m unittest -v
```

Test skutočného Windows OCR sa zapína premennou prostredia `RUN_WINDOWS_OCR=1`. Testy rozhrania bežia bez zobrazovania okien.

## Vývoj a vydávanie

Jediným zdrojom verzie je `VERSION` v `omnipdf/app_info.py`, vo formáte `MAJOR.MINOR.PATCH`. Pracovné vetvy a pull requesty smerujú do `main`; `tmp`, virtuálne prostredie, buildy a rozpracované dokumenty sa do repozitára nepridávajú.

GitHub Actions spustí Windows testy pri pushi do `main` a pri pull requestoch. Push do `main` a ručné spustenie vytvoria EXE artifact. Tag `vMAJOR.MINOR.PATCH` spustí testy, zostavenie oboch EXE, kontrolu spustenia prenosnej aj nainštalovanej aplikácie a zverejnenie GitHub Release. Tag sa musí presne zhodovať s `VERSION`; existujúce vydanie sa neprepisuje.

Pri novom vydaní upravte `omnipdf/app_info.py` a `docs/CHANGELOG.md`, otestujte zmenu a po jej začlenení do `main` vytvorte tag, napríklad:

```cmd
git tag v0.2.0
git push origin v0.2.0
```

Lokálny Windows build vyžaduje Python 3.14 x64, .NET 10 SDK a Inno Setup 6. Cestu ku kompilátoru možno nastaviť premennou `ISCC`:

```cmd
.venv\Scripts\python.exe -m pip install -r requirements\runtime.txt -r requirements\build.txt
.venv\Scripts\python.exe scripts\build_windows.py
```

Výsledky sú v `release/`. Kontrola zabalených zdrojov, Qt a PDF enginu sa dá spustiť cez `OmniPDF.exe --smoke-test --output smoke.json`.
