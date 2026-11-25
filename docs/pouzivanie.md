# Používanie Omni PDF

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
   Malé **×** pri miniatúre odstráni príslušnú stranu; ikona dvoch listov ju duplikuje. Ikona listov **Spravovať strany** hore otvorí tieto akcie aj vloženie všetkých strán ďalšieho PDF za aktuálnu stranu. Rovnaká ponuka je dostupná pravým tlačidlom na miniatúre. Odstrániť možno aj poslednú stranu; potom zostane zobrazená karta **+** na pridanie PDF. Aj tieto úpravy podporujú Späť/Dopredu a zapisujú sa až pri uložení kópie.
7. Ikona zakrivenej šípky doľava / **Ctrl+Z** vráti zmenu, šípka doprava / **Ctrl+Y** alebo **Ctrl+Shift+Z** ju zopakuje. Nová úprava po návrate zahodí predchádzajúcu vetvu Dopredu. Opakované písanie v tom istom vybranom úseku tvorí jeden krok späť.
8. PDF kópiu uložte tlačidlom **Uložiť kópiu**, pomocou **Ctrl+S** alebo **Ctrl+Shift+S**. Automaticky sa mení náhľad; zápis PDF na disk zostáva na tomto tlačidle. Existujúci súbor nemožno prepísať.

Klávesové skratky: **Ctrl+O** otvorí súbor, **Ctrl+S** alebo **Ctrl+Shift+S** uloží kópiu, **Ctrl+Z** vráti úpravu, **Ctrl+Y** alebo **Ctrl+Shift+Z** ju zopakuje. **Ctrl++** alebo **Ctrl+=** priblíži dokument, **Ctrl+-** ho oddiali a **Ctrl+0** prispôsobí šírke okna. **Escape** zruší výber a **Delete** vymaže obsah vybraný na strane; pri písaní v textovom poli fungujú bežné skratky pre text.

Dokument vytlačíte ikonou tlačiarne alebo skratkou **Ctrl+P**. Systémový tlačový dialóg zobrazuje náhľad a umožňuje vybrať tlačiareň, strany a ďalšie nastavenia tlače. Strany sa prispôsobia tlačiteľnej oblasti papiera. Ak systémový komponent nie je dostupný, aplikácia použije samostatný náhľad a štandardný tlačový dialóg.

## Aktualizácie

Ponuka pod názvom **Omni PDF** obsahuje verziu aplikácie, ručnú kontrolu a prepínač automatickej kontroly aktualizácií. V EXE vydaní sa kontrola vykoná po spustení a následne každých šesť hodín. Ak je dostupná novšia stabilná verzia, aplikácia sa opýta na súhlas. Až po jeho udelení zobrazí priebeh sťahovania a pred spustením inštalátora overí jeho veľkosť a SHA-256. Sťahovanie možno zrušiť. Koncepty, prerelease vydania a staršie verzie sa neinštalujú.

Inštaláciu možno odložiť. Pred reštartom aplikácia ponúkne uloženie rozpracovaného PDF; zrušenie uloženia zruší aj inštaláciu. Inštalátor čaká na riadne ukončenie aplikácie a násilne ju neukončuje. Po aktualizácii spustí novú verziu. Prvá aktualizácia prenosného EXE použije štandardný priečinok `%LOCALAPPDATA%\Programs\OmniPDF`; ďalšie aktualizácie nainštalovanej aplikácie zachovajú jej umiestnenie. V zdrojovom spustení je dostupná ručná kontrola a odkaz na vydanie, nie samoinštalácia do Pythonu.

## Obmedzenia

- Náhradný text môže používať iné písmo ako originál. Pri skenoch sa vybraná časť obrázka odstráni a predvolene vyplní bielou plochou.
- Pri texte nad obrázkom (napríklad sken s pôvodnou OCR vrstvou) použite zakrytie oblasti a nové textové pole.
- Zakrývací box používa jednu farbu pozadia. Na fotografii, prechode farieb alebo vzore nemusí dokonale splynúť s okolím.
- OCR závisí od jazykov OCR nainštalovaných vo Windows. Pred importom fotografie alebo skeny ručne narovnajte a orežte; čísla po rozpoznaní skontrolujte.
- Aplikácia automaticky neprepočítava DPH ani iné sumy.
- Šifrované súbory a PDF so zakázanými úpravami sa odmietnu. Digitálne podpísané PDF možno po potvrdení otvoriť alebo vložiť; aplikácia platnosť podpisu neoveruje a uložená kópia nebude mať platný pôvodný podpis.
- Stranu s neaplikovanými anotáciami na začiernenie nemožno upravovať, aby sa omylom neodstránil ďalší obsah.
