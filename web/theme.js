(function () {
  try { localStorage.setItem('beacon-appearance', 'dark'); } catch (e) {}
  var colours = '--pearl:#111513;--bg:#111513;--bg-soft:#111513;--bg-card:#18201b;--steel:#b0bbb2;--muted:#b0bbb2;' +
    '--light-grey:#303b33;--line:#303b33;--line-solid:#303b33;--text:#eef1ec;--toolbar-bg:#161c18;' +
    '--jibo-blue:#29d780;--accent-blue:#1fa866;--charlotte:#a8f0c8;--hover:#1d2a22;--surface-hover:#1a2a20;' +
    '--progress-track:#2a352d;--none-banner:#1d2620;--banner-start:#1c2b22;--banner-end:#1f3d2c;' +
    '--readme-link:#6fe3a6;--role-line:#2c6b4a;--accent-dim:rgba(41,215,128,.14);--store-link:#9fe0bd;--store-muted:#b0bbb2;';
  // Liquid Glass: translucent, blurred surfaces with a light edge, over soft 5x1 glows.
  var glass = 'background: rgba(30,44,35,.5) !important; -webkit-backdrop-filter: blur(22px) saturate(170%); backdrop-filter: blur(22px) saturate(170%);' +
    'border: 1px solid rgba(255,255,255,.1) !important; box-shadow: inset 0 1px 0 rgba(255,255,255,.08), 0 10px 30px rgba(0,0,0,.25) !important';
  var surfaces = '.card, .stat, .setting-row, .setting-block, .photo-card, .empty, .skill, .store-card, .store-switch, .store-options-menu,' +
    ' .store-options-button, .theme-details-card, .modal-box, .toast, .store-safety-note, .menu-editor, .menu-folder-edit';
  var lighter = '.btn:not(.btn-primary):not(.btn-danger):not(.store-details), .form-row input, .form-row select, select, input[type=text], input[type=url], textarea';
  var style = document.createElement('style');
  style.textContent = 'html:root, html:root[data-appearance="dark"] {' + colours + 'color-scheme: dark}' +
    '.toolbar, .bottom-nav { display: none !important }' +
    'body { background: #111513; padding-bottom: calc(96px + env(safe-area-inset-bottom, 0px)) !important }' +
    '.btn-primary, .btn-primary:hover, .btn-primary:active { color: #0d2015 !important }' +
    'body { background: radial-gradient(60% 40% at 10% 0%, #1c3023 0%, transparent 70%), radial-gradient(50% 35% at 100% 55%, #17291e 0%, transparent 70%), #111513 fixed !important }' +
    surfaces + ' {' + glass + '}' +
    '.store-card-content, .store-options-menu button { background: transparent !important }' +
    lighter + ' { background: rgba(255,255,255,.06) !important; border: 1px solid rgba(255,255,255,.12) !important;' +
    ' -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px) }' +
    '.btn-primary { box-shadow: inset 0 1px 0 rgba(255,255,255,.35), 0 6px 18px rgba(41,215,128,.25) !important }' +
    // The Store draws its buttons, switch and progress in fixed blues.
    '.store-switch-slider, .store-card .store-apply, .store-card .store-install { background: #29d780 !important; border-color: #29d780 !important; color: #0d2015 !important }' +
    '.store-card .store-install:hover:not(:disabled) { background: #1fa866 !important; border-color: #1fa866 !important }' +
    '.store-switch-tab[aria-selected="true"], .store-switch-tab[aria-checked="true"] { color: #0d2015 !important }' +
    '.store-switch-tab:focus-visible { outline-color: #29d780 !important }' +
    '.theme-download-progress progress { accent-color: #29d780 !important }' +
    '.theme-download-progress progress::-webkit-progress-value { background: #29d780 !important }' +
    'a:not(.btn) { color: #6fe3a6 }' +
    // Store: Details is a text link, and its popup sits between BEep's bars on a frosted backdrop.
    '.store-card .store-details { background: rgba(255,255,255,.06) !important; border: 1px solid rgba(255,255,255,.12) !important;' +
    ' -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px); color: #6fe3a6 !important; padding: 9px 26px !important; border-radius: 10px; font-weight: 600 }' +
    '.theme-details { background: rgba(5,10,7,.55) !important; -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px);' +
    ' padding: calc(env(safe-area-inset-top, 0px) + 64px) 16px calc(env(safe-area-inset-bottom, 0px) + 100px) !important }' +
    '.theme-details .theme-details-card { background: rgba(22,31,25,.92) !important }';
  document.documentElement.appendChild(style);
})();
