# Omni PDF

Jednoduchý lokálny editor na opravu textu v PDF dokumentoch a na obrázkoch JPG a PNG vo Windows. Práca s dokumentmi nepotrebuje účet ani internetové pripojenie; rozpoznávanie textu používa Windows OCR priamo v počítači. Pripojenie sa používa iba na kontrolu a stiahnutie aktualizácií z GitHubu, dokumenty sa neodosielajú.

Aplikácia používa pevnú svetlú tému vrátane ponúk, výberov, upozornení a súborových dialógov, aj keď Windows používa tmavý režim.

## Inštalácia

Hotové súbory pre Windows x64 sú v [GitHub Releases](https://github.com/hudakjakub/OmniPDF/releases/latest):

- **OmniPDF-Setup-windows-x64.exe** — odporúčaný inštalátor pre aktuálneho používateľa bez administrátorských práv.
- **OmniPDF-windows-x64.exe** — prenosná aplikácia, ktorú možno priamo spustiť.
- **SHA256SUMS.txt** — kontrolné súčty EXE súborov.

Vydanie obsahuje aj inštalátor s verziou v názve kvôli aktualizácii starších inštalácií.

Python netreba inštalovať. Buildy zatiaľ nemajú podpis Authenticode; Windows môže zobraziť upozornenie SmartScreen.

### Spustenie zo zdrojového kódu

Nainštalujte Python 3.14 a v priečinku aplikácie spustite v príkazovom riadku:

```cmd
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Inštalácia závislostí vyžaduje prístup k balíkom Pythonu. Potom aplikáciu spustite dvojklikom na `Spustit.cmd` alebo príkazom:

```cmd
.venv\Scripts\python.exe main.py
```

## Použitie

Aplikácia sa zobrazí po slovensky pri slovenskom systémovom jazyku; pri ostatných jazykoch použije angličtinu. Jazyk sa určí pri spustení aplikácie.

Kompaktný klasický panel spája všetko do jedného riadka: názov dokumentu a súborové akcie vľavo, prepínanie strán uprostred, textové nástroje a zväčšenie vpravo. Názvy ikon sa zobrazia po podržaní myši.

1. Otvorte PDF, JPG alebo PNG tlačidlom alebo pretiahnutím jedného súboru do prerušovaného rámu či kamkoľvek do okna. Pri otvorení ďalšieho dokumentu sa aplikácia opýta na uloženie rozpracovaných zmien.
2. Kliknite na úsek textu a prepíšte ho v pravom paneli. Náhľad sa automaticky aktualizuje približne po pol sekunde bez písania; tlačidlo na potvrdenie netreba. Ak sa text nezmestí, aplikácia ponechá poslednú platnú verziu a zobrazí vysvetlenie pri texte.
   Hore v paneli sa zobrazí zväčšený výrez vybraného textu s jeho okolím. Veľkosť písma sa vyberá z malého zoznamu; pôvodná neštandardná veľkosť zostáva dostupná.
3. Časť textu označte ťahaním myši a stlačte **Delete**. Kliknutie vyberie celý úsek. **Escape** zruší označenie, rozkreslenú oblasť aj aktívny nástroj na pridanie textu alebo zakrývanie. V textovom poli Delete funguje ako pri bežnom písaní.
   Posúvanie na inú stranu zachová výber aj rozpísaný text. Delete a úpravy v pravom paneli sa vzťahujú na pôvodne označenú stranu.
4. Text zo skenov a fotografií sa rozpozná automaticky po otvorení strany, ktorá nemá textovú vrstvu. Tlačidlo OCR netreba.
5. Ikonou **T** pridajte textové pole: kliknutím vložíte predvolené pole alebo ťahaním určíte jeho veľkosť. Potom môžete hneď písať. Nový text sa vloží nad pôvodný obsah. Ikonou prerušovaného obdĺžnika vyberte oblasť, ktorú môžete presunúť, zmeniť jej veľkosť alebo odstrániť klávesom Delete.
6. Strany sú zobrazené súvislo pod sebou. Kolieskom alebo posuvníkom prechádzate celým PDF; číslo strany a vybraná miniatúra sa prispôsobujú najviac viditeľnej strane. Šípky uprostred horného riadka alebo kliknutie na miniatúru preskočia na začiatok strany. Text možno upravovať kliknutím na ktorúkoľvek viditeľnú stranu.
   **Na šírku** prispôsobí najširšiu stranu dokumentu vrátane okrajov; prispôsobenie sa zachová pri zmene veľkosti okna až do ručného zväčšenia. Vo vyššom rozlíšení sa načítavajú viditeľné strany a ich najbližšie okolie. Prázdne podpisové pole sa v náhľade nezobrazuje ako „SIGN“.
   Vľavo sa vždy zobrazujú vycentrované miniatúry všetkých strán, aj v úzkom okne. Kliknutím na miniatúru prejdete na príslušnú stranu.
   Za poslednou stranou je karta **+** s prerušovaným rámom. Kliknutím vyberte ďalšie PDF alebo ho pretiahnite na kartu; všetky jeho strany sa pridajú na koniec otvoreného dokumentu.
   Malé **×** pri miniatúre odstráni príslušnú stranu; ikona dvoch listov ju duplikuje. Ikona listov **Spravovať strany** hore otvorí tieto akcie aj vloženie všetkých strán ďalšieho PDF za aktuálnu stranu. Rovnaká ponuka je dostupná pravým tlačidlom na miniatúre. Poslednú stranu nemožno odstrániť. Aj tieto úpravy podporujú Späť/Dopredu a zapisujú sa až pri uložení kópie.
7. Ikona zakrivenej šípky doľava / **Ctrl+Z** vráti zmenu, šípka doprava / **Ctrl+Y** alebo **Ctrl+Shift+Z** ju zopakuje. Nová úprava po návrate zahodí predchádzajúcu vetvu Dopredu. Opakované písanie v tom istom vybranom úseku tvorí jeden krok späť.
8. PDF kópiu uložte tlačidlom **Uložiť kópiu**, pomocou **Ctrl+S** alebo **Ctrl+Shift+S**. Automaticky sa mení náhľad; zápis PDF na disk zostáva na tomto tlačidle. Existujúci súbor nemožno prepísať.

Klávesové skratky: **Ctrl+O** otvorí súbor, **Ctrl+S** alebo **Ctrl+Shift+S** uloží kópiu, **Ctrl+Z** vráti úpravu, **Ctrl+Y** alebo **Ctrl+Shift+Z** ju zopakuje. **Ctrl++** alebo **Ctrl+=** priblíži dokument, **Ctrl+-** ho oddiali a **Ctrl+0** prispôsobí šírke okna. **Escape** zruší výber a **Delete** vymaže obsah vybraný na strane; pri písaní v textovom poli fungujú bežné skratky pre text.

Dokument vytlačíte ikonou tlačiarne alebo skratkou **Ctrl+P**. V tlačovom dialógu môžete vybrať tlačiareň, aktuálnu stranu alebo rozsah strán a ďalšie nastavenia tlače. Strany sa prispôsobia tlačiteľnej oblasti papiera.

## Obmedzenia

- Náhradný text môže používať iné písmo ako originál. Pri skenoch sa vybraná časť obrázka odstráni a predvolene vyplní bielou plochou.
- Pri texte nad obrázkom (napríklad sken s pôvodnou OCR vrstvou) použite zakrytie oblasti a nové textové pole.
- Zakrývací box používa jednu farbu pozadia. Na fotografii, prechode farieb alebo vzore nemusí dokonale splynúť s okolím.
- OCR závisí od jazykov OCR nainštalovaných vo Windows. Pred importom fotografie alebo skeny ručne narovnajte a orežte; čísla po rozpoznaní skontrolujte.
- Aplikácia automaticky neprepočítava DPH ani iné sumy.
- Šifrované súbory a PDF so zakázanými úpravami sa odmietnu. Digitálne podpísané PDF možno po potvrdení otvoriť alebo vložiť; aplikácia platnosť podpisu neoveruje a uložená kópia nebude mať platný pôvodný podpis.
- Stranu s neaplikovanými anotáciami na začiernenie nemožno upravovať, aby sa omylom neodstránil ďalší obsah.

## Overenie

```cmd
.venv\Scripts\python.exe -m unittest -v
```

Test skutočného Windows OCR sa zapína premennou prostredia `RUN_WINDOWS_OCR=1`. Testy rozhrania bežia bez zobrazovania okien.

## Aktualizácie

Ponuka pod názvom **Omni PDF** obsahuje verziu aplikácie, ručnú kontrolu a prepínač automatickej kontroly aktualizácií. V EXE vydaní sa kontrola vykoná po spustení a následne každých šesť hodín. Ak je dostupná novšia stabilná verzia, aplikácia sa opýta na súhlas. Až po jeho udelení zobrazí priebeh sťahovania a pred spustením inštalátora overí jeho veľkosť a SHA-256. Sťahovanie možno zrušiť. Koncepty, prerelease vydania a staršie verzie sa neinštalujú.

Inštaláciu možno odložiť. Pred reštartom aplikácia ponúkne uloženie rozpracovaného PDF; zrušenie uloženia zruší aj inštaláciu. Inštalátor čaká na riadne ukončenie aplikácie a násilne ju neukončuje. Po aktualizácii spustí novú verziu. Prvá aktualizácia prenosného EXE použije štandardný priečinok `%LOCALAPPDATA%\Programs\OmniPDF`; ďalšie aktualizácie nainštalovanej aplikácie zachovajú jej umiestnenie. V zdrojovom spustení je dostupná ručná kontrola a odkaz na vydanie, nie samoinštalácia do Pythonu.

## Vývoj a vydávanie

Jediným zdrojom verzie je `VERSION` v `app_info.py`, vo formáte `MAJOR.MINOR.PATCH`. Pracovné vetvy a pull requesty smerujú do `main`; `tmp`, virtuálne prostredie, buildy a rozpracované dokumenty sa do repozitára nepridávajú.

GitHub Actions spustí Windows testy pri pushi do `main` a pri pull requestoch. Push do `main` a ručné spustenie vytvoria EXE artifact. Tag `vMAJOR.MINOR.PATCH` spustí testy, zostavenie oboch EXE, kontrolu spustenia prenosnej aj nainštalovanej aplikácie a zverejnenie GitHub Release. Tag sa musí presne zhodovať s `VERSION`; existujúce vydanie sa neprepisuje.

Pri novom vydaní upravte `app_info.py` a `CHANGELOG.md`, otestujte zmenu a po jej začlenení do `main` vytvorte tag, napríklad:

```cmd
git tag v0.2.0
git push origin v0.2.0
```

Lokálny Windows build vyžaduje Python 3.14 x64 a Inno Setup 6. Cestu ku kompilátoru možno nastaviť premennou `ISCC`:

```cmd
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
.venv\Scripts\python.exe scripts\build_windows.py
```

Výsledky sú v `release/`. Kontrola zabalených zdrojov, Qt a PDF enginu sa dá spustiť cez `OmniPDF.exe --smoke-test --output smoke.json`.

## Licencia

GNU AGPL v3, pozri [LICENSE](LICENSE). Použité knižnice a ich zdrojové kódy sú uvedené v [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); licenčné texty sa prikladajú aj k EXE buildom.
