"""WebEngine manager simplificado para Forging Tools.

Gerencia perfis isolados por slot com sessões compartilhadas,
anti-detecção Chrome e sidebar toggle para WhatsApp.

Estratégia anti-detecção (baseada no qutebrowser):
- Chrome UA + Sec-CH-UA para sites gerais (Cloudflare, etc)
- Firefox UA para *.google.com (Google bloqueia OAuth de embedded browsers
  via User-Agent; Firefox UA bypassa essa checagem)
"""
import logging
import re
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QEvent, QObject, QUrl, Signal
from PySide6.QtWebEngineCore import (
    QWebEngineFileSystemAccessRequest,
    QWebEngineProfile,
    QWebEnginePage,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QFileDialog, QVBoxLayout

logger = logging.getLogger(__name__)

# Deve bater com o Chromium real do Qt (118) para TLS fingerprint consistente
_CHROME_VERSION = "118"
_CHROME_FULL = "118.0.5993.220"
_WHATSAPP_URL = "https://web.whatsapp.com"

# Firefox UA para domains Google (mesma técnica do qutebrowser)
_FIREFOX_VERSION = "133.0"
_FIREFOX_UA = (
    f"Mozilla/5.0 (X11; Linux x86_64; rv:{_FIREFOX_VERSION}) "
    f"Gecko/20100101 Firefox/{_FIREFOX_VERSION}"
)

# Domains onde usamos Firefox UA (Google OAuth e serviços relacionados)
_GOOGLE_DOMAINS = (
    "accounts.google.com",
    "accounts.youtube.com",
    "myaccount.google.com",
    "gds.google.com",
)

PROFILES_DIR = Path.home() / ".forging-tools" / "profiles"


class _SmartHeaderInterceptor(QWebEngineUrlRequestInterceptor):
    """Interceptor inteligente per-domain.

    - Google domains: Firefox UA (bypassa bloqueio OAuth)
    - Todos os outros: Chrome UA + Sec-CH-UA (bypassa Cloudflare)
    """

    def interceptRequest(self, info):
        host = info.requestUrl().host()

        if any(host == d or host.endswith("." + d) for d in _GOOGLE_DOMAINS):
            # Firefox UA para Google — sem Sec-CH-UA (Firefox não envia)
            info.setHttpHeader(b"User-Agent", _FIREFOX_UA.encode())
            # Remove Sec-CH-UA headers que Firefox não envia
            info.setHttpHeader(b"Sec-CH-UA", b"")
            info.setHttpHeader(b"Sec-CH-UA-Mobile", b"")
            info.setHttpHeader(b"Sec-CH-UA-Platform", b"")
            info.setHttpHeader(b"Sec-CH-UA-Full-Version-List", b"")
            info.setHttpHeader(b"Sec-CH-UA-Arch", b"")
            info.setHttpHeader(b"Sec-CH-UA-Bitness", b"")
        else:
            # Chrome UA para todos os outros sites
            info.setHttpHeader(
                b"Sec-CH-UA",
                f'"Chromium";v="{_CHROME_VERSION}", '
                f'"Google Chrome";v="{_CHROME_VERSION}", '
                f'"Not_A Brand";v="24"'.encode(),
            )
            info.setHttpHeader(b"Sec-CH-UA-Mobile", b"?0")
            info.setHttpHeader(b"Sec-CH-UA-Platform", b'"Linux"')
            info.setHttpHeader(
                b"Sec-CH-UA-Full-Version-List",
                f'"Chromium";v="{_CHROME_FULL}", '
                f'"Google Chrome";v="{_CHROME_FULL}", '
                f'"Not_A Brand";v="24.0.0.0"'.encode(),
            )
            info.setHttpHeader(b"Sec-CH-UA-Arch", b'"x86"')
            info.setHttpHeader(b"Sec-CH-UA-Bitness", b'"64"')


def _choose_files(mode):
    """Abre file dialog nativo para anexar arquivos (WhatsApp, etc)."""
    if mode == QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple:
        files, _ = QFileDialog.getOpenFileNames(
            None, "Selecionar arquivos", str(Path.home()), "Todos os arquivos (*)"
        )
    else:
        path, _ = QFileDialog.getOpenFileName(
            None, "Selecionar arquivo", str(Path.home()), "Todos os arquivos (*)"
        )
        files = [path] if path else []
    return files


def _grant_permission(page, url, feature):
    """Auto-concede permissões de features (mic, cam, notificações, etc)."""
    page.setFeaturePermission(
        url, feature,
        QWebEnginePage.PermissionPolicy.PermissionGrantedByUser,
    )


def _apply_page_settings(page):
    """Aplica configurações padrão de WebEngine a qualquer page."""
    s = page.settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
    s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.ScreenCaptureEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.AllowWindowActivationFromJavaScript, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.DnsPrefetchEnabled, True)
    # CRITICO: sem isso, drop de arquivo NAVEGA para file:// ao invés de disparar
    # o evento drop JS. Default é True no Qt 6.4+, precisa ser False.
    s.setAttribute(QWebEngineSettings.WebAttribute.NavigateOnDropEnabled, False)
    # Garante que canvas.toDataURL()/toBlob() funcione — WhatsApp usa canvas
    # para o editor de imagem no preview dialog (mesmo bug do Brave browser)
    s.setAttribute(QWebEngineSettings.WebAttribute.ReadingFromCanvasEnabled, True)


