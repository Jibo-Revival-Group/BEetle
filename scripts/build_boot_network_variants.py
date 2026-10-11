#!/usr/bin/env python3
"""Generate known legacy renderer variants from the reviewed common collector.

Inputs must be untouched startup-view files extracted read-only from releases.
No robot, image modification or network access is performed by this helper.
"""
import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOM_STOCK = "ba8b9c43dd1e1017bface6886ddfe72a9f6e1bbcf2f5710a37460e6082f18848"
DOM_STOCKS = {DOM_STOCK, 'f7042f1bcdc0d4120ca315633a447460bbd01b9806281544a49ec28321ce2ff7'}
EARLY_X11_STOCK = "8f2ba0385c5030d5bf2d86214eb28f272866b72d5ea825cd44650b278e0b1d19"

DOM_METHODS = '''
    show() {
        if (this._networkVisible) return;
        this._networkVisible = true;
        this._networkText = 'Wi-Fi: checking...';
        this._startNetwork();
    }

    hide() {
        this._networkVisible = false;
        this._stopNetwork();
        if (this._networkRow) this._networkRow.textContent = '';
    }

    _startNetwork() {
        if (!this._networkVisible || this._state !== States.Success || this._mode === 'normal') return;
        if (!this._networkRow) {
            this._networkRow = document.createElement('div');
            const style = this._networkRow.style;
            style.position = 'absolute';
            style.top = '620px';
            style.left = '100px';
            style.width = '1080px';
            style.height = '70px';
            style.color = '#ffffff';
            style.background = '#000000';
            style.font = '20px monospace';
            style.textAlign = 'center';
            style.pointerEvents = 'none';
            this._parent.appendChild(this._networkRow);
        }
        this._drawNetwork();
        if (!this._networkActive) {
            this._networkActive = true;
            this._pollNetwork();
        }
    }

    _drawNetwork() {
        if (this._networkRow && this._networkVisible && this._state === States.Success && this._mode !== 'normal') {
            this._networkRow.textContent = this._networkText;
        }
    }
'''


def generate(stock, common):
    pin = hashlib.sha256(stock).hexdigest()
    if pin == EARLY_X11_STOCK:
        # Do not introduce a ScreenScheduler dependency absent from this SSM.
        result = common.replace("const ssm = require('../lib/skills-service-manager').default;\n", "")
        result = result.replace("                        ssm.ScreenScheduler.start(true);\n", "")
        return "startup-view-x11-early.js", result
    if pin not in DOM_STOCKS:
        raise ValueError("Unknown legacy startup-view hash; refusing generation")
    text = stock.decode("utf-8").rstrip('\n')
    helpers = common[common.index("const NETWORK_POLL_MS"):common.index("/**\n * Wraps the GUI")]
    text = text.replace("'use strict';\n", "'use strict';\n\n" + helpers, 1)
    text = text.replace("constructor() {", "constructor(options) {", 1)
    initialize = '''        this._networkSource = options && options.networkStatus || queryNetworkStatus;
        this._networkText = 'Wi-Fi: checking...';
        this._networkActive = false;
        this._networkGeneration = 0;
        this._networkCancel = null;
        this._networkTimer = null;
        this._networkDeadline = null;
        this._networkVisible = !document.hidden;
        this._networkRow = null;
        this._state = States.Loading;
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) this.hide(); else this.show();
        });
        window.addEventListener('beforeunload', () => this.hide());
'''
    text = text.replace("        this._mode = 'normal';\n", "        this._mode = 'normal';\n" + initialize, 1)
    text = text.replace("        this._mode = mode;\n", "        this._mode = mode;\n        if (mode === 'normal') {\n            this._stopNetwork();\n            if (this._networkRow) this._networkRow.textContent = '';\n        }\n", 1)
    text = text.replace("    complete(error) {\n", "    complete(error) {\n        this._stopNetwork();\n        this._state = error ? States.Error : States.Success;\n        if (this._networkRow) this._networkRow.textContent = '';\n        this.replace(this._content, 'status-success', 'status-loading');\n        this.replace(this._content, 'status-error', 'status-loading');\n", 1)
    text = text.replace("        this._message.innerHTML = 'Waiting for skill to begin...';\n", "        this._message.innerHTML = 'Waiting for skill to begin...';\n        this._startNetwork();\n", 1)
    polling = common[common.index("    _stopNetwork() {"):common.index("    _ensureNetworkFont() {")]
    polling = polling.replace("!this.X", "!this._parent")
    text = text.replace("    replace(node, find, replace) {", DOM_METHODS + "\n" + polling + "    replace(node, find, replace) {", 1)
    exports = common[common.index("StartupView.queryNetworkStatus ="):]
    text = text.replace("module.exports = StartupView;", exports.strip(), 1)
    return "startup-view-dom.js", text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "assets/boot-network-status")
    args = parser.parse_args()
    common = (ROOT / "assets/boot-network-status/startup-view.js").read_text()
    args.out.mkdir(parents=True, exist_ok=True)
    for path in args.stock:
        name, text = generate(path.read_bytes(), common)
        output = args.out / name
        output.write_text(text)
        print(name, hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
