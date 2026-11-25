<div align="center">
  <img src="assets/omni.svg" width="80" alt="Logo Omni PDF">
  <h1>Omni PDF</h1>
  <p><strong>Jednoduché úpravy PDF priamo vo Windows.</strong></p>
  <p>Bez účtu · Lokálne spracovanie · Slovenčina a angličtina</p>
  <a href="https://github.com/hudakjakub/OmniPDF/actions/workflows/windows.yml"><img src="https://github.com/hudakjakub/OmniPDF/actions/workflows/windows.yml/badge.svg" alt="Stav CI a CD"></a>
  <p><a href="https://github.com/hudakjakub/OmniPDF/releases/latest"><strong>Stiahnuť Omni PDF</strong></a></p>
</div>

## Čo dokáže

- Upraviť text, pridať textové pole alebo presunúť a odstrániť časť strany.
- Spojiť PDF, usporiadať strany a spracovať sken alebo fotografiu pomocou Windows OCR.
- Vytlačiť dokument a uložiť úpravy do novej PDF kópie.

## Začíname

Na stránke [vydaní](https://github.com/hudakjakub/OmniPDF/releases/latest) nájdeš inštalátor aj prenosnú verziu pre Windows x64. Aplikácia na úpravu dokumentov nepotrebuje účet ani internet; pripojenie používa pri kontrole a sťahovaní aktualizácií.

Aktuálne vydania nie sú digitálne podpísané, takže ich Windows môže upozornením alebo pravidlom zabezpečenia zablokovať.

[Používanie a obmedzenia](docs/pouzivanie.md) · [Vývoj a zostavenie](docs/vyvoj.md) · [História zmien](CHANGELOG.md)

## CI / CD

Každá zmena prechádza automatickými kontrolami. Po úspešnom zostavení vzniknú Windows balíky; release tag navyše zverejní vydanie na GitHube.

```mermaid
flowchart LR
    A["Pull request · main · tag · ručne"] --> B["CI<br/>Testy a kontrola verzie"]
    B -->|"Pull request"| C["Výsledok kontrol"]
    B -->|"main · tag · ručne"| D["Build<br/>EXE a inštalátor"]
    D --> E["Overenie<br/>Inštalácia a aktualizácia"]
    E --> F["GitHub Actions<br/>Artefakt"]
    F -->|"tag v*"| G["CD<br/>GitHub Release"]
```

[Zobraziť workflow](https://github.com/hudakjakub/OmniPDF/actions/workflows/windows.yml) · [Ako funguje vydanie](docs/vyvoj.md#vývoj-a-vydávanie)

---

[GNU AGPL v3](LICENSE) · [Licencie závislostí](THIRD_PARTY_NOTICES.md)