class _PopupPage(QWebEnginePage):
    """Page para popups — permissões, file dialogs e nested popups."""

    def __init__(self, profile, dialog, parent=None):
        super().__init__(profile, parent)
        self._dialog = dialog
        _apply_page_settings(self)
        self.featurePermissionRequested.connect(
            lambda url, feat: _grant_permission(self, url, feat)
        )
        self.fileSystemAccessRequested.connect(lambda req: req.accept())

    def chooseFiles(self, mode, old_files, accepted_mimetypes):
        return _choose_files(mode)

    def createWindow(self, window_type):
        return self


class _OAuthPage(QWebEnginePage):
    """Page com suporte a popups OAuth (login Google, etc)."""

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self._profile = profile
        self._popup_dialogs = []

    def chooseFiles(self, mode, old_files, accepted_mimetypes):
        return _choose_files(mode)

    def createWindow(self, window_type):
        dialog = QDialog()
        dialog.setWindowTitle("WhatsApp")
        dialog.resize(800, 700)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)

        popup_view = QWebEngineView()
        popup_page = _PopupPage(self._profile, dialog, dialog)
        for script in self.scripts().toList():
            popup_page.scripts().insert(script)
        popup_view.setPage(popup_page)
        layout.addWidget(popup_view)

        dialog.finished.connect(
            lambda: self._popup_dialogs.remove(dialog)
            if dialog in self._popup_dialogs else None
        )
        self._popup_dialogs.append(dialog)
        dialog.show()
        return popup_page


# ── Audio fix JS — desabilita processamento que causa voz robótica ──

