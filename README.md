# ABBYY Batch Engleza

Automatizare Python pentru procesarea in lot a fisierelor PDF din `D:\ENGLEZA` cu ABBYY FineReader 15.

Proiectul deschide fiecare PDF eligibil, il trimite catre conversie Word (`.docx`), verifica periodic daca procesarea s-a terminat, inchide ABBYY FineReader in siguranta si continua cu urmatorul fisier.

## Ce face

- scaneaza folderul `D:\ENGLEZA` pentru fisiere `.pdf`;
- ignora PDF-urile mai mici de 300 KB;
- tine evidenta fisierelor procesate in `_abbyy_convertite.txt`;
- tine evidenta erorilor in `_abbyy_erori.txt`;
- scrie jurnalul complet in `_abbyy_rulare.log`;
- verifica din 7 in 7 minute daca ABBYY a terminat conversia;
- raspunde automat `No` la intrebarea de salvare a modificarilor in PDF-ul original;
- muta PDF-urile convertite in `D:\ENGLEZA\PDF-uri convertite`;
- evita pornirea a doua instante ale scriptului principal;
- foloseste un watcher auxiliar pentru prompturi ABBYY ramase deschise.

## Fisiere principale

- `abbyy_batch_engleza.py` - scriptul principal de automatizare.
- `abbyy_helper_watch.py` - watcher auxiliar pentru promptul de salvare si mutarea PDF-urilor convertite.
- `ruleaza_abbyy_batch_engleza.bat` - launcher Windows.
- `Version 1` si `Version 2` - versiuni intermediare pastrate pentru istoric local.

## Cerinte

- Windows
- Python 3.12+
- ABBYY FineReader 15 instalat in:

```text
C:\Program Files (x86)\ABBYY FineReader 15\FineReader.exe
```

- pachete Python:

```powershell
python -m pip install pyautogui pygetwindow pywinauto
```

## Rulare

Din folderul proiectului:

```powershell
.\ruleaza_abbyy_batch_engleza.bat
```

Test cu un singur PDF:

```powershell
.\ruleaza_abbyy_batch_engleza.bat --one
```

Verificare lista fara pornirea ABBYY:

```powershell
python .\abbyy_batch_engleza.py --dry-run
```

## Optiuni utile

```powershell
python .\abbyy_batch_engleza.py --check-minutes 7 --max-conversion-minutes 180
```

- `--check-minutes` controleaza intervalul de verificare a conversiei.
- `--max-conversion-minutes` controleaza timpul maxim acordat unui PDF.
- `--one` proceseaza doar primul PDF din coada.
- `--dry-run` arata coada fara sa porneasca ABBYY.

## Observatii

Automatizarea controleaza interfata ABBYY FineReader. Cand scriptul are de apasat un buton sau de verificat un dialog, poate aduce ABBYY in fata pentru cateva secunde.

