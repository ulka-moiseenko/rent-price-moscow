# Обновляет оглавление в итоговой записке через Word и сохраняет PDF.
param([string[]]$Files, [switch]$Pdf)
$dir = Join-Path (Split-Path $PSScriptRoot -Parent) "Пояснительная записка"
$w = New-Object -ComObject Word.Application
$w.Visible = $false
foreach ($name in $Files) {
    $path = Join-Path $dir $name
    $d = $w.Documents.Open($path)
    foreach ($id in -20, -21) {                     # стили оглавления 1 и 2 уровня
        $st = $d.Styles.Item($id)
        $st.ParagraphFormat.FirstLineIndent = 0
        $st.ParagraphFormat.SpaceBefore = 0
        $st.ParagraphFormat.SpaceAfter = 0
        $st.ParagraphFormat.LineSpacingRule = 0
        $st.Font.Name = "Times New Roman"
        $st.Font.Size = 14
    }
    $d.Styles.Item(-20).ParagraphFormat.LeftIndent = 0
    $d.Styles.Item(-21).ParagraphFormat.LeftIndent = 14
    $d.TablesOfContents.Item(1).Update()
    "$name : страниц $($d.ComputeStatistics(2)), листов оглавления до введения:"
    foreach ($p in $d.Paragraphs) {
        $lvl = $p.OutlineLevel
        if ($lvl -le 2) {
            $text = $p.Range.Text.Trim() -replace "[\x0b\r]", " "
            "  стр. $($p.Range.Information(3))  $text"
        }
    }
    $d.Save()
    if ($Pdf) {
        [string]$out = [IO.Path]::ChangeExtension($path, ".pdf")
        $d.ExportAsFixedFormat($out, 17)
        "PDF: $out"
    }
    $d.Close()
}
$w.Quit()