_AUDIO_FIX_JS = """
(function() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;

    var _origGUM = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = function(constraints) {
        if (constraints && constraints.audio) {
            var audioFix = {
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false
            };
            if (typeof constraints.audio === 'boolean') {
                constraints.audio = audioFix;
            } else {
                constraints.audio.echoCancellation = false;
                constraints.audio.noiseSuppression = false;
                constraints.audio.autoGainControl = false;
            }
        }
        return _origGUM(constraints);
    };

    // Spoof permissions API — WhatsApp checa antes de pedir mídia/clipboard/storage
    // IMPORTANTE: retornar objeto que extende EventTarget, senão WhatsApp chama
    // addEventListener('change', handler) e recebe TypeError silencioso
    if (navigator.permissions && navigator.permissions.query) {
        var _origQuery = navigator.permissions.query.bind(navigator.permissions);
        var _grantedPerms = [
            'microphone', 'camera', 'notifications', 'geolocation',
            'clipboard-read', 'clipboard-write', 'persistent-storage',
            'accelerometer', 'gyroscope', 'magnetometer',
            'background-sync', 'midi', 'storage-access',
        ];
        navigator.permissions.query = function(desc) {
            if (desc && _grantedPerms.indexOf(desc.name) !== -1) {
                var status = new EventTarget();
                status.state = 'granted';
                status.name = desc.name;
                status.onchange = null;
                return Promise.resolve(status);
            }
            return _origQuery(desc);
        };
    }

    // Garante que Notification.permission é 'granted'
    if (window.Notification) {
        Object.defineProperty(Notification, 'permission', { get: function() { return 'granted'; } });
        Notification.requestPermission = function() { return Promise.resolve('granted'); };
    }
})();
"""

# ── File System Access API polyfill ──
# WhatsApp usa showOpenFilePicker() que no QtWebEngine dispara
# fileSystemAccessRequested (tratado no Python). Este polyfill é um
# safety-net: se o sinal não funcionar, faz fallback para <input type="file">
# que aciona chooseFiles() no Python.

_FILE_PICKER_POLYFILL_JS = """
(function() {
    // Garante que showOpenFilePicker existe — se o Qt tratar via
    // fileSystemAccessRequested, a chamada nativa funciona.
    // Se não, este polyfill faz fallback para <input type="file">.
    var _origPicker = window.showOpenFilePicker;
    window.showOpenFilePicker = function(options) {
        // Tenta o nativo primeiro
        if (_origPicker) {
            try { return _origPicker.call(window, options); } catch(e) {}
        }
        // Fallback: cria <input type="file"> invisível
        return new Promise(function(resolve, reject) {
            var input = document.createElement('input');
            input.type = 'file';
            input.style.display = 'none';
            if (options && options.multiple) input.multiple = true;
            if (options && options.types) {
                var accepts = [];
                options.types.forEach(function(t) {
                    if (t.accept) {
                        Object.keys(t.accept).forEach(function(mime) {
                            var exts = t.accept[mime];
                            if (Array.isArray(exts)) accepts = accepts.concat(exts);
                            else accepts.push(mime);
                        });
                    }
                });
                if (accepts.length) input.accept = accepts.join(',');
            }
            input.addEventListener('change', function() {
                var handles = Array.from(input.files).map(function(f) {
                    return {
                        kind: 'file',
                        name: f.name,
                        getFile: function() { return Promise.resolve(f); },
                        createWritable: function() {
                            return Promise.reject(new DOMException('Not supported', 'NotAllowedError'));
                        },
                        queryPermission: function() { return Promise.resolve('granted'); },
                        requestPermission: function() { return Promise.resolve('granted'); },
                        isSameEntry: function(other) {
                            return Promise.resolve(other && other.name === f.name);
                        }
                    };
                });
                document.body.removeChild(input);
                resolve(handles);
            });
            input.addEventListener('cancel', function() {
                document.body.removeChild(input);
                reject(new DOMException('The user aborted a request.', 'AbortError'));
            });
            document.body.appendChild(input);
            input.click();
        });
    };

    // showSaveFilePicker e showDirectoryPicker — stubs para não crashar
    if (!window.showSaveFilePicker) {
        window.showSaveFilePicker = function() {
            return Promise.reject(new DOMException('Not supported', 'NotAllowedError'));
        };
    }
    if (!window.showDirectoryPicker) {
        window.showDirectoryPicker = function() {
            return Promise.reject(new DOMException('Not supported', 'NotAllowedError'));
        };
    }
})();
"""

