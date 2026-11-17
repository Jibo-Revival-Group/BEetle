(function () {
  var last = '', queued = false;
  function state() {
    var title = document.getElementById('toolbar-title');
    var tab = document.querySelector('.tab.is-active');
    return JSON.stringify({
      title: title ? title.textContent.trim() : '',
      panel: tab ? tab.getAttribute('data-panel') : '',
      actions: [].map.call(document.querySelectorAll('#toolbar-actions .toolbar-action'), function (b) {
        return { label: b.textContent.trim(), action: b.getAttribute('data-action') || '', disabled: !!b.disabled };
      })
    });
  }
  function send() {
    if (queued) return;
    queued = true;
    setTimeout(function () {
      queued = false;
      var next = state();
      if (next !== last) { last = next; window.webkit.messageHandlers.beep.postMessage(next); }
    }, 50);
  }
  window.__beep = {
    tab: function (name) { var t = document.querySelector('.tab[data-panel="' + name + '"]'); if (t) t.click(); },
    act: function (name) { var b = document.querySelector('#toolbar-actions [data-action="' + name + '"]'); if (b) b.click(); }
  };
  new MutationObserver(send).observe(document.documentElement, {
    subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['class', 'disabled']
  });
  send();
})();
