param([Parameter(Mandatory=$true)][string]$ImagePath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Await($operation, $resultType) {
    $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $task.GetAwaiter().GetResult()
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'NO_OCR_LANGUAGE' }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try {
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $width = $decoder.PixelWidth
    $height = $decoder.PixelHeight
    $scale = [Math]::Min(1.0, [Windows.Media.Ocr.OcrEngine]::MaxImageDimension / [Math]::Max($width, $height))
    $transform = [Windows.Graphics.Imaging.BitmapTransform]::new()
    $transform.ScaledWidth = [Math]::Max(1, [int][Math]::Floor($width * $scale))
    $transform.ScaledHeight = [Math]::Max(1, [int][Math]::Floor($height * $scale))
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8, [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied, $transform, [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation, [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
    try {
        $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $lines = @($result.Lines | ForEach-Object {
            $words = @($_.Words)
            if ($words.Count -gt 0) {
                $left = ($words | ForEach-Object { $_.BoundingRect.X } | Measure-Object -Minimum).Minimum
                $top = ($words | ForEach-Object { $_.BoundingRect.Y } | Measure-Object -Minimum).Minimum
                $right = ($words | ForEach-Object { $_.BoundingRect.X + $_.BoundingRect.Width } | Measure-Object -Maximum).Maximum
                $bottom = ($words | ForEach-Object { $_.BoundingRect.Y + $_.BoundingRect.Height } | Measure-Object -Maximum).Maximum
                @{ text = $_.Text; bbox = @(($left * $width / $transform.ScaledWidth), ($top * $height / $transform.ScaledHeight), ($right * $width / $transform.ScaledWidth), ($bottom * $height / $transform.ScaledHeight)) }
            }
        })
        ConvertTo-Json -InputObject $lines -Compress -Depth 4
    } finally { $bitmap.Dispose() }
} finally { $stream.Dispose() }