# ── DataTransfer normalization + clipboard paste fix ──
# QTBUG-53573: QtWebEngine adiciona um DataTransferItem extra comparado ao
# Chrome padrão. datatransfer.items tem 2 items mas datatransfer.files tem 1.
# WhatsApp itera items e encontra null no item fantasma, causando TypeError.
# Este script intercepta drop e paste events para normalizar o DataTransfer.

_DATATRANSFER_FIX_JS = """
(function() {
    // Fix 1: Normaliza DataTransfer em drop events (QTBUG-53573)
    document.addEventListener('drop', function(e) {
        if (!e.dataTransfer || !e.dataTransfer.files || e.dataTransfer.files.length === 0) return;

        // Se items e files tem tamanhos diferentes, há o bug do Qt
        var dt = e.dataTransfer;
        if (dt.items && dt.items.length !== dt.files.length) {
            // Cria um novo DataTransfer limpo com apenas os files reais
            try {
                var newDt = new DataTransfer();
                for (var i = 0; i < dt.files.length; i++) {
                    newDt.items.add(dt.files[i]);
                }
                // Substitui o dataTransfer do evento
                Object.defineProperty(e, 'dataTransfer', {
                    value: newDt,
                    writable: false,
                    configurable: true
                });
            } catch(err) {
                // DataTransfer constructor pode não existir em versões antigas
                console.warn('[forging-tools] DataTransfer fix failed:', err);
            }
        }
    }, true);  // capture phase — roda ANTES dos handlers do WhatsApp

    // Fix 2: Garante que paste de imagem funcione via clipboard API
    document.addEventListener('paste', function(e) {
        if (!e.clipboardData || !e.clipboardData.files || e.clipboardData.files.length === 0) return;

        // Mesmo fix de normalização para paste events
        var dt = e.clipboardData;
        if (dt.items && dt.items.length !== dt.files.length) {
            try {
                var newDt = new DataTransfer();
                for (var i = 0; i < dt.files.length; i++) {
                    newDt.items.add(dt.files[i]);
                }
                Object.defineProperty(e, 'clipboardData', {
                    value: newDt,
                    writable: false,
                    configurable: true
                });
            } catch(err) {
                console.warn('[forging-tools] Clipboard fix failed:', err);
            }
        }
    }, true);  // capture phase

    // Fix 3: Garante que dragover aceita files (necessário para o drop funcionar)
    document.addEventListener('dragover', function(e) {
        if (e.dataTransfer && e.dataTransfer.types &&
            (e.dataTransfer.types.indexOf('Files') !== -1 ||
             e.dataTransfer.types.indexOf('application/x-moz-file') !== -1)) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
        }
    }, true);

    document.addEventListener('dragenter', function(e) {
        if (e.dataTransfer && e.dataTransfer.types &&
            (e.dataTransfer.types.indexOf('Files') !== -1 ||
             e.dataTransfer.types.indexOf('application/x-moz-file') !== -1)) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
        }
    }, true);

    console.log('[forging-tools] DataTransfer + clipboard fixes loaded');
})();
"""

# ── Anti-detect JS ──

