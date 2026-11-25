$ErrorActionPreference = 'Stop'
$name = 'Language.OCR~~~en-US~0.0.1.0'
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$ocr = [Windows.Media.Ocr.OcrEngine]
if ('en-US' -notin $ocr::AvailableRecognizerLanguages.LanguageTag) {
    Add-WindowsCapability -Online -Name $name | Out-Host
}
if ('en-US' -notin $ocr::AvailableRecognizerLanguages.LanguageTag -or $null -eq $ocr::TryCreateFromUserProfileLanguages()) {
    throw 'The Windows runner could not initialize English OCR.'
}
