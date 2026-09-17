#!/usr/bin/env bash
#
# Baut aus der fertigen PyInstaller-Datei ein doppelklickbares
# macOS-Programmpaket (.app) und packt es versandfertig als ZIP.
#
#   packaging/macos_app.sh [BINAERDATEI] [ZIELORDNER] [PAKETNAME]
#
# Warum es dieses Skript gibt
# ---------------------------
# Bis v0.1.0 lag im Release die nackte PyInstaller-Datei: ohne Endung, ohne
# Paket, ohne Signatur. Der Finder kennt für so etwas keine Zuordnung — ein
# Doppelklick öffnet sie im Texteditor, und man sieht den Binärinhalt als
# Zeichensalat. Das ist kein Fehler des Programms, sondern der Verpackung.
#
# Ein .app-Bundle ist nichts Geheimnisvolles, sondern ein Ordner mit fester
# Struktur. Deshalb wird es hier von Hand gebaut statt über PyInstallers
# BUNDLE: So steht jede Entscheidung sichtbar in dieser Datei, das Ergebnis
# lässt sich ohne PyInstaller nachvollziehen, und der Bauplan
# (gastroviewer.spec) bleibt für alle drei Systeme derselbe.
#
#   GastroViewer.app/Contents/
#     Info.plist            — was das Paket ist und welche Datei startet
#     MacOS/GastroViewer    — genau die Datei, die vorher lose im Release lag
#
# Ein Doppelklick startet damit Contents/MacOS/GastroViewer ohne Argumente.
# Das gefrorene Paket öffnet dann das Startfenster (siehe __main__.main:
# ohne Unterbefehl und mit sys.frozen ist "fenster" die Vorgabe) — kein
# Konsolenfenster mehr, das man erklären müsste.
#
# Die Datei im Paket ist weiterhin die vollständige Kommandozeile:
#   GastroViewer.app/Contents/MacOS/GastroViewer import-gtfs --region muenchen
set -euo pipefail

BINAERDATEI="${1:-dist/GastroViewer}"
ZIELORDNER="${2:-dist}"
PAKETNAME="${3:-GastroViewer-macOS}"

if [ ! -f "$BINAERDATEI" ]; then
    echo "Datei nicht gefunden: $BINAERDATEI" >&2
    echo "Zuerst bauen:  pyinstaller --clean --noconfirm packaging/gastroviewer.spec" >&2
    exit 2
fi

# Version aus pyproject.toml lesen, damit im Paket nicht eine zweite,
# abweichende Zahl gepflegt werden muss.
WURZEL="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$WURZEL/pyproject.toml" | head -1)"
VERSION="${VERSION:-0}"

APP="$ZIELORDNER/GastroViewer.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BINAERDATEI" "$APP/Contents/MacOS/GastroViewer"
chmod +x "$APP/Contents/MacOS/GastroViewer"

# LSMinimumSystemVersion steht bewusst NICHT drin: Der Wert hängt daran, mit
# welchem Python das Paket gebaut wurde, und unterscheidet sich zwischen dem
# Intel- und dem Apple-Silicon-Lauf. Eine geratene Zahl würde das Programm
# auf älteren Macs sperren, ohne dass jemand etwas davon hätte.
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>GastroViewer</string>
    <key>CFBundleDisplayName</key>
    <string>GastroViewer</string>
    <key>CFBundleExecutable</key>
    <string>GastroViewer</string>
    <key>CFBundleIdentifier</key>
    <string>de.gastroviewer.standort-datenterminal</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.business</string>
</dict>
</plist>
PLIST

# Ad-hoc-Signatur ("-" statt eines Zertifikats). Das macht das Paket NICHT
# vertrauenswürdig für Gatekeeper — dafür bräuchte es ein bezahltes
# Entwicklerkonto und Notarisierung. Es verhindert aber den zweiten, viel
# ärgerlicheren Fehler: Auf Apple Silicon muss jede ausführbare Datei
# wenigstens ad hoc signiert sein, sonst bricht macOS sie beim Start
# kommentarlos ab ("killed: 9"), und nach dem Weg durch ZIP und Download
# meldet der Finder sonst gern "beschädigt und kann nicht geöffnet werden".
if command -v codesign >/dev/null 2>&1; then
    codesign --force --sign - --timestamp=none "$APP"
    codesign --verify --strict --verbose=2 "$APP"
else
    echo "Hinweis: codesign nicht gefunden — Paket bleibt unsigniert." >&2
fi

if command -v plutil >/dev/null 2>&1; then
    plutil -lint "$APP/Contents/Info.plist"
fi

# ditto statt zip: erhält Rechtebits, Symlinks und die erweiterten
# Attribute des Pakets. Ein mit "zip" gepacktes .app kommt beim Empfänger
# regelmäßig ohne Ausführungsrecht an — und dann ist man wieder da, wo
# v0.1.0 aufgehört hat.
ZIP="$ZIELORDNER/${PAKETNAME}.zip"
rm -f "$ZIP"
if command -v ditto >/dev/null 2>&1; then
    ditto -c -k --keepParent "$APP" "$ZIP"
else
    (cd "$ZIELORDNER" && zip -qry "$(basename "$ZIP")" "$(basename "$APP")")
fi

echo "Programmpaket : $APP"
echo "Versandfertig : $ZIP"