_ANTIDETECT_JS = f"""
(function() {{
    var isGoogle = /accounts\\.google\\.com|myaccount\\.google\\.com|gds\\.google\\.com/.test(location.hostname);

    Object.defineProperty(navigator, 'webdriver', {{get: () => false}});
    Object.defineProperty(navigator, 'languages', {{
        get: () => ['pt-BR','pt','en-US','en']
    }});

    if (isGoogle) {{
        // Em páginas Google: fingir ser Firefox (consistente com o header UA)
        Object.defineProperty(navigator, 'userAgent', {{
            get: () => '{_FIREFOX_UA}'
        }});
        Object.defineProperty(navigator, 'appVersion', {{
            get: () => '5.0 (X11)'
        }});
        Object.defineProperty(navigator, 'platform', {{
            get: () => 'Linux x86_64'
        }});
        Object.defineProperty(navigator, 'vendor', {{
            get: () => ''
        }});
        Object.defineProperty(navigator, 'product', {{
            get: () => 'Gecko'
        }});
        Object.defineProperty(navigator, 'productSub', {{
            get: () => '20100101'
        }});
        // Firefox não tem navigator.userAgentData
        if (navigator.userAgentData) {{
            Object.defineProperty(navigator, 'userAgentData', {{
                get: () => undefined
            }});
        }}
        // Firefox não tem window.chrome
        if (window.chrome) {{
            delete window.chrome;
        }}
        // Firefox plugins são diferentes
        Object.defineProperty(navigator, 'plugins', {{
            get: () => {{
                const a = [];
                a.item = i => a[i]; a.namedItem = n => null; a.refresh = ()=>{{}};
                return a;
            }}
        }});
    }} else {{
        // Em outros sites: fingir ser Chrome real
        Object.defineProperty(navigator, 'plugins', {{
            get: () => {{
                const a = [
                    {{name:'Chrome PDF Plugin',filename:'internal-pdf-viewer',description:'PDF'}},
                    {{name:'Chrome PDF Viewer',filename:'mhjfbmdgcfjbbpaeojofohoefgiehjai',description:''}},
                    {{name:'Native Client',filename:'internal-nacl-plugin',description:''}}
                ];
                a.item = i => a[i]; a.namedItem = n => a.find(p=>p.name===n); a.refresh = ()=>{{}};
                return a;
            }}
        }});
        if (navigator.userAgentData) {{
            Object.defineProperty(navigator, 'userAgentData', {{
                get: () => ({{
                    brands: [
                        {{brand:'Chromium',version:'{_CHROME_VERSION}'}},
                        {{brand:'Google Chrome',version:'{_CHROME_VERSION}'}},
                        {{brand:'Not_A Brand',version:'24'}}
                    ],
                    mobile: false, platform: 'Linux',
                    getHighEntropyValues: () => Promise.resolve({{
                        architecture:'x86', bitness:'64', mobile:false, model:'',
                        platform:'Linux', platformVersion:'6.8.0',
                        fullVersionList: [
                            {{brand:'Chromium',version:'{_CHROME_FULL}'}},
                            {{brand:'Google Chrome',version:'{_CHROME_FULL}'}},
                            {{brand:'Not_A Brand',version:'24.0.0.0'}}
                        ]
                    }})
                }})
            }});
        }}
        if (!window.chrome) {{ window.chrome = {{runtime:{{}}, app:{{isInstalled:false}}}}; }}
    }}
}})();
"""


