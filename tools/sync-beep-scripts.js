'use strict';
// Copies BEep's page scripts (the 5x1 look and the bridge) out of BEep's BEacon.swift into web/,
// the same extraction BEep's Android build does. usage: node tools/sync-beep-scripts.js <path to BEep/BEacon.swift>
const fs = require('fs'), path = require('path');
const source = fs.readFileSync(process.argv[2], 'utf8');
['theme', 'bridge'].forEach(name => {
    const start = source.indexOf('private static let ' + name + ' = """');
    if (start < 0) throw new Error('BEacon.swift has no ' + name + ' script');
    const from = source.indexOf('\n', start) + 1, body = source.slice(from, source.indexOf('"""', from));
    const indent = Math.min.apply(null, body.split('\n').filter(l => l.trim()).map(l => l.match(/^ */)[0].length));
    const text = body.split('\n').map(l => l.slice(indent)).join('\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\').trimEnd() + '\n';
    fs.writeFileSync(path.join(__dirname, '..', 'web', name + '.js'), text);
    console.log('wrote web/' + name + '.js');
});
