<div align="center">
  <img src="omnipdf/assets/omni.svg" width="72" alt="Logo Omni PDF">
  <h1>Omni PDF</h1>
  <p><strong>Upravuj PDF jednoducho, priamo vo Windows.</strong></p>
  <p>Bez účtu · Lokálne spracovanie · Slovenčina a angličtina</p>
  <p>
    <a href="https://github.com/hudakjakub/OmniPDF/actions/workflows/windows.yml"><img src="https://github.com/hudakjakub/OmniPDF/actions/workflows/windows.yml/badge.svg?branch=main&amp;event=push" alt="Stav CI a zostavenia na main"></a>
    <a href="https://github.com/hudakjakub/OmniPDF/releases/latest"><img src="https://img.shields.io/github/v/release/hudakjakub/OmniPDF?label=vydanie&amp;color=087f83" alt="Najnovšie vydanie"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/licencia-AGPL--3.0-087f83" alt="Licencia AGPL 3.0"></a>
  </p>
  <p><strong><a href="https://github.com/hudakjakub/OmniPDF/releases/latest">Stiahnuť pre Windows ↓</a></strong> &nbsp; · &nbsp; <a href="docs/pouzivanie.md">Používanie</a> &nbsp; · &nbsp; <a href="docs/vyvoj.md">Vývoj</a></p>
  <br>
  <img src="docs/images/omni-pdf.png" alt="Omni PDF: ukážka úpravy textu v PDF dokumente" width="100%">
</div>

## Jednoduchšie každodenné úpravy

- **Upravuj obsah** — prepíš text, pridaj vlastný alebo presuň či odstráň označenú oblasť.
- **Spravuj strany** — spoj dokumenty, vlož, duplikuj alebo odstráň strany.
- **Pracuj aj so skenmi** — otvor PDF, JPG či PNG a použi rozpoznávanie textu vo Windows.

Dokumenty zostávajú v počítači. Po úpravách ich môžeš vytlačiť alebo uložiť ako novú PDF kópiu.

## Stiahnutie

Na stránke [najnovšieho vydania](https://github.com/hudakjakub/OmniPDF/releases/latest) nájdeš inštalátor aj prenosnú verziu pre Windows x64. Aktualizáciu aplikácia ponúkne na potvrdenie.

> Aktuálne vydania nie sú digitálne podpísané. Windows preto môže aplikáciu alebo inštalátor zablokovať.

## CI / CD

Pull requesty, zmeny na `main` a release tagy prechádzajú kontrolami na Windows. Balíky sa po zostavení overia a release tag z nich vytvorí GitHub Release.

```mermaid
flowchart LR
    A["PR · main · tag · ručne"] --> B["CI<br/>Testy a verzia"]
    B -->|"Pull request"| C["Výsledok kontrol"]
    B -->|"push · tag · ručne"| D["Build<br/>EXE a inštalátor"]
    D --> E["Overenie<br/>Inštalácia a aktualizácia"]
    E --> F["Actions<br/>Artefakty"]
    F -->|"tag v*"| G["CD<br/>GitHub Release"]

    classDef standard fill:#eef8f7,stroke:#9acac7,color:#163b3d,stroke-width:1px;
    classDef output fill:#087f83,stroke:#087f83,color:#ffffff,stroke-width:1px;
    class A,B,C,D,E,F standard;
    class G output;
```

[Stav workflow](https://github.com/hudakjakub/OmniPDF/actions/workflows/windows.yml) · [Ako funguje vydávanie](docs/vyvoj.md#vývoj-a-vydávanie)

---

[Používanie a obmedzenia](docs/pouzivanie.md) · [Vývoj](docs/vyvoj.md) · [Zmeny](docs/CHANGELOG.md) · [Licencia AGPL v3](LICENSE)