def _sidebar_toggle_js(default_half: bool = True) -> str:
    """JS que injeta botão flutuante para toggle da sidebar do WhatsApp.

    2 estados:
      - 75%: sidebar visível com 75% da largura original
      - colapsado: sidebar hidden
    Default ao carregar: 75%.
    """
    initial_state = "'half'" if default_half else "'collapsed'"
    return r"""
    (function() {
        if (document.getElementById('__mw_sidebar_toggle')) return;

        var state = """ + initial_state + r""";
        var origWidth = '';

        function findSide() {
            return document.getElementById('side')
                || document.querySelector('[id="side"]');
        }

        function findTarget() {
            var side = findSide();
            if (!side) return null;
            var p = side.closest('[style*="flex"]') || side.parentElement;
            return (p && p !== document.body) ? p : side;
        }

        // Encontra a borda/divisor entre sidebar e chat
        function findDivider() {
            // Div com border que corta a tela (classes WhatsApp conhecidas)
            var d = document.querySelector('.x1iyjqo2.xpilrb4.x1t7ytsu');
            if (d) return d;
            var target = findTarget();
            if (!target) return null;
            var next = target.nextElementSibling;
            if (next && (next.offsetWidth <= 8 || next.getAttribute('role') === 'separator'
                || next.style.cursor === 'col-resize')) {
                return next;
            }
            return null;
        }

        function applyState() {
            var target = findTarget();
            if (!target) return;
            var divider = findDivider();

            if (state === 'half') {
                target.style.display = '';
                if (!origWidth) {
                    origWidth = target.getBoundingClientRect().width + 'px';
                }
                var newW = (parseFloat(origWidth) * 0.75) + 'px';
                target.style.width = newW;
                target.style.minWidth = newW;
                target.style.maxWidth = newW;
                target.style.overflow = 'hidden';
                if (divider) {
                    divider.style.display = '';
                    divider.style.position = 'absolute';
                    divider.style.left = (parseFloat(newW) + 67) + 'px';
                }
                btn.innerHTML = svgHalf;
                btn.title = 'Sidebar 75% — clique para colapsar';
            } else {
                target.style.display = 'none';
                if (divider) divider.style.display = 'none';
                btn.innerHTML = svgCollapsed;
                btn.title = 'Sidebar colapsada — clique para expandir';
            }
        }

        // Expõe função global para o header do Qt chamar
        window.__toggleSidebar = function() {
            state = (state === 'half') ? 'collapsed' : 'half';
            applyState();
        };

        function tryInit() {
            if (findSide()) {
                var target = findTarget();
                if (target) {
                    origWidth = target.getBoundingClientRect().width + 'px';
                }
                applyState();
            } else {
                setTimeout(tryInit, 1500);
            }
        }

        if (document.body) tryInit();
        else document.addEventListener('DOMContentLoaded', tryInit);
    })();
    """


