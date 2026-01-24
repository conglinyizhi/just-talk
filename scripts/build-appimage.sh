#!/bin/bash
# Build AppImage inside Docker container
# Uses uv for dependency management (same as build-linux)

set -eux

cd /app

# Sync dependencies with uv
uv sync --frozen --extra build

# Build with PyInstaller via uv
JT_BINARY_NAME=just-talk-x86_64 JT_ONEFILE=1 uv run pyinstaller just_talk.spec

# Get version
VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")

# Create AppDir structure
rm -rf AppDir
mkdir -p AppDir/usr/bin
mkdir -p AppDir/usr/lib
mkdir -p AppDir/usr/share/applications
mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps

# Copy binary
cp dist/just-talk-x86_64 AppDir/usr/bin/just-talk
chmod +x AppDir/usr/bin/just-talk

# Copy icon
if [ -f icon.png ]; then
    cp icon.png AppDir/usr/share/icons/hicolor/256x256/apps/just-talk.png
    cp icon.png AppDir/just-talk.png
fi

# Create desktop file
cat > AppDir/just-talk.desktop << 'DESKTOP'
[Desktop Entry]
Type=Application
Name=Just Talk
Exec=just-talk
Icon=just-talk
Terminal=false
Categories=AudioVideo;Audio;
Comment=Speech recognition with global hotkey support
DESKTOP
cp AppDir/just-talk.desktop AppDir/usr/share/applications/

# Create AppRun with GLX compatibility handling
cat > AppDir/AppRun << 'APPRUN'
#!/bin/bash
# AppRun for Just Talk - handles GLX/OpenGL compatibility

SELF=$(readlink -f "$0")
HERE=${SELF%/*}

export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib:${LD_LIBRARY_PATH:-}"

# Force XCB platform (Wayland has issues with global hotkeys and WebEngine)
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

# GLX/OpenGL compatibility:
# We don't bundle libGL/libGLX to avoid conflicts with different drivers.
# If hardware GL fails, fall back to software rendering.

check_glx() {
    if command -v glxinfo >/dev/null 2>&1; then
        glxinfo -B >/dev/null 2>&1
        return $?
    fi
    return 0
}

# Check if user explicitly set QT_OPENGL
if [ -z "${QT_OPENGL:-}" ]; then
    if ! check_glx; then
        echo "[Just Talk] GLX not available, using software OpenGL" >&2
        export QT_OPENGL=software
        export LIBGL_ALWAYS_SOFTWARE=1
    fi
fi

# Disable WebEngine GPU if software rendering
if [ "${QT_OPENGL:-}" = "software" ] || [ "${LIBGL_ALWAYS_SOFTWARE:-}" = "1" ]; then
    export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:-} --disable-gpu --disable-gpu-compositing"
fi

# Users can set JT_FORCE_SOFTWARE_GL=1 to force software rendering
if [ "${JT_FORCE_SOFTWARE_GL:-}" = "1" ]; then
    export QT_OPENGL=software
    export LIBGL_ALWAYS_SOFTWARE=1
    export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:-} --disable-gpu --disable-gpu-compositing"
fi

exec "${HERE}/usr/bin/just-talk" "$@"
APPRUN
chmod +x AppDir/AppRun

# Build AppImage using extracted appimagetool
ARCH=x86_64 /usr/local/bin/appimagetool-run AppDir "dist/just-talk-${VERSION}-x86_64.AppImage"

echo "AppImage created: dist/just-talk-${VERSION}-x86_64.AppImage"