class _DragDropWebView(QWebEngineView):
    """QWebEngineView com suporte completo a drag & drop de arquivos.

    O widget interno do Chromium (RenderWidgetHostViewQtDelegateWidget)
    intercepta eventos de drag antes do conteudo web. Este wrapper instala
    um event filter no child widget para garantir que drops de arquivos
    cheguem ao JavaScript (ex: arrastar imagem no WhatsApp).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._render_widget = None

    def event(self, event):
        if event.type() == QEvent.Type.ChildAdded:
            child = event.child()
            if hasattr(child, 'setAcceptDrops'):
                child.setAcceptDrops(True)
                child.installEventFilter(self)
                self._render_widget = child
        return super().event(event)

    def eventFilter(self, obj, event):
        if obj is self._render_widget and event.type() in (
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.DragLeave,
            QEvent.Type.Drop,
        ):
            event.acceptProposedAction()
            return False  # NAO consome — deixa Chromium processar
        return super().eventFilter(obj, event)


class BrowserEngine(QObject):
    """Gerencia perfis WebEngine por slot com sessões compartilhadas."""

    page_loaded = Signal(str, bool)  # slot_id, success

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._profiles: Dict[str, QWebEngineProfile] = {}
        self._interceptors: Dict[str, _SmartHeaderInterceptor] = {}

    def _get_or_create_profile(self, slot_id: str) -> QWebEngineProfile:
        """Retorna profile existente ou cria novo com storage persistente."""
        if slot_id in self._profiles:
            return self._profiles[slot_id]

        storage_path = PROFILES_DIR / slot_id
        storage_path.mkdir(parents=True, exist_ok=True)

        profile = QWebEngineProfile(slot_id, self)
        profile.setPersistentStoragePath(str(storage_path))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        profile.setHttpCacheMaximumSize(50 * 1024 * 1024)
        profile.setHttpUserAgent(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{_CHROME_FULL} Safari/537.36"
        )

        interceptor = _SmartHeaderInterceptor(profile)
        profile.setUrlRequestInterceptor(interceptor)

        profile.downloadRequested.connect(self._on_download_requested)

        self._profiles[slot_id] = profile
        self._interceptors[slot_id] = interceptor
        return profile

    @staticmethod
    def _on_download_requested(download) -> None:
        """Abre save dialog e inicia o download (arquivos recebidos no WhatsApp, etc)."""
        suggested = download.suggestedFileName()
        downloads_dir = Path.home() / "Downloads"
        downloads_dir.mkdir(exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            None, "Salvar arquivo", str(downloads_dir / suggested), "Todos os arquivos (*)"
        )
        if path:
            dest = Path(path)
            download.setDownloadDirectory(str(dest.parent))
            download.setDownloadFileName(dest.name)
            download.accept()
        else:
            download.cancel()

    def create_view(
        self,
        slot_id: str,
        *,
        url: str = _WHATSAPP_URL,
        inject_sidebar_toggle: bool = True,
    ) -> QWebEngineView:
        """Cria QWebEngineView vinculado ao profile do slot.

        Múltiplas views com mesmo slot_id compartilham sessão (cookies, storage).
        """
        profile = self._get_or_create_profile(slot_id)

        page = _OAuthPage(profile, self)
        _apply_page_settings(page)

        page.featurePermissionRequested.connect(self._on_permission)

        # File System Access API — CRITICO para anexar arquivos no WhatsApp
        page.fileSystemAccessRequested.connect(self._on_fs_access)

        # Audio fix + permissions spoof
        self._inject_script(page, "audio_fix",
                            _AUDIO_FIX_JS,
                            QWebEngineScript.InjectionPoint.DocumentCreation,
                            runs_on_subframes=True)

        # File picker polyfill (safety net caso fileSystemAccessRequested falhe)
        self._inject_script(page, "file_picker_polyfill",
                            _FILE_PICKER_POLYFILL_JS,
                            QWebEngineScript.InjectionPoint.DocumentCreation,
                            runs_on_subframes=True)

        # Anti-detect
        self._inject_script(page, "antidetect",
                            _ANTIDETECT_JS,
                            QWebEngineScript.InjectionPoint.DocumentCreation,
                            runs_on_subframes=True)

        # DataTransfer normalization + clipboard paste fix (QTBUG-53573)
        self._inject_script(page, "datatransfer_fix",
                            _DATATRANSFER_FIX_JS,
                            QWebEngineScript.InjectionPoint.DocumentReady,
                            runs_on_subframes=True)

        # Sidebar toggle (WhatsApp)
        if inject_sidebar_toggle:
            self._inject_script(page, "sidebar_toggle",
                                _sidebar_toggle_js(default_half=True),
                                QWebEngineScript.InjectionPoint.DocumentReady)

        page.loadFinished.connect(
            lambda ok, sid=slot_id: self.page_loaded.emit(sid, ok)
        )

        view = _DragDropWebView()
        view.setPage(page)
        view.load(QUrl(url))
        return view

    @staticmethod
    def _inject_script(
        page: QWebEnginePage,
        name: str,
        source: str,
        injection_point: QWebEngineScript.InjectionPoint,
        *,
        runs_on_subframes: bool = False,
    ) -> None:
        script = QWebEngineScript()
        script.setName(name)
        script.setInjectionPoint(injection_point)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(runs_on_subframes)
        script.setSourceCode(source)
        page.scripts().insert(script)

    def _on_permission(self, url: QUrl, feature: QWebEnginePage.Feature) -> None:
        page = self.sender()
        if not isinstance(page, QWebEnginePage):
            return
        page.setFeaturePermission(
            url, feature,
            QWebEnginePage.PermissionPolicy.PermissionGrantedByUser,
        )

    @staticmethod
    def _on_fs_access(request: QWebEngineFileSystemAccessRequest) -> None:
        """Auto-aceita File System Access API (showOpenFilePicker no WhatsApp)."""
        logger.info(
            "FS Access: path=%s, type=%s, flags=%s",
            request.filePath(), request.handleType(), request.accessFlags(),
        )
        request.accept()

    def cleanup(self) -> None:
        """Limpa recursos sem navegar (preserva sessões)."""
        self._profiles.clear()
        self._interceptors.clear()
